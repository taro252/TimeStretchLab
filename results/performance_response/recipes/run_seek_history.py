"""D3の固定30 program/300 check計画を直列実行し、CPU/RT/機能を別集計する。

arm64版Pythonで実行する。例:
  python3 results/performance_response/recipes/run_seek_history.py \
    --client-record B/seek_history_clients_01/CLIENT.json --output B/seek_history_pairs_01
RUN_PLANの出力引数だけをNEW_OUTPUT/<ID>へ置換する。既存出力は再利用しない。
タイムアウト・欠落・途中終了は合格扱いにせず、RT失敗でも残りの固定計画を記録する。
旧headerにないlatch診断はNOT_AVAILABLEとし、候補専用assertと混同しない。
"""
import argparse
import ctypes
import hashlib
import json
import math
import os
import pathlib
import platform
import signal
import statistics
import subprocess
import sys

import run_pairs as common


ROOT = pathlib.Path(__file__).resolve().parents[3]
COUNTS = (0, 1, 100, 1000, 4095)
CHECK_IDS = (
    'D3H01_empty_Ready_fixture', 'D3H02_N_Rejected_rows_stationary',
    'D3H03_explicit_Play_original_target', 'D3H04_Accepted_exact_ID_N_plus_1',
    'D3H05_first_callback_latch_and_target_identity', 'D3H06_CPU_window_latch_stops',
    'D3H07_Pause_C_stationary_terminal_immutable', 'D3H08_Stop_all_terminal_immutable',
    'D3H09_close_owned_all_IDs', 'D3H10_final_owner_checkpoint_heap_bounds',
)
CANDIDATE_LATCH_CHECKS = {
    'D3H03_explicit_Play_original_target': '元の非seek targetのvisits/latchesはともに0',
    'D3H05_first_callback_latch_and_target_identity': '採用targetのvisits>=1かつlatches==1',
    'D3H06_CPU_window_latch_stops': 'CPU窓の前後でvisits/latchesが増えない',
}
SEEK_FIELDS = frozenset((
    'mode', 'preroll_ms', 'id', 'input_generation', 'source_epoch', 'epoch', 'session',
    'requested_input', 'output_start', 'state', 'reason', 'code', 'speed_micros', 'replans',
    'accepted_ns', 'preparing_ns', 'ready_ns', 'switched_ns', 'first_callback_ns',
    'estimated_presentation_ns', 'stage', 'analysis_ready_ns', 'switch_ready_ns',
    'transition_begin_ns', 'transition_end_ns', 'old_fifo_at_switch', 'discarded_for_seek',
    'transition_frames', 'waited_for_analysis',
))


