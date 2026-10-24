#!/usr/bin/env python3
"""source08の保存物と既存結果を新しい小索引へ結ぶ。試験・音声・承認は行わない。

 --native-runs steady_pairs_native08 ... --decisions B/DECISIONS08.json --output B/final_native08_index_01
追加08runは明示列挙し、全てEXPECTED.json/SUMMARY.jsonが必要。05の固定RUNS/
HISTORY/RECORDS/REVIEWSは凍結した元finalize_evidence.pyから読取り、版を付替えない。
全768source、保存54 primary+6 extras、49実行体の照合はこのrecipeを実行した時だけ。
PCM/WAV等は再hashせず、元manifest/独立監査への参照を保存する。

decisions schema=native08-final-decisions-v1、source=固定source08、unmet=明示list。
decisions={CPU_adoption:{status,reason,evidence:[pathまたはidentity,...]},
 public_release:{...},Merodoa_default:{...},local_overall:{...},
 human_physical_application_F:{...}}。未指定の承認軸はWITHHELD、localはINCOMPLETE。
evidenceのpathはrepo相対または絶対path。RAW/WAVではなく小manifestを参照する。
unmetの各要素は{id,status,reason,...}。NOT_RUN/BLOCKED等を勝手にPASSへ変えない。
unmet/missing_evidenceのscopeは省略・不明なら局所。public/Merodoa/humanだけは
外部軸として保持し、それだけでlocal_overallをINCOMPLETEへ強制しない。
局所は明示local_overall、必須CPU軸、局所unmet/missingで判定する。
欠落した旧証拠だけはmissing_evidence={B相対path:{status:NOT_RUN|BLOCKED|INCOMPLETE,
reason:文字列}}で明示できる。明示08runの欠落をこの仕組みでは免除しない。
索引PASSは検証結果の再判定/GOではない。Gitへの小索引コピーは実行後の別工程とし、
自己出力をdeliveryへ再帰的に取り込まない。既存索引/元statusは変更しない。
"""
import argparse
import ast
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BASE = (ROOT / 'build/performance_response_20261023_01').resolve()
SOURCE = 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94'
SOURCE05 = '0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e'
HEAD = '5674bd982d98caacaa3e87cdeae5bfc0b01c66ef'
LEGACY = Path(__file__).with_name('finalize_evidence.py')
LEGACY_SHA = '7aaa592b4e0643a2c6582faf10b89a9b09079e9da387b5938b83f8892fc6f543'
PINS = {
    'native_source_08/SOURCE.json': 'f2304408ea89ba72b4d0c2dc3f1e8d609b1a780b69d0835f854586d4016515ad',
    'native_archive_08/ARCHIVE.json': '8559063d9905dddabe366c225368e27ba628250042d4e79877bd8162aae14f3a',
    'build_native_default_08/BUILD.json': '6a1ea92a6b968e916ce416f7e74e69b2a421cb7b4ee9392759fda3fbec97454f'}
SNAPSHOT = BASE / 'native_source_08'
ARCHIVE = BASE / 'native_archive_08'
BUILD_PATH = BASE / 'build_native_default_08/BUILD.json'
RAW_SUFFIXES = {'.wav', '.pcm', '.f32', '.raw', '.aiff', '.aif', '.flac'}
AXES = ('CPU_adoption', 'public_release', 'Merodoa_default', 'local_overall', 'human_physical_application_F')


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path):
    path = Path(path).resolve()
    return {'path': str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            'bytes': path.stat().st_size, 'sha256': sha(path)}


def actual_path(item):
    path = Path(item['path'])
    return path if path.is_absolute() else ROOT / path


def matches(item, recorded):
    return (actual_path(item).resolve() == actual_path(recorded).resolve()
            and all(item[k] == recorded[k] for k in ('bytes', 'sha256')))


def read(path):
    def pairs(values):
        result = {}
        for key, value in values:
            need(key not in result, 'Duplicate JSON key: ' + key);result[key] = value
        return result
    def reject(value):raise ValueError('Nonfinite JSON: ' + value)
    value = json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=reject)
    def inspect(child):
        if isinstance(child, dict):
            for v in child.values():inspect(v)
        elif isinstance(child, list):
            for v in child:inspect(v)
        elif isinstance(child, float):need(math.isfinite(child), 'Nonfinite JSON number')
    inspect(value);return value


