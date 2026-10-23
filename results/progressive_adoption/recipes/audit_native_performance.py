#!/usr/bin/env python3
"""完了済みnative性能記録を読み取り監査する。音声/DSP/buildは実行しない。

入力: --run-dir DIR/{EXPECTED.json,EXECUTION.json,data/rows.jsonl}
出力: --output NEW_JSON（新規ファイルのみ）。標準ライブラリーのみ使用。
Ready 200msと機能/実時間の判定を分離し、品質PASSは決して生成しない。
"""
import argparse
import collections
import datetime
import hashlib
import itertools
import json
import math
from pathlib import Path
import struct
import sys

SPEEDS = (400000, 500000, 1000000, 2000000)
ZERO_SUFFIXES = ('missing', 'callback_deadlines', 'host_errors', 'sample_errors',
                 'hal_errors', 'worker_deadlines', 'callback_new', 'heap_calls', 'heap_frees')
DELTA_FIELDS = tuple('delta_' + key for key in ZERO_SUFFIXES)
LIFETIME_FIELDS = tuple('lifetime_' + key for key in ZERO_SUFFIXES)
TIME_FIELDS = ('accepted_ns', 'preparing_ns', 'fifo_ready_ns', 'switch_ns',
               'first_pcm_ns', 'hal_estimate_ns', 'analysis_ready_ns',
               'switch_ready_ns', 'transition_begin_ns', 'transition_end_ns')
INTEGER_FIELDS = ('speed', 'repeat', 'input', 'rate', 'channels', 'output', 'epoch',
                  'peak_rss', 'device', 'device_buffer', 'old_fifo_at_switch',
                  'discarded_for_seek', 'transition_frames') + TIME_FIELDS + DELTA_FIELDS + LIFETIME_FIELDS
FLOAT_FIELDS = ('ready_ms', 'first_pcm_ms', 'device_rate')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(path):
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def identity(path):
    before = snapshot(path)
    digest = sha(path)
    if snapshot(path) != before:
        raise RuntimeError('File changed while hashing: ' + str(path))
    return {'path': str(path), 'bytes': before[2], 'sha256': digest, 'stat': list(before)}


