"""D3 Armed待機を旧新の同じ専用本文で直列測定する。製品は変更しない。

/usr/local/bin/python3 results/performance_response/recipes/run_armed_wait_pairs.py \
  --client B/armed_wait_clients_01/CLIENT.json --repeats 1 --output B/armed_wait_explore_01
探索はn1×旧新=2program/16checks。既定--repeats 3は6program/48checks。
各窓20秒、子期限150秒。保存n3計画の先頭ペアをn1探索として明示選択できる。
機能完走/実窓/RTを分け、CPU値0や未exerciseを改善PASSへ読み替えない。
exit0=選択全件機能/実窓/報告RT PASS、2=機能/実窓PASSかつ報告RT FAIL、
1=未実施/不完全/機能/整合性/実窓FAIL。品質/物理音声/実アプリ承認はしない。
"""
import argparse
import math
import os
from pathlib import Path
import platform
import subprocess
import sys

import build_armed_wait_clients as build_recipe
import run_pairs as common
import run_seek_history as d3

ROOT = Path(__file__).resolve().parents[3]
METRICS = ('seek_thread_cpu_s', 'seek_thread_cpu_percent', 'process_cpu_s',
           'process_cpu_percent', 'process_interrupt_wakeups', 'window_wall_s')
ARTIFACTS = ('EXPECTED.json', 'SUMMARY.json', 'checks.jsonl', 'observations.jsonl')
SCOPE = {
    'measurement': '20s scheduled-boundary Armed wait; 1 core=100%; contribution only, no adoption threshold',
    'phase_observation': 'public Armed/fixed-B facts plus normal SwitchPublished hook; private Requested phase inferred, not counted directly',
    'seek_CPU': 'live seek thread Mach THREAD_BASIC_INFO user+system delta',
    'process_CPU': 'RUSAGE_SELF user+system delta in native steady_clock window; includes polling',
    'interrupt_wakeups': 'proc_pid_rusage process interrupt-wakeup delta; not a seek-thread wakeup counter',
    'whole_process': 'wait4 child user+system/wall includes preparation, first A, 20s window, B adoption, Stop and JSON',
    'device_ID': 'outer default-output-device before/after; native reports actual device rate/buffer only',
    'RT': 'native reported deadline/host/sample/HAL/workgroup result; no physical or application approval',
    'n1': 'exploratory pair; no statistical significance or performance-improvement claim',
    'n3': 'descriptive paired values/median/p95/max only; no statistical significance',
    'callback_gate': False, 'independent_PCM': 'NOT_RUN', 'performance_improvement_approval': False,
    'quality_approval': False, 'RT_approval': False, 'physical_audio': None, 'application_F': None}


def finite_tree(value):
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(finite_tree(v) for v in value.values())
    if isinstance(value, list):
        return all(finite_tree(v) for v in value)
    return True


