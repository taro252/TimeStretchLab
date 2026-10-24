"""Debugの計画52、設定20、完全保存状態2fixtureを検査。RT性能とは分ける。"""
import argparse
import json
from pathlib import Path
import sys
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import source_manifest

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--build-record', type=Path, required=True)
p.add_argument('--base', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
common.require(out.is_relative_to(ROOT / 'build'), 'evidence under build/')
out.mkdir(parents=True, exist_ok=False)
b = common.load(a.build_record)
common.require(b['status'] == 'PASS' and b['configuration'] == 'Debug' and b['architecture'] == 'arm64', 'Debug arm64 build required')
common.require(source_manifest(ROOT)['sha256'] == b['source'], 'frozen source')
jobs = []
for preset in ('candidate', 'baseline'):
    host = b['binaries']['performance_planner_tests']
    jobs.append({'id': 'planner_' + preset, 'kind': 'planner', 'checks': 26, 'binary': host,
        'command': [host['path'], str((a.base / 'inputs/mono48_16s.wav').resolve()), preset, str(out / ('planner_' + preset)), b['source']]})
for key, inp in (('mix', ROOT / 'results/phase31/input/mix.wav'), ('stereo441', a.base / 'inputs/stereo441_16s.wav')):
    host = b['binaries']['phase61_checkpoint_tests']
    jobs.append({'id': 'checkpoint_' + key, 'kind': 'checkpoint', 'checks': None, 'binary': host, 'command': [host['path'], str(inp.resolve())]})
host = b['binaries']['progressive_adoption_contract_tests']
jobs.append({'id': 'contract', 'kind': 'contract', 'checks': 20, 'binary': host, 'command': [host['path']]})
record = {'schema': 'performance-debug-functional-v1', 'status': 'INCOMPLETE', 'source': b['source'],
    'build': common.identity(a.build_record), 'driver': common.identity(__file__), 'helper': common.identity(common.__file__),
    'jobs': jobs, 'expected_programs': 5, 'expected_planner_checks': 52, 'expected_contract_checks': 20,
    'expected_positive_checkpoint_fixtures': 2, 'audio_output': False, 'RT_approval': False,
    'inputs': [common.identity(a.base / 'inputs/mono48_16s.wav'), common.identity(a.base / 'inputs/stereo441_16s.wav'), common.identity(ROOT / 'results/phase31/input/mix.wav')]}
common.save(out / 'EXPECTED.json', record)
rows = []
for job in jobs:
    common.require(common.identity(job['binary']['path']) == job['binary'], 'binary SHA')
    log = out / (job['id'] + '.log')
    execution = common.execute(job['command'], log, 240)
    ok = execution['returncode'] == 0 and not execution['timeout'] and not execution['interrupted']
    details = None
    if job['kind'] == 'planner':
        details = common.load(out / job['id'] / 'SUMMARY.json')
        expected = common.load(out / job['id'] / 'EXPECTED.json')
        checks = [json.loads(x) for x in (out / job['id'] / 'checks.jsonl').read_text().splitlines()]
        ok = ok and details['status'] == 'PASS' and details['run_complete'] and details['expected'] == details['executed'] == len(checks) == 26 and [x['id'] for x in checks] == expected['required_ids'] and all(x['pass'] is True for x in checks)
    elif job['kind'] == 'checkpoint':
        ok = ok and log.read_text().startswith('PASS fixed/dynamic checkpoint full suffix')
    else:
        records = [json.loads(x) for x in log.read_text().splitlines() if x.startswith('{')]
        expected, checks, details = records[0], records[1:-1], records[-1]
        ok = ok and expected['contract_version'] == 4 and expected['expected'] == len(checks) == 20 and [x['id'] for x in checks] == expected['required_ids'] and all(x['status'] == 'PASS' for x in checks) and details['status'] == 'PASS' and details['executed'] == details['expected'] == 20 and details['run_complete']
    rows.append({'id': job['id'], 'PASS': bool(ok), 'execution': execution, 'result': details, 'log': common.identity(log)})
    common.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_programs': 5, 'executed_programs': len(rows), 'rows': rows})
    print(job['id'], bool(ok), flush=True)
common.require(source_manifest(ROOT)['sha256'] == b['source'], 'source changed during run')
for job in jobs:
    common.require(common.identity(job['binary']['path']) == job['binary'], 'binary changed')
complete = len(rows) == 5
common.save(out / 'SUMMARY.json', {'status': 'PASS' if complete and all(x['PASS'] for x in rows) else 'INCOMPLETE_OR_FAIL', 'complete': complete,
    'expected_programs': 5, 'executed_programs': len(rows), 'rows': rows, 'audio_output': False, 'RT_approval': False,
    'expected': common.identity(out / 'EXPECTED.json')})
sys.exit(0 if complete and all(x['PASS'] for x in rows) else 2)
