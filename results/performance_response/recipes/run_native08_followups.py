#!/usr/bin/env python3
"""最終08の残る機能・応答・PCM検査を直列実施する。旧queueは使わない。"""
import argparse
import datetime
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile

sys.dont_write_bytecode = True
import run_pairs as c
import native08_driver_supervisor as supervisor


def interrupted(signum, frame):
    raise KeyboardInterrupt('queue signal ' + str(signum))


signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)

R = Path(__file__).resolve().parents[3]
B = R / 'build/performance_response_20261023_01'
S = Path(__file__).resolve().parent
SOURCE = 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
c.require(out.is_relative_to(B), 'B内の新規出力先')
out.mkdir(exist_ok=False)
steady = c.load(B / 'steady_pairs_native08/SUMMARY.json')
c.require(steady.get('complete') is True and
          steady['executed_programs'] == steady['expected_programs'] == 48,
          'CPU48がすべて終了・回収済みであること。音声試験を重ねない')
c.require(c.current_source_digest(R) == SOURCE, '最終08のみ')
build = B / 'build_native_default_08/BUILD.json'
base = B / 'frozen_clients_02/CLIENT.json'
obs = B / 'ab_observation_clients_native08/CLIENT.json'
warm = B / 'warm_ab_clients_native08/CLIENT.json'
deep = B / 'paused_deep_clients_native08/CLIENT.json'
jobs = []


def add(key, script, args, timeout=1800, native=False, needs=()):
    path = S / script
    jobs.append({'id': key, 'command': [sys.executable, '-B', str(path), *map(str, args)],
                 'driver': c.identity(path), 'timeout_s': timeout, 'native': native,
                 'needs': list(needs),
                 'requires_zero_exit': script.startswith('build_') or script == 'prepare_native08_abi_record.py'})


add('related12', 'run_d3_regressions.py',
    ['--build-record', build, '--extra-build-record', build,
     '--output', B / 'd3_related_native08'], 2400, True)
add('interactive48', 'run_interactive_generic_pairs.py',
    ['--client', B / 'interactive_clients_native08/CLIENT.json',
     '--output', B / 'interactive_pairs_native08'], 2400, True)
add('observation_clients', 'build_generic_ab_observation_clients.py',
    ['--candidate-build', build, '--source-sha', SOURCE,
     '--output', B / 'ab_observation_clients_native08'], 300)
add('warm_clients', 'build_generic_warm_ab_clients_v2.py',
    ['--candidate-build', build, '--source-sha', SOURCE,
     '--output', B / 'warm_ab_clients_native08'], 300)
add('deep_clients', 'build_generic_paused_deep_clients_v2.py',
    ['--candidate-build', build, '--source-sha', SOURCE,
     '--output', B / 'paused_deep_clients_native08'], 300)
add('abi_full_archive', 'prepare_native08_abi_record.py', [], 180)
add('abi9', 'run_generic_abi_header_checks_v2.py',
    ['--candidate-build', build, '--candidate-snapshot', B / 'native_source_08/SOURCE.json',
     '--comparison-snapshot', B / 'timer_source_05/SOURCE.json',
     '--archive', B / 'native_archive_08/ABI_ARCHIVE60.json', '--expected-artifacts', '60',
     '--source-sha', SOURCE, '--observation-clients', obs,
     '--output', B / 'abi_headers_native08'], 300, needs=('observation_clients', 'abi_full_archive'))
add('warm12', 'run_generic_warm_ab_pairs_v3.py',
    ['--client', warm, '--source-sha', SOURCE, '--output', B / 'warm_ab_pairs_native08'],
    1800, True, ('warm_clients',))
add('deep6', 'run_paused_deep_pairs_v2.py',
    ['--client', deep, '--output', B / 'paused_deep_pairs_native08'],
    1800, True, ('deep_clients',))
add('independent_warm24', 'validate_warm_ab_captures_v3.py',
    ['--run', B / 'warm_ab_pairs_native08', '--client', warm,
     '--references', B / 'ab_fixed_references_final_01/REFERENCES.json',
     '--candidate-source', SOURCE, '--output', B / 'warm_ab_capture_audit_native08'],
    1800, needs=('warm12',))
add('fresh72', 'run_ab_main_pairs_bounded.py',
    ['--baseline-client', base, '--candidate-build', build, '--observation-clients', obs,
     '--mono-input', R / 'results/phase56/long/chain_300s.wav',
     '--stereo-input', B / 'ab_stereo48_input_01/music_48000_2_300s.wav',
     '--output', B / 'ab_main_pairs_native08'], 4200, True, ('observation_clients',))
