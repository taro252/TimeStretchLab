"""明示候補のwarm再ONを固定12program/144checksで直列実行する。
--client と --source-sha と新規--output は必須、chain300 mono48 Float32固定。
実際のcheckpoint hitを要求し、missをfreshの成功へ読み替えない。
"""
import argparse
import datetime
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys

import build_generic_warm_ab_clients as builder
import run_pairs as common
import run_seek_history as audit_helpers
import run_paused_deep_pairs as paused

ROOT = Path(__file__).resolve().parents[3]
CHECK_IDS = (
    'WAB01.Float32_mono48_300_fixture', 'WAB02.Ready_final_analysis',
    'WAB03.initial_ReturnToA', 'WAB04.two_natural_cycles',
    'WAB05.Playing_Clear_completed', 'WAB06.Pause_quiescent_capture_reset',
    'WAB07.normal_Play_actual_C_ge_B', 'WAB08.new_Loop_ID_first_A',
    'WAB09.fixed_Map_and_natural_cycles', 'WAB10.all_Accepted_terminal_close',
    'WAB11.owner_checkpoint_callback_supply', 'WAB12.full_capture_cost_SHA')
COSTS = ('prepare_to_final_analysis', 'initial_ReturnToA', 'initial_setup_to_Paused_Clear',
         'setup_capture_archive_and_reset', 'normal_Play_to_C_ge_B', 'reON_to_first_A_observed',
         'reON_through_two_cycles_Paused', 'whole_client_through_close_and_capture')
PHASES = ('initial_ReturnToA_Ready', 'initial_two_natural_cycles', 'first_Loop_Clear_terminal_owned',
          'normal_Play_actual_C_ge_B', 'warm_reON_first_A_observed', 'warm_two_cycles_Paused',
          'second_Loop_Stop_terminal_owned')
RECEIPTS = [{'action': 'initial_ON', 'id': 1}, {'action': 'Playing_Clear', 'id': 1},
            {'action': 'warm_reON', 'id': 2}]
LOOP_FIELDS = set((
    'id input_generation session source_epoch current_epoch A B cycles state enabled initial_position_complete '
    'clear_pending requested_speed applied_speed speed_request_id accepted_ns ready_ns preparation_count '
    'preparation_request_id dynamic_operation_id dynamic_cycle map_version dynamic_output_end '
    'dynamic_speed_request_id speed_failure_request_id speed_preparation_failed speed_defer_reason '
    'last_preparation_ns last_ready_ns max_preparation_ns safety_stop_frames old_missing new_missing '
    'affected failure_padding reusable period_frames cache_bytes reuse_count seed_restores map_builds '
    'worker_creations cold_discarded_frames warm_discarded_frames paused_clear_discarded paused_clear_input '
    'last_boundary reason').split())
ARTIFACTS = {'EXPECTED.json', 'SUMMARY.json', 'PROCESS_COST.json', 'checks.jsonl', 'receipts.jsonl',
             'observations.jsonl', 'owned_Loop_terminals.jsonl', 'EPOCHS.jsonl', 'FINAL_AUDIT.json',
             'PRODUCT_MAP.json', 'final_map.nodes.i64', 'final_map.events.jsonl', 'REFERENCE_RECIPE.json'}
for _segment in ('setup', 'warm'):
    ARTIFACTS |= {f'{_segment}/{name}' for name in (
        'EXPECTED.json', 'SUMMARY.json', 'raw.f32', 'raw_records.jsonl', 'output_before_gain.f32',
        'spans.jsonl', 'callbacks.jsonl', 'clock_anomaly.jsonl', 'boundaries.jsonl')}
ARTIFACTS.add('setup/first_Loop_terminal.json')
SCOPE = {
    'latency': 'native mach first A callback ns minus same native acceptedNs; warm hit only',
    'warm_goal_p95_ms': 250, 'fresh_or_prewarm_reclassification': False,
    'functional': 'same-A/B reON after Playing Clear and measured normal C>=B; all 12 native checks',
    'CPU': 'separate setup / archive-reset / normal Play / reON / whole process; do not sum nested intervals',
    'process_CPU': 'host RUSAGE_SELF all threads; external wait4 total is a distinct measurement',
    'n3': 'descriptive only; no causal significance', 'stage_hash': 'library default; detailed profile OFF',
    'independent_PCM': 'PENDING separate saved de70 full RAW/Map validation for setup/ and warm/',
    'realtime': 'counters preserved separately; do not attribute violations to observation overhead',
    'Loop_audit': 'client-owned full Clear/Stop snapshots; final public sink has no Loop request span',
    'source_freeze': 'src/tests/scripts/CMake; docs/results/build additions permitted',
    'quality_approval': False, 'RT_deadline_approval': False, 'public_approved': False,
    'CPU_improvement_approval': False, 'physical_audio': None, 'application_F': None}


def strict(body):
    def pairs(values):
        result = {}
        for key, value in values:
            common.require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    def reject(value):
        raise ValueError('nonfinite JSON constant: ' + value)
    result = json.loads(body, object_pairs_hook=pairs, parse_constant=reject)
    def finite(value):
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)
        elif type(value) is float:
            common.require(math.isfinite(value), 'nonfinite JSON number')
    finite(result)
    return result


