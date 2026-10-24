#!/usr/bin/env python3
"""段階hash CPU診断専用: 旧5674/保存05 OFF/保存05 ON各n3、固定9program/72check。

 arm64-python3 -B .../run_steady_digest_cpu_pairs.py \
   --clients B/steady_digest_cpu_clients_01/CLIENT.json --output B/steady_digest_cpu_pairs_01
30秒・mono48 chain300・2倍・Candidateは固定。元normalCPUには加算しない。
Mach採取は元processCPU窓の外側。new/goneのCPU差はnull、matched合計は全体CPU
の分解ではない。対応はID一致と名前のみの推測を分離。CPU採用/因果は自動判定しない。
既存d0/dのdspCpuS/analysisCpuS/maxDspWallSを追加。thread全CPUとの差は
計測境界/窓の異なる残差であり、待機CPUではない。最大壁時間は累積値のみ保存する。
"""
import argparse
import datetime
import hashlib
import importlib.util
import math
import os
from pathlib import Path
import platform
import statistics
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BUILDER = Path(__file__).with_name('build_steady_digest_cpu_clients.py')
BUILDER_SHA = '345701ebde14cad9581d0f729bbdeb062d702df02bb2aa0cb9909e0bd48d5463'
LABELS = ('old5674', 'saved05_off', 'saved05_on')
ORDERS = (LABELS, ('saved05_off', 'saved05_on', 'old5674'), ('saved05_on', 'old5674', 'saved05_off'))
COMPARISONS = (('old5674', 'saved05_off'), ('old5674', 'saved05_on'), ('saved05_off', 'saved05_on'))
EXPECTED_PROGRAMS = 9
EXPECTED_CHECKS = 72
CHECKS = ('C01_native_complete_exit', 'C02_profile_input_device', 'C03_rt_metrics_complete',
          'C04_artifact_source_frozen', 'C05_mach_snapshots_complete', 'C06_thread_cpu_intervals',
          'C07_roles_counters', 'C08_process_window_offsets')
COUNTERS = ('wait_calls', 'interval_starts', 'interval_finishes', 'generated', 'published', 'consumed',
            'generated_frames', 'published_frames', 'consumed_frames', 'presented_frames')
COMPUTE_CPU_COUNTERS = ('dsp_compute_cpu_s', 'analysis_cpu_s')
COMPONENT_METRICS = ('dsp_thread_user_cpu_s', 'dsp_thread_system_cpu_s', 'dsp_thread_cpu_s',
                     'dsp_compute_cpu_s', 'analysis_cpu_s', 'residual_cpu_s', 'extended_residual_cpu_s')
RESIDUAL_SCOPE = ('DSP thread CPU minus pipeline.dspCpuS; sequential thread and d0/d windows differ, '
                  'in-flight interval and endpoint sampling errors remain. Signed residual is not wait CPU.')
RT_ZERO = ('missing', 'rejected', 'worker_deadlines', 'workgroup_errors', 'callback_deadlines', 'host_missing',
           'host_backwards', 'host_cadence_errors', 'sample_errors', 'hal_window_misses', 'callback_malloc',
           'callback_free', 'callback_cpp_new', 'worker_new', 'owners_alive')


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def describe(values):
    return {'n': len(values), 'values': values, 'mean': statistics.mean(values) if values else None,
            'median': statistics.median(values) if values else None, 'min': min(values) if values else None,
            'max': max(values) if values else None,
            'sample_stdev': statistics.stdev(values) if len(values) > 1 else None}


