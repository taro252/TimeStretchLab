"""D3待機の変更前bfa/指定afterをn3交互6program/48checksで直列実行する。

/usr/local/bin/python3 results/performance_response/recipes/run_armed_timer_probe.py \
  --client B/armed_timer_clients_01/CLIENT.json --output B/armed_timer_probe_01
両native argvはversion=candidateのまま、外側labelだけbefore_wait/after_wait。
20秒窓/子期限150秒。探索n1は今回の実施件数に加算せず、過去PASSも再実施としない。
exit0=全件機能/測定/報告RT PASS、2=機能/測定PASSかつ報告RT FAIL、1=不完全/FAIL。
品質/物理音声/実アプリF/統計的有意差・改善の自動承認は行わない。
"""
import argparse
import os
from pathlib import Path
import platform
import subprocess
import sys

import build_armed_timer_probe as build_recipe
import run_armed_wait_pairs as native
import run_pairs as common
import run_seek_history as d3

ROOT = Path(__file__).resolve().parents[3]
LABELS = build_recipe.LABELS
CHECK_IDS = build_recipe.original.CHECK_IDS
METRICS = native.METRICS
SCOPE = {**native.SCOPE,
    'revision_comparison': 'before_wait=bfa V4 saved executable/object; after_wait=explicit source SHA V4 same body/headers/flags, only native engine library changed',
    'native_version': 'candidate for both; outer label carries revision, native source SHA remains its actual build source',
    'n1': 'NOT_ADDED_TO_THIS_COUNT', 'n3': '3 new runs per revision, descriptive paired values/median/p95/max',
    'before_original_library_paths': 'historical identities mapped to archive03; overwritten live original paths are not treated as before bytes'}


