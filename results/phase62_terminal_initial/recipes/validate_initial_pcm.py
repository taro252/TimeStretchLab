#!/usr/bin/env python3
"""初回Loop captureを凍結固定Exact RAWと独立したfloat32境界式で検証する。

参照は変更後の製品から作らない。既存の凍結実行体の固定CLIは次の通り。
  phase61_frozen_reference INPUT.wav SPEED_MICROS baseline REF.f32 A_INPUT B_INPUT > REF_MAP.json
REF_MAP.jsonは同CLIのstdout（positions=[OA, OB]）をそのまま渡す。
本recipeは参照・音声を生成せず、全チャンネルの全bitと座標を検査する。
raw.f32、output_before_gain.f32、参照RAWはいずれも最終gain 0.5を掛ける前。
境界の端点は参照RAWから求め、captureのboundary_last/firstを正解にしない。
"""
import argparse
import ctypes
import ctypes.util
import hashlib
import json
import platform
import struct
import sys
from pathlib import Path

FIXED_SHA = 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def identity(path):
    return dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=sha(path))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def read(path):
    return json.loads(path.read_text())


def json_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def flag(row, key):
    value = row[key]
    need(isinstance(value, (bool, int)) and value in (0, 1), '0/1の診断値ではありません: ' + key)
    return bool(value)