def uint(value):
    return type(value) is int and value >= 0


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def thread_audit(data, summary, label):
    """純関数。失敗snapshot/欠測も元rowに保持し、数値を0補完しない。"""
    errors = {key: [] for key in CHECKS[4:]}
    def check(condition, key, reason):
        if not condition:
            errors[key].append(reason)
    check(data.get('schema') == 'steady-thread-cpu-v2' and data.get('classification') == 'DIAGNOSTIC'
          and data.get('complete') is True, CHECKS[4], 'Incomplete/wrong diagnostic schema')
    check(data.get('callback_modified') is False and data.get('extra_window_getters') == 0
          and data.get('profile_changed') is False and data.get('cpu_approval') is False
          and data.get('quality') is None and data.get('physical_audio') is None, CHECKS[6], 'Changed profile/scope')
    snapshots, indexed = {}, {}
    for name in ('before', 'after'):
        s = data.get(name) or {};snapshots[name] = s;by_id = {}
        begin, end = s.get('begin_ns'), s.get('end_ns')
        check(uint(begin) and uint(end) and begin <= end, CHECKS[4], name + ' sampling time')
        check(s.get('complete') is True and s.get('task_status') == 0 and s.get('control_id_status') == 0
              and uint(s.get('control_thread_id')) and s['control_thread_id'] > 0
              and s.get('list_release_status') == 0, CHECKS[4], name + ' task/identifier/release status')
        rows = s.get('threads') or []
        check(isinstance(rows, list) and bool(rows), CHECKS[4], name + ' threads missing')
        releases = s.get('port_release_status')
        check(isinstance(releases, list) and len(releases) == len(rows) and all(x == 0 for x in releases),
              CHECKS[4], name + ' Mach send rights not all released')
        for i, r in enumerate(rows):
            tid = r.get('id');q0, q1 = r.get('query_begin_ns'), r.get('query_end_ns')
            valid_id = uint(tid) and tid > 0 and tid not in by_id
            check(valid_id, CHECKS[4], f'{name}[{i}] missing/duplicate identifier')
            if valid_id:
                by_id[tid] = r
            check(all(r.get(k) == 0 for k in ('identifier_status', 'basic_status', 'extended_status'))
                  and all(uint(r.get(k)) and r[k] > 0 for k in ('identifier_count', 'basic_count', 'extended_count')),
                  CHECKS[4], f'{name}[{i}] thread_info failed/truncated')
            check(uint(q0) and uint(q1) and uint(begin) and uint(end) and begin <= q0 <= q1 <= end,
                  CHECKS[4], f'{name}[{i}] query outside snapshot')
            basic, ext = r.get('basic'), r.get('extended')
            check(isinstance(basic, dict) and all(finite(basic.get(k)) and basic[k] >= 0 for k in ('user_s', 'system_s'))
                  and isinstance(ext, dict) and isinstance(ext.get('name'), str)
                  and all(uint(ext.get(k)) for k in ('user_ns', 'system_ns')),
                  CHECKS[5], f'{name}[{i}] missing/nonfinite CPU/name')
        check(s.get('control_thread_id') in by_id, CHECKS[4], name + ' control thread not in snapshot')
        indexed[name] = by_id
    before, after = indexed['before'], indexed['after']
    c0, c1 = data.get('counters_before') or {}, data.get('counters_after') or {}
    deltas = {}
    for key in COUNTERS:
        valid = uint(c0.get(key)) and uint(c1.get(key)) and c1[key] >= c0[key]
        check(valid, CHECKS[6], 'Counter decreased/missing: ' + key)
        deltas[key] = c1[key] - c0[key] if valid else None
    for key in ('session', 'render_epoch', 'pipeline_session', 'analysis_thread_id', 'dsp_thread_id'):
        check(uint(c0.get(key)) and uint(c1.get(key)) and c0[key] == c1[key], CHECKS[6], 'Epoch/role ID changed: ' + key)
    for key in ('fifo_high_water', 'analysis_worker_cpu_s', 'dsp_worker_cpu_s', 'backpressure_wait_s'):
        check(all(finite(c.get(key)) and c[key] >= 0 for c in (c0, c1)), CHECKS[6], 'Missing diagnostic ' + key)
    producer_key = 'analysis_producer_thread_id'
    if label == 'old5674':
        check(c0.get(producer_key) is None and c1.get(producer_key) is None, CHECKS[6], 'Old producer field invented')
    else:
        check(uint(c0.get(producer_key)) and c0.get(producer_key) == c1.get(producer_key), CHECKS[6], 'Producer ID changed/missing')
    diagnostic_cpu_deltas = {}
    for key in ('analysis_worker_cpu_s', 'dsp_worker_cpu_s', 'analysis_producer_cpu_s', 'backpressure_wait_s'):
        good = all(finite(c.get(key)) for c in (c0, c1)) and c1.get(key, 0) >= c0.get(key, 0)
        diagnostic_cpu_deltas[key] = c1[key] - c0[key] if good else None
    for key in COMPUTE_CPU_COUNTERS:
        good = all(finite(c.get(key)) and c[key] >= 0 for c in (c0, c1)) and c1[key] >= c0[key]
        delta = c1[key] - c0[key] if good else None
        good = good and finite(delta)
        check(good, CHECKS[6], 'Compute CPU missing/nonfinite/decreased: ' + key)
        diagnostic_cpu_deltas[key] = delta if good else None
    max_good = (all(finite(c.get('max_dsp_wall_s')) and c['max_dsp_wall_s'] >= 0 for c in (c0, c1))
                and c1['max_dsp_wall_s'] >= c0['max_dsp_wall_s'])
    check(max_good, CHECKS[6], 'Cumulative DSP maximum missing/nonfinite/decreased')
    cumulative_max = {'max_dsp_wall_s': {'before': c0.get('max_dsp_wall_s'),
                                       'after': c1.get('max_dsp_wall_s'),
                                       'scope': 'Cumulative endpoint maxima; no subtraction or window-local maximum claim.'}}
    role_ids = {'control': [snapshots[n].get('control_thread_id') for n in ('before', 'after')],
                'analysis_consumer': [c0.get('analysis_thread_id'), c1.get('analysis_thread_id')],
                'dsp': [c0.get('dsp_thread_id'), c1.get('dsp_thread_id')],
                'analysis_producer': [c0.get(producer_key), c1.get(producer_key)]}
    def roles(tid):
        return [k for k, ids in role_ids.items() if tid in ids and tid not in (None, 0)]
    def named_role(name):
        lower = name.lower()
        return [r for r in ('monitor', 'sync', 'seek', 'audio', 'render', 'analysis', 'dsp') if r in lower]
    matched = []
    for tid in sorted(before.keys() & after.keys()):
        a, b = before[tid], after[tid];basic_a, basic_b = a.get('basic') or {}, b.get('basic') or {}
        ext_a, ext_b = a.get('extended') or {}, b.get('extended') or {}
        valid = all(finite(v.get(k)) for v in (basic_a, basic_b) for k in ('user_s', 'system_s'))
        user = basic_b['user_s'] - basic_a['user_s'] if valid else None
        system = basic_b['system_s'] - basic_a['system_s'] if valid else None
        valid = valid and user >= 0 and system >= 0
        valid_ext = all(uint(v.get(k)) for v in (ext_a, ext_b) for k in ('user_ns', 'system_ns'))
        eu = (ext_b['user_ns'] - ext_a['user_ns']) * 1e-9 if valid_ext else None
        es = (ext_b['system_ns'] - ext_a['system_ns']) * 1e-9 if valid_ext else None
        valid_ext = valid_ext and eu >= 0 and es >= 0
        q = [a.get('query_begin_ns'), a.get('query_end_ns'), b.get('query_begin_ns'), b.get('query_end_ns')]
        valid_q = all(uint(v) for v in q) and q[0] <= q[1] < q[2] <= q[3]
        check(valid and valid_ext and valid_q, CHECKS[5], 'Invalid matched CPU/time: ' + str(tid))
        elapsed = ((q[2] + q[3]) - (q[0] + q[1])) * .5e-9 if valid_q else None
        name_a, name_b = ext_a.get('name'), ext_b.get('name')
        matched.append({'id': tid, 'name_before': name_a, 'name_after': name_b,
                        'ID_verified_roles': roles(tid), 'name_only_hints': named_role(name_b or name_a or ''),
                        'name_changed': name_a != name_b,
                        'user_cpu_s': user if valid else None, 'system_cpu_s': system if valid else None,
                        'cpu_s': user + system if valid else None,
                        'extended_user_s': eu if valid_ext else None, 'extended_system_s': es if valid_ext else None,
                        'extended_cpu_s': eu + es if valid_ext else None,
                        'query_window_lower_s': (q[2] - q[1]) * 1e-9 if valid_q else None,
                        'query_window_upper_s': (q[3] - q[0]) * 1e-9 if valid_q else None,
                        'query_midpoint_wall_s': elapsed,
                        'cpu_percent_midpoint_window': 100 * (user + system) / elapsed if valid and valid_q else None})
    check(bool(matched), CHECKS[5], 'No matched thread')
    dsp_rows = [row for row in matched if 'dsp' in row['ID_verified_roles']]
    check(len(dsp_rows) == 1, CHECKS[6], 'DSP ID must match exactly one thread at both endpoints')
    dsp = dsp_rows[0] if len(dsp_rows) == 1 else None
    compute = diagnostic_cpu_deltas['dsp_compute_cpu_s']
    residual = (dsp['cpu_s'] - compute if dsp and finite(dsp['cpu_s']) and finite(compute) else None)
    extended_residual = (dsp['extended_cpu_s'] - compute
                         if dsp and finite(dsp['extended_cpu_s']) and finite(compute) else None)
    check(finite(residual) and finite(extended_residual), CHECKS[6], 'DSP compute residual missing/nonfinite')
    compute_residual = {'dsp_thread_id': dsp['id'] if dsp else None,
                        'dsp_thread_user_cpu_s': dsp['user_cpu_s'] if dsp else None,
                        'dsp_thread_system_cpu_s': dsp['system_cpu_s'] if dsp else None,
                        'dsp_thread_cpu_s': dsp['cpu_s'] if dsp else None,
                        'dsp_compute_cpu_s': compute, 'analysis_cpu_s': diagnostic_cpu_deltas['analysis_cpu_s'],
                        'residual_cpu_s': residual, 'extended_residual_cpu_s': extended_residual,
                        'negative_residual_allowed': True, 'scope': RESIDUAL_SCOPE}
    def unmatched(ids, table):
        return [{'id': tid, 'sample': table[tid], 'ID_verified_roles': roles(tid), 'interval_cpu_s': None,
                 'reason': 'Only one endpoint observed; interval CPU unknown'} for tid in sorted(ids)]
    window = data.get('process_window') or {};offsets = None
    fields = ('start_wall_s', 'end_wall_s', 'start_cpu_s', 'end_cpu_s', 'cpu_s', 'wall_s', 'cpu_percent')
    good = all(finite(window.get(k)) for k in fields)
    check(good, CHECKS[7], 'Missing/nonfinite process a/b')
    if good:
        wall, cpu = window['end_wall_s'] - window['start_wall_s'], window['end_cpu_s'] - window['start_cpu_s']
        check(30 <= wall <= 32 and cpu >= 0 and math.isclose(window['wall_s'], wall, abs_tol=1e-8)
              and math.isclose(window['cpu_s'], cpu, abs_tol=1e-8)
              and math.isclose(window['cpu_percent'], 100 * cpu / wall, rel_tol=1e-9, abs_tol=1e-8),
              CHECKS[7], 'Process a/b formula or fixed30s window')
        check(all(finite(summary.get(k)) and math.isclose(summary[k], window[k], rel_tol=1e-9, abs_tol=1e-7)
                  for k in ('wall_s', 'cpu_s', 'cpu_percent')), CHECKS[7], 'Original SUMMARY/diagnostic window differs')
        times = [snapshots['before'].get(k) for k in ('begin_ns', 'end_ns')] + [snapshots['after'].get(k) for k in ('begin_ns', 'end_ns')]
        if all(uint(t) for t in times):
            t0, t1, t2, t3 = [v * 1e-9 for v in times]
            check(t0 <= t1 <= window['start_wall_s'] <= window['end_wall_s'] <= t2 <= t3,
                  CHECKS[7], 'Snapshots entered original process a/b window')
            offsets = {'before_sampling_s': t1 - t0, 'after_sampling_s': t3 - t2,
                       'before_end_to_process_start_s': window['start_wall_s'] - t1,
                       'process_end_to_after_start_s': t2 - window['end_wall_s'],
                       'scope': 'Sequential/non-atomic thread queries. Distinct from process a/b; no exact sum equality.'}
    sums = {k: sum(r[k] for r in matched) if all(r[k] is not None for r in matched) else None
            for k in ('cpu_s', 'extended_cpu_s')}
    sums['process_minus_matched_cpu_s'] = (window['cpu_s'] - sums['cpu_s']
        if good and sums['cpu_s'] is not None else None)
    return {'errors_by_check': errors, 'complete': not any(errors.values()), 'matched': matched,
            'new': unmatched(after.keys() - before.keys(), after),
            'gone': unmatched(before.keys() - after.keys(), before), 'role_ids': role_ids,
            'counter_delta': deltas, 'diagnostic_cpu_delta': diagnostic_cpu_deltas, 'counter_span': 'd0/d includes snapshot overhead; no getters added inside CPU window.',
            'diagnostic_cumulative_max': cumulative_max, 'compute_residual': compute_residual,
            'matched_totals_different_window': sums, 'sampling_offsets': offsets,
            'no_causal_or_automatic_adoption_claim': True}