def fixed_jobs(client, plan, out):
    after_source = client['after_requested_source']
    common.require(isinstance(after_source, str) and len(after_source) == 64
                   and all(c in '0123456789abcdef' for c in after_source)
                   and after_source != build_recipe.BEFORE_SOURCE, 'explicit after source SHA')
    initial = client['after_initial_inputs']
    common.require(set(initial) == {'after_build', 'after_archive', 'after_snapshot'}, 'all three CLI start identities')
    common.require(initial['after_build'] == client['after_build'] and initial['after_archive'] == client['after_archive']
                   and initial['after_snapshot'] == client['after_source_snapshot']['record'], 'CLI-start provenance retained')
    for item in initial.values():
        common.require(common.identity(item['path']) == item, 'after CLI input identity changed since compile start')
    after_build = common.load(Path(initial['after_build']['path']))
    after_archive = common.load(Path(initial['after_archive']['path']))
    after_snapshot = common.load(Path(initial['after_snapshot']['path']))
    common.require(after_build['status'] == 'PASS' and after_build['source'] == after_source
                   and after_build['source_manifest']['sha256'] == after_source
                   and common.manifest_digest(after_build['source_manifest']['files']) == after_source
                   and after_build['configuration'] == 'Release' and after_build['architecture'] == 'arm64', 'after BUILD source/configuration')
    common.require(after_archive['source'] == after_snapshot['source'] == after_source
                   and after_archive['build'] == initial['after_build']
                   and after_archive['source_snapshot'] == initial['after_snapshot'], 'archive/source/build identities bind')
    snapshot_rows = after_snapshot['files'] if 'files' in after_snapshot else after_snapshot['source_manifest']['files']
    common.require(snapshot_rows == after_build['source_manifest']['files'] and len(snapshot_rows) == 768
                   and common.manifest_digest(snapshot_rows) == after_source, 'after full 768-source manifest')
    common.require(client['schema'] == 'armed-timer-probe-client-v1' and client['status'] == 'PASS'
                   and client['compile_only'] is True, 'PASS compile-only revision clients')
    common.require(set(client['clients']) == set(LABELS) and client['before_relinked'] is False
                   and client['native_version_both'] == 'candidate' and client['exploration_reused_as_new_count'] is False,
                   'two revision labels/no before relink/no exploration count')
    common.require(client['before_client']['sha256'] == build_recipe.BEFORE_CLIENT_SHA
                   and client['before_build']['sha256'] == build_recipe.original.CANDIDATE_BUILD_SHA
                   and client['after_build'] == initial['after_build'],
                   'fixed linked before and explicit after BUILD identities')
    common.require(client['before_archive']['sha256'] == build_recipe.BEFORE_ARCHIVE_SHA
                   and client['after_archive'] == initial['after_archive'], 'fixed before/explicit after archive identities')
    common.require(client['before_source_snapshot']['record']['sha256'] == build_recipe.BEFORE_SNAPSHOT_SHA
                   and client['after_source_snapshot']['record'] == initial['after_snapshot'],
                   'fixed complete source snapshots')
    common.require(client['source']['sha256'] == client['copied_source']['sha256']
                   == client['before_copied_source']['sha256'] == build_recipe.original.CLIENT_SOURCE_SHA,
                   'one identical body for both clients')
    common.require(client['input']['sha256'] == build_recipe.original.INPUT_SHA
                   and client['preset'] in ('candidate', 'baseline'), 'fixed input/preset')
    for label, source in zip(LABELS, (build_recipe.BEFORE_SOURCE, after_source)):
        e = client['clients'][label]
        common.require(e['source'] == source and e['native_version'] == 'candidate'
                       and e['prepare_ABI'] == 'ContractV4Tag' and e['contract_version'] == 4
                       and e['architectures'] == ['arm64'], 'actual source and V4 ABI: ' + label)
        common.require(e['relinked'] is (label == 'after_wait')
                       and e['reused_binary'] is (label == 'before_wait')
                       and e['reused_object'] is (label == 'before_wait'), 'before reuse/after compile facts')
    before, after = (client['clients'][label] for label in LABELS)
    common.require(before['flags'] == after['flags'] and before['compiler'] == after['compiler']
                   and before['compiler_version'] == after['compiler_version'], 'same compiler/macros/flags')
    common.require(build_recipe.dependency_signature(before['dependencies'])
                   == build_recipe.dependency_signature(after['dependencies']), 'same all body/header/dependency byte identities')
    common.require(client['dependency_equivalence']['status'] == 'PASS'
                   and client['dependency_equivalence']['both_V4'] is True
                   and client['dependency_equivalence']['same_all_dependencies_bytes'] is True,
                   'compile dependency equivalence')
    common.require(client['source_changed_files'] == [build_recipe.NATIVE_SOURCE]
                   and client['archive_comparison']['total'] == 54
                   and native.exact_int(client['archive_comparison']['identical'])
                   and native.exact_int(client['archive_comparison']['changed'], 1)
                   and client['archive_comparison']['identical'] + client['archive_comparison']['changed'] == 54
                   and len(client['archive_comparison']['changed_names']) == client['archive_comparison']['changed']
                   and client['archive_comparison']['changed_libraries'] == [build_recipe.NATIVE_LIBRARY]
                   and client['archive_comparison']['shared_DSP_all_identical'] is True, 'bounded single native source/library change')
    for key, source in (('before_source_snapshot', build_recipe.BEFORE_SOURCE), ('after_source_snapshot', after_source)):
        snapshot = client[key]
        common.require(snapshot['source'] == source and len(snapshot['files']) == 768
                       and len({r['source_path'] for r in snapshot['files']}) == 768, 'full snapshot identities')
    # Re-derive source/library differences from the frozen metadata, rather
    # than trusting the compile client's difference labels alone.
    previous = common.load(Path(client['before_client']['path']))['clients']['candidate']
    for key in ('binary', 'object', 'depfile', 'compiler', 'flags_file', 'link_template', 'undefined_symbols'):
        common.require(before[key] == previous[key], 'saved bfa artifact identity: ' + key)
    common.require(build_recipe.dependency_signature(before['dependencies'])
                   == build_recipe.dependency_signature(previous['dependencies']), 'saved bfa dependency multiplicity/bytes')
    before_snapshot_meta = common.load(Path(client['before_source_snapshot']['record']['path']))
    before_rows = before_snapshot_meta['files']
    common.require(common.manifest_digest(before_rows) == build_recipe.BEFORE_SOURCE, 'before complete source ledger')
    before_map, after_map = ({r['path']: r['sha256'] for r in rows} for rows in (before_rows, snapshot_rows))
    common.require(len(before_map) == len(after_map) == 768 and set(before_map) == set(after_map)
                   and [p for p in before_map if before_map[p] != after_map[p]] == [build_recipe.NATIVE_SOURCE],
                   'recomputed sole Engine.mm source difference')
    before_archive_meta = common.load(Path(client['before_archive']['path']))
    arc_before, arc_after = ({Path(r['original']['path']).name: r for r in meta['files']}
                             for meta in (before_archive_meta, after_archive))
    common.require(len(before_archive_meta['files']) == len(after_archive['files']) == 54
                   and len(arc_before) == len(arc_after) == 54 and set(arc_before) == set(arc_after),
                   'complete unique archive target set')
    changed_names = sorted(n for n in arc_before if arc_before[n]['archived']['sha256'] != arc_after[n]['archived']['sha256'])
    common.require(changed_names == client['archive_comparison']['changed_names']
                   and [n for n in changed_names if n.endswith(('.a', '.dylib'))] == [build_recipe.NATIVE_LIBRARY],
                   'recomputed single native library difference')
    before_libraries = {Path(r['path']).name: r for r in before['libraries']}
    after_libraries = {Path(r['path']).name: r for r in after['libraries']}
    for old in previous['libraries']:
        name = Path(old['path']).name
        common.require(arc_before[name]['original'] == old and before_libraries[name] == arc_before[name]['archived']
                       and after_libraries[name] == arc_after[name]['original'], 'actual old/new library provenance: ' + name)
    expected = build_recipe.jobs_for(client, Path(client['run_plan']['path']).parent / 'run_not_started')
    common.require(plan['schema'] == 'armed-timer-probe-pairs-v1' and plan['status'] == 'NOT_RUN'
                   and plan['jobs'] == expected and plan['expected_programs'] == 6 and plan['expected_checks'] == 48
                   and plan['all_expected_ids'] == [j['id'] for j in expected]
                   and plan['required_check_ids'] == list(CHECK_IDS), 'full expected jobs/commands/check IDs')
    for key, value in {'repeats_per_version': 3, 'cpu_window_s': 20, 'child_timeout_s': 150,
                       'input': client['input'], 'preset': client['preset'], 'native_version_both': 'candidate',
                       'exploration_added_to_count': False, 'callback_gate': False,
                       'client_source_sha256': build_recipe.original.CLIENT_SOURCE_SHA,
                       'sources': {label: e['source'] for label, e in client['clients'].items()}}.items():
        common.require(plan.get(key) == value, 'RUN_PLAN field: ' + key)
    return build_recipe.jobs_for(client, out)


