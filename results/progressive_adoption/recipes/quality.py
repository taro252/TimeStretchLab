#!/usr/bin/env python3
"""保存された独立全曲参照を使うFastLocal品質検査。参照は生成しない。

known26: 26既知失敗条件+8成功対照、既定3反復=102件。
long: 旧mono1080件+stereo360件。short: 旧9素材648件。
--partition SOURCE は宣言した部分だけを実施し、全suite完了とは記録しない。
--mode local|local-v2 はstudyへ明示する。headは受け付けない。
--plan-only は容量とIDの宣言だけ、--preflight-only は現SHA監査まで。
両モードはPASSにならない。品質閾値失敗はQUALITY_FAIL/exit 2。
BLOCKED/FAIL/INCOMPLETEはexit 3。出力先は必ず新規、RAWを保持する。
"""
import argparse
import collections
import datetime
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PLAN_PATH = HERE / 'quality_plan.json'
MAX_LOG_BYTES = 32 * 1024 * 1024


class Blocked(RuntimeError):
    pass


def require(ok, why):
    if not ok:
        raise Blocked(why)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stamp(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                   allow_nan=False) + '\n')
    temporary.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def git_identity(root):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args],
                                       stderr=subprocess.PIPE)
    paths = ['src', 'include', 'tests', 'CMakeLists.txt']
    changes = git('diff', '--no-ext-diff', '--binary', 'HEAD', '--', *paths)
    untracked = {}
    for name in git('ls-files', '--others', '--exclude-standard', '-z', '--',
                    *paths).decode().split('\0'):
        if name:
            untracked[name] = sha(root / name)
    return {'root': str(root), 'HEAD': git('rev-parse', 'HEAD').decode().strip(),
            'status_porcelain': git('status', '--porcelain=v1').decode(),
            'source_diff_sha256': hashlib.sha256(changes).hexdigest(),
            'untracked_source_sha256': untracked}


def same_source(a, b):
    return all(a[k] == b[k] for k in
               ('HEAD', 'source_diff_sha256', 'untracked_source_sha256'))


class Audit:
    def __init__(self, root, plan):
        self.root, self.plan = root, plan
        self.files = {}
        self.artifacts = {}

    def relative(self, old_path):
        p = Path(old_path)
        if not p.is_absolute():
            require('..' not in p.parts, f'Unsafe relative path: {p}')
            return p
        try:
            return p.relative_to(self.plan['original_root'])
        except ValueError as error:
            raise Blocked(f'Historical path outside declared root: {p}') from error

    def path(self, old_path):
        return self.root / self.relative(old_path)

    def pin(self, path, digest, role, verify=True):
        path = Path(path).absolute()
        require(path.is_file(), f'Missing {role}: {path}')
        key = str(path)
        if key in self.files:
            item = self.files[key]
            require(item['expected_sha256'] == digest, f'Conflicting SHA: {path}')
            if verify and not item['verified']:
                require(sha(path) == digest, f'SHA mismatch {role}: {path}')
                item['verified'] = True
            require(stamp(path) == item['stat'], f'Changed during preflight: {path}')
            return item
        before = stamp(path)
        actual = sha(path) if verify else None
        item = {'path': key, 'bytes': before[2], 'expected_sha256': digest,
                'sha256': actual, 'verified': verify and actual == digest,
                'role': role, 'stat': before}
        self.files[key] = item
        require(not verify or actual == digest, f'SHA mismatch {role}: {path}')
        require(stamp(path) == before, f'Changed while hashing: {path}')
        return item

    def artifact(self, old_path, role, verify=True):
        relative = self.relative(old_path)
        key = str(Path(self.plan['original_root']) / relative)
        require(key in self.artifacts, f'Artifact absent from fixed inventory: {key}')
        entry = self.artifacts[key]
        item = self.pin(self.root / relative, entry['sha256'], role, verify)
        require(item['bytes'] == entry['bytes'], f'Artifact size mismatch: {key}')
        return item

    def unchanged(self):
        return [key for key, item in self.files.items()
                if not Path(key).is_file() or stamp(key) != item['stat']]


def inner_name(case):
    return (f"{case['speed']}_{case['preset']}_{case['preroll']}_"
            f"{case['input']}_{case['repeat']}")