def read(path, lines=False):
    body = Path(path).read_text()
    if not lines:
        return strict(body)
    values = body.splitlines()
    common.require(all(line.strip() for line in values), 'blank JSONL record: ' + str(path))
    return [strict(line) for line in values]


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def fixed_jobs(client, plan, out):
    common.require(plan['schema'] == 'warm-ab-pairs-v1' and plan['status'] == 'NOT_RUN', 'fixed unstarted warm plan')
    common.require(plan['expected_programs'] == len(plan['jobs']) == 12 and plan['expected_checks'] == 144,
                   'fixed 12-program/144-check plan')
    common.require(plan['speed_micros'] == 1000000 and plan['A_seconds'] == [30, 270] and
                   plan['loop_duration_ms'] == 100 and plan['unique_Loop_IDs_per_program'] == [1, 2] and
                   plan['accepted_receipts_per_program'] == RECEIPTS and plan['warm_target_p95_ms'] == 250 and
                   plan['callback_gate'] is False, 'warm strata/identity/goal/settings')
    common.require(plan['input'] == client['input'] and plan['client_source_sha256'] ==
                   client['source']['sha256'] == client['copied_source']['sha256'] == builder.SOURCE_SHA,
                   'same fixed source/input')
    common.require(set(client['clients']) == {'old', 'candidate'}, 'both versions required')
    preset = client['preset']
    common.require(plan['preset'] == preset and preset in ('candidate', 'baseline'), 'one fixed preset')
    jobs = []
    for repeat in (1, 2, 3):
        for at in (30, 270):
            pair = f'A{at}_{preset}_r{repeat:02d}'
            for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
                entry, raw = client['clients'][version], plan['jobs'][len(jobs)]
                values = {'id': pair + '_' + version, 'pair_id': pair, 'repeat': repeat, 'version': version,
                          'preset': preset, 'A_seconds': at, 'checks': 12}
                common.require(all(raw.get(k) == v for k, v in values.items()), 'plan identity/order changed')
                command = raw['command']
                common.require(len(command) == 7 and command[:4] ==
                               [entry['binary']['path'], client['input']['path'], preset, str(at)] and
                               command[5:] == [entry['source'], version], 'plan command binding')
                actual = command.copy()
                actual[4] = str(out / values['id'])
                jobs.append({**values, 'command': actual, 'original_command': command})
    common.require(plan['all_expected_ids'] == [j['id'] for j in jobs] and len({j['id'] for j in jobs}) == 12,
                   'fixed expected ID set')
    return jobs


