"""PausedDeepの固定n3旧新交互6program/72checksを直列実行する。

arm64 Python:
  run_paused_deep_pairs_v2.py --client B/paused_deep_clients_01/CLIENT.json --output B/paused_deep_pairs_01
入力は固定chain300、1programはC270で .4 -> 1 -> 2、各同値再試行。
受付→Readyの値/n3分位点を記録する。Paused性能の合否目標はNOT_DEFINED。
初期Exact/入力準備、観測wall、制御thread CPU、process CPU、全process費用を分離。
timeout/欠落/旧版の機能差もFAILとして保存し、残りの固定計画を実行する。
RT/品質/物理音響/実アプリFの承認は行わない。既存source/CMakeへ書かない。
"""
import argparse
import math
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys

import run_pairs as common
import run_seek_history as d3
import build_generic_paused_deep_clients_v2 as build_recipe

ROOT = Path(__file__).resolve().parents[3]
SPEEDS = (400000, 1000000, 2000000)
IDS = tuple((1 << 63) + i for i in (1, 2, 3))
C = 48000 * 270
CHECK_IDS = (
    'PAE01.Float32_mono48_300_fixture', 'PAE02.Ready_final_analysis', 'PAE03.short_Play_Pause',
    'PAE04.Exact_C270_completed_without_audio', 'PAE05.speed040_ready_duplicate_stationary',
    'PAE06.speed100_ready_duplicate_stationary', 'PAE07.speed200_ready_duplicate_stationary',
    'PAE08.no_Resume_stationary_terminal_immutable', 'PAE09.Stop_all_requests_terminal',
    'PAE10.all_epoch_joins_profiles_off', 'PAE11.close_owned_all_IDs', 'PAE12.owner_heap_cost_SHA_audit')
STOPPED_FIELDS = {
    'id', 'input_generation', 'source_session', 'source_epoch', 'source_map_version', 'source_consumed_output',
    'resume_input', 'session', 'epoch', 'output_start', 'accepted_ns', 'ready_ns', 'loop_id', 'cycle',
    'preparation_version', 'discarded_for_stopped_speed_frames', 'speed_micros', 'state',
    'position_captured', 'output_started', 'mode', 'reason'}
SEEK_FIELDS = (set(d3.SEEK_FIELDS) - {'discarded_for_seek'}) | {'discarded_for_seek_frames'}
COST_KEYS = ('wall_s', 'control_thread_cpu_s', 'process_cpu_s')
REQUEST_COSTS = ('request_call', 'request_begin_to_Ready_observed', 'accepted_return_to_Ready_observed',
                 'immediate_duplicate_call', 'Ready_duplicate_call')
PROGRAM_COSTS = ('whole_program', 'prepare_to_final_analysis', 'initial_Exact_call',
                 'initial_Exact_request_to_Completed_observed', 'reservation_reacquisition_probe', 'whole_program_including_probe')
ARTIFACTS = {
    'EXPECTED.json', 'SUMMARY.json', 'PROCESS_COST.json', 'checks.jsonl', 'measurements.jsonl',
    'initial_Exact.jsonl', 'initial_preparation.json', 'history_ready_1.jsonl', 'history_ready_2.jsonl',
    'history_ready_3.jsonl', 'stopped_after_Stop.jsonl', 'seek_after_Stop.jsonl', 'epochs.jsonl',
    'close_owned_stopped.jsonl', 'close_owned_seek.jsonl', 'close_owned_epochs.jsonl', 'RESERVATION_PROBE.json'}
SCOPE = {
    'performance_goal': 'NOT_DEFINED',
    'latency': 'native readyNs-acceptedNs values/n3 quantiles only; not an Interactive/FastLocal Ready goal',
    'initial_Exact': 'preparation cost, excluded from stopped-speed response intervals',
    'control_thread_CPU': 'CLOCK_THREAD_CPUTIME_ID on the serial control host; not worker CPU',
    'process_CPU': 'RUSAGE_SELF user+system interval, all process threads; includes polls and immediate duplicate',
    'observed_wall': 'steady_clock intervals; no cross-clock timestamp subtraction',
    'whole_process': 'external wait4 includes separate post-close reservation probe; primary host whole_program excludes probe',
    'stage_hash': 'library default: legacy v3 ON, candidate v4 default; separate from detailed profile OFF',
    'n3': 'descriptive statistics; no causal significance or adoption claim',
    'quality_approval': False, 'RT_deadline_approval': False, 'performance_improvement_approval': False,
    'physical_audio': None, 'application_F': None}