def make_cases(plan, suite, repeats, partition='all'):
    group_keys = ['chain'] if suite == 'known26' else (
        ['chain', 'music'] if suite == 'long' else ['short'])
    sources = {s['name']: dict(s, group=g)
               for g in group_keys for s in plan['groups'][g]['sources']}
    require(partition == 'all' or partition in sources,
            f'Unknown partition {partition}; choose all or {list(sources)}')
    cases = []
    for source, spec in sources.items():
        if partition != 'all' and partition != source:
            continue
        if suite == 'known26':
            points = [(p, 'known_failure') for p in
                      plan['known_failures_speed_preroll_input']]
            points += [(p, 'success_control') for p in
                       plan['success_controls_speed_preroll_input']]
        else:
            points = [((speed, warm, at), 'matrix') for speed, warm, at in
                      itertools.product(plan['speeds'], spec['prerolls'],
                                        spec['positions'])]
        for (speed, warm, at), role in points:
            for preset, repeat in itertools.product(('candidate', 'baseline'),
                                                     range(repeats)):
                c = {'source': source, 'group': spec['group'], 'speed': speed,
                     'preroll': warm, 'input': at, 'preset': preset,
                     'repeat': repeat, 'role': role}
                c['name'] = inner_name(c)
                c['id'] = source + '/' + c['name']
                cases.append(c)
    ids = [c['id'] for c in cases]
    require(len(ids) == len(set(ids)) and bool(ids), 'Duplicate/empty fixed plan')
    return cases, sources


def integer(value):
    return type(value) is int


def wav_shape(path):
    # Only read RIFF headers; no decode or resampling.
    with path.open('rb') as stream:
        header = stream.read(12)
        require(len(header) == 12 and header[:4] == b'RIFF' and
                header[8:] == b'WAVE', f'Unsupported WAV: {path}')
        fmt = data = None
        while True:
            chunk = stream.read(8)
            if not chunk:
                break
            require(len(chunk) == 8, f'Truncated WAV header: {path}')
            name, n = chunk[:4], struct.unpack('<I', chunk[4:])[0]
            start = stream.tell()
            require(start + n <= path.stat().st_size, f'Truncated WAV chunk: {path}')
            if name == b'fmt ':
                payload = stream.read(min(n, 40))
                require(len(payload) >= 16, 'Short fmt')
                encoding, channels, rate, _, align, bits = struct.unpack('<HHIIHH', payload[:16])
                require(encoding in (1, 3) and align == channels * bits // 8,
                        f'Unsupported WAV encoding: {path}')
                fmt = (rate, channels, align)
            elif name == b'data':
                require(data is None, 'Multiple data chunks')
                data = n
            stream.seek(start + n + n % 2)
        require(fmt is not None and data is not None and data % fmt[2] == 0,
                f'Incomplete WAV: {path}')
        return fmt[0], fmt[1], data // fmt[2]


