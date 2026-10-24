"""checkpointの安全拒否・状態維持・明示Exact復旧を、独立固定RAWで3case照合する。"""
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
common.require(build['status'] == 'PASS' and source_manifest(ROOT)['sha256'] == build['source'], 'frozen build/source')
host = build['binaries']['phase61_checkpoint_tests']
common.require(common.identity(host['path']) == host, 'checkpoint binary SHA')
inp = common.identity(ROOT / 'build/progressive_adoption_20261023_01/inputs/mono48_16s.wav')
common.require(inp['sha256'] == '225417ab731543dca88033f86d559275bbcbd6a7def776af39d5a971ec7e9cce', 'declared negative fixture SHA')
oracle = common.identity(ROOT / 'build/phase61/oracle_release_v1/phase61_frozen_reference')
common.require(oracle['sha256'] == 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748', 'independent frozen binary SHA')
ids = ['rejected_pcm_unchanged', 'rejected_then_duplicate', 'explicit_fixed_Exact_reprepare']
record = {'status': 'INCOMPLETE', 'source': build['source'], 'build': common.identity(a.build_record),
          'driver': common.identity(__file__), 'helper': common.identity(common.__file__), 'host': host,
          'input': inp, 'reference_binary': oracle, 'oracle_source_manifest': common.identity(ROOT / 'results/phase62_fix/recipes/oracle_manifest.json'),
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
common.save(out / 'SUMMARY.json', {'status': 'PASS' if passed else 'FAIL', 'complete': True, 'expected_cases': 3,
    'completed_cases': len(cases), 'returncode': r.returncode, 'cases': cases, 'final': final,
    'log': common.identity(log), 'expected': common.identity(out / 'EXPECTED.json'),
    'independent_fixed_PCM': passed, 'performance_approval': False, 'realtime_approval': False})
print('checkpoint_safe_rejection', 'PASS' if passed else 'FAIL', flush=True)
sys.exit(0 if passed else 2)
