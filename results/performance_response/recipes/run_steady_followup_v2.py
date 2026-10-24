#!/usr/bin/env python3
"""既存steady48を保持し、mono1x/2xだけ固定追加n3（12program）を直列収録する。

 /usr/local/bin/python3 -B results/performance_response/recipes/run_steady_followup.py \
   --primary-run build/performance_response_20261023_01/steady_pairs_final06 \
   --baseline-client build/performance_response_20261023_01/frozen_clients_02/CLIENT.json \
   --candidate-build build/performance_response_20261023_01/build_timer_candidate_05/BUILD.json \
   --output build/performance_response_20261023_01/steady_followup_final06

run_pairs原本の--suite steady --only mono1x mono2x --repeats3 --seconds30を委譲する。
追加単独n3と元3+追加3のn6を条件ごとに併記し、結果による追加反復/除外/許容差を設けない。
収録完了/RTとCPU方向は別判定。exit0は収録・RT整合のみで、CPU改善・採用承認ではない。
参照PCM/製品ソース/既存driverを変更せず、新規build/内だけへ保存する。
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
CANDIDATE_SOURCE = '0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e'
BASELINE_SOURCE = '2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392'
SOURCE_SHA = '696004d7cf55101529590fb0ce7c9137c12fcc9dd811a9765aacb40c7ba0e1a6'
STRATA = ('mono48chain300s_s100_candidate', 'mono48chain300s_s200_candidate')
SOURCE_RELATIVE = 'tests/PerformanceSteadyNative.cpp'
SCOPE = {'CPU_approval': False, 'adoption_approved': False, 'quality_approval': False,
         'physical_audio': None, 'application_F': None,
         'exit_scope': 'Completed fixed collection, integrity and measured RT only; CPU acceptance is not automatic.',
         'statistics': 'Descriptive paired n3 and n6; no significance claim or new numerical tolerance.',
         'stopping': 'One fixed additional n3 only; no optional stopping or post-result condition selection.'}


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


def ids_for(strata):
    result = []
    for repeat in (1, 2, 3):
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


def expected_jobs(hosts, inp, destination, strata):
    result = []
    for repeat in (1, 2, 3):
        for stratum in strata:
            speed = int(stratum.split('_s')[1].split('_')[0]) / 100
            for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
                pair = f'{stratum}_r{repeat:02d}'
                name = pair + '_' + version
                result.append({'id': name, 'stratum': stratum, 'repeat': repeat, 'version': version,
                               'pair_id': pair, 'preset': 'candidate', 'input': 'mono48chain300s',
                               'command': [hosts[version]['path'], inp['path'], 'candidate', str(speed),
                                           '30.0', str(destination / name)]})
    return result


def verify_suite(common, directory, count, strata, expected_source, expected_only):
    declared, summary = read(directory / 'EXPECTED.json'), read(directory / 'SUMMARY.json')
    need(declared.get('schema') == summary.get('schema') == 'performance-pairs-v1'
         and declared.get('suite') == 'steady' and declared.get('candidate_source') == expected_source
         and declared.get('baseline_source') == BASELINE_SOURCE, 'Saved steady source/schema')
    fixed = ids_for(strata)
    need(len(fixed) == count and declared.get('expected_programs') == summary.get('expected_programs') == count
         and summary.get('executed_programs') == count and declared.get('expected_pairs') == count // 2,
         'Saved program/pair counts')
    need(declared.get('repeats') == 3 and declared.get('seconds') == 30 and declared.get('only') == expected_only
         and declared.get('required_matrix') is (expected_only is None)
         and declared.get('callback_gate') is False, 'Fixed n3/30s/matrix/selection')
    jobs, rows = declared['jobs'], summary['rows']
    need(len(jobs) == len(rows) == count and [j['id'] for j in jobs] == [r['id'] for r in rows]
         == declared.get('all_expected_ids') == summary.get('all_expected_ids')
         and len(set(j['id'] for j in jobs)) == count and set(j['id'] for j in jobs) == set(fixed),
         'Missing/duplicate/unexpected native IDs or order')
    need(summary.get('complete') is True and summary.get('integrity_pass') is True
         and summary.get('errors') == [], 'Incomplete steady collection')
    need(checked(common, declared['driver'])['sha256'] == DRIVER_SHA, 'Same original driver')
    need(declared.get('client_source_sha256') == SOURCE_SHA and declared.get('cpu_formula') == common.CPU_FORMULA
         and summary.get('cpu_formula') == common.CPU_FORMULA, 'Same body and CPU formula')
    for job, row in zip(jobs, rows):
        need(job['stratum'] in strata and job['repeat'] in (1, 2, 3)
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


def preflight(common, args, destination):
    primary = args.primary_run.resolve()
    all_strata = [f'{label}_s{speed:03d}_candidate' for label in ('mono48chain300s', 'stereo441music300s')
                  for speed in (40, 50, 100, 200)]
    declared, summary = verify_suite(common, primary, 48, all_strata, CANDIDATE_SOURCE, None)
    need(summary['rt_all_versions_pass'] is True, 'Primary48 must retain its completed RT PASS')
    base, build = read(args.baseline_client), read(args.candidate_build)
    base_id, build_id = common.identity(args.baseline_client.resolve()), common.identity(args.candidate_build.resolve())
    need(identity_equal(base_id, declared['records']['baseline_client'])
         and identity_equal(build_id, declared['records']['candidate_build']), 'Primary versus requested build/client identity')
    need(base.get('status') == build.get('status') == 'PASS' and base.get('baseline_source') == BASELINE_SOURCE
         and base.get('baseline_commit') == common.OLD_COMMIT and base.get('contract_version') == 3
         and build.get('source') == CANDIDATE_SOURCE and build.get('configuration') == 'Release'
         and build.get('architecture') == 'arm64', 'Fixed source05/5674 build configuration')
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
    # 候補の動的probeと静的link入力も、同じ05保存台帳のSHAへ固定する。
    archive_path = BASE / 'timer_archive_05/ARCHIVE.json'
    archive = read(archive_path)
    need(archive['source'] == CANDIDATE_SOURCE and identity_equal(archive['build'], build_id), 'Archive05/build binding')
    inventory.append(common.identity(archive_path))
    link_names = set(base['link_inputs'])
    need(len(link_names) == 10, 'Frozen client nine archives and probe')
    link_rows = [row for row in archive['files'] if Path(row['original']['path']).name in link_names]
    need(len(link_rows) == 10 and {Path(row['original']['path']).name for row in link_rows} == link_names,
         'Same candidate nine archives and probe; unrelated legacy playback archive excluded')
    for row in link_rows:
        need(all(row['original'][k] == row['archived'][k] for k in ('bytes', 'sha256')), 'Archive05 link identity')
        inventory.extend([row['original'], row['archived']])
    for root in roots:
        need(common.current_source_digest(Path(root['root'])) == root['sha256'], 'Current source differs from primary: ' + root['name'])
    for item in inventory:
        checked(common, item)
    source_map = {row['path']: row['sha256'] for row in build['source_manifest']['files']}
    need(source_map[SOURCE_RELATIVE] == SOURCE_SHA, 'Candidate common steady source')
    expected = expected_jobs(hosts, declared['inputs']['mono48chain300s'], destination, STRATA)
    return declared, summary, inventory, roots, expected


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
    args = parser.parse_args()
    need(sys.version_info >= (3, 11), 'Python>=3.11; native arm64 Python required')
    need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native arm64 macOS parent required')
    out = args.output.resolve()
    need(out.is_relative_to(BASE) and not out.is_relative_to(args.primary_run.resolve()), 'New separate evidence directory under B')
    out.mkdir(parents=True, exist_ok=False)
    native = out / 'native_run'
    command = [sys.executable, '-B', str(DRIVER), '--baseline-client', str(args.baseline_client.resolve()),
               '--candidate-build', str(args.candidate_build.resolve()), '--suite', 'steady', '--only', *STRATA,
               '--repeats', '3', '--seconds', '30', '--presets', 'candidate', '--timeout', '180',
               '--device-rate', '48000', '--device-buffer', '512', '--output', str(native)]
    expected = {'schema': 'performance-steady-fixed-followup-v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'expected_new_programs': 12, 'expected_new_pairs': 6, 'all_expected_ids': ids_for(STRATA),
                'strata': list(STRATA), 'repeats': 3, 'measurement_seconds': 30, 'per_native_timeout_s': 180,
                'outer_driver_timeout_s': 3600, 'primary_full_programs': 48, 'primary_selected_programs': 12,
                'pooled_pairs_per_stratum': 6, 'pooled_samples_per_version_per_stratum': 6,
                'pooled_total_pairs': 12, 'primary_counted_as_new': False,
                'baseline_source': BASELINE_SOURCE, 'candidate_source': CANDIDATE_SOURCE,
                'primary_run': str(args.primary_run.resolve()), 'command': command,
                'preflight_status': 'PENDING', 'native_callback_gate': False, **SCOPE}
    save(out / 'EXPECTED.json', expected)
    common, inventory, roots, execution, groups, error, preflight_done = None, [], [], None, [], None, False
    try:
        common = import_driver()
        declared, primary, inventory, roots, jobs = preflight(common, args, native)
        command.extend(['--mono-input', declared['inputs']['mono48chain300s']['path'],
                        '--stereo-input', declared['inputs']['stereo441music300s']['path']])
        expected.update(preflight_status='PASS', command=command, jobs=jobs, inventory=inventory, source_roots=roots,
                        primary_expected=common.identity(args.primary_run / 'EXPECTED.json'),
                        primary_summary=common.identity(args.primary_run / 'SUMMARY.json'),
                        helper=common.identity(DRIVER), driver=common.identity(__file__),
                        primary_hosts=declared['hosts'], inputs=declared['inputs'])
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
        fresh_declared, fresh = verify_suite(common, native, 12, list(STRATA), CANDIDATE_SOURCE, list(STRATA))
        need(fresh_declared['hosts'] == declared['hosts'] and fresh_declared['records'] == declared['records']
             and fresh_declared['inputs'] == declared['inputs'] and fresh_declared['client_source_sha256'] == SOURCE_SHA,
             'Followup does not match primary input/host/build/helper')
        need([j['id'] for j in jobs] == fresh_declared['all_expected_ids'], 'Fixed followup job IDs')
        for wanted, actual in zip(jobs, fresh_declared['jobs']):
            need(all(actual.get(k) == v for k, v in wanted.items()), 'Fixed followup native CLI differs')
        need(execution['returncode'] == (0 if fresh['rt_all_versions_pass'] else 2), 'Driver exit/RT classification')
        for name, rows in [('primary', primary['rows']), ('followup', fresh['rows'])]:
            for row in rows:
                row['round'] = name
                row['qualified_id'] = name + '/' + row['id']
        for stratum in STRATA:
            first = [r for r in primary['rows'] if r['stratum'] == stratum]
            next_rows = [r for r in fresh['rows'] if r['stratum'] == stratum]
            need(len(first) == len(next_rows) == 6, 'Per-stratum primary/followup n3')
            group = {'stratum': stratum, 'primary_n3': comparison(first), 'followup_n3': comparison(next_rows),
                     'pooled_n6': comparison(first + next_rows)}
            need(group['pooled_n6']['pairs'] == 6 and all(group['pooled_n6']['version_samples'][v]['n'] == 6
                 for v in ('old', 'candidate')), 'Pooled n6 per version/condition, never 24 pairs')
            groups.append(group)
        expected['followup_expected'] = common.identity(native / 'EXPECTED.json')
        expected['followup_summary'] = common.identity(native / 'SUMMARY.json')
        expected['completed_new_programs'] = 12
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
    complete = preflight_done and error is None and len(groups) == 2
    rt_pass = complete and native_summary.get('rt_all_versions_pass') is True
    result = {'schema': 'performance-steady-followup-summary-v1',
              'status': 'COMPLETE_OBSERVATIONS' if complete and rt_pass else 'FAIL_OR_INCOMPLETE',
              'collection_status': 'PASS' if complete else 'FAIL_OR_INCOMPLETE', 'complete': complete,
              'RT_supply_status': 'PASS' if rt_pass else ('FAIL' if complete else 'INCOMPLETE'),
              'expected_new_programs': 12, 'executed_new_programs': len(native_summary.get('rows', [])),
              'expected_new_pairs': 6, 'pooled_pairs_per_stratum': 6, 'pooled_total_pairs': 12,
              'primary_full_programs_retained': 48, 'primary_counted_as_new': False,
              'all_expected_ids': ids_for(STRATA), 'executed_ids': [r['id'] for r in native_summary.get('rows', [])],
              'baseline_source': BASELINE_SOURCE, 'candidate_source': CANDIDATE_SOURCE,
              'groups': groups, 'reason': error, 'execution': execution,
              'whole_CPU_improvement': 'NOT_DEMONSTRATED_AUTOMATICALLY; inspect both followup and pooled distributions',
              'whole_CPU_no_regression': 'NOT_APPROVED_AUTOMATICALLY',
              'expected': common.identity(out / 'EXPECTED.json') if common else None, **SCOPE}
    save(out / 'SUMMARY.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'expected_new_programs', 'executed_new_programs',
                                           'RT_supply_status', 'whole_CPU_improvement', 'reason')}, ensure_ascii=False))
    return 0 if complete and rt_pass else 2


if __name__ == '__main__':
    raise SystemExit(main())