def preflight(audit, plan, cases, sources, full_hash):
    inventory = audit.root / plan['artifact_manifest']
    audit.pin(inventory, plan['artifact_manifest_sha256'], 'fixed artifact inventory')
    inv = read_json(inventory)
    entries = inv['files']
    require(len({x['path'] for x in entries}) == len(entries), 'Duplicate inventory paths')
    audit.artifacts = {x['path']: x for x in entries}
    audit.pin(audit.root / plan['oracle'], plan['oracle_sha256'], 'independent frozen oracle')
    audit.pin(audit.root / plan['historical_binary'],
              plan['historical_binary_sha256'], 'historical study binary')
    audit.pin(audit.root / plan['metrics_driver'], plan['metrics_driver_sha256'],
              'fixed Python numerical validator')
    source_names = {c['source'] for c in cases}
    for name in source_names:
        s = sources[name]
        audit.pin(audit.root / s['path'], s['sha256'], 'input ' + name, full_hash)
        if full_hash:
            require(wav_shape(audit.root / s['path']) ==
                    (s['rate'], s['channels'], s['frames']), f'WAV shape: {name}')
    historical = {}
    command_tables = {}
    for group in sorted({c['group'] for c in cases}):
        cfg = plan['groups'][group]
        directory = audit.root / cfg['directory']
        for filename in ('manifest.json', 'commands.json', 'rows.jsonl'):
            key = filename.split('.')[0] + '_sha256'
            audit.pin(directory / filename, cfg[key], 'historical ' + group + ' ' + filename)
        manifest = read_json(directory / 'manifest.json')
        require(manifest['binary_sha256'] == plan['historical_binary_sha256'] and
                manifest['reference_sha256'] == plan['oracle_sha256'] and
                manifest['screening_thresholds'] == plan['thresholds'] and
                manifest['speeds'] == plan['speeds'], 'Historical manifest contract: ' + group)
        audit.pin(audit.root / cfg['historical_driver'], cfg['historical_driver_sha256'],
                  'historical driver ' + group)
        require(manifest['driver_sha256'] == cfg['historical_driver_sha256'],
                'Historical driver binding: ' + group)
        require(audit.relative(manifest['binary']) == Path(plan['historical_binary']) and
                audit.relative(manifest['reference']) == Path(plan['oracle']),
                'Historical executable paths: ' + group)
        for spec in cfg['sources']:
            ms = [s for s in manifest['sources'] if Path(s['path']).stem == spec['name']]
            require(len(ms) == 1, 'Historical source count')
            require(all(ms[0][k] == spec[k] for k in ('sha256', 'rate', 'channels', 'frames'))
                    and audit.relative(ms[0]['path']) == Path(spec['path']),
                    'Historical input binding: ' + spec['name'])
        rows = [json.loads(line) for line in (directory / 'rows.jsonl').read_text().splitlines()]
        old_ids = [r['source'] + '/' + r['name'] for r in rows]
        old_suite = 'long' if group != 'short' else 'short'
        old_cases, _ = make_cases(plan, old_suite, cfg['historical_repeats'])
        required = {c['id'] for c in old_cases if c['group'] == group}
        require(len(rows) == cfg['historical_cases'] and len(set(old_ids)) == len(rows)
                and set(old_ids) == required, 'Historical complete ID set: ' + group)
        require(sum(not r['metrics']['screen_pass'] for r in rows) ==
                cfg['historical_failures'], 'Historical quality count: ' + group)
        for row in rows:
            uid = row['source'] + '/' + row['name']
            require(uid not in historical, 'Duplicate historical case')
            historical[uid] = row
        commands = read_json(directory / 'commands.json')
        require(len({c['name'] for c in commands}) == len(commands), 'Duplicate old command')
        command_tables[group] = {c['name']: c for c in commands}
        for spec in cfg['sources']:
            command = command_tables[group][spec['name'] + '_local']
            args = command['command']
            require(command['exit'] == 0 and len(args) == 9 and
                    audit.relative(args[0]) == Path(plan['historical_binary']) and
                    audit.relative(args[1]) == Path(spec['path']) and
                    args[3] == ','.join(map(str, plan['speeds'])) and
                    args[4] == ','.join(map(str, spec['prerolls'])) and
                    args[5] == ','.join(map(str, spec['positions'])) and
                    args[6:] == [str(spec['rate']), str(cfg['historical_repeats']), 'local'],
                    'Historical local command contract: ' + spec['name'])
            audit.artifact(command['stdout'], 'historical local log')
            audit.artifact(command['stderr'], 'historical local stderr')
            logged = [json.loads(x) for x in audit.path(command['stdout']).read_text().splitlines()]
            old_source = {r['name']: r for r in rows if r['source'] == spec['name']}
            require(len(logged) == len(old_source) and len({r['name'] for r in logged}) == len(logged),
                    'Historical local log count')
            for r in logged:
                require(r['name'] in old_source and
                        all(old_source[r['name']].get(k) == v for k, v in r.items()),
                        'Historical log/rows mismatch')
    references = {}
    for name, speed, preset in sorted({(c['source'], c['speed'], c['preset']) for c in cases}):
        s = sources[name]
        key = (name, speed, preset)
        label = f'{name}_{speed}_{preset}_reference'
        command = command_tables[s['group']].get(label)
        require(command is not None and command['exit'] == 0, 'Missing successful reference command: ' + label)
        args = command['command']
        require(len(args) == 5 + len(s['positions']) and
                audit.relative(args[0]) == Path(plan['oracle']) and
                audit.relative(args[1]) == Path(s['path']) and
                args[2:4] == [str(speed), preset] and
                args[5:] == list(map(str, s['positions'])), 'Independent reference command: ' + label)
        audit.artifact(command['stdout'], 'independent reference map log')
        audit.artifact(command['stderr'], 'independent reference stderr')
        meta = read_json(audit.path(command['stdout']))
        require(meta['input_frames'] == s['frames'] and meta['rate'] == s['rate'] and
                meta['channels'] == s['channels'] and
                meta['output_frames'] == (s['frames'] * 1000000 + speed // 2) // speed and
                len(meta['positions']) == len(s['positions']) and
                all(integer(p) and 0 <= p <= meta['output_frames'] for p in meta['positions']),
                'Independent reference map shape: ' + label)
        artifact = audit.artifact(args[4], 'independent full RAW', full_hash)
        require(artifact['expected_sha256'] == meta['sha256'] and
                artifact['bytes'] == meta['output_frames'] * s['channels'] * 4,
                'Reference RAW/map identity: ' + label)
        references[key] = {'path': artifact['path'], 'sha256': meta['sha256'],
                           'output_frames': meta['output_frames'],
                           'positions': dict(zip(s['positions'], meta['positions'])),
                           'map_log': str(audit.path(command['stdout']))}
    for case in cases:
        old = historical[case['source'] + '/' + case['name'].rsplit('_', 1)[0] + '_0']
        ref = references[(case['source'], case['speed'], case['preset'])]
        s = sources[case['source']]
        at = ref['positions'][case['input']]
        captured = min(s['rate'], ref['output_frames'] - at)
        require(old['reference_pcm_sha256'] == ref['sha256'] and old['output_start'] == at and
                old['captured'] == captured and old['rate'] == s['rate'] and
                old['channels'] == s['channels'] and old['local'] is True and
                old['input_error_frames'] == old['output_gaps'] == old['output_duplicates'] == 0,
                'Historical row/reference coordinates: ' + case['id'])
        if case['role'] == 'known_failure':
            require(old['metrics']['screen_pass'] is False and
                    old['metrics']['screen_failures'] == ['weighted_spectral_error_db'],
                    'Known failure disappeared from pinned evidence')
        elif case['role'] == 'success_control':
            require(old['metrics']['screen_pass'] is True, 'Historical success control failed')
        case.update(output_start=at, captured=captured,
                    reference_sha256=ref['sha256'], historical_metrics=old['metrics'])
    return references


def jobs_for(cases, sources, binary, output, repeats, suite, mode):
    grouped = collections.defaultdict(list)
    for case in cases:
        # Known failures form a sparse union, never an enlarged Cartesian product.
        key = (case['source'], case['speed'], case['preroll']) if suite == 'known26' else (case['source'],)
        grouped[key].append(case)
    jobs = []
    for index, (key, subset) in enumerate(grouped.items()):
        source = sources[key[0]]
        speeds = sorted({c['speed'] for c in subset})
        warms = sorted({c['preroll'] for c in subset})
        positions = sorted({c['input'] for c in subset})
        require(len(subset) == len(speeds) * len(warms) * len(positions) * 2 * repeats,
                'Job would create an undeclared Cartesian product')
        folder = output / 'raw' / f'{index:02d}_{key[0]}'
        jobs.append({'index': index, 'output': str(folder), 'expected_ids': [c['id'] for c in subset],
                     'cases': subset, 'command': [str(binary), str(source['actual_path']),
                         str(folder), ','.join(map(str, speeds)), ','.join(map(str, warms)),
                         ','.join(map(str, positions)), str(source['rate']), str(repeats), mode]})
    return jobs


def validate_row(row, case, source, reference, folder, metrics, np, mode):
    require(row['name'] == case['name'] and row['candidate'] is (case['preset'] == 'candidate')
            and row['local'] is True, 'Case name/preset/mode')
    if 'local_policy' in row:
        require(row['local_policy'] == mode, 'Study local_policy/mode mismatch')
    values = {'speed': case['speed'], 'input': case['input'], 'repeat': case['repeat'],
              'preroll_input_frames': case['preroll'], 'rate': source['rate'],
              'channels': source['channels'], 'output_start': case['output_start'],
              'output_end': reference['output_frames'], 'captured': case['captured'],
              'input_error_frames': 0, 'output_gaps': 0, 'output_duplicates': 0}
    require(all(integer(row.get(k)) and row[k] == v for k, v in values.items()),
            'Independent coordinates/count/gaps/duplicates')
    require(integer(row.get('seed_input')) and 0 <= row['seed_input'] <= case['input'] and
            integer(row.get('begin_output')) and 0 <= row['begin_output'] <= case['output_start'],
            'Local seed bounds')
    require(type(row.get('ready_s')) in (int, float) and math.isfinite(row['ready_s']) and
            row['ready_s'] >= 0, 'Finite Ready time')
    raw = folder / (case['name'] + '.f32')
    require(raw.is_file() and raw.stat().st_size == case['captured'] * source['channels'] * 4,
            'Captured RAW exact byte length')
    actual = np.fromfile(raw, dtype='<f4').reshape(-1, source['channels']).astype(float)
    mm = np.memmap(reference['path'], dtype='<f4', mode='r').reshape(-1, source['channels'])
    expected = np.asarray(mm[case['output_start']:case['output_start'] + case['captured']], dtype=float)
    require(actual.shape == expected.shape and actual.size > 0 and
            bool(np.all(np.isfinite(actual))) and bool(np.all(np.isfinite(expected))),
            'All-channel finite/length check')
    result = metrics(actual, expected, source['rate'], case['source'])
    require(all(math.isfinite(v) for v in result.values() if type(v) in (int, float)),
            'Nonfinite numerical metric')
    window_sha = hashlib.sha256(expected.astype('<f4').tobytes()).hexdigest()
    del expected, mm
    return {'id': case['id'], 'structural_pass': True, 'quality_pass': result['screen_pass'],
            'source': case['source'], 'mode': mode, 'role': case['role'], 'preset': case['preset'],
            'preroll': case['preroll'], 'ready_s': row['ready_s'], 'raw': str(raw),
            'pcm_sha256': sha(raw), 'reference_pcm_sha256': reference['sha256'],
            'reference_window_sha256': window_sha, 'output_start': case['output_start'],
            'captured': case['captured'], 'channels': source['channels'], 'metrics': result}


def run_jobs(jobs, sources, references, args, metrics, np, output):
    results, commands, observed, errors = [], [], [], []
    for job in jobs:
        log = output / f"job_{job['index']:02d}.jsonl"
        err = output / f"job_{job['index']:02d}.stderr"
        record = {k: v for k, v in job.items() if k != 'cases'}
        start = time.monotonic()
        record.update(started_utc=utc(), exit=None, timeout=False)
        with log.open('xb') as stdout, err.open('xb') as stderr:
            try:
                run = subprocess.run(job['command'], stdout=stdout, stderr=stderr,
                                     timeout=args.timeout_seconds)
                record['exit'] = run.returncode
            except subprocess.TimeoutExpired:
                record['timeout'] = True
        record.update(wall_s=time.monotonic() - start, stdout=str(log), stderr=str(err),
                      stdout_sha256=sha(log), stderr_sha256=sha(err))
        commands.append(record)
        write_json(output / 'COMMANDS.json', commands)
        if record['timeout'] or record['exit'] != 0:
            errors.append(f"Job {job['index']} timeout/exit: {record['exit']}")
        try:
            require(log.stat().st_size <= MAX_LOG_BYTES, 'Host log exceeds bounded expected size')
            rows = [json.loads(line) for line in log.read_text().splitlines()]
            expected = {c['name']: c for c in job['cases']}
            require(all(isinstance(r, dict) and isinstance(r.get('name'), str) for r in rows),
                    'Host rows must be objects with string IDs')
            names = [r['name'] for r in rows]
            observed.extend(job['cases'][0]['source'] + '/' + name for name in names)
            require(len(names) == len(set(names)) and set(names) == set(expected),
                    f"Job {job['index']} incomplete/duplicate/unexpected IDs")
            folder = Path(job['output'])
            actual_files = {p.name for p in folder.iterdir()}
            require(actual_files == {name + '.f32' for name in expected},
                    'Missing/unexpected RAW files')
            for row in rows:
                case = expected[row['name']]
                try:
                    result = validate_row(row, case, sources[case['source']],
                                          references[(case['source'], case['speed'], case['preset'])],
                                          folder, metrics, np, args.mode)
                except (Blocked, ValueError, KeyError, OSError) as error:
                    result = {'id': case['id'], 'structural_pass': False,
                              'quality_pass': None, 'error': str(error)}
                results.append(result)
                with (output / 'ROWS.jsonl').open('a') as stream:
                    stream.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + '\n')
        except (Blocked, ValueError, KeyError, OSError) as error:
            errors.append(str(error))
        write_json(output / 'PROGRESS.json', {'jobs_finished': len(commands),
                   'jobs_expected': len(jobs), 'rows_validated': len(results), 'errors': errors})
        if record['timeout']:
            break
    return results, commands, observed, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--suite', choices=('known26', 'long', 'short'), required=True)
    parser.add_argument('--mode', choices=('local', 'local-v2'), default='local')
    parser.add_argument('--repeats', type=int)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--partition', default='all', help='all or a fixed input name')
    parser.add_argument('--timeout-seconds', type=float, default=600)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan-only', action='store_true', help='No large-file hashes and no DSP run')
    mode.add_argument('--preflight-only', action='store_true', help='Full identity audit; no DSP run')
    args = parser.parse_args()
    if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
        parser.error('--timeout-seconds must be finite and positive')
    if args.repeats is not None and args.repeats <= 0:
        parser.error('--repeats must be positive')
    output = args.output.resolve()
    require(not output.exists(), 'Output must be a new directory')
    output.mkdir(parents=True)
    expected = {'schema': 'progressive-adoption-quality-expected-v1', 'started_utc': utc(),
                'argv': sys.argv, 'suite': args.suite, 'partition': args.partition, 'mode': args.mode,
                'offline_only': True, 'reference_generation': 'NEVER',
                'PCM_domain': 'local RAW before publication fade and final gain 0.5',
                'subjective_listening': 'UNMEASURED'}
    summary = {'schema': 'progressive-adoption-quality-summary-v1', 'PASS': False,
               'status': 'BLOCKED', 'execution_complete': False, 'quality_status': 'UNMEASURED',
               'full_suite_complete': False, 'expected_count': None, 'observed_count': 0,
               'validated_count': 0, 'errors': []}
    audit = None
    try:
        plan = read_json(PLAN_PATH)
        repeats = args.repeats or plan['defaults'][args.suite + '_repeats']
        cases, sources = make_cases(plan, args.suite, repeats, args.partition)
        all_cases, _ = make_cases(plan, args.suite, repeats)
        ids = [c['id'] for c in cases]
        summary['expected_count'] = len(ids)
        expected.update(repeats=repeats, expected_ids=ids, expected_count=len(ids),
                        full_suite_expected_count=len(all_cases), cases=cases,
                        thresholds=plan['thresholds'], validator_sha256=sha(Path(__file__)),
                        plan_sha256=sha(PLAN_PATH), scope_complete=args.partition == 'all')
        # Only new local RAW is budgeted; every frozen full reference is read in place.
        raw_bytes = sum(sources[c['source']]['rate'] * sources[c['source']]['channels'] * 4 for c in cases)
        metadata_budget = len(cases) * 16384 + 8 * 1024 * 1024
        reserve = max(512 * 1024 * 1024, raw_bytes // 20)
        free = shutil.disk_usage(output).free
        expected['capacity'] = {'new_raw_bytes_upper_bound': raw_bytes,
             'new_reference_bytes': 0, 'metadata_bytes_budget': metadata_budget,
             'reserve_bytes': reserve, 'free_bytes_at_start': free,
             'required_free_bytes': raw_bytes + metadata_budget + reserve,
             'all_new_raw_retained': True, 'old_evidence_deleted': False}
        write_json(output / 'EXPECTED.json', expected)
        require(free >= raw_bytes + metadata_budget + reserve,
                'Insufficient free space for unchanged matrix and retained new RAW')
        root = args.source_root.resolve()
        binary = args.binary.resolve()
        audit = Audit(root, plan)
        require(binary.is_file() and os.access(binary, os.X_OK), 'Study binary missing/not executable')
        expected['binary'] = audit.pin(binary, sha(binary), 'tested study binary')
        expected['repo'] = git_identity(REPO)
        expected['source_root_repo'] = git_identity(root)
        audit.pin(Path(__file__), expected['validator_sha256'], 'this validator')
        audit.pin(PLAN_PATH, expected['plan_sha256'], 'fixed case plan')
        references = preflight(audit, plan, cases, sources, not args.plan_only)
        for spec in sources.values():
            spec['actual_path'] = str(root / spec['path'])
        jobs = jobs_for(cases, sources, binary, output, repeats, args.suite, args.mode)
        expected.update(inputs=sources, references=[dict(source=k[0], speed=k[1], preset=k[2], **v)
                        for k, v in references.items()], identities=list(audit.files.values()),
                        commands=[{k: v for k, v in j.items() if k != 'cases'} for j in jobs],
                        preflight_complete=not args.plan_only)
        # Rewritten once with independent positions and actual identities, before any DSP launch.
        write_json(output / 'EXPECTED.json', expected)
        if args.plan_only or args.preflight_only:
            summary.update(status='NOT_RUN' if args.plan_only else 'PREFLIGHT_ONLY',
                           preflight_complete=not args.plan_only, planned_jobs=len(jobs),
                           planned_new_raw_bytes=raw_bytes)
        else:
            import numpy as np
            module_spec = importlib.util.spec_from_file_location('fixed_quality_metrics', root / plan['metrics_driver'])
            module = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(module)
            require(module.SCREEN == plan['thresholds'], 'Numerical threshold drift')
            results, commands, observed, errors = run_jobs(jobs, sources, references, args,
                                                          module.metrics, np, output)
            missing = sorted(set(ids) - set(observed))
            unexpected = sorted(set(observed) - set(ids))
            duplicates = sorted(k for k, n in collections.Counter(observed).items() if n > 1)
            complete = (len(commands) == len(jobs) and not errors and not missing and
                        not unexpected and not duplicates and len(observed) == len(ids) and
                        all(c['exit'] == 0 and not c['timeout'] for c in commands))
            structural = len(results) == len(ids) and all(r['structural_pass'] for r in results)
            failures = [r['id'] for r in results if r.get('quality_pass') is False]
            repo_after, source_after = git_identity(REPO), git_identity(root)
            changed = audit.unchanged()
            source_unchanged = same_source(expected['repo'], repo_after) and same_source(expected['source_root_repo'], source_after)
            if changed or not source_unchanged:
                errors.append('Identity/source changed during run: ' + repr(changed))
                complete = False
            state = ('INCOMPLETE' if not complete else 'FAIL' if not structural else
                     'QUALITY_FAIL' if failures else 'PASS')
            valid = [r for r in results if r['structural_pass']]
            groups = []
            for key in sorted({(r['source'], r['preset'], r['preroll']) for r in valid}):
                rr = [r for r in valid if (r['source'], r['preset'], r['preroll']) == key]
                groups.append({'source': key[0], 'preset': key[1], 'preroll': key[2], 'cases': len(rr),
                               'quality_failed': sum(not r['quality_pass'] for r in rr),
                               'ready_p95_ms': float(np.percentile([r['ready_s'] * 1000 for r in rr], 95)),
                               'max_weighted_spectral_error_db': max(r['metrics']['weighted_spectral_error_db'] for r in rr)})
            summary.update(status=state, PASS=state == 'PASS', execution_complete=complete,
                           full_suite_complete=complete and args.partition == 'all',
                           structural_pass=structural, quality_status=('PASS' if not failures else 'FAIL')
                           if complete and structural else 'INCOMPLETE', observed_count=len(observed),
                           validated_count=len(results), structurally_valid_count=len(valid),
                           quality_passed=sum(r.get('quality_pass') is True for r in results),
                           quality_failed=len(failures), quality_failed_ids=failures,
                           missing_ids=missing, unexpected_ids=unexpected, duplicate_ids=duplicates,
                           not_validated_ids=sorted(set(ids) - {r['id'] for r in results}),
                           structural_failed_ids=[r['id'] for r in results if not r['structural_pass']],
                           changed_artifacts=changed,
                           errors=errors, jobs_expected=len(jobs), jobs_completed=len(commands),
                           source_unchanged=source_unchanged, artifact_unchanged=not changed,
                           repo_after=repo_after, source_root_repo_after=source_after, groups=groups)
    except (Blocked, OSError, ValueError, KeyError, TypeError, ImportError,
            subprocess.SubprocessError) as error:
        summary['errors'].append(str(error))
        summary['status'] = 'INCOMPLETE' if (output / 'COMMANDS.json').exists() else 'BLOCKED'
    finally:
        if audit is not None:
            expected['identities'] = list(audit.files.values())
        write_json(output / 'EXPECTED.json', expected)
        summary.update(completed_utc=utc(), expected_sha256=sha(output / 'EXPECTED.json'),
                       validator_sha256=sha(Path(__file__)), plan_sha256=sha(PLAN_PATH))
        write_json(output / 'SUMMARY.json', summary)
        print(json.dumps({k: summary.get(k) for k in ('status', 'PASS', 'execution_complete',
                         'full_suite_complete', 'expected_count', 'observed_count',
                         'quality_passed', 'quality_failed', 'errors')}, ensure_ascii=False))
    return 0 if summary['status'] in ('PASS', 'NOT_RUN', 'PREFLIGHT_ONLY') else (
        2 if summary['status'] == 'QUALITY_FAIL' else 3)


if __name__ == '__main__':
    raise SystemExit(main())