def wav_info(path):
    with path.open('rb') as stream:
        need(stream.read(4) == b'RIFF', 'RIFF入力が必要です')
        stream.read(4)
        need(stream.read(4) == b'WAVE', 'WAVE入力が必要です')
        fmt = data = None
        while header := stream.read(8):
            need(len(header) == 8, 'WAV chunkが途中です')
            kind, size = struct.unpack('<4sI', header)
            start = stream.tell()
            if kind == b'fmt ':
                need(size >= 16, 'fmt chunkが途中です')
                fmt = struct.unpack('<HHIIHH', stream.read(16))
            elif kind == b'data':
                data = size
            stream.seek(start + size + (size & 1))
        need(fmt is not None and data is not None, 'fmt/dataがありません')
        encoding, channels, rate, _, align, bits = fmt
        need(channels in (1, 2) and rate in (44100, 48000) and align > 0 and data % align == 0,
             '入力形式またはフレーム数が不正です')
        return dict(channels=channels, rate=rate, frames=data // align, encoding=encoding, bits=bits)


def pcm(path, channels, frames=None):
    import numpy as np
    need(path.stat().st_size % (channels * 4) == 0, 'RAWのバイト数/チャンネル数が不一致: ' + str(path))
    count = path.stat().st_size // (channels * 4)
    need(count > 0 and (frames is None or count == frames), 'RAWのフレーム数が不一致: ' + str(path))
    values = np.memmap(path, dtype='<f4', mode='r', shape=(count, channels))
    for begin in range(0, count, 262144):
        need(bool(np.isfinite(values[begin:begin + 262144]).all()), 'RAWにNaN/Inf: ' + str(path))
    return values


def equal(actual, expected, label, output, **location):
    import numpy as np
    need(actual.shape == expected.shape, label + ': フレーム数/全チャンネル形状が不一致')
    a, b = actual.view('<u4'), expected.view('<u4')
    if not np.array_equal(a, b):
        frame, channel = map(int, np.argwhere(a != b)[0])
        failure = dict(label=label, local_frame=frame, channel=channel,
                       actual_bits=int(a[frame, channel]), reference_bits=int(b[frame, channel]), **location)
        save(output / 'FIRST_MISMATCH.json', failure)
        raise ValueError(label + ': PCM bit不一致（FIRST_MISMATCH.json参照）')


class Equations:
    """製品ヘッダーを取り込まない独立式。丸め方は実行前に固定する。"""
    def __init__(self, contraction):
        import numpy as np
        self.f = np.float32
        self.contraction = contraction
        self.library = ctypes.CDLL(ctypes.util.find_library('m') or '/usr/lib/libSystem.B.dylib')
        self.fmaf = self.library.fmaf
        self.fmaf.argtypes = [ctypes.c_float] * 3
        self.fmaf.restype = ctypes.c_float

    def add_product(self, a, b, c):
        f = self.f
        if self.contraction == 'fused':
            return f(self.fmaf(float(a), float(b), float(c)))
        return f(f(a * b) + c)

    def smooth(self, t):
        f = self.f
        return f(f(t * t) * f(f(3) - f(f(2) * t)))

    def correction(self, values, offset, period, width, head, tail, last, first):
        f = self.f
        result = values.copy()
        if not head and not tail:
            return result
        for i in range(len(values)):
            at = offset + i
            for ch in range(values.shape[1]):
                middle = self.add_product(last[ch], f(.5), f(first[ch] * f(.5)))
                half = f(f(last[ch] - first[ch]) * f(.5))
                if head:
                    result[i, ch] = middle if at == 0 else self.add_product(
                        half, self.smooth(f(f(1) - f(f(at) / f(width)))), result[i, ch])
                if tail:
                    j = at - (period - width)
                    result[i, ch] = middle if j + 1 == width else self.add_product(
                        f(-half), self.smooth(f(f(j + 1) / f(width))), result[i, ch])
        return result

    def mix(self, fresh, old, offset, length):
        f = self.f
        result = fresh.copy()
        for i in range(len(old)):
            gain = f(f(offset + i + 1) / f(length))
            for ch in range(fresh.shape[1]):
                result[i, ch] = self.add_product(old[i, ch], f(f(1) - gain), f(fresh[i, ch] * gain))
        return result


def validate(args, output, checks):
    import numpy as np
    capture = args.capture
    host = read(capture / 'SUMMARY.json')
    declared = read(capture / 'EXPECTED.json')
    rows = json_lines(capture / 'measurements.jsonl')
    meta = read(args.reference_map)
    info = wav_info(args.input)
    channels, rate = info['channels'], info['rate']
    need(sha(args.reference_binary) == FIXED_SHA, '凍結固定参照実行体のSHAが違います')
    need(meta['channels'] == channels and meta['rate'] == rate and meta['input_frames'] == info['frames'],
         '参照と入力の形式/長さが違います')
    need(len(meta['positions']) == 2, '参照CLIへA/Bだけを順に渡してください（positionsは2件）')
    oa, ob = map(int, meta['positions'])
    period, width = ob - oa, min(rate // 200, (ob - oa) // 4)
    need(0 <= oa < ob <= meta['output_frames'] and period >= 512, '独立参照A/B/周期が不正です')
    cache_mode = 'raw' if period <= 96000 and not (declared['A'] == 0 and declared['B'] == info['frames']) else 'uncached'
    need(args.expected_cache_mode == 'any' or args.expected_cache_mode == cache_mode,
         '独立Mapの周期が予定した短RAW/96000超の非cache条件と違います')
    need(abs(declared['speed'] * 1000000 - args.speed_micros) < .001, '要求速度と参照宣言が違います')
    need(meta['output_frames'] == (info['frames'] * 1000000 + args.speed_micros // 2) // args.speed_micros,
         '固定参照の総出力長が違います')
    reference = pcm(args.reference_raw, channels, meta['output_frames'])
    need(sha(args.reference_raw) == meta['sha256'], '固定参照RAWと参照JSONのSHAが違います')
    checks['reference_identity'] = dict(status='PASS', input_A=declared['A'], input_B=declared['B'],
                                       independent_OA=oa, independent_OB=ob, period=period)
    need(host['status'] == 'PASS' and host.get('run_complete') in (True, 1), 'hostが正常完了していません')
    need(host['expected'] == host['executed'] == declared['expected'] == args.expected_rounds == len(rows),
         '予定round数と完了round数が違います')
    need(host['owners_peak'] <= 2 and host['owners_alive'] == 0, '所有者上限/最終退役が不正です')
    raw = pcm(capture / 'raw.f32', channels, host['raw_frames'])
    processed = pcm(capture / 'output_before_gain.f32', channels, host['output_frames'])
    records = json_lines(capture / 'raw_records.jsonl')
    spans = json_lines(capture / 'spans.jsonl')
    need(len(records) == host['raw_records'] and len(spans) == host['output_spans'], '記録件数が違います')
    need(len(records) <= 8192 and len(spans) <= 8192, 'host固定記録容量を超えています')
    raw_cursor = 0
    epoch_session, epoch_next, record_sources = {}, {}, []
    for i, record in enumerate(records):
        at, count, epoch = record['at'], record['frames'], record['epoch']
        need(0 < count <= 4096 and record['raw_offset'] == raw_cursor and 0 <= at < at + count <= len(reference),
             'RAW recordの空区間/欠落/重複/範囲外')
        need(epoch > 0 and record['session'] > 0, 'RAWのepoch/sessionが欠落')
        if epoch in epoch_session:
            need(epoch_session[epoch] == record['session'] and epoch_next[epoch] == at,
                 '同epochのsession変更またはRAW座標の欠落/重複')
        epoch_session[epoch], epoch_next[epoch] = record['session'], at + count
        equal(raw[raw_cursor:raw_cursor + count], reference[at:at + count], 'raw_exact', output,
              record=i, raw_offset=raw_cursor, absolute_reference_at=at)
        record_sources.append((epoch, at, count))
        raw_cursor += count
    need(raw_cursor == len(raw), 'RAW recordがファイル末尾まで覆っていません')
    checks['raw_all_bits'] = dict(status='PASS', frames=raw_cursor, channels=channels, records=len(records))
    equations = Equations(args.fp_contraction)
    output_cursor, span_sources, span_starts = 0, [], []
    for i, span in enumerate(spans):
        n, at, mixed = span['frames'], span['new_at'], span['mixed']
        need(0 < n <= 4096 and span['new_received'] == n and 0 <= at < at + n <= len(reference),
             '出力spanの空区間/不足/範囲外')
        need(0 <= mixed <= n and 0 <= span['old_received'] <= mixed, '混合長が不正です')
        if i:
            need(span['callback_frame'] == spans[i - 1]['callback_frame'] + spans[i - 1]['frames'],
                 'callback座標に欠落/重複があります')
        span_starts.append(output_cursor)
        span_sources.append((span['new_epoch'], at, n))
        expected = reference[at:at + n].copy()

        def corrected(values, old=False):
            prefix = 'old_' if old else ''
            periodic = flag(span, prefix + 'periodic')
            head, tail = flag(span, prefix + 'head'), flag(span, prefix + 'tail')
            need(not (head and tail) and (periodic or not (head or tail)), '境界補正flagが不正です')
            if not periodic:
                return values
            source_at = span['old_at'] if old else at
            need(span[prefix + 'period_frames'] == period and span[prefix + 'boundary_frames'] == width and
                 span[prefix + 'period_offset'] == source_at - oa and oa <= source_at < source_at + len(values) <= ob,
                 '独立Mapによる周期/補正幅/絶対座標と診断が不一致')
            if head or tail:
                need((head and source_at + len(values) <= oa + width) or
                     (tail and source_at >= ob - width), '補正窓をまたぐspanです')
                equal(np.asarray(span[prefix + 'boundary_last'][:channels], dtype='<f4').reshape(1, channels),
                      reference[ob - 1:ob], 'independent_last_endpoint', output, span=i, old=old)
                equal(np.asarray(span[prefix + 'boundary_first'][:channels], dtype='<f4').reshape(1, channels),
                      reference[oa:oa + 1], 'independent_first_endpoint', output, span=i, old=old)
            return equations.correction(values, source_at - oa, period, width, head, tail,
                                        reference[ob - 1], reference[oa])

        before_mix = flag(span, 'correction_before_mix')
        if before_mix:
            expected = corrected(expected)
        if mixed:
            need(span['old_received'] == mixed and span['old_epoch'] > 0,
                 '混合に必要な旧RAWが不足しています')
            old_at = span['old_at']
            need(0 <= old_at < old_at + mixed <= len(reference), '旧RAWの絶対座標が範囲外です')
            need(span['transition_length'] == rate // 200 and
                 0 <= span['transition_offset'] < span['transition_offset'] + mixed <= span['transition_length'],
                 '5ms進入混合の座標が違います')
            previous = corrected(reference[old_at:old_at + mixed], old=True)
            expected = equations.mix(expected, previous, span['transition_offset'], span['transition_length'])
            span_sources.append((span['old_epoch'], old_at, mixed))
        if not before_mix:
            expected = corrected(expected)
        equal(processed[output_cursor:output_cursor + n], expected, 'output_before_gain_exact', output,
              span=i, output_offset=output_cursor, absolute_reference_at=at)
        output_cursor += n
    need(output_cursor == len(processed), '出力spanがファイル末尾まで覆っていません')
    need(record_sources == span_sources, 'RAW observer区間と出力spanの新/旧入力座標が一致しません')
    checks['output_all_bits'] = dict(status='PASS', frames=output_cursor, channels=channels, spans=len(spans),
                                    mixed_frames=sum(span['mixed'] for span in spans), final_gain_applied=False)
    checks['interval_coordinates'] = dict(status='PASS', raw_records_match_span_sources=True)
    previous_raw = previous_output = 0
    round_results = []
    for index, row in enumerate(rows):
        need(row['round'] == index and row['raw_begin'] == previous_raw and row['output_begin'] == previous_output,
             'roundの記録境界が欠落/重複しています')
        need(row['output_start'] == oa and row['period_frames'] == period and row['missing'] == row['callback_new'] == 0,
             'roundの独立Map座標または品質監査が不一致')
        begin, end = row['output_begin'], row['output_end']
        selected = [(start, span) for start, span in zip(span_starts, spans) if begin <= start < end]
        need(selected and selected[0][0] == begin and selected[-1][0] + selected[-1][1]['frames'] == end,
             'round境界がspan境界と一致しません')
        first_epoch, first_session = row['epoch'], row['session']
        entering = [(start, span) for start, span in selected if span['new_epoch'] == first_epoch]
        need(entering, '初回Aのepochが出力にありません')
        entry_begin = entering[0][0]
        need(args.allow_playing_entry or entry_begin == begin, '測定roundに未宣言のPlaying旧出力があります')
        for start, span in selected:
            if start < entry_begin:
                continue  # 旧通常出力も上の全bit/RAW対照からは除外しない。
            relative = start - entry_begin
            cycle, local = divmod(relative, period)
            need(span['new_at'] == oa + local and local + span['frames'] <= period,
                 'A/Bの欠落・重複または余分な周回です')
            need(epoch_session[span['new_epoch']] == first_session and
                 (span['new_epoch'] == first_epoch) == (cycle == 0), '初回epoch/周回epoch/sessionの対応が不正')
            expected_tail = local >= period - width
            expected_head = cycle > 0 and local < width
            need(flag(span, 'periodic') and flag(span, 'tail') == expected_tail and flag(span, 'head') == expected_head,
                 '独立位置から求めた初回/周回の補正窓と診断が不一致')
            need(local + span['frames'] <= (width if expected_head else period if expected_tail else period - width),
                 '独立補正窓の境界をspanがまたいでいます')
        cycles, remainder = divmod(end - entry_begin, period)
        need(cycles == row['cycles'] and cycles >= args.min_cycles, '自然周回数または必要3周期が不足')
        need(row['raw_end'] - row['raw_begin'] == sum(span['new_received'] + span['old_received'] for _, span in selected),
             'roundのRAW総長と新旧入力総長が不一致')
        if args.require_cache_hit and index:
            need(row['checkpoint_start'] > 0 and 0 <= row['cold_discarded_frames'] < 2048 and
                 row['checkpoint_start'] + row['cold_discarded_frames'] == oa,
                 '同prepareの初回A保存状態使用を確認できません')
        previous_raw, previous_output = row['raw_end'], end
        round_results.append(dict(round=index, completed_periods=cycles, final_partial_frames=remainder,
                                  old_playing_prefix_frames=entry_begin - begin,
                                  checkpoint_start=row['checkpoint_start'], cold_discarded=row['cold_discarded_frames']))
    need(previous_raw == len(raw) and previous_output == len(processed), 'roundが全captureを覆っていません')
    need(not args.require_cache_hit or len(rows) >= 2, 'cache-hit検証にはClear後の再要求が必要です')
    checks['rounds_and_cycles'] = dict(status='PASS', rounds=round_results, minimum_cycles=args.min_cycles)
    if args.require_cache_hit:
        checks['static_cache_hit'] = dict(status='PASS', checked_rounds=list(range(1, len(rows))))
    if args.allow_playing_entry:
        need(any(span['mixed'] for span in spans), 'Playing entryを宣言しましたが進入混合がありません')
    return dict(input=info, frames=output_cursor, channels=channels, period_frames=period,
                independent_OA=oa, independent_OB=ob, independent_cache_condition=cache_mode,
                mixed_frames=sum(span['mixed'] for span in spans))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('capture', 'reference-raw', 'reference-map', 'reference-binary', 'input', 'host-binary', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--preset', choices=('baseline', 'candidate'), required=True)
    parser.add_argument('--speed-micros', type=int, required=True)
    parser.add_argument('--expected-rounds', type=int, required=True)
    parser.add_argument('--min-cycles', type=int, default=3)
    parser.add_argument('--require-cache-hit', action='store_true')
    parser.add_argument('--expected-cache-mode', choices=('raw', 'uncached', 'any'), default='any')
    parser.add_argument('--allow-playing-entry', action='store_true',
                        help='measurementsのbeginを要求前に置く形式。同速旧出力/進入混合も全bit比較する')
    parser.add_argument('--fp-contraction', choices=('fused', 'separate'), default='fused',
                        help='実行前に製品のビルド条件へ合わせる。結果を見て自動選択しない')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    ids = ['reference_identity', 'raw_all_bits', 'output_all_bits', 'interval_coordinates', 'rounds_and_cycles']
    if args.require_cache_hit:
        ids.append('static_cache_hit')
    checks, result, error = {}, {}, None
    try:
        paths = dict(input=args.input, reference_raw=args.reference_raw, reference_map=args.reference_map,
                     reference_binary=args.reference_binary, host_binary=args.host_binary, driver=Path(__file__))
        paths.update({name: args.capture / name for name in
                      ('EXPECTED.json', 'SUMMARY.json', 'measurements.jsonl', 'raw_records.jsonl', 'spans.jsonl',
                       'raw.f32', 'output_before_gain.f32')})
        save(args.output / 'EXPECTED.json', dict(suite='phase62_initial_static_exact_pcm', case_id=args.case_id,
             expected_ids=ids, expected=len(ids), expected_rounds=args.expected_rounds, minimum_cycles=args.min_cycles,
             input_and_artifacts={name: identity(path) for name, path in paths.items()},
             fixed_oracle_required_sha256=FIXED_SHA, preset=args.preset, speed_micros=args.speed_micros,
             expected_cache_mode=args.expected_cache_mode, allow_playing_entry=args.allow_playing_entry,
             fp_contraction=args.fp_contraction, python=sys.version, platform=platform.platform(),
             independent_DSP='既存凍結Phase36固定Exact。変更後DSPを参照に使用しない',
             final_output_gain='RAW/観測出力/参照とも0.5適用前',
             limitations=['静的固定速度・同入力のみ。動的Mapの品質証拠ではない', '物理出音・RT期限・一般公開承認は対象外']))
        need(1 <= args.expected_rounds <= 4 and args.min_cycles >= 0 and
             400000 <= args.speed_micros <= 2000000 and args.speed_micros % 10000 == 0, '試験宣言が不正')
        result = validate(args, args.output, checks)
    except Exception as exception:
        error = str(exception)
    for check_id in ids:
        checks.setdefault(check_id, dict(status='FAIL' if error else 'INCOMPLETE', reason=error))
    good = error is None and all(checks[key]['status'] == 'PASS' for key in ids)
    summary = dict(status='PASS' if good else 'FAIL', run_complete=True, case_id=args.case_id, expected=len(ids), executed=len(checks),
                   passed=sum(check['status'] == 'PASS' for check in checks.values()), checks=checks,
                   reason=error, result=result, physical_loopback='NOT_RUN', realtime_deadline='NOT_ASSESSED',
                   public_approved=False)
    save(args.output / 'SUMMARY.json', summary)
    print(json.dumps(dict(status=summary['status'], case_id=args.case_id, expected=len(ids),
                          passed=summary['passed'], reason=error), ensure_ascii=False))
    return 0 if good else 1


if __name__ == '__main__':
    raise SystemExit(main())
