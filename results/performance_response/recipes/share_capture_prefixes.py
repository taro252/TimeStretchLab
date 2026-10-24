"""writer退役済みの新規captureをAPFSの共有prefixで保管。全パス/全byte/SHAを維持する。

音声/build/CPU測定中は実行しない。先頭1MiBが同じRAWの最大fileを基にcloneし、
異なる64KiB blockを元データへ戻す。品質・参照・フレーム数は一切変更しない。
圧縮済みの代表だけを同byteの通常fileへ戻し、共有可能なdata forkを一つ確保する。
別hardlinkを持つfileは変更対象外。全SHA一致前に元fileを置換しない。
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity
BASE = ROOT / 'build/performance_response_20261023_01'

def require(value, why):
    if not value:
        raise RuntimeError(why)

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--roots', type=Path, nargs='+', required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--quiescence-record', type=Path, required=True,
               help='対象writer終了/回収と測定間の起動停止を確認した小manifest')
a = p.parse_args()
require(a.output.resolve().is_relative_to(BASE) and (not a.output.exists()), 'capture extent safety check failed')
roots = [x.resolve() for x in a.roots]
require(all((x.is_relative_to(BASE) and x.is_dir() for x in roots)), 'capture extent safety check failed')
require(len(roots) == len(set(roots)), 'duplicate roots')
quiescence_id = identity(a.quiescence_record)
quiescence = json.loads(a.quiescence_record.read_text())
require(quiescence['status'] == 'WRITERS_QUIESCENT' and quiescence['native_measurement_in_progress'] is False
        and sorted(quiescence['roots']) == sorted(map(str, roots)), 'writer/measurement quiescence not established')
record = {'status': 'INCOMPLETE', 'driver': identity(__file__), 'roots': list(map(str, roots)), 'scope': 'idle retired-writer evidence only; all paths/bytes/full SHA retained; product memory/caches unchanged', 'quiescence': quiescence_id, 'files': [], 'canonical_files': [], 'free_bytes_before': shutil.disk_usage(BASE).free}

def no_open_files(paths):
    # Parent orchestration remains paused for this whole operation. lsof is
    # an additional observation, not an atomic exclusion of future writers.
    for at in range(0, len(paths), 64):
        result = subprocess.run(['/usr/sbin/lsof', '-t', '--', *map(str, paths[at:at+64])],
                                capture_output=True, text=True, timeout=30)
        require(result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip(),
                'open descriptor or lsof could not establish quiescence: ' + result.stdout + result.stderr)

def save():
    a.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')

def replace_same(target, temp, expected, old_stat):
    require(identity(target) == expected, 'capture extent safety check failed')
    check = identity(temp)
    require(check['bytes'] == expected['bytes'] and check['sha256'] == expected['sha256'], 'capture extent safety check failed')
    os.chmod(temp, old_stat.st_mode & 511)
    os.utime(temp, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    os.replace(temp, target)
    require(identity(target) == expected, 'capture extent safety check failed')
save()
try:
    groups = {}
    targets = []
    for root in roots:
        for path in sorted(root.rglob('*.f32')):
            if path.name not in ('raw.f32', 'output_before_gain.f32') or path.stat().st_size < 1048576 or path.stat().st_nlink != 1:
                continue
            require(not path.is_symlink() and path.resolve().is_relative_to(root), 'RAW outside selected root')
            targets.append(path)
            with path.open('rb') as f:
                prefix = hashlib.sha256(f.read(1048576)).hexdigest()
            groups.setdefault(prefix, []).append(path)
    no_open_files(targets)
    record['open_descriptor_precheck'] = 'NONE; lsof completed without warnings'
    save()
    for prefix, paths in groups.items():
        paths = sorted(set(paths), key=lambda x: (-x.stat().st_size, str(x)))
        if len(paths) < 2:
            continue
        canonical = paths[0]
        original, old_stat = (identity(canonical), canonical.stat())
        temporary = canonical.with_name('.' + canonical.name + '.prefix_plain_tmp')
        require(not temporary.exists(), 'capture extent safety check failed')
        with canonical.open('rb') as src, temporary.open('xb') as dst:
            shutil.copyfileobj(src, dst, 1048576)
            dst.flush()
            os.fsync(dst.fileno())
        replace_same(canonical, temporary, original, old_stat)
        record['canonical_files'].append(original)
        save()
        for target in paths[1:]:
            expected, old_stat = (identity(target), target.stat())
            equal, changed = (0, [])
            with canonical.open('rb') as src, target.open('rb') as dst:
                at = 0
                while True:
                    right = dst.read(65536)
                    if not right:
                        break
                    left = src.read(len(right))
                    require(len(left) == len(right), 'capture extent safety check failed')
                    if left == right:
                        equal += len(right)
                    else:
                        changed.append((at, len(right)))
                    at += len(right)
            require(equal >= 1048576, 'capture extent safety check failed')
            temporary = target.with_name('.' + target.name + '.prefix_clone_tmp')
            require(not temporary.exists(), 'capture extent safety check failed')
            command = subprocess.run(['/bin/cp', '-c', str(canonical), str(temporary)], capture_output=True, text=True)
            require(command.returncode == 0, command.stderr)
            with temporary.open('r+b') as dst, target.open('rb') as src:
                dst.truncate(expected['bytes'])
                for at, size in changed:
                    src.seek(at)
                    block = src.read(size)
                    require(len(block) == size, 'capture extent safety check failed')
                    dst.seek(at)
                    written = dst.write(block)
                    require(written == size, 'short differential write')
                dst.flush()
                os.fsync(dst.fileno())
            require(identity(canonical) == original, 'capture extent safety check failed')
            replace_same(target, temporary, expected, old_stat)
            record['files'].append({'file': expected, 'canonical': original, 'equal_block_bytes': equal, 'changed_blocks': len(changed), 'full_SHA_verified': True})
            save()
    no_open_files(targets)
    require(identity(a.quiescence_record) == quiescence_id, 'quiescence record changed')
    record.update(status='PASS', open_descriptor_postcheck='NONE', free_bytes_after=shutil.disk_usage(BASE).free)
    record['observed_volume_free_delta_bytes'] = record['free_bytes_after'] - record['free_bytes_before']
    record['free_delta_scope'] = 'volume observation includes external activity; not exact shared-extent accounting'
    save()
    print(json.dumps({'status': record['status'], 'files': len(record['files']), 'canonical': len(record['canonical_files']), 'observed_volume_free_delta_bytes': record['observed_volume_free_delta_bytes']}))
except BaseException as error:
    record.update(status='FAIL_SAFE', error=type(error).__name__ + ': ' + str(error))
    save()
    raise
