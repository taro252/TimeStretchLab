#!/usr/bin/env python3
"""B内の独立保存ソースをRelease arm64で限定ビルド。製品checkoutは変更しない。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
B = ROOT / 'build/performance_response_20261023_01'
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import source_manifest, identity


def need(value, why):
    if not value:
        raise ValueError(why)


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root', type=Path, required=True)
p.add_argument('--source-sha', required=True)
p.add_argument('--build', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--targets', nargs='+', required=True)
a = p.parse_args()
root, build, out = a.source_root.resolve(), a.build.resolve(), a.output.resolve()
need(all(x.is_relative_to(B) for x in (root, build, out)) and root != ROOT, 'B内の独立実験のみ')
need(not out.exists() and not build.exists(), '新規BUILD/出力')
out.mkdir()
before = source_manifest(root)
live = source_manifest(ROOT)
need(before['sha256'] == a.source_sha and len(before['files']) == 768, '全実験source')
need(live['sha256'] == 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94', 'root08保持')
record = {'status': 'INCOMPLETE', 'source': a.source_sha, 'source_manifest': before,
          'source_root': str(root), 'configuration': 'Release', 'architecture': 'arm64',
          'live_source': live['sha256'], 'rows': [], 'binaries': {}}


def save(name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


save('EXPECTED.json', {'source': before, 'live_source': live, 'targets': a.targets,
                      'driver': identity(__file__), 'source_record': identity(root / 'SOURCE.json')})
env = dict(os.environ, PATH='/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin')
commands = [['cmake', '-S', str(root), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
             '-DCMAKE_OSX_ARCHITECTURES=arm64', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DBUILD_TESTING=ON'],
            ['cmake', '--build', str(build), '--target', *a.targets, '-j2']]
for name, command in zip(('configure', 'build'), commands):
    with (out / (name + '.log')).open('w') as f:
        result = subprocess.run(command, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=1200)
    record['rows'].append({'command': command, 'exit': result.returncode,
                          'log': identity(out / (name + '.log'))})
    save('BUILD.json', record)
    if result.returncode:
        record['status'] = 'FAIL';save('BUILD.json', record)
        raise SystemExit(result.returncode)
need(source_manifest(root) == before and source_manifest(ROOT) == live, 'ビルド前後source不変')
record['binaries'] = {target: identity(build / target) for target in a.targets}
record['compile_commands'] = identity(build / 'compile_commands.json')
record['status'] = 'PASS'
save('BUILD.json', record)
print(json.dumps({'status': 'PASS', 'source': a.source_sha, 'targets': len(a.targets)}))
