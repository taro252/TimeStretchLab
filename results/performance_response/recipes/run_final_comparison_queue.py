"""採用候補の残る比較を、一担当でbuild→検査→実音声の順に直列実行する。

全条件は各recipeのEXPECTEDへ実行前保存。性能FAILを成功へ変換しない。
既存証拠を上書きしない固定の新規出力先。再実行は新しい--run-suffixで行う。
"""
import argparse
import datetime
import os
from pathlib import Path
import subprocess
import sys
import time
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
B = ROOT / 'build/performance_response_20261023_01'
P = ROOT / 'build/progressive_adoption_20261023_01'
RECIPES = ROOT / 'results/performance_response/recipes'
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--candidate-build', type=Path, required=True)
p.add_argument('--candidate-snapshot', type=Path, required=True)
p.add_argument('--candidate-archive', type=Path, required=True)
p.add_argument('--source-sha', required=True)
p.add_argument('--run-suffix', required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
common.require(a.run_suffix.isalnum(), 'simple unique suffix')
out = a.output.resolve()
common.require(out.is_relative_to(B), 'evidence under build/')
out.mkdir(parents=True, exist_ok=False)
build = common.load(a.candidate_build)
common.require(build['status'] == 'PASS' and build['source'] == a.source_sha == common.current_source_digest(ROOT), 'fixed candidate build/source')
base_args = ['--candidate-build', str(a.candidate_build.resolve()), '--source-sha', a.source_sha]
suffix = a.run_suffix
def dest(name):
    return B / (name + '_' + suffix)
obs, warm, deep, inter = [dest(x) for x in ('ab_observation_clients', 'warm_ab_clients', 'paused_deep_clients', 'interactive_generic_clients')]
main, nonfresh = dest('ab_main_pairs'), dest('ab_nonfresh_pairs')
jobs = []
def add(key, script, args, timeout, required=False):
    jobs.append({'id': key, 'command': [sys.executable, str(RECIPES / script), *map(str, args)], 'timeout_s': timeout, 'required_build': required,
                 'recipe': common.identity(RECIPES / script)})
add('build_observation', 'build_generic_ab_observation_clients.py', [*base_args, '--output', obs], 240, True)
add('build_warm', 'build_generic_warm_ab_clients.py', [*base_args, '--output', warm], 240, True)
add('build_deep', 'build_generic_paused_deep_clients.py', [*base_args, '--output', deep], 240, True)
add('build_interactive', 'build_interactive_generic_clients.py', ['--candidate-build', a.candidate_build.resolve(),
    '--candidate-source', a.source_sha, '--candidate-archive', a.candidate_archive.resolve(),
    '--candidate-snapshot', a.candidate_snapshot.resolve(), '--output', inter], 300, True)
add('ABI', 'run_generic_abi_header_checks.py', [*base_args, '--candidate-snapshot', a.candidate_snapshot.resolve(),
    '--comparison-snapshot', B / 'final_source_03/SOURCE.json', '--archive', a.candidate_archive.resolve(),
    '--observation-clients', obs / 'CLIENT.json', '--output', dest('abi_headers')], 300)
add('Debug_functional', 'run_debug_functional.py', ['--build-record', B / 'build_debug_01/BUILD.json', '--base', P, '--output', dest('debug_functional')], 900)
add('Debug_checkpoint', 'run_checkpoint_rejection.py', ['--build-record', B / 'build_debug_01/BUILD.json', '--output', dest('debug_checkpoint')], 600)
add('Interactive_240', 'run_interactive_generic_pairs.py', ['--client', inter / 'CLIENT.json', '--output', dest('interactive_pairs')], 1800)
add('steady_48', 'run_pairs.py', ['--baseline-client', B / 'frozen_clients_02/CLIENT.json', '--candidate-build', a.candidate_build.resolve(),
    '--suite', 'steady', '--output', dest('steady_pairs')], 2400)
add('share_retained_AB', 'share_capture_extents.py', ['--roots', B / 'ab_main_pairs_final_01', B / 'ab_pairs_03',
    '--output', dest('retained_AB_extents.json')], 300)
add('fresh_AB_72', 'run_ab_main_pairs.py', ['--baseline-client', B / 'frozen_clients_02/CLIENT.json', '--candidate-build', a.candidate_build.resolve(),
    '--observation-clients', obs / 'CLIENT.json', '--mono-input', ROOT / 'results/phase56/long/chain_300s.wav',
    '--stereo-input', B / 'ab_stereo48_input_01/music_48000_2_300s.wav', '--output', main], 3600)
add('share_fresh_AB', 'share_capture_extents.py', ['--roots', main, '--output', dest('fresh_AB_extents.json')], 300)
add('nonfresh_AB_36', 'run_pairs.py', ['--baseline-client', B / 'frozen_clients_02/CLIENT.json', '--candidate-build', a.candidate_build.resolve(),
    '--suite', 'ab', '--only', 'A30_prewarm_candidate', 'A270_prewarm_candidate', 'A30_early0_candidate', 'A270_early0_candidate',
    'A30_mid_candidate', 'A270_mid_candidate', '--output', nonfresh], 2400)
add('share_nonfresh_AB', 'share_capture_extents.py', ['--roots', nonfresh, '--output', dest('nonfresh_AB_extents.json')], 300)
add('warm_AB_12', 'run_generic_warm_ab_pairs.py', ['--client', warm / 'CLIENT.json', '--source-sha', a.source_sha, '--output', dest('warm_ab_pairs')], 1800)
add('share_warm_AB', 'share_capture_extents.py', ['--roots', dest('warm_ab_pairs'), '--output', dest('warm_AB_extents.json')], 300)
add('Paused_deep_6', 'run_paused_deep_pairs.py', ['--client', deep / 'CLIENT.json', '--output', dest('paused_deep_pairs')], 1200)
add('diagnostic_sample_2', 'run_generic_diagnostic_sample.py', [*base_args, '--output', dest('diagnostic_sample')], 300)
add('AB_independent_108', 'validate_ab_captures.py', ['--main-run', main, '--nonfresh-run', nonfresh,
    '--references', B / 'ab_fixed_references_final_01/REFERENCES.json', '--host-manifest', obs / 'CLIENT.json',
    '--candidate-source', a.source_sha, '--output', dest('ab_capture_audit')], 1200)
expected = {'schema': 'performance-final-comparison-queue-v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'driver': common.identity(__file__), 'helper': common.identity(common.__file__), 'source': a.source_sha,
    'candidate_build': common.identity(a.candidate_build), 'candidate_snapshot': common.identity(a.candidate_snapshot),
    'candidate_archive': common.identity(a.candidate_archive), 'serial_audio_build_profile': True, 'jobs': jobs,
    'performance_failure_not_success': True, 'past_counts_reused_as_new': False}
common.save(out / 'EXPECTED.json', expected)
rows = []
env = dict(os.environ, PATH='/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin')
for job in jobs:
    common.require(common.current_source_digest(ROOT) == a.source_sha, 'source changed')
    common.require(common.identity(job['recipe']['path']) == job['recipe'], 'recipe changed after plan')
    print('START', job['id'], flush=True)
    started = time.monotonic()
    with (out / (job['id'] + '.log')).open('w') as log:
        code = subprocess.run(job['command'], stdout=log, stderr=subprocess.STDOUT, env=env, timeout=job['timeout_s']).returncode
    row = {'id': job['id'], 'returncode': code, 'wall_s': time.monotonic() - started, 'log': common.identity(out / (job['id'] + '.log')),
           'scope': 'driver execution status only; complete/functional/latency/RT/quality gates remain separate in each SUMMARY'}
    rows.append(row)
    common.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_steps': len(jobs), 'executed_steps': len(rows), 'rows': rows})
    print('END', job['id'], code, flush=True)
    if code and job['required_build']:
        break
complete = len(rows) == len(jobs)
common.save(out / 'SUMMARY.json', {'status': 'PASS' if complete and all(r['returncode'] == 0 for r in rows) else 'COMPLETE_WITH_FAILURES' if complete else 'INCOMPLETE',
    'complete': complete, 'expected_steps': len(jobs), 'executed_steps': len(rows), 'rows': rows, 'source': a.source_sha,
    'expected': common.identity(out / 'EXPECTED.json')})
sys.exit(0 if complete and all(r['returncode'] == 0 for r in rows) else 2)
