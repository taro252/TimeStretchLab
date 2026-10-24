#!/usr/bin/env python3
"""保存warm AB12実行のsetup/warmを、独立固定Exact RAWで24capture/120check監査する。

例（native実行・音声・参照生成・ビルドは起動しない）:
 /usr/local/bin/python3 -B results/performance_response/recipes/validate_warm_ab_captures_v2.py \
   --run build/performance_response_20261023_01/warm_ab_pairs_final06 \
   --client build/performance_response_20261023_01/warm_ab_clients_final06/CLIENT.json \
   --references build/performance_response_20261023_01/ab_fixed_references_final_01/REFERENCES.json \
   --candidate-source 0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e \
   --output build/performance_response_20261023_01/warm_ab_capture_audit_final06

A30/270、1倍、candidate preset、旧新各3反復を固定する。12program/36受付/24Loop終端、
全source固定・成果物SHAを事前照合してから、各setup/warmの5項目を全量比較する。
65536は収録容量に限る。独立validatorのRAW/span各8192件上限は変更・切り詰めしない。
性能/RTの未達をPCM不一致へ読み替えず、品質PASSを性能/RT/物理/F/採用PASSへ昇格しない。
"""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import platform
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
RECIPES = ROOT / 'results/performance_response/recipes'
BATCH = RECIPES / 'validate_ab_captures.py'
BATCH_SHA = '76b951449dca937f27c17bca3a054f40e7041eb6f8d14bfce210ec513afde111'
RUNNER = RECIPES / 'run_generic_warm_ab_pairs_v2.py'
RUNNER_SHA = 'c06ab9d144f91ad2b1dc2d4711ad8c13a95b882421bb343d52d5e0ff81260f5c'
VALIDATOR = ROOT / 'results/progressive_adoption/recipes/validate_capture.py'
VALIDATOR_SHA = '4dac95f5e7ad882ff2a28ae648a4c10b8bd553cc9dbb7bd7c814581ab2c8f451'
EQUATIONS = ROOT / 'results/phase62_terminal_initial/recipes/validate_initial_pcm.py'
EQUATIONS_SHA = '3be115fe493b249e120cb5f42c056a458ebe6cf76d2124842dc7cf3b6cad8bb4'
ORACLE_SHA = 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
SOURCE_SHA = '422d1ff7eb52d70b9ea55e1a3e572b39c0de503352a05e6f6c12f234dbbea42e'
BASELINE_SOURCE = '2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392'
INPUT_SHA = '13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0'
RAW_SHA = '31e29e3c968672f821fe8887a702012810316687b192f6db4f1f670ffee381d2'
OLD_PINS = {
    'EXPECTED.json': '9f43a880c6ba5304a9f4617c54fbf0feb446f0840fd07f45508773ce152f6f47',
    'reference.log': '52ac58c6d90400daf363c37fd05bb3a0cb093f41c747f927eeb56ae361e671a5',
    'A30_fresh_map.json': '7bbedfaf03a7db58d57034817667f818227c9075d6c5705b1a8d465e8ad3b221',
    'A270_fresh_map.json': 'd22c0bdf461b7c59a5fc6cbf8e0a6221abda931008933a3b3747054b74cec579'}
MAP_PINS = {30: '4744e92a2d28907a3b93eb4c2bc7cfd00b488706aeb51145aeab1ed6fafd97b7',
            270: '3432aa5824d3375a892a7dda3e7eea4f86ec6038c219ac2d8bf5c61049aa6bb7'}
ORACLE_MANIFEST_SHA = 'abf48d368e907fab2fd6d6557e1e1417b457d00f114275cf0335422c8caf4630'
CHECK_IDS = ('independent_map', 'raw_all_bits', 'output_all_bits', 'coordinates', 'gain')
CAPTURE_FILES = ('EXPECTED.json', 'SUMMARY.json', 'raw.f32', 'raw_records.jsonl',
                 'output_before_gain.f32', 'spans.jsonl')
