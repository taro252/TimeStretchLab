#!/usr/bin/env python3
"""完了済み08 steady48を保持し、指定条件だけ追加n3を一度収録する。

--primary-run / --baseline-client / --candidate-build / --strata / --output は必須。
source08、native_archive_08、同じ入力/共通body/実行体に固定する。
run_pairs原本へ--repeats6と選択条件のr04/r05/r06だけを渡すため、追加は各条件3pair。
追加順は候補先/旧先/候補先。元n3と合わせたn6は先行3:3になる。
元全48、追加全n3、指定条件の併合n6を分離し、CPU改善/採用を自動承認しない。
一次結果を確認して条件を事前固定した後、一度だけ実行する。追加後に条件や反復を変えない。
"""

import argparse
import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
DRIVER = Path(__file__).with_name('run_pairs.py')
DRIVER_SHA = 'a92c133f2a33d8c4ff23153218aadb22e12304edba3674bb0df10d6b080515fb'
CANDIDATE_SOURCE = 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94'
BASELINE_SOURCE = '2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392'
SOURCE_SHA = '696004d7cf55101529590fb0ce7c9137c12fcc9dd811a9765aacb40c7ba0e1a6'
ALL_STRATA = tuple(f'{label}_s{speed:03d}_candidate' for label in ('mono48chain300s', 'stereo441music300s') for speed in (40, 50, 100, 200))
FOLLOWUP_REPEATS = (4, 5, 6)
BASE_RECIPE = Path(__file__).with_name('run_steady_followup_v2.py')
BASE_RECIPE_SHA = 'a0e026f7f9aae351f72bd15fb48241fe902eb7cc817d237c0e45ab450851933c'
SOURCE_RELATIVE = 'tests/PerformanceSteadyNative.cpp'
SCOPE = {'CPU_approval': False, 'adoption_approved': False, 'quality_approval': False,
         'physical_audio': None, 'application_F': None,
         'exit_scope': 'Completed fixed collection, integrity and measured RT only; CPU acceptance is not automatic.',
         'statistics': 'Descriptive paired n3 and n6; no significance claim or new numerical tolerance.',
         'stopping': 'One atomic primary-evidence claim, one fixed additional n3 only; no retry/condition reselection after new outcomes.',
         'selection_scope': 'Selected concerns after primary48, fixed before any followup result; all primary48 retained.',
         'adoption_policy': 'Worse or uncertain followup/pooled CPU keeps adoption withheld; no further repetitions to select favorable results.'}


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def reject(value):
        raise ValueError('Nonfinite JSON: ' + value)
    value = json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=reject)
    def finite(item):
        if isinstance(item, dict):
            for child in item.values():
                finite(child)
        elif isinstance(item, list):
            for child in item:
                finite(child)
        elif type(item) is float:
            need(math.isfinite(item), 'Nonfinite JSON number')
    finite(value)
    return value


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def import_driver():
    import hashlib
    need(hashlib.sha256(DRIVER.read_bytes()).hexdigest() == DRIVER_SHA, 'Original run_pairs source SHA changed')
    spec = importlib.util.spec_from_file_location('fixed_steady_original_driver', DRIVER)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def ids_for(strata, repeats=(1, 2, 3)):
    result = []
    for repeat in repeats:
        for stratum in strata:
            for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
                result.append(f'{stratum}_r{repeat:02d}_{version}')
    return result


def identity_equal(actual, expected):
    return all(actual[key] == expected[key] for key in ('path', 'bytes', 'sha256'))


def checked(common, item):
    actual = common.identity(item['path'])
    need(identity_equal(actual, item), 'File identity changed: ' + item['path'])
    return actual


def expected_jobs(hosts, inputs, destination, strata):
    result = []
    for repeat in FOLLOWUP_REPEATS:
        for stratum in strata:
            label, speed_code = stratum.rsplit('_s', 1)
            speed = int(speed_code.split('_')[0]) / 100
            inp = inputs[label]
            for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
                pair = f'{stratum}_r{repeat:02d}'
                name = pair + '_' + version
                result.append({'id': name, 'stratum': stratum, 'repeat': repeat, 'version': version,
                               'pair_id': pair, 'preset': 'candidate', 'input': label, 'speed': speed,
                               'command': [hosts[version]['path'], inp['path'], 'candidate', str(speed),
                                           '30.0', str(destination / name)]})
    return result