def plan_jobs(client, plan, out):
    common.require(plan['schema'] == 'paused-deep-pairs-v1' and plan['status'] == 'NOT_RUN', 'fixed RUN_PLAN required')
    common.require(plan['expected_programs'] == 6 and plan['expected_checks'] == 72 and len(plan['jobs']) == 6, 'fixed 6/72 matrix')
    common.require(plan['performance_goal'] == 'NOT_DEFINED' and plan['callback_gate'] is False, 'no transferred performance goal or callback gate')
    common.require(plan['speeds_micros'] == list(SPEEDS) and plan['accepted_stopped_IDs'] == list(IDS) and
                   plan['accepted_seek_IDs'] == [1] and plan['duplicate_requests_per_program'] == 6 and plan['C_input_frame'] == C, 'fixed speeds/IDs/C')
    common.require(set(client['clients']) == {'old', 'candidate'} and plan['input'] == client['input'], 'client pair/input')
    common.require(plan['client_source_sha256'] == client['source']['sha256'] == client['copied_source']['sha256'], 'common source SHA')
    preset = plan['preset']
    common.require(preset == client['preset'] and preset in ('candidate', 'baseline'), 'one fixed preset')
    jobs = []
    for repeat in (1, 2, 3):
        pair = f'A270_{preset}_r{repeat:02d}'
        for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
            raw, entry = plan['jobs'][len(jobs)], client['clients'][version]
            key = pair + '_' + version
            common.require(all(raw.get(k) == v for k, v in {'id': key, 'pair_id': pair, 'repeat': repeat, 'version': version, 'preset': preset, 'checks': 12}.items()), 'plan identity/order')
            command = raw['command']
            common.require(len(command) == 6 and command[:3] == [entry['binary']['path'], client['input']['path'], preset] and
                           command[4:] == [entry['source'], version], 'plan command identity')
            actual = command.copy()
            actual[3] = str(out / key)
            jobs.append({**raw, 'command': actual, 'original_command': command})
    common.require(plan['all_expected_ids'] == [j['id'] for j in jobs], 'exact job ID set')
    return jobs


def compile_inventory(client, path):
    inventory = {}
    def add(item, role):
        wanted = {k: item[k] for k in ('path', 'bytes', 'sha256')}
        common.require(str(Path(wanted['path']).resolve()) == wanted['path'], 'absolute manifest path')
        if wanted['path'] in inventory:
            common.require(inventory[wanted['path']]['identity'] == wanted, 'conflicting SHA')
            inventory[wanted['path']]['roles'].append(role)
        else:
            inventory[wanted['path']] = {'identity': wanted, 'roles': [role]}
    add(common.identity(path), 'client_compile_manifest')
    for key in ('source', 'copied_source', 'driver', 'baseline_client', 'baseline_build', 'candidate_build', 'input', 'run_plan'):
        add(client[key], key)
    for item in client['helpers'] + client['baseline_link_inputs']:
        add(item, 'compile_helper_or_baseline_link_input')
    for version, entry in client['clients'].items():
        common.require(entry['prepare_ABI'] == ('ContractV3Tag' if version == 'old' else 'ContractV4Tag') and
                       entry['contract_version'] == (3 if version == 'old' else 4) and entry['architectures'] == ['arm64'], 'ABI/architecture')
        common.require(len(entry['libraries']) == 10 and sum(i['path'].endswith('.a') for i in entry['libraries']) == 9, '9 archives + probe')
        for key in ('binary', 'object', 'depfile', 'compiler', 'flags_file', 'link_template', 'undefined_symbols'):
            add(entry[key], version + ':' + key)
        for item in entry['dependencies'] + entry['libraries']:
            add(item, version + ':dependency')
    for command in client['commands']:
        common.require(command['returncode'] == 0, 'compile/link failure')
        add(command['log'], 'compile_or_link_log')
    for module in (common, d3, build_recipe):
        add(common.identity(module.__file__), 'run_helper')
    add(common.identity(__file__), 'run_driver')
    return list(inventory.values())


def reservation_probe_errors(p, input_sha, original_serial, original_generation):
    errors = []
    def need(value, reason):
        if not value:
            errors.append('reservation probe: ' + reason)
    need(p.get('schema') == 'reservation-reacquisition-v1' and p.get('passed') is True
         and not p.get('error'), 'strict probe completion')
    need(p.get('original_engine_serial') == original_serial and
         p.get('original_input_generation') == original_generation and
         p.get('input_sha256') == input_sha, 'original/input identity')
    need(type(p.get('engine_serial')) is int and p['engine_serial'] > 0 and
         p['engine_serial'] != original_serial and type(p.get('input_generation')) is int and
         p['input_generation'] > 0 and p['input_generation'] != original_generation and
         type(p.get('session')) is int and p['session'] > 0, 'distinct probe identity')
    need(p.get('owners_before') == 0 and p.get('owners_at_Ready') == 1 and
         p.get('owners_after') == 0 and type(p.get('owners_peak')) is int and
         1 <= p['owners_peak'] <= 2, 'owner0 -> one Ready owner -> owner0 / peak2')
    need(p.get('Ready') is True and p.get('Stopped') is True and
         type(p.get('reservation_at_Ready')) is int and p['reservation_at_Ready'] > 0 and
         type(p.get('reservation_after_Stop_estimate')) is int and p['reservation_after_Stop_estimate'] >= 0,
         'real reservation reacquired; stopped estimate retained')
    need(all(p.get(k) is True for k in ('workers_joined', 'retirement_complete',
         'epoch_audit_configured', 'epochs_joined', 'callbacks_released', 'identities_match',
         'same_process', 'separate_sink', 'primary_cost_excludes_probe', 'callback_cpp_measured')) and
         p.get('audit_in_callback') is False and p.get('explicit_Play') is False and
         p.get('reservation_is_live_counter') is False, 'normal separate-sink join/no Play scope')
    need(p.get('final_audit_calls') == p.get('epoch_audit_calls') ==
         p.get('epoch_audit_observed') == 1 and all(p.get(k) == 0 for k in
         ('epoch_audit_rejected', 'operation_rows', 'callback_calls', 'first_PCM_ns',
          'missing_frames', 'rejected_writes', 'worker_deadlines', 'workgroup_errors',
          'callback_cpp_new', 'callback_heap_allocations', 'callback_heap_frees')),
         'complete empty operation audit / no actual output or worker failures')
    need(all(type(p.get(k)) is int and 0 <= p[k] <= 2 for k in
         ('checkpoint_states', 'checkpoint_peak')), 'maximum two checkpoint states')
    return errors


