#!/usr/bin/env python3
"""AB72 / nonfresh36の全captureを保存de70固定RAWで各5項目監査する。

例（試験・音声・参照合成は起動せず、保存captureの数値比較だけを行う）:
  /usr/local/bin/python3 -B results/performance_response/recipes/validate_ab_captures.py \
    --main-run B/ab_main_pairs_final_02 --nonfresh-run B/ab_nonfresh_final_01 \
    --references B/ab_references_01/MANIFEST.json \
    --host-manifest B/ab_observation_clients_01/CLIENT.json \
    --candidate-source c23094e73fd2587f4295ce850fb356e080ced0dcbdbd0c9bca2290bccbe69e98 \
    --output B/ab_capture_audit_final_01

--main-runのみは72capture/360check、--nonfresh-runのみは36/180、両方は108/540。
部分集合選択と数値比較省略は許可しない。明示disk-preplay-recovery-v1だけ70完了+2新規を区別して監査する。

参照MANIFEST schema（pathはmanifestの親を基準にも指定可）:
  {"schema":"performance-ab-fixed-references-v1",
   "reference_binary":{"path":"...","bytes":274184,"sha256":"de70..."},
   "entries":[{"id":"mono48_1000000_A30", "input":{path,bytes,sha256},
     "preset":"candidate", "speed_micros":1000000,
     "queries":[1440000,1444800,12960000,12964800],
     "input_positions":[1440000,1444800], "raw":{path,bytes,sha256},
     "map":{path,bytes,sha256}, "oracle_log":{path,bytes,sha256},
     "command":[oracle,input,"1000000","candidate",raw,"1440000",...],
     "returncode":0,"timeout":false}]}

6 input/speed組×2 A=12entriesを想定。同input/speedのRAW/log/queriesは共有できる。
logはde70のJSON metadataを一つ含み、mapはその4queriesから[A,B]を厳密に選ぶ。
旧mono1xは保存EXPECTED.jsonをgeneration_expected:{path,bytes,sha256}として追加可。
品質と性能/RT/物理音声/採用は別判定。gain監査は設定sourceの検査であり物理証明ではない。
"""

import argparse
import contextlib
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import platform
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / 'results/progressive_adoption/recipes/validate_capture.py'
VALIDATOR_SHA = '4dac95f5e7ad882ff2a28ae648a4c10b8bd553cc9dbb7bd7c814581ab2c8f451'
ORACLE_SHA = 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
EQUATIONS_SHA = '3be115fe493b249e120cb5f42c056a458ebe6cf76d2124842dc7cf3b6cad8bb4'
EQUATIONS = ROOT / 'results/phase62_terminal_initial/recipes/validate_initial_pcm.py'
CHECK_IDS = ('independent_map', 'raw_all_bits', 'output_all_bits', 'coordinates', 'gain')
CAPTURE_FILES = ('EXPECTED.json', 'SUMMARY.json', 'raw.f32', 'raw_records.jsonl',
                 'output_before_gain.f32', 'spans.jsonl')
BASELINE_SOURCE = '2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def finite_tree(value):
    if isinstance(value, dict):
        for child in value.values():
            finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            finite_tree(child)
    elif type(value) is float:
        require(math.isfinite(value), 'NaN/Inf measurement')


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def loads(body):
    def reject(value):
        raise ValueError('NaN/Inf JSON constant: ' + value)
    result = json.loads(body, parse_constant=reject, object_pairs_hook=object_pairs)
    finite_tree(result)
    return result


def read(path):
    return loads(Path(path).read_text())


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def stat(path):
    value = Path(path).stat()
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns]


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1 << 20), b''):
            value.update(part)
    return value.hexdigest()