def assess(common, job, summary, data, execution, input_id, device_rate, device_buffer, freeze):
    base = common.assess('steady', job, summary, None, execution, input_id, 30, device_rate, device_buffer)
    checks = {key: [] for key in CHECKS}
    def check(ok, key, why):
        if not ok:checks[key].append(why)
    check(summary.get('complete') is True and not execution['timeout'] and not execution['interrupted']
          and execution['returncode'] == (0 if summary.get('rt_pass') is True else 2), CHECKS[0], 'Native incomplete/exit mismatch')
    checks[CHECKS[1]].extend(base['errors'])
    rtv = data.get('rt_values') or {}
    check(all(uint(rtv.get(k)) for k in RT_ZERO) and uint(rtv.get('owners_peak'))
          and type(rtv.get('fifo_supply_failed')) is bool, CHECKS[2], 'RT/heap/supply measurements missing')
    rt = (all(rtv.get(k) == 0 for k in RT_ZERO) and uint(rtv.get('owners_peak'))
          and rtv['owners_peak'] <= 2 and rtv.get('fifo_supply_failed') is False)
    check(type(summary.get('rt_pass')) is bool and data.get('rt_pass') is summary.get('rt_pass')
          and rt is summary.get('rt_pass'), CHECKS[2], 'RT classification/metrics mismatch')
    check(freeze['status'] == 'PASS', CHECKS[3], 'Source/artifact changed')
    detail = thread_audit(data, summary, job['label'])
    for key, errors in detail['errors_by_check'].items():checks[key].extend(errors)
    return {'integrity_pass': not any(checks.values()), 'rt_pass': rt,
            'checks': [{'id': key, 'pass': not errors, 'errors': errors} for key, errors in checks.items()],
            'thread_audit': detail}