def verify_suite(common, directory, count, strata, expected_source, expected_only, repeats=(1, 2, 3), driver_repeats=3):
    declared, summary = read(directory / 'EXPECTED.json'), read(directory / 'SUMMARY.json')
    need(declared.get('schema') == summary.get('schema') == 'performance-pairs-v1'
         and declared.get('suite') == 'steady' and declared.get('candidate_source') == expected_source
         and declared.get('baseline_source') == BASELINE_SOURCE, 'Saved steady source/schema')
    fixed = ids_for(strata, repeats)
    need(len(fixed) == count and declared.get('expected_programs') == summary.get('expected_programs') == count
         and summary.get('executed_programs') == count and declared.get('expected_pairs') == count // 2,
         'Saved program/pair counts')
    need(declared.get('repeats') == driver_repeats and declared.get('seconds') == 30 and declared.get('only') == expected_only
         and declared.get('required_matrix') is (expected_only is None)
         and declared.get('callback_gate') is False, 'Fixed selected three repeats/30s/matrix/selection')
    jobs, rows = declared['jobs'], summary['rows']
    need(len(jobs) == len(rows) == count and [j['id'] for j in jobs] == [r['id'] for r in rows]
         == declared.get('all_expected_ids') == summary.get('all_expected_ids')
         and len(set(j['id'] for j in jobs)) == count and [j['id'] for j in jobs] == fixed,
         'Missing/duplicate/unexpected native IDs or order')
    need(summary.get('complete') is True and summary.get('integrity_pass') is True
         and summary.get('errors') == [], 'Incomplete steady collection')
    need(checked(common, declared['driver'])['sha256'] == DRIVER_SHA, 'Same original driver')
    need(declared.get('client_source_sha256') == SOURCE_SHA and declared.get('cpu_formula') == common.CPU_FORMULA
         and summary.get('cpu_formula') == common.CPU_FORMULA, 'Same body and CPU formula')
    for job, row in zip(jobs, rows):
        need(job['stratum'] in strata and job['repeat'] in repeats
             and job['version'] in ('old', 'candidate') and job['preset'] == 'candidate'
             and job['pair_id'] == f"{job['stratum']}_r{job['repeat']:02d}"
             and job['id'] == job['pair_id'] + '_' + job['version'], 'Fixed native condition/receipt identity')
        expected_label, speed_code = job['stratum'].rsplit('_s', 1)
        need(job['input'] == expected_label and job['speed'] == int(speed_code.split('_')[0]) / 100,
             'Native condition label/speed mismatch')
        for key in ('id', 'stratum', 'pair_id', 'repeat', 'version', 'preset', 'input'):
            need(row.get(key) == job.get(key), 'Native row condition differs: ' + job['id'])
        label = job['input']
        command = job['command']
        need(len(command) == 6 and command[:4] == [declared['hosts'][job['version']]['path'],
             declared['inputs'][label]['path'], 'candidate', str(job['speed'])]
             and float(command[4]) == 30 and command[5] == str(directory / job['id']),
             'Native command/input/binary/window binding: ' + job['id'])
        execution = row['execution']
        need(type(execution.get('returncode')) is int and execution['returncode'] in (0, 2)
             and execution.get('timeout') is False and execution.get('interrupted') is False,
             'Native exception/timeout/interruption: ' + job['id'])
        checked(common, execution['log'])
        actual = read(directory / job['id'] / 'SUMMARY.json')
        need(actual == row['summary'], 'Native summary copy differs: ' + job['id'])
        result = common.assess('steady', job, actual, row.get('host_process_cost', {}), execution,
                               declared['inputs'][label], 30, 48000, 512)
        need(all(row.get(k) == value for k, value in result.items()), 'Native reassessment differs: ' + job['id'])
        need(result['integrity_pass'] is True, 'Native functional/measurement prerequisite failed: ' + job['id'])
        for key in ('worker_deadlines', 'callback_deadlines', 'missing', 'rejected'):
            need(type(actual.get(key)) is int and actual[key] >= 0, 'Unmeasured supply/RT counter: ' + key)
        need(actual['rt_pass'] == row['rt_pass'] == (execution['returncode'] == 0), 'Native RT/exit classification')
        if row['rt_pass']:
            need(all(actual[k] == 0 for k in ('worker_deadlines', 'callback_deadlines', 'missing', 'rejected')),
                 'RT pass has a nonzero exposed failure counter')
        actual_paths = {str(p.resolve()) for p in (directory / job['id']).rglob('*') if p.is_file()}
        records = row['artifacts']
        need(len(records) == len({v['path'] for v in records}) == len(actual_paths)
             and {v['path'] for v in records} == actual_paths, 'Missing/unowned native artifacts')
        for item in records:
            checked(common, item)
    rt = all(r['rt_pass'] for r in rows)
    need(summary.get('rt_all_versions_pass') is rt and summary.get('status') == ('PASS' if rt else 'INCOMPLETE_OR_FAIL'),
         'Saved collection/RT summary classification')
    return declared, summary