def compile_inventory(client, record_path):
    inventory = {}
    def add(item, role):
        wanted = {k: item[k] for k in ('path', 'bytes', 'sha256')}
        common.require(str(Path(wanted['path']).resolve()) == wanted['path'], 'absolute immutable identity')
        if wanted['path'] in inventory:
            common.require(inventory[wanted['path']]['identity'] == wanted, 'conflicting immutable identities')
            inventory[wanted['path']]['roles'].append(role)
        else:
            inventory[wanted['path']] = {'identity': wanted, 'roles': [role]}
    def walk(value, role):
        if isinstance(value, dict):
            if {'path', 'bytes', 'sha256'} <= value.keys():
                add(value, role)
            for k, v in value.items():
                walk(v, role + '.' + k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, role + '[' + str(i) + ']')
    add(common.identity(record_path), 'revision_client_compile_manifest')
    # Historical original library fields deliberately have historical_* keys.
    # Only their archive03 copies are current-byte identities. Do not recurse
    # into the historical CLIENT JSON itself or verify its overwritten library paths.
    walk(client, 'revision_client')
    common.require(len(client['commands']) == 2 and all(c['returncode'] == 0 for c in client['commands']),
                   'after-only successful compile and link')
    for label in LABELS:
        e = client['clients'][label];libs = e['libraries']
        common.require(len(libs) == 10 and sum(x['path'].endswith('.a') for x in libs) == 9
                       and sum(x['path'].endswith('.dylib') for x in libs) == 1, 'nine archives/probe per revision')
    mapping = client['before_library_archive_mapping']
    common.require(len(mapping) == 10 and len({m['name'] for m in mapping}) == 10, 'all historical link inputs mapped once')
    before_libs = {Path(x['path']).name: x for x in client['clients']['before_wait']['libraries']}
    for row in mapping:
        common.require(before_libs.get(row['name']) == row['verified_archived']
                       and row['historical_sha256'] == row['verified_archived']['sha256']
                       and row['historical_bytes'] == row['verified_archived']['bytes'], 'historical archive byte equivalence')
    for module in (common, d3, native, build_recipe, build_recipe.original):
        add(common.identity(module.__file__), 'run_helper')
    add(common.identity(__file__), 'run_driver')
    return list(inventory.values())