def output_device():
    """既定出力装置のID/バッファを読むだけ。装置の設定は変更しない。"""
    class Address(ctypes.Structure):
        _fields_ = [('selector', ctypes.c_uint32), ('scope', ctypes.c_uint32), ('element', ctypes.c_uint32)]
    audio = ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')
    get_data = audio.AudioObjectGetPropertyData
    get_data.argtypes = [ctypes.c_uint32, ctypes.POINTER(Address), ctypes.c_uint32, ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    get_data.restype = ctypes.c_int32
    def read(obj, selector):
        address = Address(int.from_bytes(selector.encode(), 'big'), int.from_bytes(b'glob', 'big'), 0)
        value, size = ctypes.c_uint32(), ctypes.c_uint32(ctypes.sizeof(ctypes.c_uint32))
        code = get_data(obj, ctypes.byref(address), 0, None, ctypes.byref(size), ctypes.byref(value))
        common.require(code == 0, 'CoreAudio read ' + selector + ': ' + str(code))
        return value.value
    device = read(1, 'dOut')
    common.require(device != 0, 'default output device unavailable')
    return {'default_output_device': device, 'buffer_frames': read(device, 'fsiz'), 'configuration_changed': False}


def lines(path):
    def reject_constant(value):
        raise ValueError('non-finite JSON: ' + value)
    return [json.loads(line, parse_constant=reject_constant) for line in path.read_text().splitlines() if line.strip()]


def fixed_jobs(client, plan, out):
    common.require(plan['schema'] == 'seek-history-pairs-v1' and plan['status'] == 'NOT_RUN', 'wrong RUN_PLAN')
    common.require(plan['expected_programs'] == 30 and plan['expected_checks'] == 300, 'fixed 30/300 matrix required')
    common.require(client['history_strata'] == list(COUNTS) and client['real_seek_limit'] == 4096, 'history strata/limit')
    common.require(set(client['clients']) == {'old', 'candidate'}, 'old/candidate client pair missing')
    common.require(plan['client_source_sha256'] == client['source']['sha256'] == client['copied_source']['sha256'], 'same source identity')
    common.require(plan['input'] == client['input'], 'input record mismatch')
    seconds = plan['cpu_window_s']
    common.require(common.finite(seconds) and 5 <= seconds <= 30, 'CPU window must be finite and >=5 seconds')
    expected = []
    for repeat in (1, 2, 3):
        for count in COUNTS:
            order = ('old', 'candidate') if repeat % 2 else ('candidate', 'old')
            for version in order:
                pair = f'N{count}_candidate_r{repeat:02d}'
                expected.append((pair + '_' + version, pair, count, repeat, version))
    common.require(len(plan['jobs']) == len(expected), 'plan job count')
    common.require(plan['all_expected_ids'] == [row[0] for row in expected], 'plan ID set/order')
    jobs = []
    for raw, (key, pair, count, repeat, version) in zip(plan['jobs'], expected):
        common.require(raw['id'] == key and raw['pair_id'] == pair and raw['history_N'] == count and
                       raw['Accepted_ID'] == count + 1 and raw['checks'] == 10 and
                       raw['final_audit_IDs'] == '1..' + str(count + 1), 'plan case identity: ' + key)
        compiled = client['clients'][version]
        command = raw['command']
        common.require(len(command) == 8 and command[0] == compiled['binary']['path'] and
                       command[1] == client['input']['path'] and command[2] == 'candidate' and
                       command[3] == str(count) and float(command[4]) == seconds and
                       command[6] == compiled['source'] and command[7] == version, 'plan command mismatch: ' + key)
        actual = command.copy()
        actual[5] = str(out / key)
        jobs.append({'id': key, 'pair_id': pair, 'history_N': count, 'repeat': repeat, 'version': version,
                     'original_command': command, 'command': actual, 'checks': 10,
                     'expected_audit_rows': count + 1, 'expected_Accepted_IDs': [count + 1]})
    return jobs


def compile_inventory(client, client_record, plan_path):
    """compile時に記録されたsource/header/archive/binary/flagsを重複なく固定する。"""
    inventory = {}
    def add(item, label):
        path = str(pathlib.Path(item['path']).resolve())
        expected = {key: item[key] for key in ('path', 'bytes', 'sha256')}
        common.require(expected['path'] == path, 'compile record path must be absolute')
        if path in inventory:
            common.require(inventory[path]['identity'] == expected, 'conflicting compile dependency SHA')
            inventory[path]['roles'].append(label)
        else:
            inventory[path] = {'identity': expected, 'roles': [label]}
    add(common.identity(client_record), 'client_compile_manifest')
    add(client['run_plan'], 'run_plan')
    common.require(pathlib.Path(client['run_plan']['path']).resolve() == plan_path, 'run plan path')
    for key in ('source', 'copied_source', 'driver', 'compile_helper', 'baseline_client', 'candidate_build', 'input'):
        add(client[key], key)
    for version, compiled in client['clients'].items():
        common.require(compiled['latch_diagnostics_compiled'] is (version == 'candidate'), 'diagnostic compile flag')
        common.require(compiled['prepare_ABI'] == ('ContractV3Tag' if version == 'old' else 'ContractV4Tag'), 'prepare ABI')
        for key in ('binary', 'object', 'depfile', 'compiler', 'flags_file', 'link_template', 'undefined_symbols'):
            add(compiled[key], version + ':' + key)
        for key in ('dependencies', 'libraries'):
            for item in compiled[key]:
                add(item, version + ':' + key)
    # compile/linkログも元recordのidentityを再確認する。
    for row in client['commands']:
        common.require(row['returncode'] == 0, 'compile/link command did not succeed')
        add(row['log'], 'compile_or_link_log')
    add(common.identity(__file__), 'run_driver')
    add(common.identity(common.__file__), 'run_driver_helper')
    return list(inventory.values())


def verify_inventory(inventory, path):
    mismatches = []
    for row in inventory:
        expected = row['identity']
        try:
            actual = common.identity(expected['path'])
            if actual != expected:
                mismatches.append({'expected': expected, 'actual': actual, 'roles': row['roles']})
        except OSError as error:
            mismatches.append({'expected': expected, 'error': str(error), 'roles': row['roles']})
    result = {'status': 'PASS' if not mismatches else 'FAIL', 'expected_files': len(inventory),
              'checked_files': len(inventory), 'mismatches': mismatches,
              'manifest_sha256': common.manifest_digest(inventory)}
    common.save(path, result)
    common.require(not mismatches, 'frozen compile/input inventory changed: ' + str(path))
    return result


def assess(job, directory, execution, client, seconds, device_rate, device_buffer):
    summary = common.load(directory / 'SUMMARY.json')
    expected = common.load(directory / 'EXPECTED.json')
    checks = lines(directory / 'checks.jsonl')
    rejected = lines(directory / 'before_rejected.jsonl')
    adopted = lines(directory / 'after_first_callback.jsonl')
    owned = lines(directory / 'close_owned.jsonl')
    integrity_errors, functional_errors, measurement_errors = [], [], []
    def check(group, condition, message):
        if not condition:
            group.append(message)
    count, version = job['history_N'], job['version']
    check(integrity_errors, not execution['timeout'] and not execution['interrupted'], 'timeout/interrupted')
    check(integrity_errors, summary.get('history_N') == count and summary.get('accepted_id') == count + 1 and
          summary.get('preset') == 'candidate' and summary.get('version') == version, 'summary case identity')
    check(integrity_errors, summary.get('source') == client['clients'][version]['source'] and
          summary.get('input_sha256') == client['input']['sha256'] and
          summary.get('binary_sha256') == client['clients'][version]['binary']['sha256'], 'summary source/input/binary SHA')
    check(integrity_errors, isinstance(summary.get('rt_pass'), bool), 'RT result missing')
    check(integrity_errors, execution['returncode'] == (0 if summary.get('rt_pass') else 2), 'returncode/RT mismatch')
    check(functional_errors, summary.get('functional') is True and summary.get('complete') is True, 'host functional/incomplete')
    check(functional_errors, summary.get('expected') == summary.get('executed') == 10 and
          [row.get('id') for row in checks] == list(CHECK_IDS) and all(row.get('status') == 'PASS' for row in checks), 'fixed check ID set/status')
    check(integrity_errors, expected.get('required_ids') == list(CHECK_IDS) and expected.get('expected') == 10 and
          expected.get('history_N') == count and expected.get('Accepted_ID') == count + 1 and
          expected.get('expected_final_audit_rows') == count + 1 and expected.get('real_lifetime_limit') == 4096 and
          expected.get('callback_gate') is False and expected.get('history_copy_in_cpu_window') is False, 'host expected contract')
    marker, final_rows = (owned[0], owned[1:]) if owned else ({}, [])
    check(functional_errors, len(rejected) == count and len(adopted) == len(final_rows) == count + 1 and
          summary.get('final_audit_rows') == count + 1, 'audit row count')
    check(functional_errors, marker.get('record') == 'owned_audit' and marker.get('calls') == 1 and
          marker.get('copied') == marker.get('workers_joined') == marker.get('retired') == 1 and
          marker.get('error') == 0 and marker.get('rows') == count + 1 and
          common.finite(marker.get('engine_serial')) and marker['engine_serial'] > 0 and
          common.finite(marker.get('preparation')) and marker['preparation'] > 0, 'final audit copy/all joins/identity')
    wanted = list(range(1, count + 2))
    for label, values, ids in (('rejected', rejected, wanted[:-1]), ('adopted', adopted, wanted), ('owned', final_rows, wanted)):
        check(functional_errors, [row.get('id') for row in values] == ids, label + ' exact ID set/order')
        check(functional_errors, all(set(row) == SEEK_FIELDS for row in values), label + ' complete seek field set')
    check(functional_errors, adopted[:count] == rejected and final_rows == adopted, 'terminal full-field values changed')
    check(functional_errors, all(row.get('state') == 'Rejected' and row.get('code') == 'InvalidRange' for row in rejected), 'past rejection facts')
    accepted = adopted[-1] if adopted else {}
    check(functional_errors, accepted.get('id') == count + 1 and accepted.get('state') == 'Completed' and
          accepted.get('mode') == 0 and accepted.get('speed_micros') == 1000000 and accepted.get('code') == 'Available' and
          accepted.get('requested_input') == summary.get('source_rate', 0) * 2 and
          all(common.finite(accepted.get(key)) and accepted[key] > 0 for key in
              ('input_generation', 'source_epoch', 'epoch', 'session', 'first_callback_ns', 'estimated_presentation_ns')) and
          accepted.get('source_epoch') != accepted.get('epoch'), 'Accepted Exact timing/target facts')
    check(functional_errors, summary.get('owner_alive') == 0 and common.finite(summary.get('owner_peak')) and
          summary['owner_peak'] <= 2 and common.finite(summary.get('checkpoint_peak')) and summary['checkpoint_peak'] <= 2, 'owner/checkpoint bound')
    check(functional_errors, all(summary.get(key) == 0 for key in
          ('missing', 'rejected_writes', 'callback_cpp_new', 'callback_heap_allocations', 'callback_heap_frees')), 'supply/callback allocations')
    check(integrity_errors, summary.get('source_rate') == 48000 and summary.get('device_rate') == device_rate and
          summary.get('device_buffer') == device_buffer, 'fixed source/device rate/buffer')
    cpu, wall, percent = (summary.get(key) for key in ('cpu_s', 'wall_s', 'cpu_percent'))
    check(measurement_errors, common.finite(cpu) and cpu >= 0 and common.finite(wall) and seconds <= wall <= seconds + 2 and
          common.finite(percent) and percent >= 0, 'finite CPU measurement/window')
    if all(common.finite(value) for value in (cpu, wall, percent)) and wall > 0:
        check(measurement_errors, math.isclose(percent, 100 * cpu / wall, rel_tol=1e-9, abs_tol=1e-8), 'CPU formula')
    check(measurement_errors, common.finite(summary.get('polls')) and summary['polls'] >= seconds * 4 and
          common.finite(summary.get('interrupt_wakeups')) and summary['interrupt_wakeups'] >= 0, 'control polling/wakeups')
    timing_before, timing_after = summary.get('timing_before'), summary.get('timing_after')
    if version == 'candidate':
        timing_valid = (summary.get('timing_diagnostics_compiled') is True and isinstance(timing_before, dict) and
                        isinstance(timing_after, dict) and set(timing_before) == set(timing_after) == {'visits', 'latches'} and
                        common.finite(timing_before.get('visits')) and timing_before['visits'] >= 1 and
                        timing_before.get('latches') == 1 and timing_before == timing_after)
        check(functional_errors, timing_valid, 'candidate target latch/visits did not stop')
        latch = {'status': 'PASS' if timing_valid else 'FAIL', 'candidate_only': True,
                 'check_ids': CANDIDATE_LATCH_CHECKS, 'before': timing_before, 'after': timing_after,
                 'original_target_zero': 'host D3H03 assert; counters before Play are not separately exported'}
    else:
        check(integrity_errors, summary.get('timing_diagnostics_compiled') is False and
              timing_before is None and timing_after is None, 'old diagnostic must remain unavailable')
        latch = {'status': 'NOT_AVAILABLE', 'candidate_only': False, 'approved': False,
                 'reason': '旧v3 headerに内部visits/latchesなし。旧CPU/公開API検査から内部停止を推定しない。'}
    rt = summary.get('rt_pass') is True
    if rt:
        check(integrity_errors, summary.get('worker_deadlines') == summary.get('callback_deadlines') == 0, 'RT boolean/counters mismatch')
    return {'summary': summary, 'integrity_pass': not integrity_errors, 'functional_pass': not functional_errors,
            'measurement_pass': not measurement_errors, 'rt_pass': rt,
            'integrity_errors': integrity_errors, 'functional_errors': functional_errors, 'measurement_errors': measurement_errors,
            'checks_passed': sum(row.get('status') == 'PASS' for row in checks), 'candidate_latch': latch,
            'audit': {'scope': job['id'], 'engine_serial': marker.get('engine_serial'),
                      'preparation': marker.get('preparation'), 'expected_rows': count + 1,
                      'recovered_rows': len(final_rows), 'all_IDs_verified':
                      [row.get('id') for row in final_rows] == wanted, 'Accepted_IDs': [count + 1],
                      'compared_seek_fields': len(SEEK_FIELDS), 'full_field_equal': adopted[:count] == rejected and final_rows == adopted}}


def aggregate(rows):
    groups = []
    for count in COUNTS:
        versions = {}
        for version in ('old', 'candidate'):
            selected = [row for row in rows if row['history_N'] == count and row['version'] == version]
            valid = [row for row in selected if all(row.get(key) for key in ('integrity_pass', 'functional_pass', 'measurement_pass'))]
            values = [row['summary']['cpu_percent'] for row in valid]
            clean = [row['summary']['cpu_percent'] for row in valid if row.get('rt_pass')]
            versions[version] = {'expected': 3, 'executed': len(selected), 'valid': len(valid), 'samples': values,
                'mean': statistics.mean(values) if values else None, 'median': common.percentile(values, .5),
                'p95': common.percentile(values), **common.dispersion(values), 'rt_clean_samples': clean,
                'rt_clean_mean': statistics.mean(clean) if clean else None,
                'rt_all_pass': len(selected) == 3 and all(row.get('rt_pass') for row in selected),
                'latch_status': 'CANDIDATE_ASSERTED' if version == 'candidate' else 'NOT_AVAILABLE_NOT_APPROVED'}
        pairs = []
        for repeat in (1, 2, 3):
            match = {row['version']: row for row in rows if row['history_N'] == count and row['repeat'] == repeat}
            if set(match) == {'old', 'candidate'} and all(all(row.get(key) for key in
                    ('integrity_pass', 'functional_pass', 'measurement_pass')) for row in match.values()):
                old, candidate = (match[version]['summary']['cpu_percent'] for version in ('old', 'candidate'))
                pairs.append({'repeat': repeat, 'old_cpu_percent': old, 'candidate_cpu_percent': candidate,
                    'candidate_over_old': candidate / old if old else None,
                    'reduction_percent': 100 * (old - candidate) / old if old else None,
                    'both_rt_pass': all(row['rt_pass'] for row in match.values())})
        reductions = [pair['reduction_percent'] for pair in pairs if pair['reduction_percent'] is not None]
        ranges = list(versions.values())
        overlap = max(item['min'] for item in ranges) <= min(item['max'] for item in ranges) if all(item['min'] is not None for item in ranges) else None
        groups.append({'history_N': count, 'versions': versions, 'pairs': pairs,
            'paired_reduction_mean_percent': statistics.mean(reductions) if reductions else None,
            'paired_reduction_spread': common.dispersion(reductions), 'sample_ranges_overlap': overlap,
            'statistical_significance': 'NOT_ASSESSED; n=3の記述統計。有意差や正式承認を意味しない。'})
    return groups


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-record', '--client', dest='client_record', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--device-rate', type=int, default=48000)
    parser.add_argument('--device-buffer', type=int, default=512)
    args = parser.parse_args()
    common.require(common.finite(args.timeout) and 30 < args.timeout <= 300, 'bounded timeout required')
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'evidence belongs under build/')
    out.mkdir(parents=True, exist_ok=False)
    jobs, rows, errors, inventory, manifest_rows = [], [], [], [], []
    frozen_after = None
    try:
        client = common.load(args.client_record)
        common.require(client['schema'] == 'performance-seek-history-client-v1' and client['status'] == 'PASS', 'compile record must be PASS')
        plan_path = pathlib.Path(client['run_plan']['path']).resolve()
        common.require(common.identity(plan_path) == client['run_plan'], 'RUN_PLAN SHA')
        plan = common.load(plan_path)
        jobs = fixed_jobs(client, plan, out)
        inventory = compile_inventory(client, args.client_record, plan_path)
        common.save(out / 'COMPILE_INVENTORY.json', {'files': inventory, 'manifest_sha256': common.manifest_digest(inventory)})
        verify_inventory(inventory, out / 'FROZEN_BEFORE.json')
        for key in ('candidate_build',):
            build = common.load(pathlib.Path(client[key]['path']))
            common.require(build['status'] == 'PASS' and common.manifest_digest(build['source_manifest']['files']) == build['source'], 'candidate build manifest')
            source_root = pathlib.Path(build['source_root']).resolve()
            common.require(common.current_source_digest(source_root) == build['source'], 'candidate source changed after compile')
            manifest_rows.append({'root': source_root, 'sha256': build['source']})
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'arm64 macOS Python required')
        common.require(not os.environ.get('DYLD_LIBRARY_PATH') and not os.environ.get('DYLD_INSERT_LIBRARIES'), 'ambient dynamic library override')
        input_info = common.wav_identity(pathlib.Path(client['input']['path']), 48000, 1)
        common.require(input_info['sha256'] == client['input']['sha256'], 'Float32 mono48/300s input SHA')
        architectures = {}
        for version, compiled in client['clients'].items():
            arches = subprocess.check_output(['/usr/bin/lipo', '-archs', compiled['binary']['path']], text=True).split()
            common.require(arches == ['arm64'], 'native binary architecture')
            architectures[version] = arches
        common.save(out / 'EXPECTED.json', {'schema': 'seek-history-run-v1', 'expected_programs': 30, 'expected_checks': 300,
            'all_expected_ids': [job['id'] for job in jobs], 'required_check_ids': CHECK_IDS, 'jobs': jobs,
            'client_record': common.identity(args.client_record), 'run_plan': client['run_plan'],
            'driver': common.identity(__file__), 'helper': common.identity(common.__file__), 'input': input_info,
            'compile_inventory': common.identity(out / 'COMPILE_INVENTORY.json'), 'binary_architectures': architectures,
            'parent_python_architecture': platform.machine(), 'timeout_s': args.timeout, 'timeout_allowed': False,
            'cpu_window_s': plan['cpu_window_s'], 'cpu_formula': common.CPU_FORMULA,
            'device_condition': {'rate': args.device_rate, 'buffer_frames': args.device_buffer},
            'candidate_only_latch_asserts': CANDIDATE_LATCH_CHECKS,
            'old_latch': 'NOT_AVAILABLE_NOT_APPROVED', 'repeats_per_version_and_stratum': 3,
            'approval': False, 'quality_approval': False, 'physical_audio': None, 'application_F': None})
        common.save(out / 'ENVIRONMENT_BEFORE.json', common.environment())
        fixed_device = output_device()
        common.require(fixed_device['buffer_frames'] == args.device_buffer, 'default output buffer differs before run')
        common.save(out / 'DEVICE_BEFORE.json', fixed_device)
        # ヘッダ全量のhashは測定前後だけ。各実行前には実行物の固定を再確認する。
        for job in jobs:
            compiled = client['clients'][job['version']]
            common.require(common.identity(compiled['binary']['path']) == compiled['binary'], 'binary changed before run')
            common.require(common.identity(args.client_record) == next(item['identity'] for item in inventory if
                           'client_compile_manifest' in item['roles']), 'compile manifest changed before run')
            row = {key: job[key] for key in ('id', 'pair_id', 'history_N', 'repeat', 'version')}
            row['load_average_before'] = list(os.getloadavg())
            row['device_before'] = output_device()
            common.require(row['device_before'] == fixed_device, 'default output device changed before run')
            execution = common.execute(job['command'], out / (job['id'] + '.log'), args.timeout)
            row['execution'] = execution
            directory = out / job['id']
            try:
                row.update(assess(job, directory, execution, client, plan['cpu_window_s'], args.device_rate, args.device_buffer))
            except (OSError, ValueError, KeyError, TypeError) as error:
                row.update(integrity_pass=False, functional_pass=False, measurement_pass=False, rt_pass=False,
                    checks_passed=0, integrity_errors=[type(error).__name__ + ': ' + str(error)], functional_errors=[],
                    measurement_errors=[], summary={}, candidate_latch={'status': 'FAIL' if job['version'] == 'candidate' else 'NOT_AVAILABLE'})
            row['artifacts'] = [common.identity(path) for path in sorted(directory.rglob('*')) if path.is_file()] if directory.exists() else []
            row['load_average_after'] = list(os.getloadavg())
            row['device_after'] = output_device()
            if row['device_after'] != fixed_device:
                row['integrity_pass'] = False
                row['integrity_errors'].append('default output device changed during run')
            rows.append(row)
            common.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_programs': 30, 'expected_checks': 300,
                'executed_programs': len(rows), 'all_expected_ids': [item['id'] for item in jobs], 'rows': rows})
            common.save(out / 'PROCESS_COST.json', {'schema': 'seek-history-process-cost-v1',
                'note': '全process費用は初期入力prepare/履歴生成/Exact準備/CPU窓/Pause/Stop/closeを含み、5秒以上のCPU窓とは別。',
                'expected_programs': 30, 'executed_programs': len(rows),
                'rows': [{'id': item['id'], 'execution': item['execution']} for item in rows], 'physical_audio': None})
            print(job['id'], execution['returncode'], 'functional', row['functional_pass'], 'RT', row['rt_pass'],
                  'measurement', row['measurement_pass'], flush=True)
            if execution['interrupted']:
                raise KeyboardInterrupt('child interrupted and joined')
        frozen_after = verify_inventory(inventory, out / 'FROZEN_AFTER.json')
        for item in manifest_rows:
            common.require(common.current_source_digest(item['root']) == item['sha256'], 'candidate source changed during run')
        common.save(out / 'ENVIRONMENT_AFTER.json', common.environment())
        final_device = output_device()
        common.save(out / 'DEVICE_AFTER.json', final_device)
        common.require(final_device == fixed_device, 'default output device changed at final audit')
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        if inventory and frozen_after is None:
            try:
                frozen_after = verify_inventory(inventory, out / 'FROZEN_AFTER.json')
            except BaseException as error:
                errors.append('final inventory: ' + type(error).__name__ + ': ' + str(error))
    executed_ids = [row['id'] for row in rows]
    completed = len(rows) == 30 and executed_ids == [job['id'] for job in jobs] and all(
        not row['execution']['timeout'] and not row['execution']['interrupted'] and row['summary'].get('complete') is True for row in rows)
    integrity = completed and not errors and all(row.get('integrity_pass') for row in rows)
    functional = completed and all(row.get('functional_pass') for row in rows)
    rt = completed and all(row.get('rt_pass') for row in rows)
    measurement_window = completed and all(row.get('measurement_pass') for row in rows)
    measurement = integrity and functional and measurement_window
    candidate_rows = [row for row in rows if row['version'] == 'candidate']
    latch = len(candidate_rows) == 15 and all(row['candidate_latch']['status'] == 'PASS' for row in candidate_rows)
    final = {'schema': 'seek-history-run-v1', 'status': 'PASS' if integrity and functional and rt and measurement and latch else 'INCOMPLETE_OR_FAIL',
        'all_runs_completed': completed, 'integrity_pass': integrity, 'functional_pass': functional, 'rt_all_pass': rt,
        'rt_evidence_qualified': integrity and functional and rt,
        'performance_window_pass': measurement_window, 'performance_measurement_pass': measurement,
        'candidate_latch_pass': latch, 'old_latch': 'NOT_AVAILABLE_NOT_APPROVED',
        'expected_programs': 30, 'executed_programs': len(rows), 'expected_checks': 300,
        'reported_passed_checks': sum(row['checks_passed'] for row in rows), 'all_expected_ids': [job['id'] for job in jobs],
        'expected_audit_rows': sum(job['expected_audit_rows'] for job in jobs),
        'recovered_audit_rows': sum(row.get('audit', {}).get('recovered_rows', 0) for row in rows),
        'expected_Accepted_operations': 30,
        'all_audit_ID_sets_verified': completed and all(row.get('audit', {}).get('all_IDs_verified') for row in rows),
        'executed_ids': executed_ids, 'errors': errors, 'groups': aggregate(rows), 'rows': rows,
        'candidate_only_latch_asserts': CANDIDATE_LATCH_CHECKS, 'compared_seek_fields': len(SEEK_FIELDS),
        'cpu_formula': common.CPU_FORMULA, 'performance_improvement_approval': False, 'statistical_significance': 'NOT_ASSESSED',
        'formal_approval': False, 'quality_approval': False, 'physical_audio': None, 'application_F': None}
    common.save(out / 'SUMMARY.json', final)
    return 0 if final['status'] == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