def preflight(common, args, destination, strata):
    primary = args.primary_run.resolve()
    all_strata = list(ALL_STRATA)
    declared, summary = verify_suite(common, primary, 48, all_strata, CANDIDATE_SOURCE, None)
    need(summary['rt_all_versions_pass'] is True, 'Primary48 must retain its completed RT PASS')
    base, build = read(args.baseline_client), read(args.candidate_build)
    base_id, build_id = common.identity(args.baseline_client.resolve()), common.identity(args.candidate_build.resolve())
    need(identity_equal(base_id, declared['records']['baseline_client'])
         and identity_equal(build_id, declared['records']['candidate_build']), 'Primary versus requested build/client identity')
    need(base.get('status') == build.get('status') == 'PASS' and base.get('baseline_source') == BASELINE_SOURCE
         and base.get('baseline_commit') == common.OLD_COMMIT and base.get('contract_version') == 3
         and build.get('source') == CANDIDATE_SOURCE and build.get('configuration') == 'Release'
         and build.get('architecture') == 'arm64', 'Fixed source08/5674 build configuration')
    need(common.manifest_digest(build['source_manifest']['files']) == build['source_manifest']['sha256'] == CANDIDATE_SOURCE,
         'Saved candidate source inventory digest')
    hosts = {'old': base['clients']['steady']['binary'], 'candidate': build['binaries']['performance_steady_native']}
    need(hosts == declared['hosts'] and base['clients']['steady']['source']['sha256'] ==
         base['clients']['steady']['copied_source']['sha256'] == SOURCE_SHA, 'Same actual hosts/common steady body')
    roots = [{'name': 'candidate', 'root': str(Path(build['source_root']).resolve()), 'sha256': CANDIDATE_SOURCE},
             {'name': 'baseline', 'root': str(Path(base['old_source_root']).resolve()), 'sha256': BASELINE_SOURCE}]
    # old_source_rootはfrozen clientの旧ソースcheckout。別rootへ黙って差し替えない。
    inventory = [base_id, build_id, common.identity(DRIVER), common.identity(__file__),
                 common.identity(primary / 'EXPECTED.json'), common.identity(primary / 'SUMMARY.json'),
                 base['clients']['steady']['copied_source'], *hosts.values(), *base['link_inputs'].values()]
    for row in summary['rows']:
        inventory.extend(row['artifacts'])
        inventory.append(row['execution']['log'])
    for name in ('ENVIRONMENT_BEFORE.json', 'ENVIRONMENT_AFTER.json'):
        path = primary / name
        environment = read(path)
        need(environment['machine'] == 'arm64' and environment['platform'] == platform.platform(),
             'Current OS/architecture differs from the primary recording')
        inventory.append(common.identity(path))
    for item in declared['inputs'].values():
        checked(common, item)
        inventory.append({key: item[key] for key in ('path', 'bytes', 'sha256')})
    for host in hosts.values():
        checked(common, host)
    # 候補の動的probeと静的link入力も、同じ08保存台帳のSHAへ固定する。
    archive_path = BASE / 'native_archive_08/ARCHIVE.json'
    archive = read(archive_path)
    need(archive['status'] == 'PASS' and archive['source'] == CANDIDATE_SOURCE and identity_equal(archive['build'], build_id), 'Archive08/build binding')
    need(len(archive['files']) == 54 and len(archive['extra_target_files']) == 6 and
         len({Path(x['original']['path']).name for x in archive['files'] + archive['extra_target_files']}) == 60,
         'Native08 complete unique 54+6 archive members')
    snapshot_id = archive['source_snapshot']
    need(Path(snapshot_id['path']).resolve() == (BASE / 'native_source_08/SOURCE.json').resolve(), 'Native08 fixed snapshot location')
    checked(common, snapshot_id)
    snapshot = read(snapshot_id['path'])
    need(snapshot['source'] == snapshot['source_manifest']['sha256'] == CANDIDATE_SOURCE and
         snapshot['source_manifest'] == build['source_manifest'] and identity_equal(snapshot['build'], build_id), 'Snapshot08/source/build binding')
    roots.append({'name': 'candidate_snapshot', 'root': str(Path(snapshot_id['path']).parent), 'sha256': CANDIDATE_SOURCE})
    inventory.extend([common.identity(archive_path), snapshot_id])
    base_recipe = common.identity(BASE_RECIPE)
    need(base_recipe['sha256'] == BASE_RECIPE_SHA, 'Original followup v2 source changed')
    inventory.append(base_recipe)
    for entry in archive['files'] + archive['extra_target_files']:
        original, saved = entry['original'], entry['archived']
        need(all(original[k] == saved[k] for k in ('bytes', 'sha256')) and
             Path(saved['path']).resolve().is_relative_to(archive_path.parent.resolve()), 'Native08 archive identity/location')
    host_rows = [x for x in archive['files'] if Path(x['original']['path']).name == 'performance_steady_native']
    need(len(host_rows) == 1 and host_rows[0]['original'] == hosts['candidate'], 'Primary native08 host/archive binding')
    inventory.append(host_rows[0]['archived'])
    link_names = set(base['link_inputs'])
    need(len(link_names) == 10, 'Frozen client nine archives and probe')
    link_rows = [row for row in archive['files'] if Path(row['original']['path']).name in link_names]
    need(len(link_rows) == 10 and {Path(row['original']['path']).name for row in link_rows} == link_names,
         'Same candidate nine archives and probe; unrelated legacy playback archive excluded')
    for row in link_rows:
        need(all(row['original'][k] == row['archived'][k] for k in ('bytes', 'sha256')), 'Archive08 link identity')
        inventory.extend([row['original'], row['archived']])
    for root in roots:
        need(common.current_source_digest(Path(root['root'])) == root['sha256'], 'Current source differs from primary: ' + root['name'])
    for item in inventory:
        checked(common, item)
    source_map = {row['path']: row['sha256'] for row in build['source_manifest']['files']}
    need(source_map[SOURCE_RELATIVE] == SOURCE_SHA, 'Candidate common steady source')
    selection_id = common.identity(args.selection_plan.resolve())
    selection = read(selection_id['path'])
    need(selection['status'] == 'NOT_RUN' and selection['source'] == CANDIDATE_SOURCE and
         selection['base_run'] == primary.name and [g['id'] for g in selection['groups']] == list(strata) and
         selection['additional_pairs_per_group'] == 3 and selection['expected_new_programs'] == 6 * len(strata) and
         selection['additional_repeats'] == [4, 5, 6] and
         selection['additional_order'] == ['candidate/old', 'old/candidate', 'candidate/old'] and
         selection['window_seconds'] == 30 and selection['device_rate'] == 48000 and selection['device_buffer'] == 512 and
         selection['repeated_retry_after_this'] is False, 'Fixed predeclared native08 concern/one-followup plan')
    means = {}
    for stratum in ALL_STRATA:
        values = {v: [r['summary']['cpu_percent'] for r in summary['rows'] if r['stratum'] == stratum and r['version'] == v]
                  for v in ('old', 'candidate')}
        need(all(len(x) == 3 for x in values.values()), 'Primary48 three CPU samples per condition/version')
        means[stratum] = {v: sum(x) / len(x) for v, x in values.items()}
    need([k for k in ALL_STRATA if means[k]['candidate'] > means[k]['old']] == list(strata),
         'Selection must include all and only the predeclared primary48 mean-increase groups')
    for group in selection['groups']:
        need(math.isclose(group['old_mean'], means[group['id']]['old'], rel_tol=1e-12, abs_tol=1e-12) and
             math.isclose(group['candidate_mean'], means[group['id']]['candidate'], rel_tol=1e-12, abs_tol=1e-12),
             'Selection-plan means differ from original complete primary48 samples')
    inventory.append(selection_id)
    expected = expected_jobs(hosts, declared['inputs'], destination, strata)
    return declared, summary, inventory, roots, expected, selection_id, selection