def save(path, value):
    temp = path.with_name('.' + path.name + '.tmp')
    need(not temp.exists(), 'Unexpected temporary output exists')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        os.replace(temp, path)
    finally:
        if temp.exists():temp.unlink()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def git_state():
    return {'head': git('rev-parse', 'HEAD').decode().strip(),
            'branch': git('branch', '--show-current').decode().strip(),
            'status': git('status', '--porcelain=v1', '-uall', '-z'),
            'patch': git('diff', '--binary', '--full-index', 'HEAD'),
            'tracked_names': git('diff', '--name-only', '-z', 'HEAD'),
            'untracked_names': git('ls-files', '--others', '--exclude-standard', '-z')}


def delivery_files(state):
    names = {os.fsdecode(v) for key in ('tracked_names', 'untracked_names') for v in state[key].split(b'\0') if v}
    result = []
    for relative in sorted(names):
        path = ROOT / relative
        if not os.path.lexists(path):
            result.append({'path': relative, 'state': 'DELETED'});continue
        s = path.lstat()
        if stat.S_ISLNK(s.st_mode):
            data = os.fsencode(os.readlink(path));item = {'path': relative, 'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest(), 'kind': 'symlink_blob', 'mode': '120000'}
        else:
            need(stat.S_ISREG(s.st_mode), 'Unsupported delivery directory/gitlink: ' + relative)
            item = {**identity(path), 'kind': 'regular_blob', 'mode': oct(stat.S_IMODE(s.st_mode))}
        need(item['bytes'] < 50_000_000, 'Delivery blob reaches 50,000,000 bytes: ' + relative)
        result.append(item)
    return result


def contains(value, target):
    if isinstance(value, dict):return any(contains(v, target) for v in value.values())
    if isinstance(value, list):return any(contains(v, target) for v in value)
    return value == target


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--native-runs', nargs='+', required=True)
    parser.add_argument('--decisions', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    need(out.is_relative_to(BASE) and out != BASE, 'New output must be below fixed B')
    need(not os.path.lexists(out), 'Fresh output directory required')
    check = subprocess.run(['git', 'check-ignore', '--quiet', str(out)], cwd=ROOT)
    need(check.returncode == 0, 'Output must be Git-ignored, excluding self-output from delivery')
    out.mkdir(parents=True, exist_ok=False)
    result = {'schema': 'performance-response-native08-final-evidence-v1',
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'index_collection': 'INCOMPLETE', 'index_integrity': 'INCOMPLETE',
              'tests_executed_by_this_indexer': 0, 'run_results_revalidated_by_this_indexer': False,
              'no_grand_total': True, 'CPU_adoption': 'WITHHELD', 'public_release': 'WITHHELD',
              'Merodoa_default': 'WITHHELD', 'local_overall': 'INCOMPLETE',
              'commit_push_release_performed': False,
              'index_PASS_is_not_GO': True, 'self_output_git_copy': 'NOT_PERFORMED; separate later step, excluded from this delivery snapshot.'}
    save(out / 'FINAL_GATES.json', result)
    remembered = {};missing = []
    def remember(path, binary=False):
        path = Path(path).resolve();need(path.is_relative_to(ROOT) and path.is_file(), 'Missing/outside-repository record: ' + str(path))
        if not binary:
            need(path.suffix.lower() not in RAW_SUFFIXES and path.stat().st_size <= 32 * 1024 * 1024,
                 'Large/raw evidence must be referenced through a manifest, not rehashed')
        key = str(path)
        if key not in remembered:remembered[key] = identity(path)
        return remembered[key]
    try:
        decision_path = args.decisions.resolve();decision_id = remember(decision_path);decisions = read(decision_path)
        need(decisions.get('schema') == 'native08-final-decisions-v1' and decisions.get('source') == SOURCE,
             'Explicit native08 decisions schema/source required')
        need(isinstance(decisions.get('unmet'), list) and isinstance(decisions.get('decisions', {}), dict),
             'Explicit unmet list and decision object required')
        for unmet in decisions['unmet']:
            need(isinstance(unmet, dict) and all(isinstance(unmet.get(k), str) and unmet[k] for k in ('id', 'status', 'reason')),
                 'Every unmet item needs original id/status/reason')
        absent = decisions.get('missing_evidence', {});need(isinstance(absent, dict), 'missing_evidence must be an object')
        def missing_decision(path):
            relative = str(path.relative_to(BASE));value = absent.get(relative)
            need(isinstance(value, dict) and value.get('status') in ('NOT_RUN', 'BLOCKED', 'INCOMPLETE')
                 and isinstance(value.get('reason'), str) and value['reason'], 'Required legacy evidence missing: ' + relative)
            row = {'path': relative, 'original_decision': value, 'file_state': 'ABSENT_AT_INDEX'}
            missing.append(row);return row
        def reference(value):
            path = value['path'] if isinstance(value, dict) else value
            need(isinstance(path, str), 'Decision evidence path required')
            p = Path(path);p = p if p.is_absolute() else ROOT / p
            item = remember(p)
            if isinstance(value, dict) and 'sha256' in value:need(matches(item, value), 'Decision evidence identity mismatch')
            return item
        decision_rows = {}
        for axis in AXES:
            value = decisions.get('decisions', {}).get(axis)
            if value is None:
                default = 'INCOMPLETE' if axis == 'local_overall' else 'NOT_RUN' if axis == 'human_physical_application_F' else 'WITHHELD'
                decision_rows[axis] = {'original_decision': None, 'effective_status': default, 'evidence': []};continue
            need(isinstance(value, dict) and isinstance(value.get('status'), str) and value['status']
                 and isinstance(value.get('reason'), str) and value['reason'], 'Decision status/reason required: ' + axis)
            refs = value.get('evidence', []);need(isinstance(refs, list), 'Decision evidence must be a list')
            if value['status'] in ('APPROVED', 'GO', 'PASS', 'COMPLETE'):
                need(bool(refs), 'Affirmative decision requires explicit evidence: ' + axis)
            decision_rows[axis] = {'original_decision': value, 'effective_status': value['status'],
                                   'evidence': [reference(v) for v in refs],
                                   'interpretation': 'External decision indexed without result revalidation or new approval.'}
        legacy_id = remember(LEGACY);need(legacy_id['sha256'] == LEGACY_SHA, 'Frozen05 finalizer changed')
        legacy = {}
        for node in ast.parse(LEGACY.read_text()).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ('PINS', 'RUNS', 'HISTORY', 'RECORDS', 'REVIEWS'):
                    legacy[node.targets[0].id] = ast.literal_eval(node.value)
        need(set(legacy) == {'PINS', 'RUNS', 'HISTORY', 'RECORDS', 'REVIEWS'}, 'Complete frozen05 index lists required')
        metadata08 = {name: remember(BASE / name) for name in PINS}
        need(all(metadata08[name]['sha256'] == expected for name, expected in PINS.items()), 'Fixed08 metadata differs')
        metadata05 = {name: remember(BASE / name) for name in legacy['PINS']}
        need(all(metadata05[name]['sha256'] == expected for name, expected in legacy['PINS'].items()), 'Fixed05 metadata differs')
        snapshot, archive, build = read(SNAPSHOT / 'SOURCE.json'), read(ARCHIVE / 'ARCHIVE.json'), read(BUILD_PATH)
        need(snapshot['source'] == archive['source'] == build['source'] == SOURCE
             and archive['status'] == build['status'] == 'PASS'
             and build['configuration'] == 'Release' and build['architecture'] == 'arm64', 'Canonical08 source/build settings')
        need(matches(metadata08['build_native_default_08/BUILD.json'], archive['build'])
             and matches(metadata08['build_native_default_08/BUILD.json'], snapshot['build'])
             and matches(metadata08['native_source_08/SOURCE.json'], archive['source_snapshot']), '08 BUILD/SOURCE/ARCHIVE binding')
        sys.path.insert(0, str(ROOT / 'scripts'))
        from phase62_evidence import source_manifest
        current = source_manifest(ROOT);saved = source_manifest(SNAPSHOT)
        need(current == saved == snapshot['source_manifest'] == build['source_manifest']
             and current['sha256'] == SOURCE and len(current['files']) == 768, 'Full live/saved08 source mismatch')
        initial_git = git_state();need(initial_git['head'] == HEAD, 'Fixed HEAD changed')
        delivery = delivery_files(initial_git)
        (out / 'GIT_STATUS.z').write_bytes(initial_git['status'])
        (out / 'TRACKED.patch').write_bytes(initial_git['patch'])
        primary, extras = archive['files'], archive['extra_target_files']
        need(len(primary) == 54 and len(extras) == 6 and archive['distinct_executables'] == 49
             and archive['static_archives'] == 10 and archive['probe_dylibs'] == 1, '54+6/49 canonical archive counts')
        archived = [];by_name = {};executables = {}
        for group, rows, parent in (('primary', primary, ARCHIVE), ('extra', extras, ARCHIVE / 'extra_targets')):
            for row in rows:
                original, copied = row['original'], row['archived'];path = Path(copied['path']).resolve()
                need(path.parent == parent and path.name not in by_name
                     and all(original[k] == copied[k] for k in ('bytes', 'sha256')),
                     'Archive member origin/path/uniqueness mismatch')
                item = remember(path, binary=True);need(matches(item, copied), 'Saved08 artifact SHA mismatch')
                by_name[path.name] = row;archived.append({'group': group, 'identity': item, 'original': original})
                if path.suffix not in ('.a', '.dylib'):executables[path.name] = row
        need(sum(Path(n).suffix == '.a' for n in by_name) == 10
             and sum(Path(n).suffix == '.dylib' for n in by_name) == 1
             and len(executables) == 49 and len(build['binaries']) == 49, 'Archive categories/executable count mismatch')
        live_executables = []
        for name, declared in build['binaries'].items():
            need(Path(declared['path']).name == name and name in executables, 'BUILD executable absent from archive: ' + name)
            need(matches(declared, executables[name]['original']), 'BUILD/archive original executable binding')
            item = remember(declared['path'], binary=True);need(matches(item, declared), 'Live08 executable SHA mismatch: ' + name)
            live_executables.append(item)
        runs = []
        native_names = args.native_runs
        need(len(native_names) == len(set(native_names)) and all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', n)
             and n not in ('.', '..') for n in native_names), 'Unique direct-child native run names required')
        need(not set(native_names) & set((*legacy['RUNS'], *legacy['HISTORY'])), 'Do not relabel a legacy run as08')
        groups = (('legacy_list_RUNS', legacy['RUNS']), ('legacy_list_HISTORY', legacy['HISTORY']), ('explicit_native08', native_names))
        for group, names in groups:
            for name in names:
                summary_path = BASE / name / 'SUMMARY.json';expected_path = BASE / name / 'EXPECTED.json'
                if not summary_path.is_file():
                    need(group != 'explicit_native08', 'Missing explicit08 SUMMARY: ' + name)
                    runs.append({'run': name, 'index_group': group, 'missing': missing_decision(summary_path)});continue
                summary_id = remember(summary_path);value = read(summary_path);companions = []
                expected = None
                if expected_path.is_file():
                    companions.append(remember(expected_path));expected = read(expected_path)
                elif group != 'legacy_list_HISTORY':
                    need(group != 'explicit_native08', 'Missing explicit08 EXPECTED: ' + name)
                    companions.append(missing_decision(expected_path))
                if group == 'explicit_native08':
                    need(contains(expected, SOURCE), 'Explicit08 EXPECTED does not identify canonical source08: ' + name)
                rows_path = BASE / name / 'ROWS.json'
                if rows_path.is_file():companions.append(remember(rows_path))
                elif name in ('steady_thread_cpu_pairs_01', 'steady_thread_cpu_pairs_02', 'steady_digest_cpu_pairs_01'):
                    companions.append(missing_decision(rows_path))
                runs.append({'run': name, 'index_group': group, 'summary': summary_id,
                             'original_scalar_fields': {k: v for k, v in value.items() if not isinstance(v, (dict, list))},
                             'companions': companions, 'candidate08_identified_in_EXPECTED': group == 'explicit_native08',
                             'source_scope': 'Original version/source maps remain authoritative; mixed-version rows are not relabelled08.',
                             'result_scope': 'Status/count/RT/PCM/CPU values are indexed, not revalidated or added to new trial totals.'})
        records = []
        for group in ('RECORDS', 'REVIEWS'):
            for name in legacy[group]:
                path = BASE / name
                records.append({'legacy_group': group, 'identity': remember(path)} if path.is_file()
                               else {'legacy_group': group, 'missing': missing_decision(path)})
        core_path = ROOT / 'results/performance_response/evidence/CORE_GATES.json'
        history_path = ROOT / 'results/performance_response/evidence/FAILURE_HISTORY.json'
        core, history = remember(core_path), remember(history_path)
        local = decision_rows['local_overall']['effective_status']
        external_scopes = ('public', 'Merodoa', 'human')
        local_unmet = [item for item in decisions['unmet'] if item.get('scope') not in external_scopes]
        local_missing = [item for item in missing if item['original_decision'].get('scope') not in external_scopes]
        cpu_unresolved = decision_rows['CPU_adoption']['effective_status'] not in ('APPROVED', 'PASS', 'GO')
        unresolved = bool(local_unmet) or bool(local_missing) or cpu_unresolved
        result.update(head=initial_git['head'], branch=initial_git['branch'], source_inventory_sha256=SOURCE,
                      source_files=768, source_inventory_is_not_commit_SHA=True, uncommitted=bool(initial_git['status']),
                      metadata08=metadata08, metadata05=metadata05, legacy_finalizer=legacy_id,
                      legacy_source_scope=SOURCE05 + '; metadata pins/index references only, not rerun as08',
                      canonical08_archive_members=archived, canonical08_archive_counts={'primary': 54, 'extras': 6, 'executables': 49},
                      live08_executables=live_executables, runs=runs, legacy_records=records,
                      core_gates=core, original_failure_history=history, decisions={'identity': decision_id,
                      'original_record': decisions, 'axes': decision_rows}, declared_missing_evidence=missing,
                      tracked_patch=identity(out / 'TRACKED.patch'), git_status=identity(out / 'GIT_STATUS.z'),
                      delivery_files_before_later_Git_index_copy=delivery,
                      native_run_names_explicit=native_names, local_overall='INCOMPLETE' if unresolved else local,
                      local_completion_basis={'explicit_status': local,
                      'required_CPU_status': decision_rows['CPU_adoption']['effective_status'],
                      'local_unmet_ids': [item['id'] for item in local_unmet],
                      'local_missing_paths': [item['path'] for item in local_missing],
                      'scope_policy': 'Missing/unknown scope is local; public/Merodoa/human remain separate. Original decisions are retained.'},
                      human_physical_application_F=decision_rows['human_physical_application_F']['effective_status'],
                      large_PCM_policy='No RAW/WAV rehash; refer to original manifests and independent capture audits. No new PCM trial credit.')
        for axis in ('CPU_adoption', 'public_release', 'Merodoa_default'):
            result[axis] = decision_rows[axis]['effective_status']
        need(source_manifest(ROOT) == current and source_manifest(SNAPSHOT) == saved,
             'Source changed during index collection')
        need(git_state() == initial_git and delivery_files(initial_git) == delivery, 'Git HEAD/status/patch/delivery changed during index')
        for path, item in remembered.items():need(identity(path) == item, 'Evidence/artifact changed during index: ' + path)
        for item in missing:need(not (BASE / item['path']).exists(), 'Absent legacy evidence appeared during index')
        need(identity(out / 'TRACKED.patch') == result['tracked_patch']
             and identity(out / 'GIT_STATUS.z') == result['git_status'], 'Own Git snapshot files changed')
        result.update(index_collection='COMPLETE', index_integrity='PASS', canonical_source_archive_verification='PASS',
                      begin_end_source_HEAD_metadata_artifact_delivery_consistent=True)
    except BaseException as error:
        result.update(index_collection='INCOMPLETE', index_integrity='INCOMPLETE',
                      local_overall='INCOMPLETE',
                      error=type(error).__name__ + ': ' + str(error))
    save(out / 'FINAL_GATES.json', result)
    print(json.dumps({'index_integrity': result['index_integrity'], 'local_overall': result['local_overall'],
                      'record': identity(out / 'FINAL_GATES.json'), 'index_PASS_is_not_GO': True}, ensure_ascii=False))
    return 0 if result['index_integrity'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