def assess(job, directory, execution, client, device_rate, device_buffer):
    integrity, functional, measurement = [], [], []
    def check(group, value, reason):
        if not value:
            group.append(reason)
    def load(name, lines=False):
        try:
            return read(directory / name, lines)
        except (OSError, ValueError, TypeError, RuntimeError) as error:
            integrity.append(name + ': ' + str(error))
            return [] if lines else {}
    summary, expected, costs = load('SUMMARY.json'), load('EXPECTED.json'), load('PROCESS_COST.json')
    checks, receipts, observations = (load(name, True) for name in ('checks.jsonl', 'receipts.jsonl', 'observations.jsonl'))
    terminals, epochs, audit = load('owned_Loop_terminals.jsonl', True), load('EPOCHS.jsonl', True), load('FINAL_AUDIT.json')
    mapped, reference = load('PRODUCT_MAP.json'), load('REFERENCE_RECIPE.json')
    manifest = load('ARTIFACTS.json')
    actual_names = {str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()
                    and p.name != 'ARTIFACTS.json'}
    declared = manifest.get('artifacts', [])
    names = [item.get('path') for item in declared]
    check(integrity, set(names) == actual_names == ARTIFACTS and len(names) == len(set(names)),
          'full artifact set once; no omitted/extra/truncated evidence')
    for item in declared:
        name = item.get('path', '')
        relative = Path(name)
        check(integrity, bool(name) and not relative.is_absolute() and '..' not in relative.parts, 'artifact path scope')
        if not name or relative.is_absolute() or '..' in relative.parts:
            continue
        try:
            actual = common.identity(directory / relative)
            check(integrity, actual['bytes'] == item.get('bytes') and actual['sha256'] == item.get('sha256'),
                  'native artifact SHA: ' + name)
        except OSError as error:
            integrity.append('artifact read: ' + str(error))
    a, b = job['A_seconds'] * 48000, job['A_seconds'] * 48000 + 4800
    entry = client['clients'][job['version']]
    for key, wanted in {'source': entry['source'], 'version': job['version'], 'contract_version': entry['contract_version'],
                        'input_sha256': client['input']['sha256'], 'binary_sha256': entry['binary']['sha256'],
                        'preset': job['preset'], 'A': a, 'B': b}.items():
        check(integrity, summary.get(key) == expected.get(key) == wanted, 'native identity: ' + key)
    check(integrity, expected.get('expected') == summary.get('expected') == 12 and
          expected.get('required_ids') == list(CHECK_IDS) and
          [row.get('id') for row in checks] == list(CHECK_IDS) and
          all(row.get('pass') is True for row in checks), 'complete fixed 12-check set')
    check(functional, summary.get('run_complete') is True and summary.get('functional') is True and
          summary.get('executed') == 12 and not summary.get('error'), 'all native functional checks completed')
    check(integrity, summary.get('seek_checkpoints') is False and summary.get('prewarm_requests') == 0 and
          summary.get('callback_gate') is False and summary.get('detailed_profile') == 'OFF' and
          expected.get('capture_seconds') == 180 and expected.get('capture_records') == 65536,
          'unchanged profile/cache/finite observation settings')
    check(integrity, summary.get('source_rate') == device_rate == 48000 and summary.get('device_rate') == device_rate and
          summary.get('device_buffer') == device_buffer and summary.get('channels') == 1 and
          summary.get('input_frames') == 48000 * 300 and summary.get('speed') == expected.get('speed') == 1,
          'native mono48/1x/source/device conditions')
    check(integrity, all(summary.get(k) is False for k in ('quality_approval', 'RT_deadline_approval', 'public_approved')) and
          summary.get('physical_audio') is None and summary.get('application_F') is None, 'approval scope')
    got_receipts = [{'action': r.get('action'), 'id': r.get('id')} for r in receipts]
    check(functional, got_receipts == RECEIPTS and all(r.get('accepted') is True and r.get('code') == 0 for r in receipts),
          'all three Accepted receipt identities, Clear reuses Loop1')
    generation = None
    for row in receipts:
        context = row.get('context', {})
        check(functional, all(integer(context.get(k), 1) for k in ('generation', 'session', 'epoch')), 'receipt full context')
        if generation is None:
            generation = context.get('generation')
        check(functional, context.get('generation') == generation, 'same input generation across reON')
    check(functional, summary.get('accepted_receipts') == {'initial_ON': 1, 'Playing_Clear': 1, 'warm_reON': 2} and
          summary.get('observed_terminal_Loop_IDs') == [1, 2], 'summary all Accepted unique IDs')
    check(functional, [row.get('phase') for row in observations] == list(PHASES), 'all action snapshots preserved')
    snapshots = {row.get('phase'): row.get('snapshot', {}) for row in observations}
    check(functional, len(terminals) == 2 and [row.get('id') for row in terminals] == [1, 2] and
          all(set(row) == LOOP_FIELDS and row.get('state') == 'Cancelled' and row.get('enabled') in (0, False) and
              row.get('clear_pending') in (0, False) and row.get('input_generation') == generation and
              row.get('A') == a and row.get('B') == b and row.get('cycles', 0) >= 2 for row in terminals),
          'all common Loop terminal fields, identities and actual cycles')
    check(functional, terminals == [snapshots.get(PHASES[2]), snapshots.get(PHASES[-1])] and
          load('setup/first_Loop_terminal.json') == (terminals[0] if terminals else {}),
          'owned terminal copies equal Clear/Stop full snapshots')
    check(integrity, len(terminals) == 2 and summary.get('initial_cycles_at_Clear') == terminals[0].get('cycles') and
          summary.get('reON_cycles') == terminals[1].get('cycles'), 'summary actual cycles equal owned terminals')
    check(functional, integer(summary.get('C_at_reON'), b) and summary.get('C_at_or_after_B') is True,
          'actual normal C>=B before reON')
    check(functional, summary.get('owners_alive') == 0 and integer(summary.get('owners_peak'), 1) and
          summary['owners_peak'] <= 2 and integer(summary.get('checkpoint_peak'), 1) and summary['checkpoint_peak'] <= 2 and
          summary.get('seek_checkpoint_states_final_snapshot') == 0 and
          integer(summary.get('loop_checkpoint_states_final_snapshot')) and summary['loop_checkpoint_states_final_snapshot'] <= 2 and
          summary.get('reservation_after_Stop') == 0, 'owner/checkpoint/reservation bounds')
    check(functional, all(summary.get(k) == 0 for k in ('missing_frames', 'underrun_calls', 'rejected_writes',
          'workgroup_errors', 'callback_cpp_new', 'callback_heap_allocations', 'callback_heap_frees')),
          'callback heap/supply failure counters')
    owned_epochs = audit.get('epochs', [])
    check(functional, audit.get('calls') == summary.get('final_audit_calls') == 1 and audit.get('workers_joined') is True and
          audit.get('retirement_complete') is True and audit.get('failed') is False and audit.get('callback_delivery') is False and
          audit.get('configured') is True and audit.get('epoch_rejected') == summary.get('epoch_audit_rejected') == 0 and
          audit.get('epoch_calls') == summary.get('epoch_audit_calls') == len(owned_epochs) and len(owned_epochs) >= 4,
          'final audit delivery and all worker joins')
    check(functional, all(audit.get(k) == 0 for k in ('seek_rows', 'stopped_rows', 'Loop_speed_rows', 'preparation_rows')) and
          all(row.get('workers_joined') is True and row.get('callback_released') is True and
              row.get('ordinary_speed_rows') == 0 and row.get('generation') == generation and
              row.get('engine_serial') == audit.get('engine_serial') and row.get('preparation') == audit.get('preparation')
              for row in owned_epochs) and
          sorted(row.get('sequence', 0) for row in owned_epochs) == list(range(1, len(owned_epochs) + 1)),
          'empty unrequested operation spans and unique complete epoch identities')
    check(functional, len(epochs) >= 4 and len({row.get('session') for row in epochs}) == len(epochs) and
          {row.get('session') for row in epochs} == {row.get('session') for row in owned_epochs} and
          all(row.get('final_data_available') is True and row.get('generation') == generation and
              row.get('analysis_final') is True and row.get('input_sha256') == client['input']['sha256'] and
              row.get('joins') == row.get('leaves') == row.get('restores') and
              integer(row.get('checkpoint_peak')) and row['checkpoint_peak'] <= 2 and
              integer(row.get('checkpoint_states_at_join_snapshot')) and row['checkpoint_states_at_join_snapshot'] <= 2
              for row in epochs), 'all finalized shared-input epochs and checkpoint bounds')
    for name in COSTS:
        check(measurement, paused.valid_cost(costs.get(name)), 'finite separate cost: ' + name)
    check(measurement, costs.get('setup_excluded_from_warm_latency') is True and
          costs.get('includes_capture_IO_in_whole') is True, 'cost scope separates setup and capture IO')
    for key in ('wall_s', 'process_user_s', 'process_system_s', 'whole_process_cpu_s'):
        check(measurement, common.finite(execution.get(key)) and execution[key] >= 0, 'finite wait4: ' + key)
    counters = {key: summary.get(key) for key in ('worker_deadlines', 'workgroup_errors', 'callback_deadlines',
                'host_missing', 'host_backwards', 'host_cadence', 'sample_errors', 'hal_window_misses')}
    check(measurement, all(integer(value) for value in counters.values()), 'all RT counters measured')
    native_rt = all(value == 0 for value in counters.values())
    check(measurement, type(summary.get('rt_pass')) is bool and summary['rt_pass'] == native_rt, 'RT formula')
    hit = summary.get('initial_checkpoint_hit')
    check(measurement, type(hit) is bool, 'actual checkpoint hit measured')
    exercised = hit is True
    check(measurement, summary.get('warm_status') == ('EXERCISED' if exercised else 'NOT_EXERCISED') and
          summary.get('performance_exercised') is exercised and summary.get('warm_miss_reclassified_fresh') is False,
          'warm hit/miss classification; no fresh relabel')
    native_ns, accepted_ns = summary.get('first_A_callback_ns'), summary.get('reON_accepted_ns')
    native_order = integer(native_ns, 1) and integer(accepted_ns, 1) and native_ns >= accepted_ns
    latency = (native_ns - accepted_ns) / 1e6 if native_order else None
    check(measurement, native_order and common.finite(summary.get('accepted_to_first_A_ms')) and
          math.isclose(summary['accepted_to_first_A_ms'], latency, rel_tol=1e-9, abs_tol=1e-8), 'native latency formula')
    target = latency is not None and latency <= 250
    check(measurement, summary.get('warm_target_ms') == 250 and
          (summary.get('warm_latency_ms') == summary.get('accepted_to_first_A_ms') and
           summary.get('performance_pass') is target if exercised else
           summary.get('warm_latency_ms') is None and summary.get('performance_pass') is None),
          'only true warm hit has a warm latency/250ms result')
    wanted_exit = (0 if native_rt and target else 2) if exercised else 3
    check(integrity, execution.get('timeout') is False and execution.get('interrupted') is False and
          execution.get('returncode') == wanted_exit, 'exit/RT/target/NOT_EXERCISED or timeout mismatch')
    capture_metadata = {}
    for segment in ('setup', 'warm'):
        meta, cap = load(segment + '/EXPECTED.json'), load(segment + '/SUMMARY.json')
        raw, spans = load(segment + '/raw_records.jsonl', True), load(segment + '/spans.jsonl', True)
        boundaries = load(segment + '/boundaries.jsonl', True)
        terminal = terminals[0 if segment == 'setup' else 1] if len(terminals) == 2 else {}
        check(functional, boundaries and len(boundaries) <= 64 and
              all(row.get('loop_id') == terminal.get('id') and row.get('A') == a and row.get('B') == b and
                  integer(row.get('cycle'), 1) and integer(row.get('setting_cycle'), 1) and
                  integer(row.get('render_ns'), 1) for row in boundaries) and
              boundaries[-1].get('setting_cycle') == terminal.get('cycles'),
              segment + ' actual bounded natural boundary events/Loop identity/cycle count')
        raw_frames, output_frames = sum(r.get('frames', 0) for r in raw), sum(s.get('frames', 0) for s in spans)
        check(functional, raw and spans and len(raw) <= 65536 and len(spans) <= 65536 and
              cap.get('run_complete') is True and cap.get('functional') is True and
              cap.get('raw_records') == len(raw) and cap.get('output_spans') == len(spans) and
              cap.get('raw_frames') == raw_frames and cap.get('output_frames') == output_frames and
              raw_frames <= 48000 * 180 and output_frames <= 48000 * 180, segment + ' full finite capture lengths')
        check(integrity, meta.get('A') == a and meta.get('B') == b and meta.get('speed') == 1 and
              meta.get('preset') == job['preset'] and meta.get('input_sha256') == cap.get('input_sha256') == client['input']['sha256'] and
              meta.get('binary_sha256') == entry['binary']['sha256'], segment + ' independent-validator metadata binding')
        check(integrity, (directory / segment / 'raw.f32').stat().st_size == raw_frames * 4 and
              (directory / segment / 'output_before_gain.f32').stat().st_size == output_frames * 4,
              segment + ' all RAW/spans own binary file lengths')
        raw_cursor, sources, used, callback_end = 0, [], [], None
        for record in raw:
            n, at = record.get('frames'), record.get('at')
            check(functional, integer(n, 1) and n <= 4096 and integer(at) and at + n <= 48000 * 300 and
                  integer(record.get('epoch'), 1) and integer(record.get('session'), 1) and
                  record.get('raw_offset') == raw_cursor, segment + ' RAW interval identity/order')
            raw_cursor += n
            sources.append((record['epoch'], at, n))
        for span in spans:
            n, mixed = span.get('frames'), span.get('mixed')
            check(functional, integer(n, 1) and n <= 4096 and integer(mixed) and mixed <= n and
                  span.get('new_received') == n and span.get('old_received') == mixed and
                  (callback_end is None or span.get('callback_frame') == callback_end),
                  segment + ' complete callback spans/supply/order')
            callback_end = span['callback_frame'] + n
            used.append((span['new_epoch'], span['new_at'], n))
            if mixed:
                used.append((span['old_epoch'], span['old_at'], mixed))
        check(functional, sources == used, segment + ' all raw sources exactly owned by output spans')
        if segment == 'warm':
            check(functional, cap.get('first_A_epoch') == summary.get('first_A_epoch') and
                  cap.get('first_A_output') == summary.get('first_A_output') == mapped.get('OA') and
                  not spans[0].get('periodic') and any(span.get('new_epoch') == cap.get('first_A_epoch') and
                  span.get('periodic') for span in spans), 'normal first PCM, exact new A and actual periodic output')
        capture_metadata[segment] = {'expected': meta, 'summary': cap, 'raw_records': len(raw), 'output_spans': len(spans),
                                    'natural_boundary_records': len(boundaries),
                                    'actual_natural_cycles': terminal.get('cycles'),
                                    'independent_validator_8192_rows_exercised': len(raw) <= 8192 and len(spans) <= 8192,
                                    'numerical_PCM': 'PENDING, no bit comparison performed by this runner'}
    check(functional, mapped.get('A') == a and mapped.get('B') == b and mapped.get('OA') == summary.get('first_A_output') and
          integer(mapped.get('OB'), mapped.get('OA', 0) + 512) and integer(mapped.get('source_hop'), 1),
          'joined final product Map evidence (independent reference still required)')
    check(integrity, mapped.get('nodes_sha256') == common.identity(directory / 'final_map.nodes.i64')['sha256'] and
          mapped.get('events_sha256') == common.identity(directory / 'final_map.events.jsonl')['sha256'],
          'all final Map nodes/events SHA')
    check(integrity, reference.get('queries') == reference.get('reference_map_input_positions') == [a, b] and
          reference.get('speed_micros') == 1000000 and reference.get('input_sha256') == client['input']['sha256'] and
          reference.get('preset') == job['preset'] and reference.get('quality_approval') is False,
          'independent reference recipe exact input/preset/speed/A/B')
    return {'summary': summary, 'native_expected': expected, 'process_cost': costs, 'final_audit': audit,
            'owned_Loop_terminals': terminals, 'capture_metadata': capture_metadata, 'product_map': mapped,
            'reference_recipe': reference, 'integrity_pass': not integrity, 'functional_pass': not functional,
            'measurement_valid': not measurement, 'integrity_errors': integrity, 'functional_errors': functional,
            'measurement_errors': measurement, 'checks_passed': sum(row.get('pass') is True for row in checks),
            'warm_classification': 'EXERCISED' if exercised else 'NOT_EXERCISED', 'rt_observation_pass': native_rt,
            'latency_target_single_pass': target if exercised else None,
            'audit': {'expected_Accepted_receipts': RECEIPTS, 'all_receipts_verified': got_receipts == RECEIPTS,
                      'expected_unique_Loop_IDs': [1, 2], 'terminal_rows': len(terminals),
                      'terminal_fields': len(LOOP_FIELDS), 'terminal_full_fields_equal_owned_snapshots':
                      terminals == [snapshots.get(PHASES[2]), snapshots.get(PHASES[-1])],
                      'all_epoch_sessions': [row.get('session') for row in owned_epochs],
                      'epoch_audit_count': len(owned_epochs), 'API_scope': SCOPE['Loop_audit']}}


