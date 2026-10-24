"""Debugの安全拒否・全suffix・明示Exact復旧を、既存凍結Debug参照で同一flags比較する。
Release O3参照との失敗attemptは保持し、3固定ID/完全bit一致/有限性を維持する。
独立Debug binary/source/manifestを既知SHAで確認し、候補DSPから作り直さない。
"""
import argparse
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import source_manifest

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--build-record', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
build = common.load(a.build_record)
common.require(build['status'] == 'PASS' and build['configuration'] == 'Debug' and build['architecture'] == 'arm64' and source_manifest(ROOT)['sha256'] == build['source'], 'frozen build/source')
host = build['binaries']['phase61_checkpoint_tests']
common.require(common.identity(host['path']) == host, 'checkpoint binary SHA')
inp = common.identity(ROOT / 'build/progressive_adoption_20261023_01/inputs/mono48_16s.wav')
common.require(inp['sha256'] == '225417ab731543dca88033f86d559275bbcbd6a7def776af39d5a971ec7e9cce', 'declared negative fixture SHA')
oracle = common.identity(ROOT / 'build/phase61/oracle_debug_v1/phase61_frozen_reference')
common.require(oracle['sha256'] == '4ee8f3d61cab5aa7d8b39cb148525d7d81a65061efdfe3ce50d4cdc66f637f3f', 'independent frozen binary SHA')
debug_manifest = common.identity(ROOT / 'build/phase61/oracle_debug_v1/manifest.json')
common.require(debug_manifest['sha256'] == '678af349f94c4232293b14af9dfc023f1ba7c239811b27b578d52bc9780f16be', 'saved Debug oracle manifest SHA')
legacy_source = common.identity(ROOT / 'build/phase61/oracle_debug_v1/Phase36Legacy.cpp')
manifest = common.load(Path(debug_manifest['path']))
common.require(manifest['source_commit'] == 'ec087019626d9ff0d9f157245729b74ddb6847d7' and manifest['source_sha256'] == legacy_source['sha256'] == '4ffec7c4db196f51e89bd4ebaf336020ae71d0969c31393a40752b4a37ed3899' and manifest['binary_sha256'] == oracle['sha256'] and manifest['host_source_sha256'] == '72fc5f99ce49ea3bff6cb3260ecc5bbf8a5ff8a47ff5016ce9800a532e7ab742' and manifest['flags'] == '-g -std=c++20 -arch arm64', 'independent Debug source/binary/flags provenance')
oracle_arch = subprocess.check_output(['/usr/bin/lipo', '-archs', oracle['path']], text=True).split()
common.require(oracle_arch == ['arm64'], 'frozen Debug oracle architecture')
flags = Path(host['path']).parent / 'CMakeFiles/phase61_checkpoint_tests.dir/flags.make'
flag_line = next(x.partition('=')[2].strip() for x in flags.read_text().splitlines() if x.startswith('CXX_FLAGS ='))
import shlex
parts = shlex.split(flag_line)
common.require('-g' in parts and '-std=c++20' in parts and not any(x.startswith('-O') or x == '-DNDEBUG' or x == '-ffast-math' for x in parts), 'Debug comparison requires O0 without NDEBUG/fast-math')
ids = ['rejected_pcm_unchanged', 'rejected_then_duplicate', 'explicit_fixed_Exact_reprepare']
record = {'status': 'INCOMPLETE', 'source': build['source'], 'build': common.identity(a.build_record),
          'driver': common.identity(__file__), 'helper': common.identity(common.__file__), 'host': host,
          'input': inp, 'reference_binary': oracle, 'oracle_architectures': oracle_arch, 'oracle_source_manifest': debug_manifest, 'oracle_legacy_source': legacy_source, 'oracle_configuration': 'Debug -g O0 without NDEBUG', 'host_flags': common.identity(flags), 'host_flag_line': flag_line,
          'expected_cases': 3, 'all_expected_ids': ids, 'references': [], 'audio_output': False,
          'mode': 'declared NoSafeInterval negative fixture; original positive checkpoint test unchanged',
          'independent_fixed_PCM': True, 'planner_reference': 'full Phase39 diagnostic replay; separate from frozen fixed DSP',
          'performance_approval': False, 'realtime_approval': False}
common.save(out / 'EXPECTED.json', record)
for speed in (500000, 400000):
    raw, log = out / f'{speed}.f32', out / f'{speed}.log'
    cmd = [oracle['path'], inp['path'], str(speed), 'candidate', str(raw), '0']
    with log.open('w') as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=90)
    common.require(r.returncode == 0, 'frozen reference generation')
    meta = common.load(log)
    item = common.identity(raw)
    common.require(meta['rate'] == 48000 and meta['channels'] == 1 and meta['input_frames'] == 768000 and meta['positions'] == [0], 'reference metadata')
    common.require(meta['output_frames'] == (768000 * 1000000 + speed // 2) // speed and item['bytes'] == meta['output_frames'] * 4 and item['sha256'] == meta['sha256'], 'reference frames/hash')
    with raw.open('rb') as f:
        for block in iter(lambda: f.read(65536), b''):
            common.require(all(math.isfinite(x[0]) for x in struct.iter_unpack('<f', block)), 'reference NaN/Inf')
    record['references'].append({'speed_micros': speed, 'preset': 'candidate', 'raw': item, 'log': common.identity(log), 'command': cmd, 'returncode': r.returncode, 'finite': True})
    common.save(out / 'EXPECTED.json', record)
cmd = [host['path'], inp['path'], '--expect-no-safe-interval', record['references'][0]['raw']['path'], record['references'][1]['raw']['path']]
record['command'] = cmd
common.save(out / 'EXPECTED.json', record)
log = out / 'checkpoint.log'
with log.open('w') as f:
    r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=180)
rows = [json.loads(x) for x in log.read_text().splitlines() if x.startswith('{')]
cases = [x for x in rows if 'case' in x]
final = [x for x in rows if x.get('suite') == 'checkpoint_safe_rejection']
passed = (r.returncode == 0 and [x['case'] for x in cases] == ids and all(x.get('PASS') is True for x in cases)
          and len(final) == 1 and final[0].get('PASS') is True and final[0].get('expected') == final[0].get('completed') == 3)
common.require(common.identity(host['path']) == host and common.identity(oracle['path']) == oracle and common.identity(inp['path']) == inp and source_manifest(ROOT)['sha256'] == build['source'], 'source/input/binary changed')
common.require(common.identity(debug_manifest['path']) == debug_manifest and common.identity(legacy_source['path']) == legacy_source, 'Debug oracle provenance changed')
common.save(out / 'SUMMARY.json', {'status': 'PASS' if passed else 'FAIL', 'complete': True, 'expected_cases': 3,
    'completed_cases': len(cases), 'returncode': r.returncode, 'cases': cases, 'final': final,
    'log': common.identity(log), 'expected': common.identity(out / 'EXPECTED.json'),
    'independent_fixed_PCM': passed, 'performance_approval': False, 'realtime_approval': False})
print('checkpoint_safe_rejection', 'PASS' if passed else 'FAIL', flush=True)
sys.exit(0 if passed else 2)