def exact_int(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def fixed_jobs(client, plan, out, repeats):
    common.require(client['schema'] == 'performance-armed-wait-clients-v1' and client['status'] == 'PASS'
                   and client['compile_only'] is True, 'PASS compile-only Armed clients required')
    common.require(set(client['clients']) == {'old', 'candidate'}, 'exact old/candidate clients')
    common.require(client['clients']['old']['source'] == build_recipe.frozen.OLD_SOURCE_SHA
                   and client['clients']['candidate']['source'] == build_recipe.CANDIDATE_SOURCE, 'fixed source pair')
    common.require(client['baseline_source'] == build_recipe.frozen.OLD_SOURCE_SHA
                   and client['baseline_commit'] == build_recipe.frozen.OLD_COMMIT, 'fixed baseline commit/source')
    common.require(client['baseline_client']['sha256'] == build_recipe.BASELINE_CLIENT_SHA
                   and client['candidate_build']['sha256'] == build_recipe.CANDIDATE_BUILD_SHA, 'frozen02/final03 records')
    common.require(client['source']['sha256'] == client['copied_source']['sha256'] == build_recipe.CLIENT_SOURCE_SHA,
                   'identical fixed Armed body')
    common.require(client['input']['sha256'] == build_recipe.INPUT_SHA, 'chain300 input SHA')
    common.require(client['preset'] in ('candidate', 'baseline') and client['repeats'] in (1, 3), 'preset/repeats')
    declared = client['repeats']
    common.require(repeats <= declared, 'n3 requires an n3 saved client plan')
    expected = build_recipe.jobs_for(client, Path(client['run_plan']['path']).parent / 'run_not_started', declared)
    common.require(plan['schema'] == 'armed-wait-pairs-v1' and plan['status'] == 'NOT_RUN'
                   and plan['jobs'] == expected, 'saved full RUN_PLAN commands/order/IDs')
    common.require(plan['expected_programs'] == 2 * declared and plan['expected_checks'] == 16 * declared
                   and plan['all_expected_ids'] == [j['id'] for j in expected]
                   and plan['required_check_ids'] == list(build_recipe.CHECK_IDS), 'full declared ID/count set')
    for key, wanted in {'repeats_per_version': declared, 'cpu_window_s': 20, 'child_timeout_s': 150,
                        'A_input_frame': 0, 'B_input_frame': 1440000, 'initial_speed_micros': 1000000,
                        'target_speed_micros': 750000, 'preset': client['preset'], 'input': client['input'],
                        'client_source_sha256': build_recipe.CLIENT_SOURCE_SHA, 'callback_gate': False,
                        'performance_goal': 'CONTRIBUTION_MEASUREMENT_ONLY'}.items():
        common.require(plan.get(key) == wanted, 'RUN_PLAN field: ' + key)
    return build_recipe.jobs_for(client, out, repeats)


def compile_inventory(client, path):
    inventory = {}
    def add(item, role):
        wanted = {k: item[k] for k in ('path', 'bytes', 'sha256')}
        common.require(str(Path(wanted['path']).resolve()) == wanted['path'], 'absolute identity path')
        if wanted['path'] in inventory:
            common.require(inventory[wanted['path']]['identity'] == wanted, 'conflicting artifact identities')
            inventory[wanted['path']]['roles'].append(role)
        else:
            inventory[wanted['path']] = {'identity': wanted, 'roles': [role]}
    def walk(value, role):
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys():
                add(value, role)
            for key, child in value.items():
                walk(child, role + '.' + key)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, role + '[' + str(i) + ']')
    add(common.identity(path), 'client_compile_manifest')
    walk(client, 'compiled')
    for version, entry in client['clients'].items():
        common.require(entry['prepare_ABI'] == ('ContractV3Tag' if version == 'old' else 'ContractV4Tag')
                       and entry['contract_version'] == (3 if version == 'old' else 4)
                       and entry['architectures'] == ['arm64'], 'prepare ABI/arm64')
        libraries = entry['libraries']
        common.require(len(libraries) == 10 and sum(i['path'].endswith('.a') for i in libraries) == 9
                       and sum(i['path'].endswith('.dylib') for i in libraries) == 1, 'nine archives plus heap probe')
        if version == 'old':
            common.require({Path(i['path']).name: i['sha256'] for i in libraries} == build_recipe.frozen.OLD_LINK_SHA,
                           'old archive/probe known SHA set')
    common.require(len(client['commands']) == 4 and all(c['returncode'] == 0 for c in client['commands']),
                   'exact four successful compile/link commands')
    for module in (common, d3, build_recipe):
        add(common.identity(module.__file__), 'run_helper')
    add(common.identity(__file__), 'run_driver')
    return list(inventory.values())