def paired_metrics(samples, fields):
    """固定3比較を各n3で示す。欠測を0補完せず採用判定もしない。"""
    comparisons = []
    for left, right in COMPARISONS:
        pairs = []
        for repeat in (1, 2, 3):
            found = {label: next((v for v in samples[label] if v['repeat'] == repeat), None)
                     for label in (left, right)}
            complete = all(found.values())
            pair = {'repeat': repeat, 'complete': complete, 'metrics': {},
                    'rt_pass': all(v.get('rt_pass') is True for v in found.values()) if complete else None}
            for key in fields:
                values = {label: found[label].get(key) if found[label] else None for label in (left, right)}
                pair['metrics'][key] = {**values, 'right_minus_left': values[right] - values[left]
                                        if all(finite(v) for v in values.values()) else None,
                                        'unit': 'percentage_points' if key == 'cpu_percent' else 'seconds'}
            if any(v and 'max_dsp_wall_s' in v for v in found.values()):
                pair['max_dsp_wall_s'] = {label: found[label]['max_dsp_wall_s'] if found[label] else None
                                          for label in (left, right)}
            pairs.append(pair)
        comparisons.append({'left': left, 'right': right, 'pairs': pairs,
                            'complete_n3': all(p['complete'] for p in pairs),
                            'pair_deltas': {key: describe([p['metrics'][key]['right_minus_left'] for p in pairs
                                                          if finite(p['metrics'][key]['right_minus_left'])])
                                            for key in fields},
                            'scope': 'Descriptive n3 only; no causal/significance/automatic approval.'})
    return comparisons


