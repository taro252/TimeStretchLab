#!/usr/bin/env python3
"""独立保存ソースの小回帰。保存済みde70固定RAWを再hashし拒否後PCMを3case照合。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
import run_pairs as c

R = Path(__file__).resolve().parents[3]
B = R / 'build/performance_response_20261023_01'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--build-record', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
c.require(out.is_relative_to(B) and not out.exists(), 'B内新規run')
out.mkdir()
build = c.load(a.build_record)
root = Path(build['source_root']).resolve()
c.require(build['status'] == 'PASS' and build['configuration'] == 'Release' and
          root.is_relative_to(B) and c.current_source_digest(root) == build['source'], '独立Releaseソース')
live = c.current_source_digest(R)
c.require(live == 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94', 'root08保持')
old_path = B / 'checkpoint_rejection_final_01/EXPECTED.json'
old_id, old = c.identity(old_path), c.load(old_path)
oracle = old['reference_binary']
c.require(oracle['sha256'] == 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
          and c.identity(oracle['path']) == oracle, '独立固定oracle')
inputs = [old['input'], *[r[k] for r in old['references'] for k in ('raw', 'log')]]
for item in inputs:
    c.require(c.identity(item['path']) == item, '保存input/独立RAW/log変更')
host = build['binaries']['phase61_checkpoint_tests']
c.require(c.identity(host['path']) == host, '新しく成功した実行体')
ids = ['rejected_pcm_unchanged', 'rejected_then_duplicate', 'explicit_fixed_Exact_reprepare']
cmd = [host['path'], old['input']['path'], '--expect-no-safe-interval',
       old['references'][0]['raw']['path'], old['references'][1]['raw']['path']]
record = {'source': build['source'], 'live_source': live, 'build': c.identity(a.build_record),
          'source_root': str(root), 'host': host, 'driver': c.identity(__file__), 'command': cmd,
          'expected_cases': 3, 'all_expected_ids': ids, 'old_reference_record': old_id,
          'reused_reference_generation_not_new_runs': True, 'input_and_references': inputs,
          'reference_binary': oracle, 'reference_manifest': old['oracle_source_manifest'],
          'independent_fixed_PCM': True, 'performance_approval': False, 'realtime_approval': False}
c.save(out / 'EXPECTED.json', record)
log = out / 'checkpoint.log'
with log.open('w') as f:
    run = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=180)
rows = [json.loads(s) for s in log.read_text().splitlines() if s.startswith('{')]
cases = [r for r in rows if 'case' in r]
final = [r for r in rows if r.get('suite') == 'checkpoint_safe_rejection']
passed = run.returncode == 0 and [r['case'] for r in cases] == ids and all(r.get('PASS') is True for r in cases)
passed &= len(final) == 1 and final[0].get('PASS') is True and final[0].get('expected') == final[0].get('completed') == 3
c.require(c.identity(host['path']) == host and c.current_source_digest(root) == build['source']
          and c.current_source_digest(R) == live and c.identity(old_path) == old_id, '前後同一性')
c.save(out / 'SUMMARY.json', {'status': 'PASS' if passed else 'FAIL', 'complete': True,
       'expected_cases': 3, 'completed_cases': len(cases), 'cases': cases, 'final': final,
       'returncode': run.returncode, 'log': c.identity(log), 'expected': c.identity(out / 'EXPECTED.json'),
       'new_reference_renders': 0, 'independent_fixed_PCM': bool(passed),
       'performance_approval': False, 'realtime_approval': False})
print('isolated_checkpoint', 'PASS' if passed else 'FAIL')
sys.exit(0 if passed else 2)
