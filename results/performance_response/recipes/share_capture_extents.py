"""完了済みの新規AB証拠のRAW/加工後PCMをAPFS cloneで共有する。全byte/SHA/パスを保持。

製品のcache/予算とは無関係。音声試験と並行実行しない。既存履歴には適用しない。
同じfolderのraw.f32→output_before_gain.f32だけ、64KiB単位で異なるblockを書き戻す。
元ファイルは全SHA一致を確認するまで変更せず、別hardlinkがあるfileは対象外。
"""
import argparse
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
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--roots', type=Path, nargs='+', required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
assert a.output.resolve().is_relative_to(BASE) and not a.output.exists()
roots = [x.resolve() for x in a.roots]
assert all(x.is_relative_to(BASE) and x.is_dir() for x in roots)
record = {'status': 'INCOMPLETE', 'driver': identity(__file__), 'roots': list(map(str, roots)),
    'scope': 'idle new-run evidence only; same paths, bytes, complete SHA; physical clone only; no PCM/criteria discarded',
    'block_bytes': 65536, 'files': [], 'shared_pairs': 0, 'free_bytes_before': shutil.disk_usage(BASE).free}
def save():
    a.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
save()
try:
    for root in roots:
        for raw in sorted(root.rglob('raw.f32')):
            target = raw.with_name('output_before_gain.f32')
            if not target.exists() or raw.stat().st_size != target.stat().st_size or target.stat().st_nlink != 1 or raw.stat().st_size < 1048576:
                continue
            src_id, dst_id = identity(raw), identity(target)
            changed, equal = [], 0
            with raw.open('rb') as source, target.open('rb') as expected:
                at = 0
                while True:
                    left, right = source.read(65536), expected.read(65536)
                    assert len(left) == len(right)
                    if not left:
                        break
                    if left != right:
                        changed.append((at, len(left)))
                    else:
                        equal += len(left)
                    at += len(left)
            if equal < 1048576:
                continue
            temporary = target.with_name('.' + target.name + '.clone_tmp')
            assert not temporary.exists()
            before = target.stat()
            code = subprocess.run(['/bin/cp', '-c', str(raw), str(temporary)], capture_output=True, text=True)
            assert code.returncode == 0, code.stderr
            with temporary.open('r+b') as result, target.open('rb') as expected:
                for at, size in changed:
                    expected.seek(at)
                    data = expected.read(size)
                    assert len(data) == size
                    result.seek(at)
                    assert result.write(data) == size
                result.flush()
                os.fsync(result.fileno())
            assert identity(raw) == src_id and identity(target) == dst_id
            assert identity(temporary)['bytes'] == dst_id['bytes'] and identity(temporary)['sha256'] == dst_id['sha256']
            os.chmod(temporary, before.st_mode & 0o777)
            os.utime(temporary, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.replace(temporary, target)
            assert identity(target) == dst_id
            record['files'].append({'raw': src_id, 'output': dst_id, 'equal_block_bytes': equal,
                'changed_blocks': len(changed), 'SHA_verified_before_and_after': True})
            record['shared_pairs'] += 1
            save()
    record['free_bytes_after'] = shutil.disk_usage(BASE).free
    record['physical_free_delta_observed_bytes'] = record['free_bytes_after'] - record['free_bytes_before']
    record['physical_delta_scope'] = 'OS volume free-space observation; includes external activity, not exact per-file shared extent accounting'
    record['status'] = 'PASS'
    save()
    print(json.dumps({k: record[k] for k in ('status', 'shared_pairs', 'physical_free_delta_observed_bytes')}))
except BaseException as error:
    record.update(status='FAIL_SAFE', error=type(error).__name__ + ': ' + str(error))
    save()
    raise