def probe_costs_separate(costs, primary, inclusive):
    a, b, total = (costs.get(k) for k in (primary, 'reservation_reacquisition_probe', inclusive))
    if not all(valid_cost(v) for v in (a, b, total)):
        return False
    return all(total[k] + 1e-8 >= a[k] + b[k] for k in COST_KEYS)


def valid_cost(value):
    return isinstance(value, dict) and set(value) == set(COST_KEYS) and all(common.finite(value[k]) and value[k] >= 0 for k in COST_KEYS)


def assess(job, directory, execution, client, rate, buffer):
    integrity, functional, measurement = [], [], []
    def check(group, value, reason):
        if not value:
            group.append(reason)
    def read(name, line=False):
        try:
            return d3.lines(directory / name) if line else common.load(directory / name)
        except (OSError, ValueError, TypeError) as error:
            integrity.append(name + ': ' + str(error))
            return [] if line else {}
    s, expected, costs = read('SUMMARY.json'), read('EXPECTED.json'), read('PROCESS_COST.json')
    probe = read('RESERVATION_PROBE.json')
    checks, records = read('checks.jsonl', True), read('measurements.jsonl', True)
    initial, initial_meta = read('initial_Exact.jsonl', True), read('initial_preparation.json')
    stopped, seeks = read('stopped_after_Stop.jsonl', True), read('seek_after_Stop.jsonl', True)
    owned, owned_seeks = read('close_owned_stopped.jsonl', True), read('close_owned_seek.jsonl', True)
    epochs, owned_epochs = read('epochs.jsonl', True), read('close_owned_epochs.jsonl', True)
    histories = [read(f'history_ready_{i}.jsonl', True) for i in (1, 2, 3)]
    artifact_manifest = read('ARTIFACTS.json')
    files = artifact_manifest.get('files', [])
    check(integrity, len(files) == len(ARTIFACTS) and {r.get('path') for r in files} == ARTIFACTS, 'all artifact names once')
    for item in files:
        try:
            common.require(item['path'] in ARTIFACTS, 'unexpected artifact path')
            current = common.identity(directory / item['path'])
            check(integrity, current['bytes'] == item['bytes'] and current['sha256'] == item['sha256'], 'artifact SHA ' + item['path'])
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            integrity.append('artifact: ' + str(error))
    version, entry = job['version'], client['clients'][job['version']]
    check(integrity, not execution['timeout'] and not execution['interrupted'] and execution['returncode'] == 0, 'process failed/timeout/interrupted')
    for key, value in {'schema': 'performance-paused-deep-v1', 'preset': job['preset'], 'version': version, 'source': entry['source'],
                       'contract_version': entry['contract_version'], 'input_sha256': client['input']['sha256'], 'binary_sha256': entry['binary']['sha256'],
                       'source_rate': 48000, 'channels': 1, 'input_frames': 48000 * 300, 'C_input_frame': C,
                       'device_rate': rate, 'device_buffer': buffer}.items():
        check(integrity, s.get(key) == value, 'summary identity ' + key)
    check(functional, s.get('status') == 'PASS' and s.get('functional') is True and s.get('run_complete') is True, 'host functional/incomplete')
    check(functional, s.get('expected') == s.get('executed') == 12 and [r.get('id') for r in checks] == list(CHECK_IDS) and
          all(r.get('status') == 'PASS' for r in checks), 'fixed 12 check IDs/status')
    check(integrity, expected.get('checks') == list(CHECK_IDS) and expected.get('expected') == 12 and expected.get('speeds_micros') == list(SPEEDS) and
          expected.get('accepted_stopped_IDs') == list(IDS) and expected.get('accepted_seek_IDs') == [1] and expected.get('duplicate_requests') == 6 and
          expected.get('C_input_frame') == C and expected.get('analysis_final_required') is True and expected.get('seek_checkpoints') is False and
          expected.get('callback_gate') is False and expected.get('source') == entry['source'] and expected.get('input_sha256') == client['input']['sha256'] and
          expected.get('binary_sha256') == entry['binary']['sha256'], 'EXPECTED contract/SHA')
    check(functional, s.get('accepted_speed_requests') == 3 and s.get('duplicate_requests') == 6 and s.get('final_stopped_rows') == 3 and
          s.get('final_seek_rows') == 1 and s.get('final_audit_calls') == 1 and s.get('epoch_audit_rejected') == 0, 'all Accepted IDs/duplicate/audit counts')
    for name, values in (('Stop', stopped), ('close', owned)):
        check(functional, [v.get('id') for v in values] == list(IDS) and all(set(v) == STOPPED_FIELDS for v in values), name + ' complete stopped field/ID set')
        check(functional, [v.get('state') for v in values] == ['Replaced', 'Replaced', 'Cancelled'] and
              all(v.get('resume_input') == C and v.get('output_started') is False for v in values), name + ' terminal facts')
    check(functional, stopped == owned, 'stopped terminal full fields changed on close')
    for name, values in (('initial', initial), ('Stop', seeks), ('close', owned_seeks)):
        check(functional, len(values) == 1 and values[0].get('id') == 1 and set(values[0]) == SEEK_FIELDS and
              values[0].get('state') == 'Completed' and values[0].get('mode') == 0 and values[0].get('requested_input') == C and
              values[0].get('first_callback_ns') == values[0].get('estimated_presentation_ns') == 0, name + ' complete terminal Exact')
    check(functional, initial == seeks == owned_seeks and (not initial or initial_meta.get('initial_Exact') == initial[0]) and
          initial_meta.get('analysis_final') is True and initial_meta.get('C_after') == C, 'Exact full fields/analysis/C unchanged')
    check(functional, common.finite(s.get('raw_frames')) and s['raw_frames'] > 0 and s.get('raw_frames') == initial_meta.get('raw_frames_before_speed') and
          common.finite(s.get('raw_calls')) and s['raw_calls'] > 0 and common.finite(s.get('output_calls')) and s['output_calls'] > 0, 'short original playback and no later raw consumption')
    check(functional, len(records) == 3, 'three measurement rows')
    for i, (speed, wanted_id) in enumerate(zip(SPEEDS, IDS)):
        m = records[i] if i < len(records) else {}
        ready = m.get('Ready_operation', {})
        history = histories[i]
        check(functional, [v.get('id') for v in history] == list(IDS[:i + 1]) and all(set(v) == STOPPED_FIELDS for v in history), 'Ready history field/ID set')
        check(functional, len(history) == i + 1 and ready == history[-1] and set(ready) == STOPPED_FIELDS and ready.get('state') == 'ReadyForResume', 'Ready row/history correlation')
        check(functional, m.get('id') == wanted_id and m.get('ordinal') == i + 1 and m.get('receipt_result') == 'Accepted' and
              m.get('speed_micros') == speed and ready.get('speed_micros') == speed and ready.get('id') == wanted_id and ready.get('resume_input') == C and
              ready.get('position_captured') is True and ready.get('output_started') is False and ready.get('loop_id') == ready.get('cycle') == 0, 'Ready identity/C/no output')
        check(functional, m.get('immediate_duplicate_id') == m.get('Ready_duplicate_id') == wanted_id and
              m.get('immediate_duplicate_result') == m.get('Ready_duplicate_result') == 'Duplicate' and
              m.get('duplicate_creates_new_ID_or_timestamp') is False and
              m.get('immediate_duplicate_observed_state') in ('Preparing', 'ReadyForResume'), 'same-ID duplicate receipts')
        check(functional, m.get('analysis_final_before') is True and m.get('analysis_final_after') is True and
              m.get('C_before') == m.get('C_after') == C and m.get('audio_consumed_frames_during_request') == 0 and
              m.get('discarded_is_not_audio_consumption') is True and m.get('new_Map_output_start') == ready.get('output_start'), 'final analysis/stationary C/new Map coordinate')
        disc, pub, consumed = (m.get(k) for k in ('discarded_for_stopped_speed_frames', 'retired_source_published', 'retired_source_consumed'))
        check(functional, all(type(v) is int and v >= 0 for v in (disc, pub, consumed)) and pub >= consumed and pub - consumed == disc and
              disc == ready.get('discarded_for_stopped_speed_frames') and consumed == ready.get('source_consumed_output'), 'discard belongs to retired FIFO, no consumed increment')
        if i < len(stopped):
            check(functional, {k: v for k, v in ready.items() if k not in ('state', 'reason')} ==
                  {k: v for k, v in stopped[i].items() if k not in ('state', 'reason')}, 'ready facts changed at replacement/Stop')
        for past in history[:-1]:
            final_row = next((v for v in stopped if v.get('id') == past.get('id')), {})
            check(functional, past == final_row, 'past terminal fields changed in later Ready history')
        latency = m.get('accepted_to_Ready_native_ms')
        check(measurement, common.finite(latency) and latency >= 0 and type(ready.get('accepted_ns')) is int and type(ready.get('ready_ns')) is int and
              ready['ready_ns'] >= ready['accepted_ns'] > 0 and math.isclose(latency, (ready['ready_ns'] - ready['accepted_ns']) / 1e6, rel_tol=1e-9, abs_tol=1e-8), 'native accepted/Ready clock formula')
        check(measurement, all(valid_cost(m.get(k)) for k in REQUEST_COSTS) and type(m.get('polls')) is int and m['polls'] >= 1, 'finite separate request/duplicate costs')
        if all(valid_cost(m.get(k)) for k in ('request_call', 'request_begin_to_Ready_observed', 'accepted_return_to_Ready_observed')):
            for key in COST_KEYS:
                check(measurement, math.isclose(m['request_begin_to_Ready_observed'][key],
                      m['request_call'][key] + m['accepted_return_to_Ready_observed'][key], rel_tol=1e-8, abs_tol=1e-8), 'observed interval CPU/wall formula')
    check(functional, len(epochs) >= 5 and len({v.get('session') for v in epochs}) == len(epochs) and
          all(v.get('final_data_available') is True and v.get('worker_profile_records') == v.get('detail_records') == 0 and
              v.get('thread_sampling') is False and v.get('analysis_done') is True and common.finite(v.get('checkpoint_states')) and
              v['checkpoint_states'] <= 2 and common.finite(v.get('checkpoint_peak')) and v['checkpoint_peak'] <= 2 for v in epochs), 'all finalized epochs/profile/checkpoint coverage')
    check(measurement, all(all(common.finite(v.get(k)) and v[k] >= 0 for k in ('dsp_worker_cpu_s', 'analysis_worker_cpu_s')) for v in epochs), 'final worker CPU finite')
    check(functional, len(owned_epochs) >= 5 and s.get('epoch_audit_calls') == len(owned_epochs) and
          len({v.get('sequence') for v in owned_epochs}) == len(owned_epochs) and
          all(v.get('workers_joined') is True and v.get('callback_released') is True and v.get('ordinary_speed_rows') == 0 and
              type(v.get('engine_serial')) is int and v['engine_serial'] > 0 and type(v.get('preparation')) is int and v['preparation'] > 0 for v in owned_epochs), 'owned all-join epoch audit/unique delivery')
    check(functional, len({v.get('engine_serial') for v in owned_epochs}) == len({v.get('preparation') for v in owned_epochs}) == 1 and
          {v.get('session') for v in owned_epochs} == {v.get('session') for v in epochs}, 'epoch audit scope/all sessions')
    check(functional, s.get('owners_alive') == 0 and common.finite(s.get('owners_peak')) and 1 <= s['owners_peak'] <= 2 and
          s.get('reservation_after_Stop_is_saved_estimate') is True and s.get('reservation_reacquired') is True and
          common.finite(s.get('reservation_bytes')) and s['reservation_bytes'] >= 0 and common.finite(s.get('checkpoint_states')) and 0 <= s['checkpoint_states'] <= 2 and
          common.finite(s.get('checkpoint_peak')) and 0 <= s['checkpoint_peak'] <= 2, 'owner/reservation/checkpoint bounds')
    for problem in reservation_probe_errors(probe, client['input']['sha256'],
            owned_epochs[0].get('engine_serial') if owned_epochs else None,
            owned_epochs[0].get('input_generation') if owned_epochs else None):
        check(functional, False, problem)
    check(measurement, costs.get('reservation_probe_excluded_from_primary_costs') is True,
          'probe excluded from primary costs')
    check(measurement, probe_costs_separate(costs, 'whole_program', 'whole_program_including_probe'),
          'primary/probe/inclusive cost accounting')
    check(functional, all(s.get(k) == 0 for k in ('nonfinite', 'affected_frames', 'missing', 'rejected_writes', 'callback_cpp_new',
          'callback_heap_allocations', 'callback_heap_frees')), 'PCM/supply/callback heap bounds')
    check(integrity, s.get('control_and_worker_profile') == 'OFF' and s.get('seek_checkpoints') is False and
          s.get('callback_gate') is False and s.get('explicit_Resume') is False and s.get('quality_approval') is False and
          s.get('RT_deadline_approval') is False and s.get('physical_audio') is None and s.get('application_F') is None, 'profile/settings/approval scope')
    check(measurement, all(valid_cost(costs.get(k)) for k in PROGRAM_COSTS) and costs.get('initial_Exact_is_speed_response') is False, 'initial/whole program costs separated')
    for key in ('wall_s', 'process_user_s', 'process_system_s', 'whole_process_cpu_s'):
        check(measurement, common.finite(execution.get(key)) and execution[key] >= 0, 'wait4 finite ' + key)
    rt_counts = {k: s.get(k) for k in ('worker_deadlines', 'workgroup_errors', 'callback_deadlines', 'host_missing',
                 'host_backwards', 'host_cadence', 'sample_errors', 'hal_window_misses')}
    return {'summary': s, 'process_cost': costs, 'measurements': records, 'integrity_pass': not integrity,
            'functional_pass': not functional, 'measurement_valid': not measurement,
            'integrity_errors': integrity, 'functional_errors': functional, 'measurement_errors': measurement, 'reservation_probe': probe,
            'checks_passed': sum(r.get('status') == 'PASS' for r in checks), 'RT_observation': {'counters': rt_counts, 'approval': False},
            'audit': {'run_scope': job['id'], 'engine_serials': sorted({v.get('engine_serial', 0) for v in owned_epochs}),
                      'expected_Accepted_IDs': {'seeks': [1], 'stopped_speeds': list(IDS)}, 'expected_rows': 4,
                      'recovered_rows': len(owned) + len(owned_seeks), 'all_IDs_verified': [v.get('id') for v in owned] == list(IDS) and
                      [v.get('id') for v in owned_seeks] == [1], 'stopped_fields': len(STOPPED_FIELDS), 'seek_fields': len(SEEK_FIELDS),
                      'close_full_fields_equal': stopped == owned and initial == seeks == owned_seeks}}