def strict_key(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    speed, candidate, repeat, at = value
    if not (type(speed) is int and type(candidate) is bool and
            type(repeat) is int and type(at) is int):
        return None
    return speed, candidate, repeat, at


def row_key(row):
    return strict_key([row.get(k) for k in ('speed', 'candidate', 'repeat', 'input')])


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * q
    left = int(math.floor(position))
    right = min(left + 1, len(values) - 1)
    return values[left] + (position - left) * (values[right] - values[left])


def distribution(values):
    return {'count': len(values), 'p50_ms': quantile(values, 0.5),
            'p95_ms': quantile(values, 0.95), 'max_ms': max(values) if values else None}


def floating_errors(value, prefix=''):
    errors = []
    if isinstance(value, dict):
        for key, child in value.items():
            errors.extend(floating_errors(child, prefix + '.' + key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(floating_errors(child, prefix + '[' + str(index) + ']'))
    elif type(value) is float and not math.isfinite(value):
        errors.append(prefix)
    return errors


def json_safe(value):
    # Keep failed/nonfinite measurements diagnosable in strict JSON output.
    if type(value) is float and not math.isfinite(value):
        return {'nonfinite': repr(value)}
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def wav_shape(path):
    with path.open('rb') as stream:
        head = stream.read(12)
        if len(head) != 12 or head[:4] != b'RIFF' or head[8:] != b'WAVE':
            raise ValueError('Unsupported WAV header')
        fmt = data = None
        while True:
            chunk = stream.read(8)
            if not chunk:
                break
            if len(chunk) != 8:
                raise ValueError('Truncated chunk')
            kind, count = chunk[:4], struct.unpack('<I', chunk[4:])[0]
            start = stream.tell()
            if start + count > path.stat().st_size:
                raise ValueError('Truncated WAV payload')
            if kind == b'fmt ':
                b = stream.read(min(count, 40))
                if len(b) < 16:
                    raise ValueError('Short fmt chunk')
                encoding, channels, rate, _, align, bits = struct.unpack('<HHIIHH', b[:16])
                if encoding not in (1, 3) or align != channels * bits // 8:
                    raise ValueError('Unsupported WAV encoding')
                fmt = rate, channels, align
            elif kind == b'data':
                if data is not None:
                    raise ValueError('Multiple WAV data chunks')
                data = count
            stream.seek(start + count + count % 2)
        if fmt is None or data is None or data % fmt[2]:
            raise ValueError('Incomplete WAV')
        return {'rate': fmt[0], 'channels': fmt[1], 'frames': data // fmt[2]}


def table(rows, fields, cumulative):
    result = []
    for field in fields:
        values = [(row_key(row), row.get(field)) for row in rows]
        measured = [(key, value) for key, value in values
                    if type(value) is int and value >= 0]
        bad = [list(key) if key is not None else None for key, value in measured if value != 0]
        item = {'field': field, 'measured_rows': len(measured),
                'unmeasured_or_invalid_rows': len(values) - len(measured),
                'max': max((v for _, v in measured), default=None),
                'nonzero_rows': len(bad), 'nonzero_keys': bad,
                'all_zero': bool(values) and len(measured) == len(values) and not bad}
        if cumulative:
            item['sum'] = None
            item['scope'] = 'Input session cumulative snapshots; never sum snapshots across rows.'
        else:
            item['sum'] = sum(v for _, v in measured)
            item['scope'] = 'Per-operation after-minus-before delta recorded by the host.'
        result.append(item)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-device-rate', type=float, default=48000)
    parser.add_argument('--expected-device-buffer', type=int, default=512)
    parser.add_argument('--expected-device-id', type=int,
                        help='Optional independently known device ID; otherwise consistency is checked.')
    args = parser.parse_args()
    if not math.isfinite(args.expected_device_rate) or args.expected_device_rate <= 0 or args.expected_device_buffer <= 0:
        parser.error('Expected device rate/buffer must be finite and positive')
    if args.expected_device_id is not None and args.expected_device_id <= 0:
        parser.error('Expected device ID must be positive')
    root, output = args.run_dir.resolve(), args.output.resolve()
    if output.exists():
        parser.error('Output already exists; choose a new file')
    if not output.parent.is_dir():
        parser.error('Output parent directory must exist')
    report = {'schema': 'adoption-native-performance-audit-v1', 'PASS': False,
              'audit_status': 'BLOCKED', 'execution_complete': False, 'performance_status': 'UNASSESSED',
              'functional_rt_status': 'UNASSESSED', 'latency_status': 'UNASSESSED',
              'quality_status': 'UNMEASURED', 'quality_pass': None, 'allow_quality_pass': False,
              'publication_status': 'NOT_DECIDED', 'expected_count': 120,
              'observed_count': 0, 'checks': [], 'identities': [],
              'PASS_scope': 'Native functional/RT and Ready p95 target only; excludes PCM quality.',
              'statistics_method': 'Linear interpolation at (N-1)*q, using each operation timestamp difference.',
              'argv': sys.argv}
    checks = report['checks']
    def check(name, passed, detail=None):
        item = {'id': name, 'PASS': bool(passed)}
        if detail is not None:
            item['detail'] = json_safe(detail)
        checks.append(item)
        return bool(passed)
    rows, valid_rows, latencies = [], [], []
    parsed_count = 0
    expected_keys = set()
    execution_ok = keys_ok = False
    try:
        paths = {key: root / value for key, value in
                 [('expected', 'EXPECTED.json'), ('execution', 'EXECUTION.json'), ('rows', 'data/rows.jsonl')]}
        for path in paths.values():
            report['identities'].append(identity(path))
        expected = json.loads(paths['expected'].read_text())
        execution = json.loads(paths['execution'].read_text())
        row_lines = paths['rows'].read_text().splitlines()
        parsed_count = len(row_lines)
        check('expected_schema', expected.get('schema') == 'adoption-native-performance-v1')
        check('quality_pass_prohibited', expected.get('allow_quality_pass') is False)
        check('ready_target_is_200ms', type(expected.get('ready_target_p95_ms')) in (int, float)
              and expected['ready_target_p95_ms'] == 200)
        check('normal_zero_fields_complete', isinstance(expected.get('normal_zero_fields'), list)
              and len(expected['normal_zero_fields']) == len(DELTA_FIELDS)
              and set(expected['normal_zero_fields']) == set(DELTA_FIELDS))
        check('execution_finite', not floating_errors(execution))
        execution_ok = check('execution_exit_and_timeout', type(execution.get('returncode')) is int
                             and execution['returncode'] == 0 and execution.get('timed_out') is False
                             and type(execution.get('wall_s')) in (int, float)
                             and math.isfinite(execution['wall_s']) and execution['wall_s'] > 0,
                             execution)
        command = expected.get('command')
        if not check('native_command_shape', isinstance(command, list) and len(command) == 3
                     and all(isinstance(x, str) for x in command)):
            raise ValueError('Native command must be [host,input,data_directory]')
        host, source, data_directory = map(lambda p: Path(p).resolve(), command)
        check('data_directory_binding', data_directory == paths['rows'].parent)
        for label, path, digest in [('host', host, expected.get('host_sha256')),
                                    ('input', source, expected.get('input_sha256'))]:
            item = identity(path)
            item['role'], item['expected_sha256'] = label, digest
            report['identities'].append(item)
            check(label + '_current_sha256', item['sha256'] == digest)
        shape = wav_shape(source)
        report['input'] = dict(path=str(source), **shape)
        check('input_300s_44100_stereo', shape == {'rate': 44100, 'channels': 2, 'frames': 13230000})
        rate = shape['rate']
        positions = [30 * rate, 150 * rate, 270 * rate, 285 * rate, 83 * rate + 12345]
        fixed_keys = set(itertools.product(SPEEDS, (True, False), range(3), positions))
        declared = expected.get('expected_keys', [])
        parsed = [strict_key(key) for key in declared]
        check('expected_key_types', isinstance(declared, list) and all(k is not None for k in parsed))
        expected_keys = {k for k in parsed if k is not None}
        check('expected_keys_fixed_complete_120', expected.get('expected_count') == 120
              and len(declared) == len(expected_keys) == 120 and expected_keys == fixed_keys)
        expected_keys = fixed_keys
        report['expected_keys'] = [list(k) for k in sorted(expected_keys)]
        build_path = Path(expected['build']).resolve()
        report['identities'].append(identity(build_path))
        build = json.loads(build_path.read_text())
        binaries = build.get('binaries', {})
        entry = binaries.get(host.name, {})
        build_rows = build.get('rows', [])
        check('successful_build', build.get('status') == 'PASS' and bool(build_rows)
              and all(type(r.get('exit')) is int and r['exit'] == 0 for r in build_rows))
        check('build_binary_binding', entry.get('sha256') == expected.get('host_sha256')
              and Path(entry.get('path', '')).resolve() == host
              and entry.get('bytes') == host.stat().st_size)
        check('build_source_identity', isinstance(build.get('source'), str)
              and build.get('source') == build.get('source_manifest', {}).get('sha256'))
        report['build'] = {'path': str(build_path), 'source': build.get('source'),
                           'source_root': build.get('source_root'), 'configuration': build.get('configuration'),
                           'architecture': build.get('architecture'), 'baseline_commit_label': expected.get('baseline')}
        malformed = []
        for number, line in enumerate(row_lines, 1):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError('row is not an object')
                rows.append(value)
            except (json.JSONDecodeError, ValueError) as error:
                malformed.append({'line': number, 'error': str(error)})
        report['observed_count'] = parsed_count
        check('all_rows_parse', not malformed, malformed)
        keys = [row_key(row) for row in rows]
        key_counts = collections.Counter(k for k in keys if k is not None)
        missing = expected_keys - set(key_counts)
        extra = set(key_counts) - expected_keys
        duplicates = [key for key, count in key_counts.items() if count > 1]
        report.update(missing_keys=[list(k) for k in sorted(missing)],
                      unexpected_keys=[list(k) for k in sorted(extra)],
                      duplicate_keys=[list(k) for k in sorted(duplicates)],
                      malformed_rows=malformed)
        keys_ok = check('observed_keys_exact_120', parsed_count == len(rows) == 120
                        and all(k is not None for k in keys) and not missing and not extra and not duplicates)
        row_errors = []
        devices = set()
        for index, row in enumerate(rows):
            errors = []
            key = row_key(row)
            for field in INTEGER_FIELDS:
                v = row.get(field)
                if type(v) is not int or not 0 <= v < 2**64:
                    errors.append('missing/invalid integer ' + field)
            for field in FLOAT_FIELDS:
                v = row.get(field)
                if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
                    errors.append('missing/nonfinite measurement ' + field)
            errors.extend('nonfinite ' + k for k in floating_errors(row))
            if row.get('analysis_complete_at_play') is not True:
                errors.append('analysis was not complete at play')
            if not errors:
                if row['rate'] != rate or row['channels'] != shape['channels']:
                    errors.append('input shape differs')
                if row['epoch'] == 0 or row['peak_rss'] == 0 or any(row[t] == 0 for t in TIME_FIELDS):
                    errors.append('zero epoch/RSS/timestamp')
                if not (row['accepted_ns'] <= row['preparing_ns'] <= row['analysis_ready_ns'] <= row['fifo_ready_ns']
                        <= row['switch_ready_ns'] <= row['transition_begin_ns'] <= row['transition_end_ns']
                        and row['fifo_ready_ns'] <= row['first_pcm_ns'] <= row['hal_estimate_ns']
                        and row['switch_ns'] == row['transition_begin_ns']):
                    errors.append('timestamp order')
                # first_pcm_ns may precede transition_begin_ns by a few microseconds:
                # their host observations occur at different points within one callback.
                ready = (row['fifo_ready_ns'] - row['accepted_ns']) / 1e6
                first = (row['first_pcm_ns'] - row['accepted_ns']) / 1e6
                if not math.isclose(row['ready_ms'], ready, rel_tol=1e-5, abs_tol=0.01):
                    errors.append('reported ready_ms differs from timestamps')
                if not math.isclose(row['first_pcm_ms'], first, rel_tol=1e-5, abs_tol=0.01):
                    errors.append('reported first_pcm_ms differs from timestamps')
                if row['device'] <= 0 or row['device_buffer'] != args.expected_device_buffer or not math.isclose(row['device_rate'], args.expected_device_rate, abs_tol=1e-6, rel_tol=0):
                    errors.append('actual device values differ from declared numeric condition')
                if args.expected_device_id is not None and row['device'] != args.expected_device_id:
                    errors.append('actual device ID differs')
                devices.add((row['device'], row['device_rate'], row['device_buffer']))
                if key not in expected_keys:
                    errors.append('invalid operation key')
                if row['speed'] not in SPEEDS:
                    errors.append('unsupported/zero speed')
                elif row['output'] > (shape['frames'] * 1000000 + row['speed'] // 2) // row['speed']:
                    errors.append('output coordinate outside full track')
                if any(row['lifetime_' + suffix] < row['delta_' + suffix] for suffix in ZERO_SUFFIXES):
                    errors.append('operation delta exceeds lifetime counter')
            if errors:
                row_errors.append({'row': index + 1, 'key': list(key) if key is not None else None, 'errors': errors})
            else:
                valid_rows.append(row)
                latencies.append({'key': key, 'candidate': row['candidate'], 'speed': row['speed'],
                                  'ready_ms': ready, 'first_pcm_ms': first})
        check('all_measurements_finite_present_analysis_complete', not row_errors and len(valid_rows) == 120,
              row_errors)
        check('device_actual_values_consistent', len(devices) == 1, [list(d) for d in sorted(devices)])
        report['device'] = {'actual_values': [dict(id=d[0], rate=d[1], buffer_frames=d[2]) for d in sorted(devices)],
             'expected_rate': args.expected_device_rate, 'expected_buffer_frames': args.expected_device_buffer,
             'independently_expected_id': args.expected_device_id,
             'recorded_hardware_label': expected.get('hardware'),
             'hardware_label_verification': 'UNVERIFIED: model/OS/RAM/speaker name are not proven by these row fields.'}
        sessions = collections.defaultdict(list)
        for row in valid_rows:
            sessions[(row['speed'], row['candidate'], row['repeat'])].append(row)
        session_errors = []
        for key, session in sessions.items():
            ordered = sorted(session, key=lambda r: r['accepted_ns'])
            if len(ordered) != 5 or len({r['epoch'] for r in ordered}) != 5 or any(
                    ordered[i]['epoch'] >= ordered[i + 1]['epoch'] or ordered[i]['accepted_ns'] >= ordered[i + 1]['accepted_ns']
                    for i in range(len(ordered) - 1)):
                session_errors.append({'session': list(key), 'error': 'epoch/operation sequence'})
            for field in LIFETIME_FIELDS:
                if any(ordered[i][field] > ordered[i + 1][field] for i in range(len(ordered) - 1)):
                    session_errors.append({'session': list(key), 'error': 'cumulative counter regressed', 'field': field})
        check('session_epoch_and_lifetime_order', len(sessions) == 24 and not session_errors, session_errors)
        report['counter_tables'] = {'delta': table(rows, DELTA_FIELDS, False),
                                    'lifetime': table(rows, LIFETIME_FIELDS, True)}
        report['realtime_delta_zero'] = all(r['all_zero'] for r in report['counter_tables']['delta'])
        report['realtime_lifetime_zero'] = all(r['all_zero'] for r in report['counter_tables']['lifetime'])
        changed = []
        for item in report['identities']:
            p = Path(item['path'])
            if not p.is_file() or list(snapshot(p)) != item['stat']:
                changed.append(str(p))
        check('artifacts_unchanged_during_audit', not changed, changed)
        complete = execution_ok and keys_ok and not malformed
        report['execution_complete'] = complete
        audit_ok = complete and all(c['PASS'] for c in checks)
        report['audit_status'] = 'PASS' if audit_ok else ('INCOMPLETE' if not complete else 'FAIL')
        rt = report['realtime_delta_zero'] and report['realtime_lifetime_zero']
        report['functional_rt_status'] = ('PASS' if rt else 'FAIL') if audit_ok else 'UNASSESSED'
        report['latency_status'] = ('PASS' if quantile([r['ready_ms'] for r in latencies], .95) <= 200 else 'FAIL') if audit_ok else 'UNASSESSED'
        report['performance_status'] = ('PASS' if rt and report['latency_status'] == 'PASS' else 'FAIL') if audit_ok else 'UNASSESSED'
        report['PASS'] = audit_ok and report['performance_status'] == 'PASS'
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, OverflowError) as error:
        check('read_or_schema_failure', False, str(error))
        report['audit_status'] = 'INCOMPLETE' if parsed_count else 'BLOCKED'
    finally:
        report['observed_count'] = parsed_count
        report['valid_measurement_count'] = len(valid_rows)
        report['summary'] = {'ready': distribution([r['ready_ms'] for r in latencies]),
                             'first_pcm': distribution([r['first_pcm_ms'] for r in latencies]),
                             'target_ready_p95_ms': 200,
                             'target_applies_to': 'All 120 operations combined, FIFO Ready only.',
                             'provisional': report['audit_status'] != 'PASS'}
        grouped = []
        for kind in ('preset', 'speed', 'preset_speed'):
            keys = sorted({('candidate' if r['candidate'] else 'baseline',) if kind == 'preset'
                           else (r['speed'],) if kind == 'speed' else
                           ('candidate' if r['candidate'] else 'baseline', r['speed']) for r in latencies})
            for key in keys:
                subset = [r for r in latencies if
                          (('candidate' if r['candidate'] else 'baseline',) if kind == 'preset' else
                           (r['speed'],) if kind == 'speed' else
                           ('candidate' if r['candidate'] else 'baseline', r['speed'])) == key]
                grouped.append({'group_by': kind, 'key': list(key),
                     'ready': distribution([r['ready_ms'] for r in subset]),
                     'first_pcm': distribution([r['first_pcm_ms'] for r in subset]),
                     'ready_over_200ms': sum(r['ready_ms'] > 200 for r in subset)})
        report['groups'] = grouped
        report['checks_passed'] = sum(c['PASS'] for c in checks)
        report['checks_total'] = len(checks)
        report['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        report['validator_sha256'] = sha(Path(__file__))
        # Exclusive creation preserves every earlier audit and failed run.
        with output.open('x') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        print(json.dumps({k: report[k] for k in ('audit_status', 'performance_status', 'functional_rt_status',
              'latency_status', 'quality_status', 'expected_count', 'observed_count', 'checks_passed', 'checks_total')}, ensure_ascii=False))
    return 0 if report['PASS'] else 2 if report['audit_status'] == 'PASS' else 3


if __name__ == '__main__':
    raise SystemExit(main())