def inventory_check(common, inventory, path):
    mismatches = []
    for item in inventory:
        try:
            checked(common, item)
        except (OSError, ValueError) as error:
            mismatches.append({'expected': item, 'error': str(error)})
    value = {'status': 'PASS' if not mismatches else 'FAIL', 'expected_files': len(inventory),
             'checked_files': len(inventory), 'mismatches': mismatches,
             'manifest_sha256': common.manifest_digest(inventory)}
    save(path, value)
    need(not mismatches, 'Frozen source/binary/input/helper inventory changed')


def order_balance(primary_rows, followup_rows, strata):
    result = []
    for stratum in strata:
        counts = {}
        for label, rows, repeats in (('primary', primary_rows, (1, 2, 3)), ('followup', followup_rows, FOLLOWUP_REPEATS)):
            first = []
            for repeat in repeats:
                pair = [r for r in rows if r['stratum'] == stratum and r['repeat'] == repeat]
                wanted = ['old', 'candidate'] if repeat % 2 else ['candidate', 'old']
                need([r['version'] for r in pair] == wanted, 'Fixed paired execution order')
                first.append(pair[0]['version'])
            counts[label] = {v: first.count(v) for v in ('old', 'candidate')}
        pooled = {v: counts['primary'][v] + counts['followup'][v] for v in ('old', 'candidate')}
        need(pooled == {'old': 3, 'candidate': 3}, 'Pooled six-pair first-version order is not 3:3')
        result.append({'stratum': stratum, 'first_version_counts': counts, 'pooled_first_version_counts': pooled})
    return result


