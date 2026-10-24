"""今回の新規RAWをAPFS透過圧縮する。全パス・全byte・SHAを保ち、旧証拠は触らない。

音声・性能測定・buildと重ねない。圧縮後も普通のfile/mmapとして読め、別archiveへの
退避やRAW削除は行わない。hardlinkは全リンクが指定範囲内にある場合だけ同時に置換し、
全元パスを同一内容の圧縮inodeへ結び直す。範囲外リンクがあれば触らない。
"""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
import subprocess
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--roots', type=Path, nargs='+', required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
assert out.is_relative_to(BASE) and not out.exists()
roots = [r.resolve() for r in a.roots]
assert all(r.is_relative_to(BASE) and r.is_dir() for r in roots)
record = {'status': 'INCOMPLETE', 'driver_sha256': sha(Path(__file__)), 'roots': list(map(str, roots)),
          'command': '/usr/bin/ditto --hfsCompression --noclone --noqtn SOURCE TEMP',
          'same_paths_bytes_sha256': True, 'rows': []}


def save():
    temp = out.with_suffix('.tmp')
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    temp.replace(out)


save()
groups = defaultdict(set)
for r in roots:
    for f in r.rglob('*.f32'):
        s = f.stat()
        groups[(s.st_dev, s.st_ino)].add(f)
for paths in groups.values():
    paths = sorted(paths)
    f = paths[0]
    s = f.stat()
    if s.st_nlink != len(paths) or s.st_size < 65536:
        continue
    before = sha(f)
    temp = f.with_name('.' + f.name + '.compress-' + str(os.getpid()))
    assert not temp.exists()
    cmd = ['/usr/bin/ditto', '--hfsCompression', '--noclone', '--noqtn', str(f), str(temp)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    # ditto can leave complete decmpfs data without UF_COMPRESSED under a
    # restricted host. Set the flag on the disposable copy only, then verify
    # every decoded byte before replacing any original name.
    flag_repaired = False
    temporary_stat = temp.stat()
    if (temporary_stat.st_size == 0 and s.st_size > 0
            and not (temporary_stat.st_flags & stat.UF_COMPRESSED)
            and 'com.apple.decmpfs' in os.listxattr(temp)):
        os.chflags(temp, temporary_stat.st_flags | stat.UF_COMPRESSED)
        flag_repaired = True
    assert temp.stat().st_size == s.st_size and sha(temp) == before and sha(f) == before
    after_blocks = temp.stat().st_blocks
    adopted = after_blocks < s.st_blocks
    if adopted:
        for alias in paths:
            link = alias.with_name('.' + alias.name + '.compressed-link-' + str(os.getpid()))
            assert not link.exists() and alias.stat().st_ino == s.st_ino
            os.link(temp, link)
            link.replace(alias)
        temp.unlink()
    else:
        temp.unlink()
    assert all(alias.stat().st_size == s.st_size and sha(alias) == before for alias in paths)
    assert len({alias.stat().st_ino for alias in paths}) == 1
    record['rows'].append({'path': str(f), 'aliases': list(map(str, paths)), 'bytes': s.st_size, 'sha256': before, 'adopted': adopted,
                           'temporary_compressed_flag_repaired': flag_repaired,
                           'physical_before_bytes': s.st_blocks * 512,
                           'physical_after_bytes': f.stat().st_blocks * 512})
    save()
record.update(status='PASS', complete=True,
              saved_physical_bytes=sum(x['physical_before_bytes'] - x['physical_after_bytes'] for x in record['rows']))
save()
print(json.dumps({k: record[k] for k in ('status', 'complete', 'saved_physical_bytes')}))