def compute_component_statistics(rows):
    versions, samples_by_label = {}, {}
    for label in LABELS:
        samples = []
        for row in rows:
            if row['label'] != label or not row.get('integrity_pass'):
                continue
            detail = row['thread_audit']
            samples.append({'id': row['id'], 'repeat': row['repeat'], 'rt_pass': row['rt_pass'],
                            **detail['compute_residual'],
                            'max_dsp_wall_s': detail['diagnostic_cumulative_max']['max_dsp_wall_s']})
        samples_by_label[label] = samples
        versions[label] = {'samples': samples,
                           'complete_n3': len(samples) == 3 and {s['repeat'] for s in samples} == {1, 2, 3},
                           'statistics': {key: describe([s[key] for s in samples if finite(s[key])])
                                          for key in COMPONENT_METRICS},
                           'max_dsp_wall_s': {endpoint: describe([s['max_dsp_wall_s'][endpoint] for s in samples])
                                              for endpoint in ('before', 'after')}}
    return {'versions': versions, 'comparisons': paired_metrics(samples_by_label, COMPONENT_METRICS),
            'scope': RESIDUAL_SCOPE, 'wait_CPU_measured': False,
            'max_scope': 'Only before/after cumulative endpoint maxima; no max differences.',
            'CPU_adoption': 'NOT_ASSESSED', 'causal_attribution': 'NOT_DEMONSTRATED'}