def claim_once(common, primary, out, strata, expected):
    # 元runへ追記せず、別の小manifestを排他的作成する。途中失敗でも自動削除/再試行しない。
    original_expected = common.identity(primary / 'EXPECTED.json')
    original_summary = common.identity(primary / 'SUMMARY.json')
    registry = BASE / 'steady_native08_followup_claims'
    registry.mkdir(exist_ok=True)
    need(registry.resolve().parent == BASE.resolve(), 'Once-claim directory outside B')
    path = registry / (original_expected['sha256'] + '_' + original_summary['sha256'] + '.json')
    plan = {'status': 'FIXED_PLAN_CLAIMED_ONCE', 'candidate_source': CANDIDATE_SOURCE,
            'primary_expected': original_expected, 'primary_summary': original_summary,
            'output': str(out), 'selected_strata': list(strata), 'repeat_labels': list(FOLLOWUP_REPEATS),
            'all_expected_new_ids': ids_for(strata, FOLLOWUP_REPEATS),
            'driver': common.identity(__file__), 'expected': common.identity(expected),
            'retry_policy': 'No automatic retry, claim deletion, extra strata, or further n3 after new results.'}
    try:
        with path.open('x') as stream:
            stream.write(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ValueError('Primary48 already has a once-only native08 followup claim: ' + str(path)) from error
    return common.identity(path)


def distribution(values):
    x = sorted(values)
    def quantile(p):
        at = (len(x) - 1) * p
        i = int(at)
        return x[i] + (x[min(i + 1, len(x) - 1)] - x[i]) * (at - i)
    return {'n': len(x), 'samples': values, 'mean': statistics.mean(x), 'median': statistics.median(x),
            'min': min(x), 'max': max(x), 'p95': quantile(.95), 'sample_stdev': statistics.stdev(x)}


def comparison(rows):
    versions = {v: [r['summary']['cpu_percent'] for r in rows if r['version'] == v] for v in ('old', 'candidate')}
    rounds = sorted({(r['round'], r['repeat']) for r in rows})
    pairs = []
    for name, repeat in rounds:
        found = {r['version']: r for r in rows if r['round'] == name and r['repeat'] == repeat}
        need(set(found) == {'old', 'candidate'}, 'Missing paired version')
        old, new = (found[v]['summary']['cpu_percent'] for v in ('old', 'candidate'))
        pairs.append({'round': name, 'native_repeat': repeat, 'old': old, 'candidate': new,
                      'candidate_minus_old_pp': new - old, 'candidate_over_old': new / old if old else None,
                      'source_ids': {v: found[v]['qualified_id'] for v in ('old', 'candidate')}})
    old, new = (distribution(versions[v]) for v in ('old', 'candidate'))
    deltas = [p['candidate_minus_old_pp'] for p in pairs]
    overlap = max(old['min'], new['min']) <= min(old['max'], new['max'])
    lower, higher = sum(d < 0 for d in deltas), sum(d > 0 for d in deltas)
    classification = ('OBSERVED_CONSISTENT_DECREASE' if lower == len(pairs) and not overlap else
                      'OBSERVED_CONSISTENT_INCREASE' if higher == len(pairs) and not overlap else 'NOT_DEMONSTRATED')
    return {'pairs': len(pairs), 'version_samples': {'old': old, 'candidate': new}, 'paired_rows': pairs,
            'paired_candidate_minus_old_pp': distribution(deltas), 'lower_pairs': lower, 'higher_pairs': higher,
            'equal_pairs': len(pairs) - lower - higher, 'ranges_overlap': overlap,
            'mean_candidate_minus_old_pp': new['mean'] - old['mean'],
            'median_candidate_minus_old_pp': new['median'] - old['median'], 'classification': classification,
            'classification_scope': 'Observed direction/range description; no statistical or adoption acceptance.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--primary-run', type=Path, required=True)
    parser.add_argument('--baseline-client', type=Path, required=True)
    parser.add_argument('--candidate-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--strata', nargs='+', choices=ALL_STRATA, required=True)
    parser.add_argument('--selection-plan', type=Path, default=BASE / 'NATIVE08_CPU_FOLLOWUP_PLAN.json')
    args = parser.parse_args()
    need(len(args.strata) == len(set(args.strata)), 'Duplicate selected stratum')
    strata = tuple(x for x in ALL_STRATA if x in args.strata)
    need(bool(strata), 'At least one primary48 stratum must be declared')
    selected_pairs = [f'{stratum}_r{repeat:02d}' for repeat in FOLLOWUP_REPEATS for stratum in strata]
    new_count = 6 * len(strata)
    need(sys.version_info >= (3, 11), 'Python>=3.11; native arm64 Python required')
    need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native arm64 macOS parent required')
    out = args.output.resolve()
    need(out.is_relative_to(BASE) and not out.is_relative_to(args.primary_run.resolve()), 'New separate evidence directory under B')
    out.mkdir(parents=True, exist_ok=False)
    native = out / 'native_run'
    command = [sys.executable, '-B', str(DRIVER), '--baseline-client', str(args.baseline_client.resolve()),
               '--candidate-build', str(args.candidate_build.resolve()), '--suite', 'steady', '--only', *selected_pairs,
               '--repeats', '6', '--seconds', '30', '--presets', 'candidate', '--timeout', '180',
               '--device-rate', '48000', '--device-buffer', '512', '--output', str(native)]
    expected = {'schema': 'performance-steady-native08-fixed-followup-v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'expected_new_programs': new_count, 'expected_new_pairs': 3 * len(strata), 'all_expected_ids': ids_for(strata, FOLLOWUP_REPEATS),
                'strata': list(strata), 'requested_strata': args.strata, 'repeats': 3, 'native_repeat_labels': list(FOLLOWUP_REPEATS), 'delegated_repeat_range': 6, 'measurement_seconds': 30, 'per_native_timeout_s': 180,
                'outer_driver_timeout_s': 3600, 'primary_full_programs': 48, 'primary_selected_programs': new_count,
                'pooled_pairs_per_stratum': 6, 'pooled_samples_per_version_per_stratum': 6,
                'pooled_total_pairs': 6 * len(strata), 'primary_counted_as_new': False,
                'baseline_source': BASELINE_SOURCE, 'candidate_source': CANDIDATE_SOURCE,
                'primary_run': str(args.primary_run.resolve()), 'command': command,
                'preflight_status': 'PENDING', 'native_callback_gate': False, **SCOPE}
    save(out / 'EXPECTED.json', expected)
    common, inventory, roots, execution, groups, error, preflight_done = None, [], [], None, [], None, False
    try:
        common = import_driver()
        declared, primary, inventory, roots, jobs, selection_id, selection = preflight(common, args, native, strata)
        expected.update(selection_plan=selection_id, fixed_selection=selection)
        balance_plan = order_balance(declared['jobs'], jobs, strata)
        expected.update(first_version_balance_plan=balance_plan, no_primary_id_overlap=not bool(set(j['id'] for j in jobs) & set(declared['all_expected_ids'])))
        need(expected['no_primary_id_overlap'], 'Followup IDs overlap primary48')
        command.extend(['--mono-input', declared['inputs']['mono48chain300s']['path'],
                        '--stereo-input', declared['inputs']['stereo441music300s']['path']])
        expected.update(preflight_status='PASS', command=command, jobs=jobs, inventory=inventory, source_roots=roots,
                        primary_expected=common.identity(args.primary_run / 'EXPECTED.json'),
                        primary_summary=common.identity(args.primary_run / 'SUMMARY.json'),
                        helper=common.identity(DRIVER), driver=common.identity(__file__),
                        primary_hosts=declared['hosts'], inputs=declared['inputs'])
        save(out / 'EXPECTED.json', expected)
        save(out / 'FIXED_ADDITIONAL_PLAN.json', expected)
        inventory.append(common.identity(out / 'FIXED_ADDITIONAL_PLAN.json'))
        claim = claim_once(common, args.primary_run.resolve(), out, strata, out / 'FIXED_ADDITIONAL_PLAN.json')
        inventory.append(claim)
        expected.update(once_only_claim=claim)
        save(out / 'EXPECTED.json', expected)
        inventory_check(common, inventory, out / 'FROZEN_BEFORE.json')
        save(out / 'SOURCE_BEFORE.json', {'status': 'PASS', 'roots': roots})
        preflight_done = True
        child = None
        timed_out, interrupted, retirement_confirmed = False, False, True
        def stop(signum, frame):
            raise KeyboardInterrupt('signal ' + str(signum))
        previous = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGINT)}
        try:
            delegated_begin = time.monotonic()
            with (out / 'RUN_PAIRS.log').open('w') as stream:
                child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    child.wait(timeout=3600)
                except (subprocess.TimeoutExpired, KeyboardInterrupt) as failure:
                    timed_out = isinstance(failure, subprocess.TimeoutExpired)
                    interrupted = isinstance(failure, KeyboardInterrupt)
                    child.send_signal(signal.SIGTERM)  # 元driverが現在のnativeをkill/reapするfinallyを通す。
                    try:
                        child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        retirement_confirmed = False
                        child.kill()
                        child.wait()
                execution = {'command': command, 'returncode': child.returncode, 'timeout': timed_out,
                             'interrupted': interrupted, 'driver_retirement_confirmed': retirement_confirmed,
                             'wall_s': time.monotonic() - delegated_begin, 'log': common.identity(out / 'RUN_PAIRS.log')}
                save(out / 'EXECUTION.json', execution)
        finally:
            if child is not None and child.poll() is None:
                child.send_signal(signal.SIGTERM)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    retirement_confirmed = False
                    child.kill()
                    child.wait()
            for signum, handler in previous.items():
                signal.signal(signum, handler)
        need(execution['returncode'] in (0, 2) and not timed_out and not interrupted and retirement_confirmed,
             'Delegated collection timeout/interruption/exception; no automatic retry')
        fresh_declared, fresh = verify_suite(common, native, new_count, list(strata), CANDIDATE_SOURCE, selected_pairs, FOLLOWUP_REPEATS, 6)
        need(fresh_declared['hosts'] == declared['hosts'] and fresh_declared['records'] == declared['records']
             and fresh_declared['inputs'] == declared['inputs'] and fresh_declared['client_source_sha256'] == SOURCE_SHA,
             'Followup does not match primary input/host/build/helper')
        need([j['id'] for j in jobs] == fresh_declared['all_expected_ids'], 'Fixed followup job IDs')
        for wanted, actual in zip(jobs, fresh_declared['jobs']):
            need(all(actual.get(k) == v for k, v in wanted.items()), 'Fixed followup native CLI differs')
        need(execution['returncode'] == (0 if fresh['rt_all_versions_pass'] else 2), 'Driver exit/RT classification')
        measured_balance = order_balance(primary['rows'], fresh['rows'], strata)
        need(measured_balance == balance_plan, 'Measured order differs from fixed 3:3 plan')
        for name, rows in [('primary', primary['rows']), ('followup', fresh['rows'])]:
            for row in rows:
                row['round'] = name
                row['qualified_id'] = name + '/' + row['id']
        for stratum in strata:
            first = [r for r in primary['rows'] if r['stratum'] == stratum]
            next_rows = [r for r in fresh['rows'] if r['stratum'] == stratum]
            need(len(first) == len(next_rows) == 6, 'Per-stratum primary/followup n3')
            group = {'stratum': stratum, 'primary_n3': comparison(first), 'followup_n3': comparison(next_rows),
                     'pooled_n6': comparison(first + next_rows)}
            need(group['pooled_n6']['pairs'] == 6 and all(group['pooled_n6']['version_samples'][v]['n'] == 6
                 for v in ('old', 'candidate')), 'Pooled n6 per version/condition, never 24 pairs')
            groups.append(group)
        for row in fresh['rows']:
            inventory.extend(row['artifacts'])
            inventory.append(row['execution']['log'])
        for name in ('EXPECTED.json', 'SUMMARY.json', 'ENVIRONMENT_BEFORE.json', 'ENVIRONMENT_AFTER.json'):
            inventory.append(common.identity(native / name))
        expected['followup_expected'] = common.identity(native / 'EXPECTED.json')
        expected['followup_summary'] = common.identity(native / 'SUMMARY.json')
        expected['completed_new_programs'] = new_count
        save(out / 'EXPECTED.json', expected)
    except (Exception, KeyboardInterrupt) as failure:
        error = type(failure).__name__ + ': ' + str(failure)
        if not preflight_done:
            expected.update(preflight_status='BLOCKED', preflight_reason=error)
            save(out / 'EXPECTED.json', expected)
    finally:
        if common and inventory:
            try:
                inventory_check(common, inventory, out / 'FROZEN_AFTER.json')
                after = [{**root, 'actual_sha256': common.current_source_digest(Path(root['root']))} for root in roots]
                for row in after:
                    row['unchanged'] = row['actual_sha256'] == row['sha256']
                save(out / 'SOURCE_AFTER.json', {'status': 'PASS' if all(r['unchanged'] for r in after) else 'FAIL', 'roots': after})
                need(all(r['unchanged'] for r in after), 'Source changed during followup')
            except (Exception, KeyboardInterrupt) as failure:
                error = (error + '; ' if error else '') + 'final freeze: ' + type(failure).__name__ + ': ' + str(failure)
    native_summary = {}
    if (native / 'SUMMARY.json').is_file():
        try:
            native_summary = read(native / 'SUMMARY.json')
        except (OSError, ValueError) as failure:
            error = (error + '; ' if error else '') + 'final native summary: ' + str(failure)
    complete = preflight_done and error is None and len(groups) == len(strata)
    rt_pass = complete and native_summary.get('rt_all_versions_pass') is True
    result = {'schema': 'performance-steady-native08-followup-summary-v1',
              'status': 'COMPLETE_OBSERVATIONS' if complete and rt_pass else 'FAIL_OR_INCOMPLETE',
              'collection_status': 'PASS' if complete else 'FAIL_OR_INCOMPLETE', 'complete': complete,
              'RT_supply_status': 'PASS' if rt_pass else ('FAIL' if complete else 'INCOMPLETE'),
              'expected_new_programs': new_count, 'executed_new_programs': len(native_summary.get('rows', [])),
              'expected_new_pairs': 3 * len(strata), 'pooled_pairs_per_stratum': 6, 'pooled_total_pairs': 6 * len(strata),
              'primary_full_programs_retained': 48 if preflight_done else None, 'primary_counted_as_new': False,
              'selected_strata': list(strata), 'all_expected_ids': ids_for(strata, FOLLOWUP_REPEATS), 'executed_ids': [r['id'] for r in native_summary.get('rows', [])],
              'baseline_source': BASELINE_SOURCE, 'candidate_source': CANDIDATE_SOURCE,
              'groups': groups, 'reason': error, 'execution': execution,
              'first_version_balance_plan': expected.get('first_version_balance_plan'),
              'once_only_claim': expected.get('once_only_claim'),
              'original_primary_expected': expected.get('primary_expected'), 'original_primary_summary': expected.get('primary_summary'),
              'primary_and_followup_final_identity_check_complete': complete,
              'measured_order_balance': measured_balance if 'measured_balance' in locals() else None,
              'selection_plan': expected.get('selection_plan'),
              'whole_CPU_improvement': 'NOT_DEMONSTRATED_AUTOMATICALLY; inspect both followup and pooled distributions',
              'whole_CPU_no_regression': 'NOT_APPROVED_AUTOMATICALLY',
              'expected': common.identity(out / 'EXPECTED.json') if common else None, **SCOPE}
    save(out / 'SUMMARY.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'expected_new_programs', 'executed_new_programs',
                                           'RT_supply_status', 'whole_CPU_improvement', 'reason')}, ensure_ascii=False))
    return 0 if complete and rt_pass else 2


if __name__ == '__main__':
    raise SystemExit(main())