def qualified(row):
    return all(row.get(key) is True for key in ('integrity_pass', 'functional_pass', 'measurement_valid'))


def aggregate(rows):
    def cost_value(row, phase, key):
        costs = row.get('process_cost')
        phase_cost = costs.get(phase) if isinstance(costs, dict) else None
        return phase_cost.get(key) if isinstance(phase_cost, dict) else None
    groups = []
    for at in (30, 270):
        versions = {}
        for version in ('old', 'candidate'):
            selected = [r for r in rows if r['A_seconds'] == at and r['version'] == version]
            valid = [r for r in selected if qualified(r)]
            warm = [r for r in valid if r.get('warm_classification') == 'EXERCISED']
            latencies = [r['summary']['warm_latency_ms'] for r in warm]
            generic = [r['summary']['accepted_to_first_A_ms'] for r in selected
                       if common.finite(r.get('summary', {}).get('accepted_to_first_A_ms'))]
            metrics = {}
            for phase in COSTS:
                for key in paused.COST_KEYS:
                    values = [cost_value(r, phase, key) for r in valid]
                    warm_values = [cost_value(r, phase, key) for r in warm]
                    metrics[phase + '.' + key] = {
                        'all_qualified_reON_intent_including_miss': paused.stats([v for v in values if common.finite(v)]),
                        'actual_warm_hit_only': paused.stats([v for v in warm_values if common.finite(v)])}
            for key in ('wall_s', 'whole_process_cpu_s'):
                metrics['external_wait4.' + key] = {
                    'all_recorded_unqualified': paused.stats([r['execution'][key] for r in selected
                                                            if common.finite(r['execution'].get(key))]),
                    'actual_warm_hit_only': paused.stats([r['execution'][key] for r in warm
                                                         if common.finite(r['execution'].get(key))])}
            enough = len(warm) == 3
            p95 = common.percentile(latencies)
            versions[version] = {'expected_programs': 3, 'executed_programs': len(selected),
                'qualified_programs': len(valid), 'warm_exercised_programs': len(warm),
                'NOT_EXERCISED_ids': [r['id'] for r in valid if r.get('warm_classification') == 'NOT_EXERCISED'],
                'invalid_ids': [r['id'] for r in selected if not qualified(r)],
                'generic_accepted_delay_unqualified_not_warm': paused.stats(generic),
                'warm_latency_ms': paused.stats(latencies), 'warm_p95_goal_ms': 250,
                'warm_p95_pass': p95 <= 250 if enough else None,
                'rt_observation_pass': all(r.get('rt_observation_pass') is True for r in valid) if len(valid) == 3 else None,
                'separate_cost_statistics': metrics}
        pairs = []
        for repeat in (1, 2, 3):
            pair = {r['version']: r for r in rows if r['A_seconds'] == at and r['repeat'] == repeat}
            compare = set(pair) == {'old', 'candidate'} and all(qualified(r) and
                      r.get('warm_classification') == 'EXERCISED' for r in pair.values())
            values = {}
            for metric in ('warm_latency_ms', 'reON_to_first_A_observed.process_cpu_s',
                           'reON_to_first_A_observed.control_thread_cpu_s', 'reON_to_first_A_observed.wall_s'):
                def sample(version):
                    row = pair.get(version, {})
                    if metric == 'warm_latency_ms':
                        return row.get('summary', {}).get(metric)
                    phase, key = metric.split('.')
                    return cost_value(row, phase, key)
                left, right = sample('old'), sample('candidate')
                finite = compare and common.finite(left) and common.finite(right) and left > 0
                values[metric] = {'old': left, 'candidate': right,
                    'candidate_over_old': right / left if finite else None,
                    'candidate_reduction_percent': 100 * (left - right) / left if finite else None}
            pairs.append({'repeat': repeat, 'qualified_warm_pair': compare,
                          'differences': values, 'causal_significance': 'NOT_ASSESSED'})
        groups.append({'A_seconds': at, 'speed_micros': 1000000, 'loop_duration_ms': 100,
                       'versions': versions, 'pairs': pairs, 'scope': SCOPE})
    return groups


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--device-rate', type=int, default=48000)
    parser.add_argument('--device-buffer', type=int, default=512)
    args = parser.parse_args()
    common.require(common.finite(args.timeout) and 30 < args.timeout <= 300,
                   'finite process watchdog 30..300s; timeout is failure, never a performance target')
    common.require(args.device_rate == 48000 and args.device_buffer == 512, 'fixed native built-in 48k/512 condition')
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new evidence under build/')
    out.mkdir(parents=True, exist_ok=False)
    jobs, rows, errors, inventory, source_manifests = [], [], [], [], []
    after_inventory, source_after = None, []
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 runtime Python required')
        common.require(not any(os.environ.get(key) for key in ('DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'CPATH',
                       'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH', 'LIBRARY_PATH')), 'ambient library/include override')
        client_id, client = common.identity(args.client), read(args.client)
        common.require(client['schema'] == 'performance-warm-ab-clients-v1' and client['status'] == 'PASS',
                       'PASS warm client compile manifest')
        common.require(client['candidate_source'] == client['clients']['candidate']['source'] == args.source_sha and len(args.source_sha) == 64 and
                       client['baseline_source'] == client['clients']['old']['source'] == builder.frozen.OLD_SOURCE_SHA and
                       client['baseline_commit'] == builder.frozen.OLD_COMMIT, 'explicit candidate/5674-v3 source provenance')
        common.require(Path(client['baseline_client']['path']).resolve() ==
                       (builder.BASE / 'frozen_clients_02/CLIENT.json').resolve(), 'fixed frozen02 baseline path')
        plan_path = Path(client['run_plan']['path'])
        common.require(common.identity(plan_path) == client['run_plan'], 'RUN_PLAN SHA')
        jobs = fixed_jobs(client, read(plan_path), out)
        inventory = paused.compile_inventory(client, args.client)
        for module, role in ((sys.modules[__name__], 'warm_run_driver'), (builder, 'warm_build_recipe'), (paused, 'reused_paused_audit')):
            inventory.append({'identity': common.identity(module.__file__), 'roles': [role]})
        common.save(out / 'COMPILE_INVENTORY.json', {'files': inventory, 'manifest_sha256': common.manifest_digest(inventory)})
        audit_helpers.verify_inventory(inventory, out / 'FROZEN_BEFORE.json')
        for name in ('baseline_build', 'candidate_build'):
            build = read(client[name]['path'])
            root = Path(build['source_root']).resolve()
            common.require(build['status'] == 'PASS' and build['configuration'] == 'Release' and build['architecture'] == 'arm64',
                           'Release arm64 build')
            common.require(common.manifest_digest(build['source_manifest']['files']) ==
                           build['source'] == build['source_manifest']['sha256'], 'recorded source inventory contents')
            common.require(common.current_source_digest(root) == build['source'], name + ' source changed')
            source_manifests.append({'name': name, 'root': str(root), 'sha256': build['source']})
        common.save(out / 'SOURCE_BEFORE.json', {'status': 'PASS', 'source_manifests': source_manifests,
                                                'scope': SCOPE['source_freeze']})
        input_info = common.wav_identity(Path(client['input']['path']), 48000, 1)
        common.require(input_info['sha256'] == client['input']['sha256'] == builder.INPUT_SHA, 'fixed chain300 SHA')
        for entry in client['clients'].values():
            common.require(subprocess.check_output(['/usr/bin/lipo', '-archs', entry['binary']['path']], text=True).split() ==
                           ['arm64'], 'native arm64 child binary')
        common.require(client['capture_helper']['common_sha256'] ==
                       client['capture_helper']['old']['sha256'] == client['capture_helper']['candidate']['sha256'] and
                       client['capture_helper']['original_helper_modified'] is False, 'same frozen InitialCapture helper')
        declaration = {'schema': 'warm-ab-run-v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'expected_programs': 12, 'expected_checks': 144, 'all_expected_ids': [j['id'] for j in jobs], 'jobs': jobs,
            'required_check_ids': CHECK_IDS, 'expected_Accepted_receipts': 36, 'expected_unique_Loop_IDs': 24,
            'expected_owned_Loop_terminal_rows': 24, 'accepted_receipts_per_program': RECEIPTS,
            'input': input_info, 'client': client_id, 'run_plan': client['run_plan'], 'source_manifests': source_manifests,
            'driver': common.identity(__file__), 'helpers': [common.identity(m.__file__) for m in (builder, common, audit_helpers, paused)],
            'parent_python_architecture': platform.machine(), 'timeout_s': args.timeout, 'timeout_allowed': False,
            'device_rate': args.device_rate, 'device_buffer': args.device_buffer, 'serial_audio': True, 'scope': SCOPE}
        common.save(out / 'EXPECTED.json', declaration)
        common.save(out / 'ENVIRONMENT_BEFORE.json', common.environment())
        device = audit_helpers.output_device()
        common.require(device['buffer_frames'] == args.device_buffer, 'actual default device buffer')
        common.save(out / 'DEVICE_BEFORE.json', device)
        for job in jobs:
            entry = client['clients'][job['version']]
            common.require(common.identity(args.client) == client_id and
                           common.identity(entry['binary']['path']) == entry['binary'], 'compile manifest/binary changed')
            common.require(audit_helpers.output_device() == device, 'default device changed before process')
            execution = common.execute(job['command'], out / (job['id'] + '.log'), args.timeout)
            directory = out / job['id']
            row = {k: job[k] for k in ('id', 'pair_id', 'repeat', 'version', 'preset', 'A_seconds')}
            row['execution'] = execution
            try:
                row.update(assess(job, directory, execution, client, args.device_rate, args.device_buffer))
            except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as error:
                def partial(name):
                    try:
                        return read(directory / name)
                    except (OSError, ValueError, TypeError, RuntimeError):
                        return {}
                try:
                    count = sum(r.get('pass') is True for r in read(directory / 'checks.jsonl', True))
                except (OSError, ValueError, TypeError, RuntimeError):
                    count = 0
                row.update(summary=partial('SUMMARY.json'), native_expected=partial('EXPECTED.json'),
                    process_cost=partial('PROCESS_COST.json'), final_audit=partial('FINAL_AUDIT.json'),
                    integrity_pass=False, functional_pass=False, measurement_valid=False, checks_passed=count,
                    integrity_errors=[type(error).__name__ + ': ' + str(error)], functional_errors=[],
                    measurement_errors=[], audit={}, capture_metadata={}, warm_classification='INCOMPLETE',
                    rt_observation_pass=False, latency_target_single_pass=None)
            row['artifacts'] = [common.identity(path) for path in sorted(directory.rglob('*'))
                                if path.is_file()] if directory.exists() else []
            row['device_after'] = audit_helpers.output_device()
            if row.get('summary', {}).get('device') != device['default_output_device'] or row['device_after'] != device:
                row['integrity_pass'] = False
                row['integrity_errors'].append('default/native device identity changed')
            rows.append(row)
            common.save(out / 'SUMMARY.json', {**declaration, 'status': 'IN_PROGRESS', 'executed_programs': len(rows), 'rows': rows})
            common.save(out / 'PROCESS_COST.json', {'schema': 'warm-ab-process-cost-v1', 'scope': SCOPE,
                'expected_programs': 12, 'executed_programs': len(rows),
                'rows': [{'id': r['id'], 'external_wait4': r['execution'], 'host_separate_costs': r.get('process_cost', {})} for r in rows]})
            print(job['id'], execution['returncode'], 'functional', row['functional_pass'],
                  'warm', row['warm_classification'], 'RT', row['rt_observation_pass'], flush=True)
            if execution['interrupted']:
                raise KeyboardInterrupt('own child interrupted and reaped')
        after_inventory = audit_helpers.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
        for item in source_manifests:
            actual = common.current_source_digest(Path(item['root']))
            source_after.append({**item, 'actual_sha256': actual, 'unchanged': actual == item['sha256']})
        common.save(out / 'SOURCE_AFTER.json', {'status': 'PASS' if all(v['unchanged'] for v in source_after) else 'FAIL',
                                               'source_manifests': source_after, 'scope': SCOPE['source_freeze']})
        common.require(all(v['unchanged'] for v in source_after), 'source changed during run')
        common.save(out / 'ENVIRONMENT_AFTER.json', common.environment())
        final_device = audit_helpers.output_device()
        common.save(out / 'DEVICE_AFTER.json', final_device)
        common.require(final_device == device, 'default output device changed after collection')
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        if inventory and after_inventory is None:
            try:
                after_inventory = audit_helpers.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
            except BaseException as error:
                errors.append('final inventory: ' + type(error).__name__ + ': ' + str(error))
        if source_manifests and not source_after:
            try:
                for item in source_manifests:
                    actual = common.current_source_digest(Path(item['root']))
                    source_after.append({**item, 'actual_sha256': actual, 'unchanged': actual == item['sha256']})
                common.save(out / 'SOURCE_AFTER.json', {'status': 'PASS' if all(v['unchanged'] for v in source_after) else 'FAIL',
                                                       'source_manifests': source_after, 'scope': SCOPE['source_freeze']})
                common.require(all(v['unchanged'] for v in source_after), 'source changed before interruption')
            except BaseException as error:
                errors.append('final source: ' + type(error).__name__ + ': ' + str(error))
    expected_ids, executed_ids = [j['id'] for j in jobs], [r['id'] for r in rows]
    finished = len(jobs) == len(rows) == 12 and executed_ids == expected_ids and all(
        r['execution']['timeout'] is False and r['execution']['interrupted'] is False for r in rows)
    complete = finished and all(r.get('summary', {}).get('run_complete') is True for r in rows)
    integrity = complete and not errors and after_inventory is not None and all(r.get('integrity_pass') is True for r in rows)
    functional = complete and all(r.get('functional_pass') is True for r in rows)
    measurement = integrity and functional and all(r.get('measurement_valid') is True for r in rows)
    not_exercised = [r['id'] for r in rows if qualified(r) and r.get('warm_classification') == 'NOT_EXERCISED']
    warm_complete = measurement and not not_exercised and all(r.get('warm_classification') == 'EXERCISED' for r in rows)
    groups = aggregate(rows)
    gates = {}
    for version in ('old', 'candidate'):
        version_complete = measurement and all(g['versions'][version]['qualified_programs'] ==
                           g['versions'][version]['warm_exercised_programs'] == 3 for g in groups)
        gates[version] = all(g['versions'][version]['warm_p95_pass'] is True and
                            g['versions'][version]['rt_observation_pass'] is True for g in groups) if version_complete else None
    status = ('FAIL_OR_INCOMPLETE' if not measurement else 'NOT_EXERCISED' if not_exercised
              else 'PASS' if all(gates.values()) else 'FAIL')
    result = {'schema': 'warm-ab-run-v1', 'status': status,
        'status_scope': 'complete collection plus both-version warm p95/RT observations; no quality/public approval',
        'collection_status': 'PASS' if measurement else 'FAIL_OR_INCOMPLETE',
        'all_programs_finished': finished, 'all_cases_complete': complete, 'integrity_pass': integrity,
        'functional_pass': functional, 'performance_measurement_valid': measurement, 'warm_complete': warm_complete,
        'NOT_EXERCISED_ids': not_exercised, 'warm_miss_reclassified_fresh': False,
        'version_warm_250ms_p95_and_RT_observation_gates': gates,
        'expected_programs': 12, 'executed_programs': len(rows), 'expected_checks': 144,
        'baseline_source': builder.frozen.OLD_SOURCE_SHA, 'candidate_source': args.source_sha,
        'client_compile_manifest': common.identity(args.client) if args.client.is_file() else None,
        'expected_manifest': common.identity(out / 'EXPECTED.json') if (out / 'EXPECTED.json').is_file() else None,
        'source_after': source_after,
        'reported_passed_checks': sum(r.get('checks_passed', 0) for r in rows),
        'all_expected_ids': expected_ids, 'executed_ids': executed_ids,
        'expected_Accepted_receipts': 36, 'expected_unique_Loop_IDs': 24, 'expected_owned_Loop_terminal_rows': 24,
        'recovered_owned_Loop_terminal_rows': sum(r.get('audit', {}).get('terminal_rows', 0) for r in rows),
        'all_Accepted_ID_sets_verified': measurement and all(r.get('audit', {}).get('all_receipts_verified') is True for r in rows),
        'Loop_snapshot_fields': len(LOOP_FIELDS), 'groups': groups, 'errors': errors, 'scope': SCOPE, 'rows': rows}
    common.save(out / 'SUMMARY.json', result)
    return 0 if status == 'PASS' else 3 if status == 'NOT_EXERCISED' else 2


if __name__ == '__main__':
    sys.exit(main())