def assess(job, directory, execution, client):
    integrity, functional, measurement = [], [], []
    def check(group, condition, text):
        if not condition:
            group.append(text)
    def read(name, jsonl=False):
        try:
            value = d3.lines(directory / name) if jsonl else common.load(directory / name)
            common.require(finite_tree(value), 'nonfinite JSON measurement')
            return value
        except (OSError, ValueError, RuntimeError) as error:
            integrity.append(name + ': ' + str(error))
            return [] if jsonl else {}
    summary, expected = read('SUMMARY.json'), read('EXPECTED.json')
    checks, observations = read('checks.jsonl', True), read('observations.jsonl', True)
    check(integrity, isinstance(summary, dict) and isinstance(expected, dict)
          and isinstance(checks, list) and isinstance(observations, list), 'artifact object/list types')
    ids = [c.get('id') for c in checks if isinstance(c, dict)]
    passed = sum(isinstance(c, dict) and c.get('status') == 'PASS' for c in checks)
    check(functional, len(checks) == 8 and len(ids) == len(set(ids)) == 8
          and set(ids) == set(build_recipe.CHECK_IDS) and passed == 8, 'all eight unique fixed check IDs PASS')
    check(integrity, expected.get('required_ids') == list(build_recipe.CHECK_IDS)
          and expected.get('expected') == 8 and expected.get('suite') == 'D3_scheduled_boundary_Armed'
          and expected.get('schema') == summary.get('schema') == 1, 'native EXPECTED schema/IDs/count')
    for key, wanted in {'source': client['clients'][job['version']]['source'], 'version': job['version'],
                        'preset': job['preset']}.items():
        check(integrity, summary.get(key) == expected.get(key) == wanted, 'native identity: ' + key)
    for key, wanted in {'input_sha256': client['input']['sha256'],
                        'binary_sha256': client['clients'][job['version']]['binary']['sha256'],
                        'contract_version': 3 if job['version'] == 'old' else 4,
                        'A': 0, 'B': 1440000, 'initial_speed': 1, 'target_speed': .75,
                        'CPU_window_s': 20, 'callback_gate': False, 'normal_hook_blocks': False,
                        'history_copy_in_CPU_window': False, 'direct_private_phase_read': False,
                        'independent_PCM': 'NOT_RUN', 'RT_approval': False}.items():
        check(integrity, expected.get(key) == wanted, 'native EXPECTED field: ' + key)
    check(functional, summary.get('status') == 'PASS' and summary.get('run_complete') is True
          and summary.get('expected') == summary.get('executed') == 8
          and summary.get('Armed_exercised') is True and summary.get('reason') == '', 'complete/exercised native result')
    check(integrity, not execution['timeout'] and not execution['interrupted'], 'child timeout/interruption')
    check(integrity, isinstance(summary.get('rt_pass'), bool)
          and execution['returncode'] == (0 if summary.get('rt_pass') is True else 2), 'exit0/2 must match reported RT')
    for key in METRICS:
        check(measurement, common.finite(summary.get(key)) and summary[key] >= 0, 'finite nonnegative measurement: ' + key)
    for key in ('seek_thread_ID', 'polls', 'loop_id', 'speed_id', 'owner_alive', 'owner_peak',
                'worker_deadlines', 'callback_deadlines', 'missing', 'callback_cpp_new',
                'callback_heap_allocations', 'callback_heap_frees', 'process_interrupt_wakeups'):
        check(measurement, exact_int(summary.get(key)), 'unsigned counter: ' + key)
    wall = summary.get('window_wall_s')
    check(measurement, common.finite(wall) and 20 <= wall <= 20.5, 'full finite 20s window')
    if common.finite(wall) and wall > 0:
        for cpu, percent in (('seek_thread_cpu_s', 'seek_thread_cpu_percent'), ('process_cpu_s', 'process_cpu_percent')):
            a, b = summary.get(cpu), summary.get(percent)
            check(measurement, common.finite(a) and common.finite(b)
                  and math.isclose(100 * a / wall, b, rel_tol=1e-10, abs_tol=1e-8), 'CPU formula: ' + cpu)
    check(measurement, exact_int(summary.get('seek_thread_ID'), 1)
          and exact_int(summary.get('loop_id'), 1) and exact_int(summary.get('speed_id'), 1)
          and exact_int(summary.get('polls')) and 90 <= summary['polls'] <= 110, 'live thread/loop/speed and finite polls')
    check(functional, summary.get('owner_alive') == 0 and exact_int(summary.get('owner_peak'), 1)
          and summary['owner_peak'] <= 2, 'released owners/peak <= 2')
    for key in ('missing', 'callback_cpp_new', 'callback_heap_allocations', 'callback_heap_frees'):
        check(functional, summary.get(key) == 0, 'supply/callback zero: ' + key)
    check(measurement, summary.get('source_rate') == summary.get('device_rate') == 48000
          and summary.get('device_buffer') == 512, 'actual native source/device rate and buffer')
    check(integrity, summary.get('direct_private_phase_read') is False, 'phase inference must remain explicit')
    for key in ('performance_improvement_approval', 'quality_approval', 'RT_approval'):
        check(integrity, summary.get(key) is False, 'no transferred approval: ' + key)
    check(integrity, summary.get('physical_audio') is None and summary.get('application_F') is None,
          'physical/application evidence remains unmeasured')
    check(measurement, len(observations) == 1 and observations[0].get('record') == 'window_end', 'exact window-end observation')
    if len(observations) == 1:
        ob = observations[0]
        check(measurement, ob.get('loop_id') == summary.get('loop_id') and ob.get('speed_id') == summary.get('speed_id')
              and exact_int(ob.get('old_session'), 1) and exact_int(ob.get('cycle'))
              and exact_int(ob.get('published_hook'), 1) and exact_int(ob.get('start_hook'))
              and exact_int(ob.get('old_RAW_frames_during_window'), 1), 'window identity/actual continuing old PCM')
    rt = summary.get('rt_pass') is True
    if rt:
        check(integrity, summary.get('worker_deadlines') == summary.get('callback_deadlines') == 0,
              'reported RT PASS contradicts exported deadlines')
    return {'integrity_pass': not integrity, 'functional_pass': not functional,
            'measurement_valid': not measurement, 'rt_pass': rt, 'checks_passed': passed,
            'integrity_errors': integrity, 'functional_errors': functional, 'measurement_errors': measurement,
            'summary': summary, 'native_expected': expected, 'observations': observations}