def aggregate(rows):
    groups, process_samples = {}, {}
    for label in LABELS:
        selected = [r for r in rows if r['label'] == label and r.get('integrity_pass')]
        roles = {}
        for role in ('control', 'analysis_consumer', 'dsp', 'analysis_producer'):
            samples = []
            for row in selected:
                found = [t for t in row['thread_audit']['matched'] if role in t['ID_verified_roles']]
                samples.append({'repeat': row['repeat'], 'cpu_s': found[0]['cpu_s'] if len(found) == 1 else None,
                                'id': found[0]['id'] if len(found) == 1 else None,
                                'state': 'matched' if len(found) == 1 else 'not observed at both endpoints'})
            roles[role] = {'samples': samples, 'complete_n3': len(samples) == 3 and all(v['cpu_s'] is not None for v in samples),
                           'matched_only': describe([s['cpu_s'] for s in samples if s['cpu_s'] is not None])}
        groups[label] = {'valid_programs': len(selected), 'rt_pass_programs': sum(r['rt_pass'] for r in selected),
                         'RT_qualified_n3': len(selected) == 3 and all(r['rt_pass'] for r in selected),
                         'process_cpu_percent': describe([r['summary']['cpu_percent'] for r in selected]),
                         'process_cpu_s': describe([r['summary']['cpu_s'] for r in selected]), 'roles': roles,
                         'counter_deltas': {k: describe([r['thread_audit']['counter_delta'][k] for r in selected])
                                            for k in COUNTERS},
                         'new_thread_counts': [len(r['thread_audit']['new']) for r in selected],
                         'gone_thread_counts': [len(r['thread_audit']['gone']) for r in selected]}
        process_samples[label] = [{'repeat': r['repeat'], 'rt_pass': r['rt_pass'],
                                  'cpu_percent': r['summary']['cpu_percent'], 'cpu_s': r['summary']['cpu_s']}
                                 for r in selected]
    names = sorted({t['name_after'] or t['name_before'] or '<unnamed>'
                    for row in rows if row.get('integrity_pass') for t in row['thread_audit']['matched']})
    named = {}
    for name in names:
        by_version, samples = {}, {}
        for label in LABELS:
            entries = []
            for row in rows:
                if row['label'] != label or not row.get('integrity_pass'):
                    continue
                matches = [t for t in row['thread_audit']['matched']
                           if (t['name_after'] or t['name_before'] or '<unnamed>') == name]
                entries.append({'repeat': row['repeat'], 'rt_pass': row['rt_pass'],
                                'ids': [t['id'] for t in matches], 'threads': len(matches),
                                'matched_cpu_s': sum(t['cpu_s'] for t in matches) if matches else None,
                                'matched_extended_cpu_s': sum(t['extended_cpu_s'] for t in matches) if matches else None})
            samples[label] = entries
            by_version[label] = {'samples': entries, 'matched_only_cpu_s': describe(
                [x['matched_cpu_s'] for x in entries if x['matched_cpu_s'] is not None]),
                'note': 'Name groups are not verified roles; missing/new/gone CPU is never zero-filled.'}
        named[name] = {'versions': by_version, 'comparisons': paired_metrics(samples, ('matched_cpu_s',)),
                       'scope': 'Name group only, not a causal CPU attribution.'}
    return {'versions': groups, 'thread_name_groups': named,
            'comparisons': paired_metrics(process_samples, ('cpu_percent', 'cpu_s')),
            'dsp_compute_components': compute_component_statistics(rows),
            'classification': 'DIAGNOSTIC_ONLY', 'CPU_adoption': 'NOT_ASSESSED',
            'statistical_significance': 'NOT_ASSESSED', 'causal_attribution': 'NOT_DEMONSTRATED',
            'limits': 'Same05 OFF/ON source and archives; only host option differs. Old legacy default is separate. '
                      'Thread/counter/process windows differ. Role labels can alias; no new/gone zero filling.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device-rate', type=int, default=48000)
    parser.add_argument('--device-buffer', type=int, default=512)
    args = parser.parse_args()
    if hashlib.sha256(BUILDER.read_bytes()).hexdigest() != BUILDER_SHA:
        raise ValueError('Pinned v2 builder changed')
    builder = module(BUILDER, 'steady_digest_cpu_client_builder');audit, _, common = builder.helpers();need = audit.need
    need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native arm64 Python required')
    need(not any(k.startswith('DYLD_') and v for k, v in os.environ.items()), 'Ambient dyld override forbidden')
    out = args.output.resolve();need(out.is_relative_to(ROOT / 'build'), 'New build/ output required')
    out.mkdir(parents=True, exist_ok=False)
    rows, jobs, expected = [], [], None
    try:
        client_id = common.identity(args.clients);client = audit.read(args.clients)
        need(client['status'] == 'PASS' and client['schema'] == 'steady-digest-cpu-clients-v1'
             and client['compile_only'] is True and set(client['clients']) == set(LABELS)
             and len(client['clients']) == 3, 'Complete fixed three-client manifest')
        plan = client['provenance']
        canonical = builder.provenance(audit, common)
        for key in ('roots', 'source_maps', 'libraries', 'source', 'original_body', 'compiler', 'flags', 'base', 'normal_hosts', 'source_transform'):
            need(plan[key] == canonical[key], 'Compile provenance differs from fixed canonical old/05: ' + key)
        need(client['driver']['sha256'] == common.identity(BUILDER)['sha256'], 'Builder identity changed')
        expected_sources = {'old5674': audit.OLD_SOURCE, 'saved05_off': audit.SAVED_SOURCE, 'saved05_on': audit.SAVED_SOURCE}
        need({r['label']: r['source'] for r in plan['roots']} == expected_sources, 'Old5674/saved05 exact sources')
        need({r['label']: r['count'] for r in plan['roots']} == {'old5674': 752, 'saved05_off': 768, 'saved05_on': 768}, 'Full source counts')
        need(client['copied_source']['sha256'] == plan['source']['sha256'] == common.identity(builder.SOURCE)['sha256'], 'Same diagnostic body')
        need(hashlib.sha256(builder.strip_diagnostic(builder.SOURCE.read_text()).encode()).hexdigest() == audit.BODY_SHA,
             'Original normal options/callback/body identity')
        input_id = plan['input'];need(input_id['sha256'] == audit.INPUT_SHA, 'Pinned input')
        start = builder.freeze(plan, common);need(start['status'] == 'PASS', str(start))
        linkages = {}
        for label in LABELS:
            host = client['clients'][label]
            need(host['libraries'] == canonical['libraries'][label], 'Runtime link libraries are not canonical old/05')
            need(host['source'] == expected_sources[label] and host['contract_version'] == (3 if label == 'old5674' else 4),
                 'Host source/ABI mismatch')
            macro = int(label == 'saved05_on')
            need(host['digest_macro'] == macro and host['digest_mode'] == builder.DIGEST_MODES[label]
                 and host['compile_command'].count('-DTS_NATIVE_DIGEST_ON=' + str(macro)) == 1,
                 'Actual host macro/mode differs from fixed client label')
            probe = next(v for v in host['libraries'] if Path(v['path']).name == audit.PROBE)
            linkages[label] = audit.linkage(common, host['binary'], probe)
        off, on = client['clients']['saved05_off'], client['clients']['saved05_on']
        need(off['source'] == on['source'] == audit.SAVED_SOURCE
             and off['libraries'] == on['libraries'] and off['source_root'] == on['source_root'],
             'Saved05 OFF/ON source/archive isolation')
        for repeat, order in enumerate(ORDERS, 1):
            for label in order:
                key = f'mono2_digest_cpu_r{repeat:02d}_{label}'
                jobs.append({'id': key, 'repeat': repeat, 'label': label, 'version': label,
                             'source': expected_sources[label], 'preset': 'candidate', 'speed': 2.0,
                             'digest_macro': int(label == 'saved05_on'), 'digest_mode': builder.DIGEST_MODES[label],
                             'command': [client['clients'][label]['binary']['path'], input_id['path'], 'candidate', '2.0', '30', str(out / key)]})
        need(len(jobs) == len({j['id'] for j in jobs}) == EXPECTED_PROGRAMS
             and EXPECTED_PROGRAMS == len(LABELS) * len(ORDERS)
             and EXPECTED_CHECKS == EXPECTED_PROGRAMS * len(CHECKS), 'Fixed9 programs/72 checks')
        expected = {'schema': 'steady-digest-cpu-run-v1', 'status': 'NOT_RUN', 'scope': builder.SCOPE,
                    'expected_programs': EXPECTED_PROGRAMS, 'expected_checks': EXPECTED_CHECKS, 'required_check_ids': list(CHECKS),
                    'required_ids': [j['id'] for j in jobs], 'jobs': jobs, 'seconds': 30, 'timeout_s': 180,
                    'client': client_id, 'driver': common.identity(__file__), 'builder': common.identity(BUILDER),
                    'helpers': [common.identity(audit.__file__), common.identity(audit.COMMON)],
                    'input': input_id, 'source': expected_sources, 'runtime_linkages': linkages,
                    'sourcefreeze_before': start, 'device_rate': args.device_rate, 'device_buffer': args.device_buffer,
                    'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        common.save(out / 'EXPECTED.json', expected)
        common.save(out / 'ENVIRONMENT_BEFORE.json', common.environment())
        for job in jobs:
            space = audit.capacity(input_id['bytes'])
            before = builder.freeze(plan, common);need(before['status'] == 'PASS', str(before))
            execution = common.execute(job['command'], out / (job['id'] + '.log'), 180)
            after = builder.freeze(plan, common)
            directory = Path(job['command'][-1]);summary_path, data_path = directory / 'SUMMARY.json', directory / 'THREAD_CPU.json'
            summary = audit.read(summary_path) if summary_path.is_file() else {}
            data = audit.read(data_path) if data_path.is_file() else {}
            result = assess(common, job, summary, data, execution, input_id, args.device_rate, args.device_buffer, after)
            row = {**job, **result, 'summary': summary, 'raw_thread_data': data,
                   'execution': execution, 'capacity_before': space, 'sourcefreeze_before': before, 'sourcefreeze_after': after,
                   'artifacts': [common.identity(p) for p in (summary_path, data_path) if p.is_file()]}
            rows.append(row)
            common.save(out / 'ROWS.json', rows)
            print(job['id'], 'MEASURED' if result['integrity_pass'] else 'FAIL', 'RT_PASS' if result['rt_pass'] else 'RT_FAIL', flush=True)
        final = builder.freeze(plan, common)
        need(common.identity(args.clients) == client_id and common.identity(__file__) == expected['driver'], 'Driver/client manifest changed during run')
        ids = [r['id'] for r in rows]
        complete = len(ids) == len(set(ids)) == EXPECTED_PROGRAMS and ids == expected['required_ids'] and final['status'] == 'PASS'
        checks = sum(len(r['checks']) for r in rows);passed = sum(c['pass'] for r in rows for c in r['checks'])
        valid = complete and checks == passed == EXPECTED_CHECKS
        rt_all = complete and all(r['rt_pass'] for r in rows)
        summary = {'status': 'PASS' if valid and rt_all else 'FAIL', 'classification': 'DIAGNOSTIC',
                   'complete': complete, 'functional_measurement_pass': valid, 'rt_pass': rt_all,
                   'expected_programs': EXPECTED_PROGRAMS, 'executed_programs': len(rows), 'expected_checks': EXPECTED_CHECKS,
                   'executed_checks': checks, 'passed_checks': passed, 'failed_checks': checks - passed,
                   'required_ids': expected['required_ids'], 'actual_ids': ids, 'sourcefreeze_after': final,
                   'expected': common.identity(out / 'EXPECTED.json'), 'rows': common.identity(out / 'ROWS.json'),
                   'statistics': aggregate(rows), 'scope': builder.SCOPE, 'quality': None, 'physical_audio': None,
                   'normal_CPU_counts_added': 0, 'automatic_adoption': False}
        common.save(out / 'SUMMARY.json', summary)
        common.save(out / 'ENVIRONMENT_AFTER.json', common.environment())
        print(out / 'SUMMARY.json')
        return 0 if valid and rt_all else 2
    except BaseException as error:
        common.save(out / 'ROWS.json', rows)
        common.save(out / 'SUMMARY.json', {'status': 'INCOMPLETE', 'complete': False, 'classification': 'DIAGNOSTIC',
                    'expected_programs': EXPECTED_PROGRAMS, 'executed_programs': len(rows), 'expected_checks': EXPECTED_CHECKS,
                    'executed_checks': sum(len(r.get('checks', [])) for r in rows),
                    'error': type(error).__name__ + ': ' + str(error), 'scope': builder.SCOPE,
                    'automatic_adoption': False, 'quality': None, 'physical_audio': None})
        raise


if __name__ == '__main__':
    sys.exit(main())