add('nonfresh36', 'run_pairs.py',
    ['--baseline-client', base, '--candidate-build', build, '--suite', 'ab',
     '--only', 'A30_prewarm_candidate', 'A270_prewarm_candidate',
     'A30_early0_candidate', 'A270_early0_candidate', 'A30_mid_candidate', 'A270_mid_candidate',
     '--output', B / 'ab_nonfresh_pairs_native08'], 2400, True)
add('independent_AB108', 'validate_ab_captures_v2.py',
    ['--main-run', B / 'ab_main_pairs_native08', '--nonfresh-run', B / 'ab_nonfresh_pairs_native08',
     '--references', B / 'ab_fixed_references_final_01/REFERENCES.json', '--host-manifest', obs,
     '--candidate-source', SOURCE, '--output', B / 'ab_capture_audit_native08'],
    1800, needs=('fresh72', 'nonfresh36'))
supervisor_identity = c.identity(supervisor.__file__)
c.save(out / 'EXPECTED.json', {'source': SOURCE, 'driver': c.identity(__file__),
       'supervisor': supervisor_identity,
       'steady_completed': c.identity(B / 'steady_pairs_native08/SUMMARY.json'),
       'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
       'expected_steps': len(jobs), 'jobs': jobs, 'all_expected_ids': [j['id'] for j in jobs],
       'serial': True, 'counts_are_driver_completion_only': True,
       'acceptance': '各元SUMMARYの機能・CPU・RT・品質・目標を個別判定。rc2を成功へ変えない。',
       'physical_audio': None, 'application_F': None})
rows = []
queue_error = None
try:
    for job in jobs:
        execution = None
        c.require(c.current_source_digest(R) == SOURCE and c.identity(job['driver']['path']) == job['driver']
                  and c.identity(supervisor.__file__) == supervisor_identity, 'ソースまたはrecipeが変わった')
        prior = {r['id']: r for r in rows}
        blocked = [key for key in job['needs'] if prior.get(key, {}).get('status') != 'COMPLETED']
        free = min(shutil.disk_usage(B).free, shutil.disk_usage(tempfile.gettempdir()).free)
        floor = 512 * 1024 * 1024 if job['id'] == 'related12' else 115200100 + 256 * 1024 * 1024 + 16 * 1024 * 1024
        if job['native'] and free < floor:
            blocked.append('容量guard: free=' + str(free) + ',required=' + str(floor))
        if blocked:
            row = {'id': job['id'], 'status': 'BLOCKED', 'reasons': blocked, 'execution': None}
        else:
            before_quiescence = supervisor.assert_managed_quiescent(B)
            print('START', job['id'], flush=True)
            execution = supervisor.execute(job['command'], out / (job['id'] + '.log'), job['timeout_s'])
            after_quiescence = supervisor.assert_managed_quiescent(B)
            allowed_exits = (0,) if job['requires_zero_exit'] else (0, 2)
            completed = (not execution['timeout'] and not execution['interrupted'] and execution['returncode'] in allowed_exits
                         and execution['cleanup_confirmed'] is True and execution['next_job_allowed'] is True)
            # rc2には目標未達や不完全試行も含まれる。依存監査は元証拠を再検査する。
            row = {'id': job['id'], 'status': 'COMPLETED' if completed else 'INCOMPLETE',
                   'returncode_is_not_test_verdict': True, 'execution': execution,
                   'before_quiescence': before_quiescence, 'after_quiescence': after_quiescence}
            print('END', job['id'], execution['returncode'], row['status'], flush=True)
        rows.append(row)
        c.save(out / 'SUMMARY.json', {'source': SOURCE, 'status': 'IN_PROGRESS',
               'expected_steps': len(jobs), 'executed_steps': len(rows), 'rows': rows})
        if row['execution'] and not row['execution']['next_job_allowed']:
            break
    c.require(c.current_source_digest(R) == SOURCE, '終了時ソース変更')
except BaseException as error:
    queue_error = type(error).__name__ + ': ' + str(error)
    c.save(out / 'QUEUE_EXCEPTION.json', {'source': SOURCE, 'error': queue_error,
           'current_job': job['id'] if 'job' in locals() else None,
           'execution': execution if 'execution' in locals() else None,
           'scope': '異常/排他未確認なら後続を起動しない。各元試験結果は変更しない。'})
complete = len(rows) == len(jobs) and queue_error is None
c.save(out / 'SUMMARY.json', {'source': SOURCE, 'status': 'COMPLETE_WITH_RESULTS' if complete else 'INCOMPLETE',
       'complete': complete, 'expected_steps': len(jobs), 'executed_steps': len(rows), 'rows': rows,
       'queue_error': queue_error,
       'test_verdict_scope': '個別SUMMARYを参照。driver完了は全体GOを意味しない。'})
sys.exit(0 if complete else 2)