class Identities:
    """今回プロセス内だけでhashを共有。stat不一致は再採用せず失敗する。"""
    def __init__(self):
        self.values = {}
        self.hits = 0

    def identity(self, path):
        path = Path(path).resolve()
        before = stat(path)
        if str(path) in self.values:
            item = self.values[str(path)]
            require(item['stat'] == before, 'Artifact changed during batch: ' + str(path))
            self.hits += 1
            return dict(item)
        item = {'path': str(path), 'bytes': before[2], 'sha256': sha(path), 'stat': before}
        require(stat(path) == before, 'Artifact changed while hashing: ' + str(path))
        self.values[str(path)] = item
        return dict(item)

    def check(self, record, base):
        require(isinstance(record, dict) and {'path', 'bytes', 'sha256'} <= set(record), 'File identity declaration missing')
        path = Path(record['path'])
        path = path if path.is_absolute() else base / path
        item = self.identity(path)
        require(type(record['bytes']) is int and item['bytes'] == record['bytes']
                and item['sha256'] == record['sha256'], 'File identity differs: ' + str(path))
        return item

    def unchanged(self):
        for path, item in self.values.items():
            require(stat(path) == item['stat'], 'Artifact changed before completion: ' + path)


def number(text):
    try:
        value = Decimal(str(text))
    except InvalidOperation as error:
        raise ValueError('Invalid decimal: ' + str(text)) from error
    require(value.is_finite(), 'Nonfinite decimal')
    return value


def rounded_frames(seconds, rate=48000):
    return int((number(seconds) * rate).to_integral_value(rounding=ROUND_HALF_UP))


def matrix(suite):
    result = {}
    for repeat in range(1, 4):
        inputs = ('mono48', 'stereo48') if suite == 'main72' else ('mono48chain300s',)
        for label in inputs:
            for at in (30, 270):
                for variant in ((40, 100, 200) if suite == 'main72' else ('prewarm', 'early0', 'mid')):
                    layer = (f'{label}_A{at}_s{variant:03d}_candidate' if suite == 'main72'
                             else f'A{at}_{variant}_candidate')
                    pair = f'{layer}_r{repeat:02d}'
                    for version in ('old', 'candidate'):
                        name = pair + '_' + version
                        result[name] = {'id': name, 'input': label, 'A_seconds': at, 'preset': 'candidate',
                                        'repeat': repeat, 'version': version, 'pair_id': pair,
                                        'mode': 'fresh' if suite == 'main72' else variant,
                                        'speed_micros': variant * 10000 if suite == 'main72' else 1000000,
                                        'lead_ms': (500 if at == 30 else 2500) if variant == 'mid' else 0}
    return result