def assess(job, directory, execution, client):
    e = client['clients'][job['label']]
    shim = {'clients': {'candidate': e}, 'input': client['input']}
    # Both programs truthfully write native version=candidate and their own source SHA.
    return native.assess({**job, 'version': 'candidate'}, directory, execution, shim)


def aggregate(rows):
    groups, pairs = {}, []
    for label in LABELS:
        selected = [r for r in rows if r['label'] == label]
        valid = [r for r in selected if native.qualified(r)]
        groups[label] = {'expected_programs': 3, 'executed_programs': len(selected),
            'qualified_programs': len(valid), 'qualified_rt_pass_programs': sum(r.get('rt_pass') is True for r in valid),
            'invalid_program_ids': [r['id'] for r in selected if not native.qualified(r)],
            'metrics': {metric: {'qualified': native.stats([r['summary'][metric] for r in valid]),
                        'qualified_rt_pass': native.stats([r['summary'][metric] for r in valid if r.get('rt_pass')])}
                        for metric in METRICS}}
    for repeat in (1, 2, 3):
        pair = {r['label']: r for r in rows if r['repeat'] == repeat and native.qualified(r)}
        result = {'repeat': repeat, 'complete_qualified_pair': set(pair) == set(LABELS), 'differences': {}}
        if result['complete_qualified_pair']:
            result['both_rt_pass'] = all(r.get('rt_pass') for r in pair.values())
            for metric in METRICS:
                before, after = (pair[label]['summary'][metric] for label in LABELS)
                result['differences'][metric] = {'before_wait': before, 'after_wait': after,
                    'after_minus_before': after - before, 'after_over_before': after / before if before > 0 else None,
                    'reduction_percent': 100 * (before - after) / before if before > 0 else None,
                    'before_zero_no_relative_reduction_defined': before == 0}
        pairs.append(result)
    return {'by_label': groups, 'pairs': pairs, 'significance': 'NOT_ASSESSED',
            'decision': 'DESCRIPTIVE_ONLY', 'n1_exploration_counted': False, 'performance_improvement_approval': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new run output under build/')
    out.mkdir(parents=True, exist_ok=False)
    rows, jobs, errors, inventory, source_rows = [], [], [], [], []
    frozen_after = fixed_device = final_device = None
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS Python')
        common.require(not any(os.environ.get(k) for k in ('DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'CPATH',
            'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH', 'LIBRARY_PATH')), 'ambient include/library override')
        client = common.load(args.client)
        plan_path = Path(client['run_plan']['path']).resolve()
        common.require(common.identity(plan_path) == client['run_plan'], 'saved RUN_PLAN identity')
        jobs = fixed_jobs(client, common.load(plan_path), out)
        common.save(out / 'EXPECTED.json', {'schema': 'armed-timer-probe-run-v1', 'status': 'NOT_RUN',
            'expected_programs': 6, 'expected_checks': 48, 'repeats_per_revision': 3,
            'all_expected_ids': [j['id'] for j in jobs], 'required_check_ids': list(CHECK_IDS),
            'all_expected_check_ids': [j['id'] + '/' + c for j in jobs for c in CHECK_IDS], 'jobs': jobs,
            'cpu_window_s': 20, 'child_timeout_s': 150, 'timeout_allowed': False,
            'sources': {label: e['source'] for label, e in client['clients'].items()},
            'binaries': {label: e['binary'] for label, e in client['clients'].items()},
            'objects': {label: e['object'] for label, e in client['clients'].items()}, 'input': client['input_format'],
            'client_record': common.identity(args.client), 'run_plan': client['run_plan'], 'driver': common.identity(__file__),
            'helpers': [common.identity(m.__file__) for m in (common, d3, native, build_recipe)],
            'archive_comparison': client['archive_comparison'], 'patch': client['patch'],
            'after_requested_source': client['after_requested_source'], 'after_initial_inputs': client['after_initial_inputs'],
            'before_relinked': False, 'exploration_added_to_count': False, 'scope': SCOPE})
        inventory = compile_inventory(client, args.client)
        common.save(out / 'COMPILE_INVENTORY.json', {'files': inventory, 'manifest_sha256': common.manifest_digest(inventory)})
        d3.verify_inventory(inventory, out / 'FROZEN_BEFORE.json')
        for label, e in client['clients'].items():
            root = Path(e['source_root']).resolve()
            common.require(common.current_source_digest(root) == e['source'], label + ' full source bytes before run')
            source_rows.append({'label': label, 'root': str(root), 'source': e['source']})
            common.require(subprocess.check_output(['/usr/bin/lipo', '-archs', e['binary']['path']], text=True).split() == ['arm64'], 'arm64 client')
        info = common.wav_identity(Path(client['input']['path']), 48000, 1)
        common.require({k: info[k] for k in ('path', 'bytes', 'sha256')} == client['input'], 'fixed chain300 input and Float32 format')
        common.save(out / 'ENVIRONMENT_BEFORE.json', common.environment())
        fixed_device = d3.output_device();common.save(out / 'DEVICE_BEFORE.json', fixed_device)
        common.require(fixed_device['buffer_frames'] == 512, 'default output buffer must be 512')
        manifest_identity = common.identity(args.client)
        for job in jobs:
            e = client['clients'][job['label']]
            common.require(common.identity(e['binary']['path']) == e['binary']
                           and common.identity(e['object']['path']) == e['object']
                           and common.identity(args.client) == manifest_identity, 'client/executable/object changed before child')
            before_device = d3.output_device()
            common.require(before_device == fixed_device, 'device changed before child')
            row = {k: job[k] for k in ('id', 'pair_id', 'repeat', 'label', 'version', 'preset')}
            row.update(command=job['command'], source=e['source'], binary=e['binary'], device_before=before_device,
                       load_average_before=list(os.getloadavg()))
            execution = common.execute(job['command'], out / (job['id'] + '.log'), 150)
            row['execution'] = execution;directory = out / job['id']
            try:
                row.update(assess(job, directory, execution, client))
            except (OSError, ValueError, KeyError, TypeError, RuntimeError, OverflowError) as error:
                row.update(integrity_pass=False, functional_pass=False, measurement_valid=False, rt_pass=False,
                    checks_passed=0, integrity_errors=[type(error).__name__ + ': ' + str(error)],
                    functional_errors=[], measurement_errors=[], summary={})
            row['artifacts'] = [common.identity(directory / name) for name in native.ARTIFACTS if (directory / name).is_file()]
            row['load_average_after'] = list(os.getloadavg())
            try:
                row['device_after'] = d3.output_device()
                if row['device_after'] != fixed_device:
                    row['integrity_pass'] = False;row['integrity_errors'].append('device changed during child')
            except (OSError, RuntimeError) as error:
                row['integrity_pass'] = False;row['integrity_errors'].append('device after: ' + str(error))
            row['classification'] = ('FUNCTIONAL_AND_RT_PASS' if native.qualified(row) and row['rt_pass']
                else 'FUNCTIONAL_PASS_RT_FAIL' if native.qualified(row) else 'INCOMPLETE_OR_FAIL')
            rows.append(row)
            common.save(out / 'ROWS.json', {'rows': rows})
            common.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_programs': 6, 'expected_checks': 48,
                'executed_programs': len(rows), 'reported_passed_checks': sum(r['checks_passed'] for r in rows),
                'statistics': aggregate(rows), 'rows': rows, 'scope': SCOPE})
            print(job['id'], execution['returncode'], row['classification'], flush=True)
            if execution['interrupted']:
                raise KeyboardInterrupt('child interrupted and joined')
        frozen_after = d3.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
        for item in source_rows:
            common.require(common.current_source_digest(Path(item['root'])) == item['source'], item['label'] + ' source changed during run')
        common.save(out / 'ENVIRONMENT_AFTER.json', common.environment())
        final_device = d3.output_device();common.save(out / 'DEVICE_AFTER.json', final_device)
        common.require(final_device == fixed_device, 'device changed at final audit')
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        if inventory and frozen_after is None:
            try:
                frozen_after = d3.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
            except BaseException as error:
                errors.append('final inventory: ' + type(error).__name__ + ': ' + str(error))
    executed_ids, expected_ids = [r['id'] for r in rows], [j['id'] for j in jobs]
    complete = bool(len(jobs) == len(rows) == 6 and executed_ids == expected_ids and len(set(executed_ids)) == 6
        and all(r['summary'].get('run_complete') is True and not r['execution']['timeout']
                and not r['execution']['interrupted'] for r in rows))
    integrity = bool(complete and not errors and frozen_after and frozen_after['status'] == 'PASS'
                     and all(r['integrity_pass'] for r in rows))
    functional = bool(complete and all(r['functional_pass'] for r in rows))
    measured = bool(integrity and functional and all(r['measurement_valid'] for r in rows))
    rt = bool(complete and all(r['rt_pass'] for r in rows))
    status = 'PASS' if measured and rt else 'FUNCTIONAL_PASS_RT_FAIL' if measured else 'INCOMPLETE_OR_FAIL'
    final = {'schema': 'armed-timer-probe-run-v1', 'status': status, 'run_complete': complete,
        'expected_programs': 6, 'expected_checks': 48, 'executed_programs': len(rows),
        'reported_passed_checks': sum(r['checks_passed'] for r in rows), 'all_expected_ids': expected_ids,
        'executed_ids': executed_ids, 'missing_ids': [i for i in expected_ids if i not in executed_ids],
        'required_check_ids': list(CHECK_IDS), 'integrity_pass': integrity, 'functional_pass': functional,
        'measurement_valid': measured, 'rt_all_reported_pass': rt, 'rt_evidence_qualified': bool(measured and rt),
        'repeats_per_revision': 3, 'exploration_added_to_count': False, 'statistics': aggregate(rows),
        'errors': errors, 'rows': rows, 'scope': SCOPE, 'frozen_after': frozen_after,
        'expected_record': common.identity(out / 'EXPECTED.json') if (out / 'EXPECTED.json').exists() else None,
        'device_before': fixed_device, 'device_after': final_device}
    common.save(out / 'SUMMARY.json', final)
    return 0 if status == 'PASS' else 2 if status == 'FUNCTIONAL_PASS_RT_FAIL' else 1


if __name__ == '__main__':
    sys.exit(main())
