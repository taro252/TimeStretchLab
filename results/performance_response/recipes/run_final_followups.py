"""主比較の完了を待ち、事前固定したCPU2層とwarm独立PCMだけを追加する。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
B = ROOT / 'build/performance_response_20261023_01'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--queue', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
common.require(out.is_relative_to(B), 'new evidence under build/')
out.mkdir(parents=True, exist_ok=False)
source = '0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e'
common.require(common.current_source_digest(ROOT) == source, 'fixed source')
jobs = [
    {'id': 'CPU_targeted_12', 'command': [sys.executable, str(Path(__file__).with_name('run_steady_followup.py')),
        '--primary-run', str(B / 'steady_pairs_final06'), '--baseline-client', str(B / 'frozen_clients_02/CLIENT.json'),
        '--candidate-build', str(B / 'build_timer_candidate_05/BUILD.json'), '--output', str(B / 'steady_followup_final06')], 'timeout_s': 1200},
    {'id': 'warm_independent_24', 'command': [sys.executable, str(Path(__file__).with_name('validate_warm_ab_captures.py')),
        '--run', str(B / 'warm_ab_pairs_final06'), '--client', str(B / 'warm_ab_clients_final06/CLIENT.json'),
        '--references', str(B / 'ab_fixed_references_final_01/REFERENCES.json'), '--candidate-source', source,
        '--output', str(B / 'warm_ab_capture_audit_final06')], 'timeout_s': 1200}]
for job in jobs:
    job['driver'] = common.identity(job['command'][1])
common.save(out / 'EXPECTED.json', {'driver': common.identity(__file__), 'source': source, 'wait_for_queue': str(a.queue.resolve()),
    'jobs': jobs, 'expected_drivers': 2, 'all_expected_ids': [j['id'] for j in jobs], 'serial_after_primary': True,
    'CPU_original48_preserved': True, 'CPU_additional_programs': 12, 'warm_captures': 24, 'warm_checks': 120})
print('waiting for complete primary serial queue', flush=True)
deadline = time.monotonic() + 7200
while True:
    try:
        q = common.load(a.queue / 'SUMMARY.json')
    except (OSError, ValueError):
        q = {}
    if q.get('complete') is True:
        common.require(q['executed_steps'] == q['expected_steps'] == 19, 'all planned primary steps required')
        break
    common.require(time.monotonic() < deadline, 'primary queue did not complete')
    time.sleep(5)
common.save(out / 'PRIMARY_QUEUE.json', {'queue_summary': common.identity(a.queue / 'SUMMARY.json'), 'status': q['status'],
    'scope': 'completion only; individual failures preserved and not promoted to PASS'})
rows = []
env = dict(os.environ, PATH='/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin')
for job in jobs:
    common.require(common.current_source_digest(ROOT) == source and common.identity(job['driver']['path']) == job['driver'], 'source/recipe changed')
    print('START', job['id'], flush=True)
    started = time.monotonic()
    with (out / (job['id'] + '.log')).open('w') as log:
        code = subprocess.run(job['command'], stdout=log, stderr=subprocess.STDOUT, env=env, timeout=job['timeout_s']).returncode
    rows.append({'id': job['id'], 'returncode': code, 'wall_s': time.monotonic() - started,
                 'log': common.identity(out / (job['id'] + '.log'))})
    common.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_drivers': 2, 'executed_drivers': len(rows), 'rows': rows})
    print('END', job['id'], code, flush=True)
common.save(out / 'SUMMARY.json', {'status': 'PASS' if all(x['returncode'] == 0 for x in rows) else 'COMPLETE_WITH_FAILURES',
    'complete': True, 'expected_drivers': 2, 'executed_drivers': len(rows), 'rows': rows, 'source': source})
sys.exit(0 if all(x['returncode'] == 0 for x in rows) else 2)