def load_references(path, identities, validator):
    base = path.parent
    manifest = read(path)
    require(manifest.get('schema') == 'performance-ab-fixed-references-v1', 'Reference manifest schema')
    require(manifest.get('status') == 'PASS' and manifest.get('complete') is True
            and type(manifest.get('expected_entries')) is int and manifest['expected_entries'] == 12,
            'Reference generation is incomplete or the fixed 12-entry declaration differs')
    oracle = identities.check(manifest['reference_binary'], base)
    require(oracle['sha256'] == ORACLE_SHA, 'Saved de70 oracle required; product/head reference forbidden')
    refs, names, groups = {}, set(), {}
    entries = manifest['entries']
    require(isinstance(entries, list) and len(entries) == manifest['expected_entries'],
            'Reference entry count is incomplete; all 12 entries are required')
    for entry in entries:
        require(isinstance(entry.get('id'), str) and entry['id'] not in names, 'Duplicate/missing reference ID')
        names.add(entry['id'])
        input_id = identities.check(entry['input'], base)
        raw = identities.check(entry['raw'], base)
        mapped = identities.check(entry['map'], base)
        logged = identities.check(entry['oracle_log'], base)
        info = validator.wav_info(Path(input_id['path']))
        require(info['rate'] == 48000 and info['channels'] in (1, 2) and info['encoding'] == 3
                and info['bits'] == 32 and info['frames'] == 14400000, 'Expected 300s 48k Float32 reference input')
        speed = entry['speed_micros']
        require(type(speed) is int and speed in (400000, 1000000, 2000000)
                and entry['preset'] == 'candidate', 'Reference speed/preset outside declared matrix')
        queries, selected, command = entry['queries'], entry['input_positions'], entry['command']
        require(isinstance(queries, list) and len(queries) == len(set(queries))
                and all(type(q) is int and 0 <= q <= info['frames'] for q in queries), 'Independent queries')
        require(isinstance(selected, list) and len(selected) == 2 and selected[0] < selected[1]
                and all(type(q) is int and q in queries for q in selected), 'Selected independent [A,B] queries')
        require(isinstance(command, list) and len(command) == 5 + len(queries)
                and all(isinstance(x, str) for x in command), 'Saved full oracle command')
        for actual, target in ((command[0], oracle['path']), (command[1], input_id['path']), (command[4], raw['path'])):
            require(Path(actual).resolve() == Path(target), 'Oracle command file binding')
        require(command[2:4] == [str(speed), 'candidate'] and command[5:] == [str(q) for q in queries], 'Oracle command speed/preset/all queries')
        require(type(entry['returncode']) is int and entry['returncode'] == 0 and entry['timeout'] is False,
                'Reference generation did not finish successfully')
        candidates = []
        for line in Path(logged['path']).read_text().splitlines():
            if line.lstrip().startswith('{'):
                obj = loads(line)
                if isinstance(obj, dict) and 'output_frames' in obj:
                    candidates.append(obj)
        require(len(candidates) == 1, 'Expected exactly one saved oracle metadata object')
        full, meta = candidates[0], read(mapped['path'])
        frames = (info['frames'] * 1000000 + speed // 2) // speed
        for field, value in (('channels', info['channels']), ('rate', 48000), ('input_frames', info['frames']),
                             ('output_frames', frames), ('sha256', raw['sha256'])):
            require(full.get(field) == meta.get(field) == value, 'Oracle log/map field mismatch: ' + field)
        positions = full['positions']
        require(isinstance(positions, list) and len(positions) == len(queries)
                and all(type(q) is int and 0 <= q <= frames for q in positions), 'Full oracle output queries')
        require(meta.get('input_positions') == selected and meta.get('positions') ==
                [positions[queries.index(q)] for q in selected], 'Map is not the exact independent query slice')
        require(raw['bytes'] == frames * info['channels'] * 4, 'Reference RAW length/channel mismatch')
        if 'input_sha256' in meta:
            require(meta['input_sha256'] == input_id['sha256'], 'Map input SHA')
        if 'generation_expected' in entry:
            original_id = identities.check(entry['generation_expected'], base)
            original = read(original_id['path'])
            require(original.get('command') == command and original.get('input_positions') == queries,
                    'Original generation EXPECTED command/queries differ')
            require(original['input']['sha256'] == input_id['sha256'] and original['oracle']['sha256'] == ORACLE_SHA,
                    'Original generation input/oracle binding')
        key = (input_id['sha256'], speed, tuple(selected))
        require(key not in refs, 'Ambiguous duplicate reference key')
        refs[key] = {'entry_id': entry['id'], 'input': input_id, 'raw': raw, 'map': mapped,
                     'oracle_log': logged, 'oracle': oracle, 'queries': queries, 'input_positions': selected}
        group = (input_id['sha256'], speed)
        witness = (raw['sha256'], logged['sha256'], tuple(queries), tuple(positions))
        if group not in groups:
            groups[group] = {'witness': witness, 'selected': set()}
        require(groups[group]['witness'] == witness, 'Same input/speed has conflicting RAW/log/query witnesses')
        groups[group]['selected'].update(selected)
    for group in groups.values():
        require(group['selected'] == set(group['witness'][2]), 'Some independent oracle queries have no exact map slice')
    return refs


def run_manifest(path, suite, args, identities, host_manifests):
    expected_path, summary_path = path / 'EXPECTED.json', path / 'SUMMARY.json'
    identities.identity(expected_path)
    identities.identity(summary_path)
    expected, summary = read(expected_path), read(summary_path)
    fixed = matrix(suite)
    require(expected.get('baseline_source') == args.baseline_source and expected.get('candidate_source') == args.candidate_source,
            'Run old/candidate source identity differs')
    require(expected.get('expected_programs') == len(fixed), 'Run expected program count differs')
    jobs = expected['jobs']
    ids = [job['id'] for job in jobs]
    require(len(ids) == len(set(ids)) == len(fixed) and set(ids) == set(fixed), 'Run missing/duplicate/unexpected fixed IDs')
    if 'all_expected_ids' in expected:
        require(len(expected['all_expected_ids']) == len(set(expected['all_expected_ids'])) == len(fixed)
                and set(expected['all_expected_ids']) == set(fixed), 'Run all_expected_ids declaration differs')
    rows = summary['rows']
    got = [row['id'] for row in rows]
    require(summary.get('complete') is True and summary.get('executed_programs') == len(fixed)
            and len(got) == len(set(got)) == len(fixed) and set(got) == set(fixed),
            'Native fixed ID set is incomplete/partial/duplicate')
    require(not summary.get('errors'), 'Native run collection errors')
    baseline_id = identities.check(expected['records']['baseline_client'], path)
    build_id = identities.check(expected['records']['candidate_build'], path)
    baseline, build = read(baseline_id['path']), read(build_id['path'])
    require(baseline.get('status') == build.get('status') == 'PASS'
            and baseline.get('baseline_source') == args.baseline_source
            and build.get('source') == args.candidate_source, 'Saved build/client source identity differs')
    hosts = {version: identities.check(expected['hosts'][version], path) for version in ('old', 'candidate')}
    standard_hosts = {'old': baseline['clients']['ab']['binary'],
                      'candidate': build['binaries']['progressive_adoption_ab_native']}
    standard = all(hosts[version]['sha256'] == standard_hosts[version]['sha256']
                   and hosts[version]['bytes'] == standard_hosts[version]['bytes'] for version in hosts)
    matching_manifests = [item for item in host_manifests
                          if all(item['hosts'][version]['sha256'] == hosts[version]['sha256'] for version in hosts)]
    if 'observation_clients' in expected:
        record_id = identities.check(expected['observation_clients'], path)
        require(any(item['identity']['sha256'] == record_id['sha256'] for item in matching_manifests),
                'Supply the exact observation manifest with --host-manifest')
    require(standard or matching_manifests, 'Neither saved standard build/client nor supplied observation manifest matches BOTH hosts')
    for item in matching_manifests:
        require(item['baseline_client']['sha256'] == baseline_id['sha256']
                and item['candidate_build']['sha256'] == build_id['sha256'], 'Observation client underlying build provenance differs')
    recovery = expected.get('recovery')
    if recovery is not None:
        require(suite == 'main72' and recovery['schema'] == 'disk-preplay-recovery-v1'
                and recovery['new_programs'] == 2 and recovery['retained_programs'] == 70
                and recovery['continuous72_new_run'] is False, 'explicit recovery scope')
        original_path = Path(identities.check(recovery['original_summary'], path)['path'])
        original = read(original_path)
        previous = {row['id']: row for row in original['rows']}
        require(len(previous) == 72 and len(set(recovery['reused_ids'])) == 70
                and len(set(recovery['new_execution_ids'])) == 2
                and set(recovery['reused_ids']).isdisjoint(recovery['new_execution_ids'])
                and set(recovery['reused_ids'] + recovery['new_execution_ids']) == set(fixed), 'recovery72 partition')
        identities.check(recovery['original_expected'], path)
        devices = {row['summary']['device'] for row in rows}
        require(devices == {recovery['retained_device']}, 'same actual device in retained70 and new2')
        for row in rows:
            if row['id'] in recovery['reused_ids']:
                require({k:v for k,v in row.items() if k != 'retained_from'} == previous[row['id']]
                        and row['retained_from'] == recovery['original_summary'], 'retained row changed')
            else:
                old = previous[row['id']]
                identities.check(old['execution']['log'], path)
                require(old['execution']['returncode'] == 1 and not old['execution']['timeout'] and not old['execution']['interrupted']
                        and Path(old['execution']['log']['path']).read_text().strip() == '一時入力複製の空き容量が不足しています', 'recover only preplay disk rejection')
    row_by_id = {row['id']: row for row in rows}
    result = []
    for job in jobs:
        target = fixed[job['id']]
        for key in ('input', 'A_seconds', 'preset', 'repeat', 'version', 'pair_id', 'mode', 'lead_ms'):
            require(job.get(key) == target[key], 'Run job condition mismatch: ' + job['id'] + '/' + key)
        command = job['command']
        require(len(command) == 11 and all(isinstance(x, str) for x in command), 'AB host command must have 11 elements')
        input_id = identities.check(expected['inputs'][target['input']], path)
        host = hosts[target['version']]
        capture = path / job['id']
        if recovery is not None and job['id'] in recovery['reused_ids']:
            capture = original_path.parent / job['id']
            require(job.get('capture_directory') == str(capture), 'retained capture origin must remain explicit')
        else:
            require('capture_directory' not in job, 'unexpected capture origin override')
        for actual, desired in ((command[0], host['path']), (command[1], input_id['path']), (command[9], str(capture.resolve()))):
            require(Path(actual).resolve() == Path(desired), 'Native command executable/input/output binding')
        mode = target['mode'] if target['mode'] in ('fresh', 'prewarm') else 'early_on'
        require(command[2] == 'candidate' and number(command[3]) == target['A_seconds']
                and number(command[4]) == Decimal('.1') and number(command[5]) * 1000000 == target['speed_micros']
                and command[6:9] == [mode, 'Playing', '0'] and number(command[10]) == target['lead_ms'],
                'Native CLI conditions differ from fixed matrix')
        row = row_by_id[job['id']]
        execution = row['execution']
        native_rt = row['summary'].get('rt_pass')
        # hostのexit2は明示RT違反。完了したPCM品質をRT判定へ結合しない。
        require(type(native_rt) is bool and type(execution['returncode']) is int
                and execution['returncode'] == (0 if native_rt else 2)
                and execution['timeout'] is False and execution.get('interrupted') is False,
                'Native exit/RT mismatch, timeout or interruption: ' + job['id'])
        require(row.get('integrity_pass') is True, 'Native capture integrity prerequisite failed: ' + job['id'])
        artifact_map = {}
        for record in row['artifacts']:
            item_path = Path(record['path']).resolve()
            require(str(item_path) not in artifact_map, 'Duplicate native artifact identity')
            artifact_map[str(item_path)] = record
        for name in CAPTURE_FILES:
            record = artifact_map.get(str((capture / name).resolve()))
            require(record is not None, 'Native artifact was not recorded: ' + job['id'] + '/' + name)
            identities.check(record, path)
        declared, native = read(capture / 'EXPECTED.json'), read(capture / 'SUMMARY.json')
        a, b = rounded_frames(command[3]), rounded_frames(command[3]) + rounded_frames(command[4])
        require(declared.get('A') == a and declared.get('B') == b and declared.get('mode') == mode
                and declared.get('state') == 'Playing' and declared.get('requested_C') == 0
                and declared.get('seek_checkpoints') is False, 'Capture EXPECTED does not match the native job')
        require(native == row['summary'] and native.get('input_sha256') == input_id['sha256'], 'Native summary copy/input binding differs')
        for name in ('raw_records.jsonl', 'spans.jsonl'):
            with (capture / name).open() as stream:
                count = sum(1 for _ in stream)
            require(0 < count <= 8192, 'BLOCKED: unchanged independent validator requires 1..8192 records: '
                    + job['id'] + '/' + name + '=' + str(count))
        key = (input_id['sha256'], target['speed_micros'], (a, b))
        result.append({'id': suite + '/' + job['id'], 'job': job, 'capture': str(capture.resolve()),
                       'host_binary': host, 'input': input_id, 'reference_key': key,
                       'native_rt_reported': native.get('rt_pass'),
                       'native_performance_reported': native.get('performance_pass')})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--main-run', type=Path)
    parser.add_argument('--nonfresh-run', type=Path)
    parser.add_argument('--references', type=Path, required=True)
    parser.add_argument('--host-manifest', type=Path, action='append', default=[])
    parser.add_argument('--candidate-source', required=True)
    parser.add_argument('--baseline-source', default=BASELINE_SOURCE)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(args.main_run or args.nonfresh_run, 'At least one complete fixed suite is required')
    require(len(args.candidate_source) == 64 and all(c in '0123456789abcdef' for c in args.candidate_source), 'Candidate source SHA-256')
    out = args.output.resolve()
    require(out.is_relative_to(ROOT / 'build'), 'Audit outputs belong under build/')
    out.mkdir(parents=True, exist_ok=False)
    suites = [(name, path.resolve()) for name, path in (('main72', args.main_run), ('nonfresh36', args.nonfresh_run)) if path]
    fixed_ids = [suite + '/' + name for suite, _ in suites for name in matrix(suite)]
    identities = Identities()
    expected = {'schema': 'performance-ab-capture-batch-v1', 'expected_programs': len(fixed_ids),
                'expected_checks': 5 * len(fixed_ids), 'all_expected_ids': fixed_ids, 'required_check_ids': list(CHECK_IDS),
                'candidate_source': args.candidate_source, 'baseline_source': args.baseline_source,
                'run_directories': {suite: str(path) for suite, path in suites},
                'references': str(args.references.resolve()), 'host_manifests': [str(p.resolve()) for p in args.host_manifest],
                'validator_required_sha256': VALIDATOR_SHA, 'oracle_required_sha256': ORACLE_SHA,
                'equations_required_sha256': EQUATIONS_SHA,
                'hash_reuse': 'This batch process only; same stat before/after; every capture numerical comparison is executed.',
                'python': sys.version, 'platform': platform.platform(),
                'performance_status': 'NOT_ASSESSED', 'realtime_status': 'NOT_ASSESSED',
                'physical_audio_continuity_verified': None, 'application_F': None, 'public_approved': False}
    save(out / 'EXPECTED.json', expected)
    rows, error = [], None
    try:
        expected['driver'] = identities.identity(__file__)
        expected['validator'] = identities.identity(VALIDATOR)
        require(expected['validator']['sha256'] == VALIDATOR_SHA, 'Independent validator source changed')
        require(identities.identity(EQUATIONS)['sha256'] == EQUATIONS_SHA, 'Independent boundary helper changed')
        spec = importlib.util.spec_from_file_location('performance_independent_capture_validator', VALIDATOR)
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        # 同一run内のhashのみ共有する。全stat検査・pcm()/equal()/境界数式は元validatorをそのまま使う。
        validator.identity = identities.identity
        expected['reference_manifest'] = identities.identity(args.references)
        references = load_references(args.references.resolve(), identities, validator)
        manifests = []
        for path in args.host_manifest:
            item_id = identities.identity(path)
            item = read(path)
            require(item.get('schema') == 'performance-ab-observation-clients-v1' and item.get('status') == 'PASS',
                    'Expected PASS bounded observation-client manifest')
            require(item.get('baseline_source') == args.baseline_source and item.get('candidate_source') == args.candidate_source,
                    'Observation manifest old/candidate source binding')
            require(set(item['clients']) == {'old', 'candidate'}, 'Both observation clients required')
            hosts = {version: identities.check(item['clients'][version]['binary'], path.parent) for version in ('old', 'candidate')}
            for version, source, contract in (('old', args.baseline_source, 3), ('candidate', args.candidate_source, 4)):
                require(item['clients'][version].get('source') == source
                        and item['clients'][version].get('contract_version') == contract, 'Observation version/source/ABI binding')
            for key in ('common_client', 'common_capture_source', 'observation_diff'):
                identities.check(item[key], path.parent)
            manifests.append({'identity': item_id, 'hosts': hosts,
                              'baseline_client': identities.check(item['baseline_client'], path.parent),
                              'candidate_build': identities.check(item['candidate_build'], path.parent)})
        jobs = []
        for suite, path in suites:
            jobs.extend(run_manifest(path, suite, args, identities, manifests))
        require(set(job['id'] for job in jobs) == set(fixed_ids) and len(jobs) == len(fixed_ids), 'Fixed batch ID set')
        for job in jobs:
            key = job.pop('reference_key')
            require(key in references, 'Missing exact input/speed/A/B frozen reference: ' + job['id'])
            job['reference'] = references[key]
        expected['jobs'] = jobs
        save(out / 'EXPECTED.json', expected)
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
            summary = read(child_out / 'SUMMARY.json')
            checks = summary.get('checks', {})
            passed = (code == 0 and summary.get('status') == 'PASS' and summary.get('run_complete') is True
                      and summary.get('expected') == summary.get('executed') == summary.get('passed') == 5
                      and set(checks) == set(CHECK_IDS) and all(checks[k].get('status') == 'PASS' for k in CHECK_IDS)
                      and summary.get('validator_sha256') == VALIDATOR_SHA)
            rows.append({'id': job['id'], 'status': 'PASS' if passed else 'FAIL', 'validator_exit': code,
                         'wall_s': time.monotonic() - begin, 'expected_checks': 5, 'passed_checks': summary.get('passed', 0),
                         'executed_checks': summary.get('executed', 0),
                         'failed_checks': sum(check.get('status') == 'FAIL' for check in checks.values()),
                         'incomplete_checks': sum(check.get('status') == 'INCOMPLETE' for check in checks.values()),
                         'reason': summary.get('reason'), 'native_rt_reported': job['native_rt_reported'],
                         'native_performance_reported': job['native_performance_reported'],
                         'summary': identities.identity(child_out / 'SUMMARY.json'),
                         'expected': identities.identity(child_out / 'EXPECTED.json')})
            save(out / 'PROGRESS.json', {'status': 'IN_PROGRESS', 'expected_programs': len(fixed_ids),
                                        'executed_programs': len(rows), 'rows': rows})
            print(job['id'], rows[-1]['status'], flush=True)
        identities.unchanged()
    except (Exception, KeyboardInterrupt) as failure:
        error = type(failure).__name__ + ': ' + str(failure)
    completed = len(rows) == len(fixed_ids) and error is None
    good = completed and all(row['status'] == 'PASS' for row in rows)
    result = {'schema': 'performance-ab-capture-batch-summary-v1',
              'status': 'PASS' if good else ('BLOCKED' if not rows else 'FAIL_OR_INCOMPLETE'),
              'run_complete': completed, 'expected_programs': len(fixed_ids), 'executed_programs': len(rows),
              'passed_programs': sum(row['status'] == 'PASS' for row in rows),
              'expected_checks': len(fixed_ids) * 5, 'executed_checks': sum(row['executed_checks'] for row in rows),
              'passed_checks': sum(row['passed_checks'] for row in rows),
              'failed_checks': sum(row['failed_checks'] for row in rows),
              'incomplete_checks': sum(row['incomplete_checks'] for row in rows) + (len(fixed_ids) - len(rows)) * 5,
              'all_expected_ids': fixed_ids, 'executed_ids': [row['id'] for row in rows], 'rows': rows,
              'reason': error, 'hash_unique_files': len(identities.values), 'hash_cache_hits': identities.hits,
              'expected_sha256': sha(out / 'EXPECTED.json'), 'driver_sha256': sha(__file__),
              'performance_status': 'NOT_ASSESSED', 'realtime_status': 'NOT_ASSESSED',
              'physical_audio_continuity_verified': None, 'application_F': None, 'public_approved': False,
              'PASS_scope': 'Independent captured PCM/coordinate/configuration audit only; prior native RT/latency are separate.'}
    save(out / 'SUMMARY.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'expected_programs', 'executed_programs', 'passed_checks', 'reason')}, ensure_ascii=False))
    return 0 if good else 2


if __name__ == '__main__':
    raise SystemExit(main())