SCOPE = {'performance_status': 'NOT_ASSESSED', 'realtime_status': 'NOT_ASSESSED',
         'physical_audio_continuity_verified': None, 'application_F': None, 'public_approved': False,
         'PASS_scope': 'Independent saved PCM, coordinates and gain configuration only; no native execution.',
         'warm_RT_latency': 'Native results preserved separately; exit2 may be a completed RT/latency failure.'}


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def module(path, name, expected_sha):
    need(sha(path) == expected_sha, 'Pinned existing helper changed: ' + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def fixed_ids():
    result = []
    for repeat in (1, 2, 3):
        for at in (30, 270):
            for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
                result.append(f'A{at}_candidate_r{repeat:02d}_{version}')
    return result


def load_references(path, ids, read, validator):
    """全12宣言の完了と集合を確認し、使用するmono1xの2sliceだけを実ファイル照合する。"""
    base, manifest = path.parent, read(path)
    need(manifest.get('schema') == 'performance-ab-fixed-references-v1' and manifest.get('status') == 'PASS'
         and manifest.get('complete') is True and manifest.get('expected_entries') == 12
         and manifest.get('independent_fixed_DSP') is True, 'Incomplete independent fixed reference manifest')
    entries = manifest['entries']
    names = [entry['id'] for entry in entries]
    expected_names = {f'{label}_A{at}_{speed}' for label in ('mono48', 'stereo48')
                      for at in (30, 270) for speed in (400000, 1000000, 2000000)}
    need(len(names) == len(set(names)) == 12 and set(names) == expected_names, 'Fixed 12 reference entry IDs')
    oracle = ids.check(manifest['reference_binary'], base)
    need(oracle['sha256'] == ORACLE_SHA, 'Saved de70 oracle required; product/head reference forbidden')
    source = ids.check(manifest['reference_source_manifest'], base)
    need(source['sha256'] == ORACLE_MANIFEST_SHA, 'Frozen oracle source manifest SHA')
    queries, refs = [1440000, 1444800, 12960000, 12964800], {}
    witness = None
    for at, offset in ((30, 0), (270, 2)):
        entry = next(e for e in entries if e['id'] == f'mono48_A{at}_1000000')
        input_id = ids.check(entry['input'], base)
        raw, mapped, logged = (ids.check(entry[k], base) for k in ('raw', 'map', 'oracle_log'))
        need(input_id['sha256'] == INPUT_SHA and raw['sha256'] == RAW_SHA
             and logged['sha256'] == OLD_PINS['reference.log'] and mapped['sha256'] == MAP_PINS[at],
             'Known mono1x input/RAW/log/Map SHA differs')
        need(validator.wav_info(Path(input_id['path'])) ==
             {'channels': 1, 'rate': 48000, 'frames': 14400000, 'encoding': 3, 'bits': 32},
             'Fixed chain300 mono48 Float32 input')
        selected = queries[offset:offset + 2]
        command = entry['command']
        need(entry['preset'] == 'candidate' and type(entry['speed_micros']) is int
             and entry['speed_micros'] == 1000000 and entry['queries'] == queries
             and entry['input_positions'] == selected and entry.get('query_slice') == [offset, offset + 1]
             and entry.get('finite') is True and entry.get('reused') is True
             and type(entry['returncode']) is int and entry['returncode'] == 0 and entry['timeout'] is False,
             'Selected reference input/speed/queries/completion differ')
        need(isinstance(command, list) and len(command) == 9 and all(type(x) is str for x in command)
             and command[2:4] == ['1000000', 'candidate'] and command[5:] == list(map(str, queries)),
             'Full frozen oracle command and all four independent queries')
        for actual, wanted in ((command[0], oracle['path']), (command[1], input_id['path']), (command[4], raw['path'])):
            need(Path(actual).resolve() == Path(wanted), 'Frozen command file binding')
        full, meta = read(logged['path']), read(mapped['path'])
        need(isinstance(full.get('positions'), list) and len(full['positions']) == 4
             and all(type(v) is int and 0 <= v <= 14400000 for v in full['positions']), 'Oracle query positions')
        for key, value in (('channels', 1), ('rate', 48000), ('input_frames', 14400000),
                           ('output_frames', 14400000), ('sha256', RAW_SHA)):
            need(full.get(key) == meta.get(key) == value, 'Independent log/Map field: ' + key)
        need(raw['bytes'] == 57600000 and meta.get('input_sha256') == INPUT_SHA
             and meta.get('input_positions') == selected and meta.get('positions') == full['positions'][offset:offset + 2],
             'Exact independent full-RAW length and selected query slice')
        old_expected = ids.check(entry['old_expected'], base)
        old_map = ids.check(entry['old_reference_map'], base)
        need(entry.get('old_fixed_metadata_pins') == OLD_PINS and entry.get('old_map_values_identical') is True
             and old_expected['sha256'] == OLD_PINS['EXPECTED.json']
             and old_map['sha256'] == OLD_PINS[f'A{at}_fresh_map.json'], 'Old independent reference pins')
        original, old_values = read(old_expected['path']), read(old_map['path'])
        need(original.get('command') == command and original.get('input_positions') == queries
             and original['input']['sha256'] == INPUT_SHA and original['oracle']['sha256'] == ORACLE_SHA,
             'Original generation command/input/oracle binding')
        need(all(old_values.get(k) == meta.get(k) for k in
                 ('output_frames', 'input_frames', 'channels', 'rate', 'sha256', 'positions', 'input_positions')),
             'Reused old Map is not the exact two-query slice')
        current = (raw['path'], logged['path'], tuple(full['positions']), tuple(command))
        need(witness is None or witness == current, 'A30/A270 must share identical full render and four queries')
        witness = current
        refs[at] = {'entry_id': entry['id'], 'input': input_id, 'raw': raw, 'map': mapped,
                    'oracle_log': logged, 'oracle': oracle, 'source_manifest': source,
                    'old_expected': old_expected, 'old_map': old_map, 'queries': queries,
                    'input_positions': selected}
    return refs


def preflight(args, out, ids, batch, warm, validator):
    run, client_path = args.run.resolve(), args.client.resolve()
    read = batch.read
    expected_id, summary_id, client_id = (ids.identity(p) for p in (run / 'EXPECTED.json', run / 'SUMMARY.json', client_path))
    declared, summary, client = (read(p) for p in (run / 'EXPECTED.json', run / 'SUMMARY.json', client_path))
    need(client.get('schema') == 'performance-warm-ab-clients-v1' and client.get('status') == 'PASS'
         and client.get('compile_only') is True and client.get('preset') == 'candidate'
         and client.get('expected_programs') == 12 and client.get('expected_checks') == 144,
         'Complete candidate-preset warm client manifest')
    need(client['baseline_source'] == client['clients']['old']['source'] == BASELINE_SOURCE
         and client['candidate_source'] == client['clients']['candidate']['source'] == args.candidate_source
         and client['baseline_commit'] == '5674bd982d98caacaa3e87cdeae5bfc0b01c66ef',
         'Own client old/new source binding')
    for key in ('source', 'copied_source'):
        need(ids.check(client[key], client_path.parent)['sha256'] == SOURCE_SHA, 'Same fixed warm C++ body')
    need(client['capture_helper']['original_helper_modified'] is False and
         client['capture_helper']['common_sha256'] == client['capture_helper']['old']['sha256'] ==
         client['capture_helper']['candidate']['sha256'], 'Same preallocated capture helper')
    for version in ('old', 'candidate'):
        entry = client['clients'][version]
        need(entry['contract_version'] == (3 if version == 'old' else 4), 'Own client ABI')
        ids.check(entry['binary'], client_path.parent)
        ids.check(client['capture_helper'][version], client_path.parent)
    plan_id = ids.check(client['run_plan'], client_path.parent)
    jobs = warm.fixed_jobs(client, read(plan_id['path']), run)
    want_ids = fixed_ids()
    need([j['id'] for j in jobs] == want_ids and declared.get('schema') == summary.get('schema') == 'warm-ab-run-v1'
         and declared.get('jobs') == jobs and declared.get('all_expected_ids') == summary.get('all_expected_ids') ==
         summary.get('executed_ids') == want_ids, 'Exact 12 native IDs/commands/order; no attempt merging')
    for obj in (declared, summary):
        need(obj.get('expected_programs') == 12 and obj.get('expected_checks') == 144
             and obj.get('expected_Accepted_receipts') == 36 and obj.get('expected_unique_Loop_IDs') == 24
             and obj.get('expected_owned_Loop_terminal_rows') == 24, 'Native fixed program/check/receipt/terminal declarations')
    need(declared.get('required_check_ids') == list(warm.CHECK_IDS)
         and declared.get('accepted_receipts_per_program') == warm.RECEIPTS and declared.get('timeout_allowed') is False
         and declared.get('serial_audio') is True and declared.get('device_rate') == 48000
         and declared.get('device_buffer') == 512, 'Native fixed functional/device/watchdog settings')
    need(summary.get('collection_status') == 'PASS' and all(summary.get(k) is True for k in
         ('all_programs_finished', 'all_cases_complete', 'integrity_pass', 'functional_pass',
          'performance_measurement_valid', 'warm_complete', 'all_Accepted_ID_sets_verified'))
         and summary.get('executed_programs') == 12 and summary.get('reported_passed_checks') == 144
         and summary.get('recovered_owned_Loop_terminal_rows') == 24 and summary.get('NOT_EXERCISED_ids') == []
         and summary.get('warm_miss_reclassified_fresh') is False and summary.get('errors') == []
         and summary.get('Loop_snapshot_fields') == len(warm.LOOP_FIELDS)
         and summary.get('status') in ('PASS', 'FAIL'),
         'Incomplete, failed collection or NOT_EXERCISED warm run')
    need(summary.get('baseline_source') == BASELINE_SOURCE and summary.get('candidate_source') == args.candidate_source,
         'Run source identity')
    for record, wanted in ((declared['client'], client_id), (summary['client_compile_manifest'], client_id),
                           (summary['expected_manifest'], expected_id), (declared['run_plan'], plan_id)):
        need(ids.check(record, run)['sha256'] == wanted['sha256'], 'Run/CLIENT/EXPECTED/RUN_PLAN SHA binding')
    need(ids.check(declared['driver'], run)['sha256'] == RUNNER_SHA, 'Frozen warm collection driver')
    for record in declared['helpers']:
        ids.check(record, run)
    inventory_path = run / 'COMPILE_INVENTORY.json'
    ids.identity(inventory_path)
    inventory = read(inventory_path)
    digest = warm.common.manifest_digest(inventory['files'])
    need(inventory.get('manifest_sha256') == digest and bool(inventory['files']), 'Compile inventory content digest')
    inventory_records = {}
    for row in inventory['files']:
        item = ids.check(row['identity'], run)
        inventory_records[item['path']] = item['sha256']
    for name in ('FROZEN_BEFORE.json', 'FROZEN_AFTER.json'):
        ids.identity(run / name)
        frozen = read(run / name)
        need(frozen.get('status') == 'PASS' and frozen.get('mismatches') == []
             and frozen.get('expected_files') == frozen.get('checked_files') == len(inventory['files'])
             and frozen.get('manifest_sha256') == digest, 'Compile/input source freeze: ' + name)
    source_rows = []
    for key, source_sha in (('baseline_build', BASELINE_SOURCE), ('candidate_build', args.candidate_source)):
        build_id = ids.check(client[key], client_path.parent)
        build = read(build_id['path'])
        need(build.get('status') == 'PASS' and build.get('source') == build['source_manifest']['sha256'] == source_sha
             and warm.common.manifest_digest(build['source_manifest']['files']) == source_sha,
             'Saved build source inventory: ' + key)
        source_rows.append({'name': key, 'root': str(Path(build['source_root']).resolve()), 'sha256': source_sha})
    for name in ('SOURCE_BEFORE.json', 'SOURCE_AFTER.json'):
        ids.identity(run / name)
    before, after = read(run / 'SOURCE_BEFORE.json'), read(run / 'SOURCE_AFTER.json')
    expected_after = [{**row, 'actual_sha256': row['sha256'], 'unchanged': True} for row in source_rows]
    need(before.get('status') == after.get('status') == 'PASS' and before.get('source_manifests') ==
         declared.get('source_manifests') == source_rows and after.get('source_manifests') ==
         summary.get('source_after') == expected_after, 'Saved source freeze before/after mismatch')
    # 停止済み記録だけでなく、今回使用するソース・ヘルパーも開始時と終了時に固定する。
    for row in source_rows:
        need(warm.common.current_source_digest(Path(row['root'])) == row['sha256'], 'Current source differs from run: ' + row['name'])
    for helper in (RUNNER, Path(warm.builder.__file__), Path(warm.common.__file__),
                   Path(warm.audit_helpers.__file__), Path(warm.paused.__file__)):
        item = ids.identity(helper)
        need(inventory_records.get(item['path']) == item['sha256'], 'Assessment helper is not in the native frozen inventory')
    input_id = ids.check(client['input'], client_path.parent)
    need(input_id['sha256'] == INPUT_SHA and ids.check(declared['input'], run)['sha256'] == INPUT_SHA,
         'Fixed native chain300 input')
    refs = load_references(args.references.resolve(), ids, read, validator)
    rows = summary['rows']
    need([r['id'] for r in rows] == want_ids and len(rows) == 12, 'Missing/duplicate native rows')
    results, native_audits = [], []
    for job, row in zip(jobs, rows):
        for key in ('id', 'pair_id', 'repeat', 'version', 'preset', 'A_seconds'):
            need(row.get(key) == job[key], 'Native row fixed condition: ' + job['id'] + '/' + key)
        need(type(row['execution'].get('returncode')) is int and row['execution']['returncode'] in (0, 2)
             and row['execution'].get('timeout') is False and row['execution'].get('interrupted') is False,
             'Incomplete native execution or invalid exit type: ' + job['id'])
        directory = run / job['id']
        audited = warm.assess(job, directory, row['execution'], client, 48000, 512)
        need(all(audited.get(k) is True for k in ('integrity_pass', 'functional_pass', 'measurement_valid'))
             and audited.get('warm_classification') == 'EXERCISED', 'Native re-audit failed/NOT_EXERCISED: ' + job['id'])
        need(all(row.get(k) == value for k, value in audited.items()), 'Saved native assessment differs from current files: ' + job['id'])
        actual_artifacts = {str(p.resolve()) for p in directory.rglob('*') if p.is_file()}
        records = row['artifacts']
        paths = [str(Path(item['path']).resolve()) for item in records]
        need(len(paths) == len(set(paths)) == len(actual_artifacts) and set(paths) == actual_artifacts,
             'Missing/duplicate/unowned native artifact identities: ' + job['id'])
        for record in records:
            ids.check(record, run)
        native_audits.append({'id': job['id'], 'Accepted_receipts': 3, 'owned_Loop_terminals': 2,
                             'native_check_ids': list(warm.CHECK_IDS), 'native_checks_passed': audited['checks_passed'],
                             'audit': audited['audit'], 'rt_reported': audited['rt_observation_pass'],
                             'warm_250ms_reported': audited['latency_target_single_pass']})
        for segment in ('setup', 'warm'):
            capture = directory / segment
            count = {}
            for name in ('raw_records.jsonl', 'spans.jsonl'):
                count[name] = len(warm.read(capture / name, True))
                need(0 < count[name] <= 8192, 'BLOCKED: unchanged independent validator requires 1..8192 complete records: '
                     + job['id'] + '/' + segment + '/' + name + '=' + str(count[name]))
            cap = read(capture / 'SUMMARY.json')
            need(cap.get('validator_row_limit_exercised') is True, 'Native declares independent row limit unexercised')
            artifacts = {name: ids.identity(capture / name) for name in CAPTURE_FILES}
            results.append({'id': job['id'] + '/' + segment, 'native_id': job['id'], 'segment': segment,
                            'capture': str(capture), 'host_binary': ids.check(client['clients'][job['version']]['binary'], client_path.parent),
                            'input': input_id, 'reference': refs[job['A_seconds']], 'records': count,
                            'capture_artifacts': artifacts, 'native_rt_reported': audited['rt_observation_pass'],
                            'native_performance_reported': audited['latency_target_single_pass']})
    need(len(results) == 24 and len(native_audits) == 12 and sum(x['Accepted_receipts'] for x in native_audits) == 36
         and sum(x['owned_Loop_terminals'] for x in native_audits) == 24, 'Fixed aggregate native prerequisites')
    return results, {'status': 'PASS', 'native_programs': 12, 'native_checks': 144, 'Accepted_receipts': 36,
                     'owned_Loop_terminals': 24, 'expected_manifest': expected_id, 'summary': summary_id,
                     'client': client_id, 'compile_inventory_sha256': digest, 'source_rows': source_rows,
                     'native_status_reported': summary['status'], 'native_audits': native_audits,
                     'reference_entries_declared': 12, 'reference_entries_used': 2,
                     'reference_hash_scope': 'Only both selected mono1x entries; unused stereo/speed RAWs are not rehashed.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--candidate-source', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    need(len(args.candidate_source) == 64 and all(c in '0123456789abcdef' for c in args.candidate_source), 'Candidate source SHA-256')
    out = args.output.resolve()
    need(out.is_relative_to(ROOT / 'build'), 'New audit evidence must be under build/')
    need(not any(out.is_relative_to(p.resolve()) for p in (args.run, args.client.parent, args.references.parent)),
         'Audit output must not modify capture/client/reference directories')
    out.mkdir(parents=True, exist_ok=False)
    native_ids = fixed_ids()
    capture_ids = [name + '/' + segment for name in native_ids for segment in ('setup', 'warm')]
    expected = {'schema': 'performance-warm-ab-capture-batch-v1', 'expected_native_programs': 12,
                'expected_captures': 24, 'expected_checks': 120, 'all_native_ids': native_ids,
                'all_expected_ids': capture_ids, 'required_check_ids': list(CHECK_IDS),
                'expected_Accepted_receipts': 36, 'expected_owned_Loop_terminals': 24,
                'candidate_source': args.candidate_source, 'baseline_source': BASELINE_SOURCE,
                'run': str(args.run.resolve()), 'client': str(args.client.resolve()),
                'references': str(args.references.resolve()), 'preflight': {'status': 'PENDING'},
                'validator_required_sha256': VALIDATOR_SHA, 'oracle_required_sha256': ORACLE_SHA,
                'equations_required_sha256': EQUATIONS_SHA, 'runner_required_sha256': RUNNER_SHA,
                'metadata_helper_required_sha256': BATCH_SHA, 'record_limit_each_raw_and_spans': 8192,
                'truncate': False, 'python': sys.version, 'platform': platform.platform(),
                'hash_reuse': 'This process only; same stat before/after. No numerical PCM comparison is skipped.', **SCOPE}
    save(out / 'EXPECTED.json', expected)
    rows, error, ids, preflight_complete = [], None, None, False
    try:
        sys.path.insert(0, str(RECIPES))
        batch = module(BATCH, 'warm_fixed_metadata_helpers', BATCH_SHA)
        ids = batch.Identities()
        expected['driver'] = ids.identity(__file__)
        expected['metadata_helper'] = ids.identity(BATCH)
        expected['runner'] = ids.identity(RUNNER)
        expected['validator'] = ids.identity(VALIDATOR)
        need(expected['validator']['sha256'] == VALIDATOR_SHA and ids.identity(EQUATIONS)['sha256'] == EQUATIONS_SHA,
             'Independent validator or boundary equations changed')
        validator = module(VALIDATOR, 'warm_independent_capture_validator', VALIDATOR_SHA)
        validator.identity = ids.identity
        warm = module(RUNNER, 'warm_saved_native_assessment', RUNNER_SHA)
        # 読取りSHAのみ共有。凍結PCM/境界数式、判定と8192制限には触れない。
        def cached_native_identity(path):
            item = ids.identity(path)
            return {key: item[key] for key in ('path', 'bytes', 'sha256')}
        warm.common.identity = cached_native_identity
        expected['reference_manifest'] = ids.identity(args.references)
        jobs, prerequisites = preflight(args, out, ids, batch, warm, validator)
        need([job['id'] for job in jobs] == capture_ids, 'Exact 24-capture fixed ID set')
        expected.update(jobs=jobs, preflight=prerequisites)
        save(out / 'EXPECTED.json', expected)
        preflight_complete = True
        for job in jobs:
            child_out = out / job['id'].replace('/', '__')
            ref = job['reference']
            argv = [str(VALIDATOR), '--capture', job['capture'], '--input', job['input']['path'],
                    '--host-binary', job['host_binary']['path'], '--reference-binary', ref['oracle']['path'],
                    '--reference-raw', ref['raw']['path'], '--reference-map', ref['map']['path'], '--output', str(child_out)]
            begin, original_argv, log = time.monotonic(), sys.argv, io.StringIO()
            try:
                sys.argv = argv
                with contextlib.redirect_stdout(log):
                    code = validator.main()
            finally:
                sys.argv = original_argv
                (out / (job['id'].replace('/', '__') + '.log')).write_text(log.getvalue())
            summary = batch.read(child_out / 'SUMMARY.json')
            checks = summary.get('checks', {})
            need(set(checks) == set(CHECK_IDS), 'Child validator fixed five-check ID set changed')
            need(all(c.get('status') in ('PASS', 'FAIL', 'INCOMPLETE') for c in checks.values()), 'Unknown child check status')
            executed = sum(c['status'] != 'INCOMPLETE' for c in checks.values())
            passed = sum(c['status'] == 'PASS' for c in checks.values())
            need(summary.get('expected') == 5 and summary.get('executed') == executed and summary.get('passed') == passed
                 and summary.get('validator_sha256') == VALIDATOR_SHA, 'Child counts/validator source differ')
            good = code == 0 and summary.get('status') == 'PASS' and summary.get('run_complete') is True and passed == executed == 5
            rows.append({'id': job['id'], 'status': 'PASS' if good else 'FAIL_OR_INCOMPLETE', 'command': argv,
                         'validator_exit': code, 'wall_s': time.monotonic() - begin, 'executed_checks': executed,
                         'passed_checks': passed, 'failed_checks': sum(c['status'] == 'FAIL' for c in checks.values()),
                         'incomplete_checks': 5 - executed, 'reason': summary.get('reason'),
                         'expected': ids.identity(child_out / 'EXPECTED.json'), 'summary': ids.identity(child_out / 'SUMMARY.json')})
            save(out / 'PROGRESS.json', {'status': 'IN_PROGRESS', 'expected_captures': 24, 'executed_captures': len(rows), 'rows': rows})
            print(job['id'], rows[-1]['status'], flush=True)
        for source in prerequisites['source_rows']:
            need(warm.common.current_source_digest(Path(source['root'])) == source['sha256'],
                 'Source changed during batch: ' + source['name'])
        ids.unchanged()
    except (Exception, KeyboardInterrupt) as failure:
        error = type(failure).__name__ + ': ' + str(failure)
        if not preflight_complete:
            expected['preflight'] = {'status': 'BLOCKED', 'reason': error}
            save(out / 'EXPECTED.json', expected)
    complete = preflight_complete and len(rows) == 24 and error is None
    good = complete and all(row['status'] == 'PASS' for row in rows)
    result = {'schema': 'performance-warm-ab-capture-summary-v1',
              'status': 'PASS' if good else ('BLOCKED' if not preflight_complete else 'FAIL_OR_INCOMPLETE'),
              'run_complete': complete, 'preflight_complete': preflight_complete,
              'expected_native_programs': 12, 'verified_native_programs': 12 if preflight_complete else 0,
              'expected_captures': 24, 'executed_captures': len(rows),
              'passed_captures': sum(r['status'] == 'PASS' for r in rows),
              'expected_checks': 120, 'executed_checks': sum(r['executed_checks'] for r in rows),
              'passed_checks': sum(r['passed_checks'] for r in rows), 'failed_checks': sum(r['failed_checks'] for r in rows),
              'incomplete_checks': sum(r['incomplete_checks'] for r in rows) + 5 * (24 - len(rows)),
              'all_expected_ids': capture_ids, 'executed_ids': [r['id'] for r in rows], 'rows': rows, 'reason': error,
              'expected_sha256': sha(out / 'EXPECTED.json'), 'driver_sha256': sha(__file__),
              'validator_sha256': VALIDATOR_SHA, 'hash_unique_files': len(ids.values) if ids else 0,
              'hash_cache_hits': ids.hits if ids else 0, **SCOPE}
    save(out / 'SUMMARY.json', result)
    print(json.dumps({key: result[key] for key in ('status', 'expected_captures', 'executed_captures', 'passed_checks', 'reason')}, ensure_ascii=False))
    return 0 if good else 2


if __name__ == '__main__':
    raise SystemExit(main())