def stats(values):
    return {'n': len(values), 'values': values, 'mean': statistics.mean(values) if values else None,
            'median': common.percentile(values, .5), 'p95_interpolated': common.percentile(values),
            **common.dispersion(values)}


def qualified(row):
    return all(row.get(k) is True for k in ('integrity_pass', 'functional_pass', 'measurement_valid'))


def sample(row, speed, metric):
    entry = next((m for m in row.get('measurements', []) if m.get('speed_micros') == speed), {})
    value = entry
    for key in metric.split('.'):
        value = value.get(key) if isinstance(value, dict) else None
    return value if common.finite(value) and value >= 0 else None


def aggregate(rows):
    groups = []
    metrics = ['accepted_to_Ready_native_ms'] + [name + '.' + key for name in REQUEST_COSTS for key in COST_KEYS]
    for speed in SPEEDS:
        versions = {}
        for version in ('old', 'candidate'):
            selected = [r for r in rows if r['version'] == version]
            valid = [r for r in selected if qualified(r)]
            values = {}
            for metric in metrics:
                all_values = [sample(r, speed, metric) for r in selected]
                valid_values = [sample(r, speed, metric) for r in valid]
                values[metric] = {'all_recorded_unqualified': stats([v for v in all_values if v is not None]),
                                  'qualified': stats([v for v in valid_values if v is not None])}
            versions[version] = {'expected_programs': 3, 'executed_programs': len(selected), 'valid_programs': len(valid),
                                 'invalid_program_ids': [r['id'] for r in selected if not qualified(r)], 'metrics': values}
        pairs = []
        for repeat in (1, 2, 3):
            pair = {r['version']: r for r in rows if r['repeat'] == repeat}
            if set(pair) != {'old', 'candidate'}:
                continue
            differences = {}
            for metric in ('accepted_to_Ready_native_ms', 'request_begin_to_Ready_observed.process_cpu_s',
                           'request_begin_to_Ready_observed.control_thread_cpu_s', 'request_begin_to_Ready_observed.wall_s'):
                left, right = (sample(pair[v], speed, metric) for v in ('old', 'candidate'))
                differences[metric] = {'old': left, 'candidate': right,
                    'candidate_over_old': right / left if left is not None and right is not None and left > 0 else None,
                    'candidate_reduction_percent': 100 * (left - right) / left if left is not None and right is not None and left > 0 else None}
            left_ready = next((m.get('Ready_operation', {}) for m in pair['old'].get('measurements', []) if m.get('speed_micros') == speed), {})
            right_ready = next((m.get('Ready_operation', {}) for m in pair['candidate'].get('measurements', []) if m.get('speed_micros') == speed), {})
            pairs.append({'repeat': repeat, 'qualified': all(qualified(r) for r in pair.values()),
                          'differences': differences, 'same_target_output_start_equal':
                          left_ready.get('output_start') == right_ready.get('output_start') if left_ready and right_ready else None,
                          'PCM_oracle': False})
        groups.append({'speed_micros': speed, 'versions': versions, 'pairs': pairs, 'performance_goal': 'NOT_DEFINED',
                       'n3_significance': 'NOT_ASSESSED; descriptive only', 'performance_approval': False})
    preparation = {}
    for version in ('old', 'candidate'):
        selected = [r for r in rows if r['version'] == version]
        values = {}
        for phase in PROGRAM_COSTS:
            for key in COST_KEYS:
                observed, valid = [], []
                for row in selected:
                    cost = row.get('process_cost', {}).get(phase)
                    value = cost.get(key) if isinstance(cost, dict) else None
                    if common.finite(value) and value >= 0:
                        observed.append(value)
                        if qualified(row):
                            valid.append(value)
                values[phase + '.' + key] = {'all_recorded_unqualified': stats(observed), 'qualified': stats(valid)}
        for key in ('wall_s', 'whole_process_cpu_s'):
            values['external_wait4.' + key] = stats([r['execution'][key] for r in selected if common.finite(r['execution'].get(key))])
        preparation[version] = values
    return groups, preparation


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', '--client-record', dest='client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--device-rate', type=int, default=48000)
    parser.add_argument('--device-buffer', type=int, default=512)
    args = parser.parse_args()
    common.require(common.finite(args.timeout) and 30 < args.timeout <= 300, 'finite process watchdog 30..300s; not a performance target')
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new evidence output belongs under build/')
    out.mkdir(parents=True, exist_ok=False)
    jobs, rows, errors, inventory, source_manifests = [], [], [], [], []
    frozen_after = None
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS Python required (use bundled runtime Python)')
        common.require(not os.environ.get('DYLD_LIBRARY_PATH') and not os.environ.get('DYLD_INSERT_LIBRARIES'), 'ambient dynamic-library override')
        client_id = common.identity(args.client)
        client = common.load(args.client)
        common.require(client['schema'] == 'performance-paused-deep-clients-v1' and client['status'] == 'PASS' and client.get('host_revision') == 2 and
                       client['source']['sha256'] == client['copied_source']['sha256'] == build_recipe.SOURCE_SHA, 'PASS client compile manifest required')
        plan_path = Path(client['run_plan']['path'])
        common.require(common.identity(plan_path) == client['run_plan'], 'RUN_PLAN SHA changed')
        jobs = plan_jobs(client, common.load(plan_path), out)
        inventory = compile_inventory(client, args.client)
        common.save(out / 'COMPILE_INVENTORY.json', {'files': inventory, 'manifest_sha256': common.manifest_digest(inventory)})
        d3.verify_inventory(inventory, out / 'FROZEN_BEFORE.json')
        for name in ('baseline_build', 'candidate_build'):
            build = common.load(Path(client[name]['path']))
            root = Path(build['source_root']).resolve()
            common.require(common.manifest_digest(build['source_manifest']['files']) == build['source'] == build['source_manifest']['sha256'], 'recorded source manifest SHA')
            common.require(common.current_source_digest(root) == build['source'], name + ' current source differs')
            source_manifests.append({'name': name, 'root': str(root), 'sha256': build['source']})
        input_info = common.wav_identity(Path(client['input']['path']), 48000, 1)
        common.require(input_info['sha256'] == client['input']['sha256'] == build_recipe.INPUT_SHA, 'fixed chain300 input SHA')
        for entry in client['clients'].values():
            arches = subprocess.check_output(['/usr/bin/lipo', '-archs', entry['binary']['path']], text=True).split()
            common.require(arches == ['arm64'], 'native arm64 binary required')
        common.save(out / 'EXPECTED.json', {'schema': 'paused-deep-run-v1', 'expected_programs': 6, 'expected_checks': 72,
            'all_expected_ids': [j['id'] for j in jobs], 'jobs': jobs, 'check_ids': CHECK_IDS,
            'expected_Accepted_operations': 24, 'expected_owned_audit_rows': 24, 'expected_same_ID_duplicate_requests': 36,
            'accepted_IDs_per_program': {'seeks': [1], 'stopped_speeds': IDS}, 'input': input_info,
            'driver': common.identity(__file__), 'helpers': [common.identity(m.__file__) for m in (common, d3, build_recipe)],
            'client': client_id, 'run_plan': client['run_plan'], 'source_manifests': source_manifests,
            'source_freeze_scope': 'src/tests/scripts/CMake; docs/results/build additions permitted',
            'parent_python_architecture': platform.machine(), 'timeout_s': args.timeout, 'timeout_allowed': False,
            'process_watchdog_is_performance_target': False, 'device_rate': args.device_rate, 'device_buffer': args.device_buffer,
            'scope': SCOPE})
        common.save(out / 'ENVIRONMENT_BEFORE.json', common.environment())
        device = d3.output_device()
        common.require(device['buffer_frames'] == args.device_buffer, 'default device buffer condition')
        common.save(out / 'DEVICE_BEFORE.json', device)
        for job in jobs:
            entry = client['clients'][job['version']]
            common.require(common.identity(args.client) == client_id and common.identity(entry['binary']['path']) == entry['binary'], 'client/binary changed before process')
            common.require(d3.output_device() == device, 'default output device changed before process')
            execution = common.execute(job['command'], out / (job['id'] + '.log'), args.timeout)
            row = {k: job[k] for k in ('id', 'pair_id', 'repeat', 'version', 'preset')}
            row['execution'] = execution
            directory = out / job['id']
            try:
                row.update(assess(job, directory, execution, client, args.device_rate, args.device_buffer))
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
                try:
                    passed = sum(r.get('status') == 'PASS' for r in d3.lines(directory / 'checks.jsonl'))
                except (OSError, ValueError, TypeError):
                    passed = 0
                row.update(summary={}, process_cost={}, measurements=[], integrity_pass=False, functional_pass=False,
                    measurement_valid=False, checks_passed=passed, integrity_errors=[type(error).__name__ + ': ' + str(error)],
                    functional_errors=[], measurement_errors=[], audit={})
            row['artifacts'] = [common.identity(p) for p in sorted(directory.rglob('*')) if p.is_file()] if directory.exists() else []
            row['device_after'] = d3.output_device()
            if row.get('summary', {}).get('device_id') != device['default_output_device']:
                row['integrity_pass'] = False
                row['integrity_errors'].append('native device ID differs from fixed default output')
            if row['device_after'] != device:
                row['integrity_pass'] = False
                row['integrity_errors'].append('default output device changed during process')
            rows.append(row)
            common.save(out / 'SUMMARY.json', {'schema': 'paused-deep-run-v1', 'status': 'IN_PROGRESS', 'expected_programs': 6,
                'expected_checks': 72, 'executed_programs': len(rows), 'all_expected_ids': [j['id'] for j in jobs], 'scope': SCOPE, 'rows': rows})
            common.save(out / 'PROCESS_COST.json', {'schema': 'paused-deep-process-cost-v1', 'scope': SCOPE,
                'expected_programs': 6, 'executed_programs': len(rows),
                'rows': [{'id': r['id'], 'external_wait4': r['execution'], 'host_separate_costs': r.get('process_cost', {}),
                          'request_measurements': r.get('measurements', [])} for r in rows]})
            print(job['id'], execution['returncode'], 'functional', row['functional_pass'], 'measurement_valid', row['measurement_valid'], flush=True)
            if execution['interrupted']:
                raise KeyboardInterrupt('child interrupted and joined')
        frozen_after = d3.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
        for item in source_manifests:
            common.require(common.current_source_digest(Path(item['root'])) == item['sha256'], item['name'] + ' source changed during run')
        common.save(out / 'ENVIRONMENT_AFTER.json', common.environment())
        after_device = d3.output_device()
        common.save(out / 'DEVICE_AFTER.json', after_device)
        common.require(after_device == device, 'default device changed at final audit')
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        if inventory and frozen_after is None:
            try:
                frozen_after = d3.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
            except BaseException as error:
                errors.append('final inventory: ' + type(error).__name__ + ': ' + str(error))
    expected_ids = [j['id'] for j in jobs]
    executed_ids = [r['id'] for r in rows]
    finished = len(rows) == 6 and executed_ids == expected_ids and all(not r['execution']['timeout'] and not r['execution']['interrupted'] for r in rows)
    completed = finished and all(r['summary'].get('run_complete') is True and r['execution']['returncode'] == 0 for r in rows)
    integrity = completed and not errors and all(r.get('integrity_pass') for r in rows)
    functional = completed and all(r.get('functional_pass') for r in rows)
    valid_measurement = integrity and functional and all(r.get('measurement_valid') for r in rows)
    groups, preparation = aggregate(rows)
    final = {'schema': 'paused-deep-run-v1', 'status': 'PASS' if integrity and functional and valid_measurement else 'INCOMPLETE_OR_FAIL',
        'status_scope': 'functional/integrity/measurement completeness only; latency/performance goal NOT_DEFINED',
        'all_programs_finished': finished, 'all_cases_complete': completed, 'integrity_pass': integrity,
        'functional_pass': functional, 'performance_measurement_valid': valid_measurement, 'performance_goal': 'NOT_DEFINED',
        'expected_programs': 6, 'executed_programs': len(rows), 'expected_checks': 72,
        'reported_passed_checks': sum(r['checks_passed'] for r in rows), 'all_expected_ids': expected_ids, 'executed_ids': executed_ids,
        'expected_Accepted_operations': 24, 'expected_owned_audit_rows': 24,
        'recovered_owned_audit_rows': sum(r.get('audit', {}).get('recovered_rows', 0) for r in rows),
        'all_audit_ID_sets_verified': completed and all(r.get('audit', {}).get('all_IDs_verified') for r in rows),
        'expected_same_ID_duplicates': 36, 'reported_same_ID_duplicates': sum(r['summary'].get('duplicate_requests', 0) for r in rows),
        'compared_stopped_fields': len(STOPPED_FIELDS), 'compared_seek_fields': len(SEEK_FIELDS),
        'groups': groups, 'preparation_and_whole_process_statistics': preparation, 'errors': errors, 'scope': SCOPE, 'rows': rows}
    common.save(out / 'SUMMARY.json', final)
    return 0 if final['status'] == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