def stats(values):
    return {'n': len(values), 'median': common.percentile(values, .5),
            'p95_interpolated': common.percentile(values, .95), **common.dispersion(values)}


def qualified(row):
    return all(row.get(k) is True for k in ('integrity_pass', 'functional_pass', 'measurement_valid'))


def aggregate(rows, repeats):
    groups, pairs = {}, []
    for version in ('old', 'candidate'):
        selected = [r for r in rows if r['version'] == version]
        valid = [r for r in selected if qualified(r)]
        groups[version] = {'expected_programs': repeats, 'executed_programs': len(selected),
            'qualified_programs': len(valid), 'qualified_rt_pass_programs': sum(r.get('rt_pass') is True for r in valid),
            'invalid_program_ids': [r['id'] for r in selected if not qualified(r)],
            'metrics': {metric: {'qualified': stats([r['summary'][metric] for r in valid]),
                        'qualified_rt_pass': stats([r['summary'][metric] for r in valid if r.get('rt_pass')])}
                        for metric in METRICS}}
    for repeat in range(1, repeats + 1):
        found = {r['version']: r for r in rows if r['repeat'] == repeat and qualified(r)}
        result = {'repeat': repeat, 'complete_qualified_pair': set(found) == {'old', 'candidate'}, 'differences': {}}
        if result['complete_qualified_pair']:
            result['both_rt_pass'] = all(r.get('rt_pass') for r in found.values())
            for metric in METRICS:
                old, new = (found[v]['summary'][metric] for v in ('old', 'candidate'))
                result['differences'][metric] = {'old': old, 'candidate': new, 'candidate_minus_old': new - old,
                    'candidate_over_old': new / old if old > 0 else None,
                    'candidate_reduction_percent': 100 * (old - new) / old if old > 0 else None,
                    'old_zero_no_relative_reduction_defined': old == 0}
        pairs.append(result)
    return {'by_version': groups, 'pairs': pairs, 'significance': 'NOT_ASSESSED',
            'decision': 'EXPLORATORY_ONLY' if repeats == 1 else 'DESCRIPTIVE_ONLY',
            'performance_improvement_approval': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeats', type=int, choices=(1, 3), default=3)
    args = parser.parse_args()
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new run output under build/')
    out.mkdir(parents=True, exist_ok=False)
    rows, jobs, errors, inventory, source_rows = [], [], [], [], []
    frozen_after = fixed_device = final_device = None
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'arm64 macOS Python required')
        common.require(not any(os.environ.get(k) for k in ('DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'CPATH',
                       'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH', 'LIBRARY_PATH')), 'ambient include/library override')
        client = common.load(args.client)
        plan_path = Path(client['run_plan']['path']).resolve()
        common.require(common.identity(plan_path) == client['run_plan'], 'RUN_PLAN identity changed')
        jobs = fixed_jobs(client, common.load(plan_path), out, args.repeats)
        common.save(out / 'EXPECTED.json', {'schema': 'armed-wait-run-v1', 'status': 'NOT_RUN',
            'expected_programs': args.repeats * 2, 'expected_checks': args.repeats * 16,
            'all_expected_ids': [j['id'] for j in jobs], 'required_check_ids': list(build_recipe.CHECK_IDS),
            'all_expected_check_ids': [j['id'] + '/' + c for j in jobs for c in build_recipe.CHECK_IDS], 'jobs': jobs,
            'repeats_per_version': args.repeats, 'exploratory': args.repeats == 1, 'cpu_window_s': 20,
            'child_timeout_s': 150, 'timeout_allowed': False, 'client_record': common.identity(args.client),
            'run_plan': client['run_plan'], 'driver': common.identity(__file__),
            'helpers': [common.identity(m.__file__) for m in (common, d3, build_recipe)],
            'sources': {v: c['source'] for v, c in client['clients'].items()},
            'binaries': {v: c['binary'] for v, c in client['clients'].items()},
            'input': client['input_format'], 'scope': SCOPE})
        inventory = compile_inventory(client, args.client)
        common.save(out / 'COMPILE_INVENTORY.json', {'files': inventory, 'manifest_sha256': common.manifest_digest(inventory)})
        d3.verify_inventory(inventory, out / 'FROZEN_BEFORE.json')
        for version, entry in client['clients'].items():
            root = Path(entry['source_root']).resolve()
            common.require(common.current_source_digest(root) == entry['source'], version + ' source changed before run')
            source_rows.append({'root': str(root), 'sha256': entry['source']})
            arches = subprocess.check_output(['/usr/bin/lipo', '-archs', entry['binary']['path']], text=True).split()
            common.require(arches == ['arm64'], 'native arm64 client')
        input_info = common.wav_identity(Path(client['input']['path']), 48000, 1)
        common.require({k: input_info[k] for k in ('path', 'bytes', 'sha256')} == client['input'], 'fixed input/format')
        common.save(out / 'ENVIRONMENT_BEFORE.json', common.environment())
        fixed_device = d3.output_device()
        common.save(out / 'DEVICE_BEFORE.json', fixed_device)
        common.require(fixed_device['buffer_frames'] == 512, 'actual default output buffer must be 512')
        for job in jobs:
            common.require(common.identity(client['clients'][job['version']]['binary']['path'])
                           == client['clients'][job['version']]['binary'], 'binary changed before child')
            before = d3.output_device()
            common.require(before == fixed_device, 'device changed before child')
            row = {k: job[k] for k in ('id', 'pair_id', 'repeat', 'version', 'preset')}
            row.update(command=job['command'], device_before=before, load_average_before=list(os.getloadavg()))
            execution = common.execute(job['command'], out / (job['id'] + '.log'), 150)
            row['execution'] = execution
            directory = out / job['id']
            try:
                row.update(assess(job, directory, execution, client))
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, OverflowError) as error:
                row.update(integrity_pass=False, functional_pass=False, measurement_valid=False, rt_pass=False,
                    checks_passed=0, integrity_errors=[type(error).__name__ + ': ' + str(error)],
                    functional_errors=[], measurement_errors=[], summary={})
            row['artifacts'] = [common.identity(directory / name) for name in ARTIFACTS if (directory / name).is_file()]
            row['load_average_after'] = list(os.getloadavg())
            try:
                row['device_after'] = d3.output_device()
                if row['device_after'] != fixed_device:
                    row['integrity_pass'] = False
                    row['integrity_errors'].append('default output device changed during child')
            except (OSError, RuntimeError) as error:
                row['integrity_pass'] = False
                row['integrity_errors'].append('device after: ' + str(error))
            row['classification'] = ('FUNCTIONAL_AND_RT_PASS' if qualified(row) and row['rt_pass']
                                     else 'FUNCTIONAL_PASS_RT_FAIL' if qualified(row) else 'INCOMPLETE_OR_FAIL')
            rows.append(row)
            common.save(out / 'ROWS.json', {'rows': rows})
            common.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_programs': args.repeats * 2,
                'expected_checks': args.repeats * 16, 'executed_programs': len(rows),
                'reported_passed_checks': sum(r['checks_passed'] for r in rows),
                'statistics': aggregate(rows, args.repeats), 'rows': rows, 'scope': SCOPE})
            print(job['id'], execution['returncode'], row['classification'], flush=True)
            if execution['interrupted']:
                raise KeyboardInterrupt('child interrupted and joined')
        frozen_after = d3.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
        for item in source_rows:
            common.require(common.current_source_digest(Path(item['root'])) == item['sha256'], 'source changed during run')
        common.save(out / 'ENVIRONMENT_AFTER.json', common.environment())
        final_device = d3.output_device()
        common.save(out / 'DEVICE_AFTER.json', final_device)
        common.require(final_device == fixed_device, 'device changed at final audit')
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        if inventory and frozen_after is None:
            try:
                frozen_after = d3.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
            except BaseException as error:
                errors.append('final frozen audit: ' + type(error).__name__ + ': ' + str(error))
    executed_ids = [r['id'] for r in rows]
    expected_ids = [j['id'] for j in jobs]
    complete = (len(jobs) == args.repeats * 2 and executed_ids == expected_ids
                and len(set(executed_ids)) == len(executed_ids)
                and all(r['summary'].get('run_complete') is True and not r['execution']['timeout']
                        and not r['execution']['interrupted'] for r in rows))
    integrity = bool(complete and not errors and frozen_after and frozen_after['status'] == 'PASS'
                     and all(r['integrity_pass'] for r in rows))
    functional = bool(complete and all(r['functional_pass'] for r in rows))
    measured = bool(integrity and functional and all(r['measurement_valid'] for r in rows))
    rt = bool(complete and all(r['rt_pass'] for r in rows))
    status = 'PASS' if measured and rt else 'FUNCTIONAL_PASS_RT_FAIL' if measured else 'INCOMPLETE_OR_FAIL'
    final = {'schema': 'armed-wait-run-v1', 'status': status, 'run_complete': complete,
        'expected_programs': args.repeats * 2, 'expected_checks': args.repeats * 16,
        'executed_programs': len(rows), 'reported_passed_checks': sum(r['checks_passed'] for r in rows),
        'all_expected_ids': expected_ids, 'executed_ids': executed_ids,
        'missing_ids': [i for i in expected_ids if i not in executed_ids],
        'required_check_ids': list(build_recipe.CHECK_IDS), 'integrity_pass': integrity,
        'functional_pass': functional, 'measurement_valid': measured,
        'rt_all_reported_pass': rt, 'rt_evidence_qualified': bool(measured and rt),
        'exploratory': args.repeats == 1, 'repeats_per_version': args.repeats,
        'statistics': aggregate(rows, args.repeats), 'errors': errors, 'rows': rows,
        'scope': SCOPE, 'frozen_after': frozen_after,
        'expected_record': common.identity(out / 'EXPECTED.json') if (out / 'EXPECTED.json').exists() else None,
        'device_before': fixed_device, 'device_after': final_device}
    common.save(out / 'SUMMARY.json', final)
    return 0 if status == 'PASS' else 2 if status == 'FUNCTIONAL_PASS_RT_FAIL' else 1


if __name__ == '__main__':
    sys.exit(main())
