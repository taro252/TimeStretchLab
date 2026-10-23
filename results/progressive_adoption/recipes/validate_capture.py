#!/usr/bin/env python3
"""独立frozen固定RAWと独立float32境界式でcapture全体を検査する。

旧validate_fixed_captureと同じCLIに --host-binary（必須）を追加した。
参照合成・製品head参照・音声・buildは実行しない。期待checkは常に5件。
性能/RT/物理音声のPASSを生成せず、両RAWは最終gain0.5の前として扱う。
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
EQUATIONS = ROOT / 'results/phase62_terminal_initial/recipes/validate_initial_pcm.py'
EQUATIONS_SHA = '3be115fe493b249e120cb5f42c056a458ebe6cf76d2124842dc7cf3b6cad8bb4'
FIXED_SHA = 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
IDS = ('independent_map', 'raw_all_bits', 'output_all_bits', 'coordinates', 'gain')
FLAGS = ('periodic', 'head', 'tail', 'correction_before_mix', 'old_periodic', 'old_head', 'old_tail')
SPAN_INTS = ('callback_frame', 'new_epoch', 'old_epoch', 'new_at', 'old_at', 'frames',
             'new_received', 'old_received', 'mixed', 'transition_offset', 'transition_length',
             'boundary_frames', 'period_frames', 'period_offset',
             'old_boundary_frames', 'old_period_frames', 'old_period_offset')


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def stat(path):
    s = path.stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def identity(path):
    path = path.resolve()
    before = stat(path)
    digest = sha(path)
    need(stat(path) == before, 'File changed while hashing: ' + str(path))
    return {'path': str(path), 'bytes': before[2], 'sha256': digest, 'stat': before}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def reject_constant(value):
    raise ValueError('NaN/Inf JSON constant is forbidden: ' + value)


def finite_tree(value):
    if isinstance(value, dict):
        for child in value.values():
            finite_tree(child)
    elif isinstance(value, list):
        for child in value:
            finite_tree(child)
    elif type(value) is float:
        need(math.isfinite(value), 'Nonfinite JSON measurement')


def read(path):
    result = json.loads(path.read_text(), parse_constant=reject_constant)
    finite_tree(result)
    return result


def json_lines(path):
    result = []
    for index, line in enumerate(path.read_text().splitlines()):
        need(bool(line.strip()), 'Blank record at line ' + str(index + 1))
        row = json.loads(line, parse_constant=reject_constant)
        need(isinstance(row, dict), 'JSONL record must be an object')
        finite_tree(row)
        result.append(row)
    return result


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def ints(row, names):
    need(all(integer(row.get(key)) for key in names), 'Missing/negative/noninteger fields: ' + ','.join(names))


def flag(row, key):
    value = row[key]
    need(type(value) in (bool, int) and value in (0, 1), 'Expected bool or 0/1: ' + key)
    return bool(value)


def wav_info(path):
    fmt = data = None
    with path.open('rb') as stream:
        header = stream.read(12)
        need(len(header) == 12 and header[:4] == b'RIFF' and header[8:] == b'WAVE', 'RIFF/WAVE input required')
        while True:
            header = stream.read(8)
            if not header:
                break
            need(len(header) == 8, 'Truncated WAV chunk header')
            kind, size = struct.unpack('<4sI', header)
            start = stream.tell()
            need(start + size <= path.stat().st_size, 'Truncated WAV chunk data')
            if kind == b'fmt ':
                need(fmt is None and size >= 16, 'Invalid/duplicate WAV fmt')
                fmt = struct.unpack('<HHIIHH', stream.read(16))
            elif kind == b'data':
                need(data is None, 'Duplicate WAV data')
                data = size
            stream.seek(start + size + (size & 1))
    need(fmt is not None and data is not None, 'WAV fmt/data missing')
    encoding, channels, rate, _, align, bits = fmt
    need(channels in (1, 2) and rate in (44100, 48000) and encoding in (1, 3)
         and bits in (16, 32) and align == channels * bits // 8 and data % align == 0,
         'Unsupported input format/frame layout')
    return {'channels': channels, 'rate': rate, 'frames': data // align,
            'encoding': encoding, 'bits': bits}


def native_completion(host, declared, capture):
    need(flag(host, 'run_complete'), 'Native host did not complete')
    if 'status' in host:
        need(host['status'] == 'PASS', 'NativeTest SUMMARY status is not PASS')
        schema = 'NativeTest.status'
    else:
        need(flag(host, 'functional'), 'AB native functional check failed')
        for name in ('rt_pass', 'performance_pass', 'performance_exercised'):
            if name in host:
                flag(host, name)  # Validate its type, but do not turn it into a PCM criterion.
        schema = 'AbNative.functional'
    if 'expected' in host or 'executed' in host:
        need(integer(host.get('expected'), 1) and host['expected'] == host.get('executed')
             and host['expected'] == declared.get('expected'), 'Native check count is incomplete')
    if 'required_ids' in declared:
        ids = declared['required_ids']
        need(isinstance(ids, list) and bool(ids) and all(isinstance(x, str) for x in ids)
             and len(ids) == len(set(ids)) == declared.get('expected'), 'Native required ID declaration')
        rows = json_lines(capture / 'checks.jsonl')
        got = [row.get('id') for row in rows]
        need(all(isinstance(x, str) for x in got) and len(got) == len(set(got)) == len(ids)
             and set(got) == set(ids) and all(flag(row, 'pass') for row in rows),
             'Native expected checks are missing/duplicate/failed')
    return {'schema': schema, 'functional_complete': True,
            'reported_rt_pass': host.get('rt_pass'), 'reported_performance_pass': host.get('performance_pass'),
            'reported_performance_exercised': host.get('performance_exercised'),
            'RT_deadline_approval': host.get('RT_deadline_approval'),
            'interpretation': 'Native completion prerequisite only; no RT/performance/physical approval is inferred.'}


def validate(args, expected, checks):
    import numpy as np
    artifacts = expected['identities']
    def ident(name, path):
        item = identity(path)
        artifacts[name] = item
        return item
    for name, path in [('input', args.input), ('host_binary', args.host_binary),
                       ('reference_binary', args.reference_binary), ('reference_raw', args.reference_raw),
                       ('reference_map', args.reference_map), ('validator', Path(__file__)),
                       ('equations', EQUATIONS)]:
        ident(name, path)
    for name in ('EXPECTED.json', 'SUMMARY.json', 'raw.f32', 'raw_records.jsonl',
                 'output_before_gain.f32', 'spans.jsonl'):
        ident('capture/' + name, args.capture / name)
    if (args.capture / 'checks.jsonl').is_file():
        ident('capture/checks.jsonl', args.capture / 'checks.jsonl')
    need(artifacts['reference_binary']['sha256'] == FIXED_SHA, 'Frozen oracle must be the saved de70... executable')
    need(artifacts['equations']['sha256'] == EQUATIONS_SHA, 'Independent fused equation helper changed')
    spec = importlib.util.spec_from_file_location('adoption_independent_equations', EQUATIONS)
    equations_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(equations_module)
    eq = equations_module.Equations('fused')
    equal, pcm = equations_module.equal, equations_module.pcm
    info = wav_info(args.input)
    ch, rate = info['channels'], info['rate']
    meta = read(args.reference_map)
    declared, host = read(args.capture / 'EXPECTED.json'), read(args.capture / 'SUMMARY.json')
    need(isinstance(declared, dict) and isinstance(host, dict) and isinstance(meta, dict), 'Object metadata required')
    ints(declared, ('A', 'B'))
    need(0 <= declared['A'] < declared['B'] <= info['frames'], 'Declared A/B input bounds')
    positions = meta.get('input_positions')
    need(isinstance(positions, list) and len(positions) == 2 and all(integer(x) for x in positions)
         and positions == [declared['A'], declared['B']], 'reference-map.input_positions must equal declared [A,B]')
    ints(meta, ('channels', 'rate', 'input_frames', 'output_frames'))
    need(meta['channels'] == ch and meta['rate'] == rate and meta['input_frames'] == info['frames']
         and meta['output_frames'] > 0, 'Reference input format/length')
    output_positions = meta.get('positions')
    need(isinstance(output_positions, list) and len(output_positions) == 2
         and all(integer(x) for x in output_positions), 'Exactly two independent output positions required')
    oa, ob = output_positions
    period, width = ob - oa, min(rate // 200, (ob - oa) // 4)
    need(0 <= oa < ob <= meta['output_frames'] and period >= 512 and width > 0, 'Independent A/B period/width')
    need(meta.get('sha256') == artifacts['reference_raw']['sha256'], 'Independent full RAW SHA differs from reference map')
    for obj in (declared, host, meta):
        if 'input_sha256' in obj:
            need(obj['input_sha256'] == artifacts['input']['sha256'], 'Input SHA binding mismatch')
    if 'binary_sha256' in declared:
        need(declared['binary_sha256'] == artifacts['host_binary']['sha256'], 'Capture host SHA binding mismatch')
    if 'host_sha256' in declared:
        need(declared['host_sha256'] == artifacts['host_binary']['sha256'], 'Capture host SHA binding mismatch')
    if 'speed' in declared:
        speed = declared['speed']
        need(type(speed) in (int, float) and math.isfinite(speed), 'Declared fixed speed')
        micros = int(math.floor(speed * 1000000 + .5))
        need(400000 <= micros <= 2000000 and micros % 10000 == 0
             and abs(speed * 1000000 - micros) < .001, 'Declared speed grid')
        need(meta['output_frames'] == (info['frames'] * 1000000 + micros // 2) // micros,
             'Reference full length differs from declared speed')
    native = native_completion(host, declared, args.capture)
    reference = pcm(args.reference_raw, ch, meta['output_frames'])
    raw, output = pcm(args.capture / 'raw.f32', ch), pcm(args.capture / 'output_before_gain.f32', ch)
    records, spans = json_lines(args.capture / 'raw_records.jsonl'), json_lines(args.capture / 'spans.jsonl')
    need(records and spans and len(records) <= 8192 and len(spans) <= 8192, 'Empty/over-capacity RAW or span records')
    for name, count in [('raw_records', len(records)), ('output_spans', len(spans)),
                        ('raw_frames', len(raw)), ('output_frames', len(output))]:
        if name in host:
            need(integer(host[name]) and host[name] == count, 'Native summary/file length mismatch: ' + name)
    checks['independent_map'] = {'status': 'PASS', 'input_A': declared['A'], 'input_B': declared['B'],
          'independent_OA': oa, 'independent_OB': ob, 'period_frames': period, 'boundary_frames': width,
          'native_completion': native, 'host_SHA_bound_in_capture':
          'binary_sha256' in declared or 'host_sha256' in declared}
    save(args.output / 'EXPECTED.json', expected)
    raw_cursor, sources = 0, []
    epoch_session, epoch_next = {}, {}
    for index, row in enumerate(records):
        ints(row, ('frames', 'at', 'raw_offset', 'epoch', 'session'))
        n, at, epoch = row['frames'], row['at'], row['epoch']
        need(0 < n <= 4096 and row['raw_offset'] == raw_cursor and 0 <= at < at + n <= len(reference)
             and epoch > 0 and row['session'] > 0, 'RAW zero/negative/ordering/identity/range')
        if epoch in epoch_session:
            need(epoch_session[epoch] == row['session'] and epoch_next[epoch] == at,
                 'Same epoch changed session or skipped/duplicated RAW coordinates')
        epoch_session[epoch], epoch_next[epoch] = row['session'], at + n
        equal(raw[raw_cursor:raw_cursor + n], reference[at:at + n], 'independent_RAW', args.output,
              record=index, absolute_reference_at=at, raw_offset=raw_cursor)
        raw_cursor += n
        sources.append((epoch, at, n))
    need(raw_cursor == len(raw), 'RAW records do not own the entire RAW file')
    checks['raw_all_bits'] = {'status': 'PASS', 'frames': raw_cursor, 'channels': ch, 'records': len(records)}
    cursor, used, previous_callback_end, previous_new_end = 0, [], None, None
    session_tails, epoch_previous_tail = set(), {}
    periodic_count = mixed_frames = head_frames = tail_frames = 0
    ab_epoch_started = False
    first_a_epoch = host.get('first_A_epoch')
    if first_a_epoch is not None:
        need(integer(first_a_epoch, 1) and host.get('first_A_output') == oa,
             'AB host first-A coordinate is not independent OA')
    for index, span in enumerate(spans):
        ints(span, SPAN_INTS)
        for key in FLAGS:
            flag(span, key)
        for key in ('boundary_last', 'boundary_first', 'old_boundary_last', 'old_boundary_first'):
            values = span[key]
            need(isinstance(values, list) and len(values) >= ch and
                 all(type(v) in (int, float) and math.isfinite(v) for v in values), 'Finite endpoint array required')
            with np.errstate(over='ignore', invalid='ignore'):
                need(bool(np.isfinite(np.asarray(values, dtype='<f4')).all()), 'Endpoint Float32 overflow')
        n, at, mixed = span['frames'], span['new_at'], span['mixed']
        need(0 < n <= 4096 and span['new_received'] == n and span['new_epoch'] in epoch_session
             and 0 <= at < at + n <= len(reference) and 0 <= mixed <= n
             and span['old_received'] == mixed and cursor + n <= len(output), 'Span zero progress/supply/ownership/bounds')
        need(previous_callback_end is None or span['callback_frame'] == previous_callback_end,
             'Callback output coordinates skipped/duplicated')
        previous_callback_end = span['callback_frame'] + n
        if first_a_epoch is not None:
            ab_epoch_started |= span['new_epoch'] == first_a_epoch
            if ab_epoch_started:
                need(flag(span, 'periodic'), 'AB active output was reported nonperiodic')
        expected_pcm = reference[at:at + n].copy()
        used.append((span['new_epoch'], at, n))

        def corrected(values, old=False):
            nonlocal periodic_count, head_frames, tail_frames
            prefix = 'old_' if old else ''
            periodic, head, tail = (flag(span, prefix + name) for name in ('periodic', 'head', 'tail'))
            need(not (head and tail) and (periodic or not (head or tail)), 'Invalid boundary flags')
            if not periodic:
                return values
            periodic_count += 1
            pos = span['old_at'] if old else at
            epoch = span['old_epoch'] if old else span['new_epoch']
            need(epoch in epoch_session and oa <= pos < pos + len(values) <= ob
                 and span[prefix + 'period_frames'] == period and span[prefix + 'boundary_frames'] == width
                 and span[prefix + 'period_offset'] == pos - oa, 'Independent A/B/period/width mismatch')
            if epoch not in epoch_previous_tail:
                epoch_previous_tail[epoch] = (epoch_session[epoch] in session_tails or
                                             (not old and previous_new_end == ob and pos == oa))
            expected_head = epoch_previous_tail[epoch] and pos < oa + width
            expected_tail = pos >= ob - width
            need(head == expected_head and tail == expected_tail, 'Boundary window flags differ from independent coordinates/history')
            limit = oa + width if expected_head else ob if expected_tail else ob - width
            need(pos + len(values) <= limit, 'Span crosses an independent correction-window boundary')
            if head or tail:
                equal(np.asarray(span[prefix + 'boundary_last'][:ch], dtype='<f4').reshape(1, ch),
                      reference[ob - 1:ob], 'independent_last_endpoint', args.output, span=index, old=old)
                equal(np.asarray(span[prefix + 'boundary_first'][:ch], dtype='<f4').reshape(1, ch),
                      reference[oa:oa + 1], 'independent_first_endpoint', args.output, span=index, old=old)
                head_frames += len(values) if head else 0
                tail_frames += len(values) if tail else 0
            result = eq.correction(values, pos - oa, period, width, head, tail, reference[ob - 1], reference[oa])
            if pos + len(values) == ob:
                session_tails.add(epoch_session[epoch])
            return result

        before = flag(span, 'correction_before_mix')
        if before:
            expected_pcm = corrected(expected_pcm)
        if mixed:
            old = span['old_at']
            need(span['old_epoch'] in epoch_session and span['old_epoch'] != span['new_epoch']
                 and 0 <= old < old + mixed <= len(reference)
                 and span['transition_length'] == rate // 200
                 and 0 <= span['transition_offset'] < span['transition_offset'] + mixed <= span['transition_length'],
                 'Independent old RAW/5ms transition coordinates')
            expected_pcm = eq.mix(expected_pcm, corrected(reference[old:old + mixed], True),
                                  span['transition_offset'], span['transition_length'])
            used.append((span['old_epoch'], old, mixed))
            mixed_frames += mixed
        if not before:
            expected_pcm = corrected(expected_pcm)
        need(bool(np.isfinite(expected_pcm).all()), 'Nonfinite equation result')
        equal(output[cursor:cursor + n], expected_pcm, 'independent_output_before_gain', args.output,
              span=index, output_offset=cursor, absolute_reference_at=at)
        cursor += n
        previous_new_end = at + n if flag(span, 'periodic') else None
    need(cursor == len(output), 'Spans do not own the entire output file')
    if first_a_epoch is not None:
        need(ab_epoch_started and periodic_count > 0, 'Declared AB entry epoch was never observed')
    checks['output_all_bits'] = {'status': 'PASS', 'frames': cursor, 'channels': ch, 'spans': len(spans),
          'mixed_frames': mixed_frames, 'head_frames': head_frames, 'tail_frames': tail_frames,
          'arithmetic': 'independent Equations(fused)', 'final_gain_applied': False}
    need(sources == used, 'RAW observer intervals differ from new/old span ownership (order/range/length)')
    checks['coordinates'] = {'status': 'PASS', 'raw_sources_exactly_match_spans': True,
          'periodic_source_intervals': periodic_count, 'AB_boundary_exercised': periodic_count > 0,
          'callback_first_frame': spans[0]['callback_frame'], 'callback_end_frame': previous_callback_end}
    gain_source = ROOT / 'src/platform/macos/ProgressiveMacPlaybackEngine.mm'
    ident('gain_configuration_source', gain_source)
    need('engine.mainMixerNode.outputVolume=.5f' in gain_source.read_text(), 'Configured final mixer gain differs from 0.5')
    changed = [item['path'] for item in artifacts.values()
               if not Path(item['path']).is_file() or stat(Path(item['path'])) != item['stat']]
    need(not changed, 'Input/artifact changed during audit: ' + repr(changed))
    checks['gain'] = {'status': 'PASS', 'configured_final_gain': .5,
          'scope': 'Configuration source inspection only; captured/reference/output PCM all precede final gain.',
          'physical_gain_verified': None, 'runtime_binary_gain_attestation': None,
          'all_artifacts_unchanged': True}
    return {'channels': ch, 'rate': rate, 'input_frames': info['frames'], 'raw_frames': len(raw),
            'output_frames': len(output), 'records': len(records), 'spans': len(spans),
            'independent_OA': oa, 'independent_OB': ob, 'period_frames': period,
            'boundary_frames': width, 'mixed_frames': mixed_frames, 'native_reported': native,
            'artifact_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('capture', 'input', 'host-binary', 'reference-binary', 'reference-raw', 'reference-map', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    expected = {'schema': 'adoption-independent-fixed-capture-v1', 'expected': 5, 'expected_ids': list(IDS),
          'capture': str(args.capture.resolve()), 'fixed_oracle_required_sha256': FIXED_SHA,
          'equations_required_sha256': EQUATIONS_SHA, 'fp_contraction': 'fused', 'identities': {},
          'python': sys.version, 'platform': platform.platform(),
          'scope': 'Every captured PCM sample/channel/bit and span ownership; fixed-speed same-input reference.',
          'performance_status': 'NOT_ASSESSED', 'realtime_status': 'NOT_ASSESSED',
          'physical_audio_continuity_verified': None, 'public_approved': False}
    checks, result, reason = {}, {}, None
    save(args.output / 'EXPECTED.json', expected)
    try:
        result = validate(args, expected, checks)
    except Exception as error:
        reason = str(error)
    for name in IDS:
        if name not in checks:
            checks[name] = {'status': 'FAIL' if reason and not any(c['status'] == 'FAIL' for c in checks.values())
                            else 'INCOMPLETE', 'reason': reason}
    good = reason is None and all(checks[name]['status'] == 'PASS' for name in IDS)
    save(args.output / 'EXPECTED.json', expected)
    summary = {'schema': 'adoption-independent-fixed-capture-summary-v1', 'status': 'PASS' if good else 'FAIL',
          'run_complete': reason is None, 'expected': 5, 'executed': sum(c['status'] != 'INCOMPLETE' for c in checks.values()),
          'passed': sum(c['status'] == 'PASS' for c in checks.values()), 'checks': checks, 'reason': reason,
          'result': result, 'expected_sha256': sha(args.output / 'EXPECTED.json'),
          'validator_sha256': sha(Path(__file__)), 'performance_status': 'NOT_ASSESSED',
          'realtime_status': 'NOT_ASSESSED', 'physical_audio_continuity_verified': None, 'public_approved': False,
          'PASS_scope': 'Independent captured PCM/coordinates/configuration audit only; no RT/performance/physical approval.'}
    save(args.output / 'SUMMARY.json', summary)
    print(json.dumps({key: summary[key] for key in ('status', 'expected', 'executed', 'passed', 'reason')}, ensure_ascii=False))
    return 0 if good else 2


if __name__ == '__main__':
    raise SystemExit(main())
