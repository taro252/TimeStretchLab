"""Phase55 isolated prefix experiments. Standard library; never edits Golden.

WAVs are reproducible synthetic fixtures, not recordings of natural songs.
Snapshots reanalyse growing prefixes, so timings are NOT incremental throughput.
"""
import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def write_wav(path, rate, channels, encoding, payload):
    width = 2 if encoding == 1 else 4
    header = b'RIFF' + struct.pack('<I', 36 + len(payload)) + b'WAVEfmt '
    header += struct.pack('<IHHIIHH', 16, encoding, channels, rate,
                          rate * channels * width, channels * width, width * 8)
    path.write_bytes(header + b'data' + struct.pack('<I', len(payload)) + payload)


def motif(rate, channels, encoding, kind):
    data = array.array('h' if encoding == 1 else 'f')
    attacks = [int(rate * t) for t in (.15, .45, .8, 1.48, 1.50, 1.52,
                                      2.45, 2.50, 2.52, 3.45, 3.50, 3.52, 3.95)]
    for i in range(rate * 4):
        if kind == 'silence':
            value = 0.
        elif kind == 'impulse':
            value = .8 if i == int(rate * .83) else 0.
        elif kind == 'sustained':
            value = (.12 * math.sin(2 * math.pi * 437.3 * i / rate)
                     if i > rate // 5 else 0.)
            if i == int(3.7 * rate):
                value += .7
        else:
            value = .07 * math.sin(2 * math.pi * 437.3 * i / rate)
            for onset in attacks:
                distance = i - onset
                if 0 <= distance < 180:
                    value += .55 * math.exp(-distance / 30) * math.cos(distance * 1.731)
            if i == rate * 4 - 3:  # a real EOS-adjacent transient
                value += .7
        for c in range(channels):
            v = value if c == 0 else value * .77
            data.append(round(v * 32767) if encoding == 1 else v)
    if sys.byteorder != 'little':
        data.byteswap()
    return data.tobytes()


def run_probe(binary, output, rate, channels, encoding, kind, seconds, pcm):
    name = f'{kind}_{encoding}_{channels}_{rate}_{seconds}'
    case = output / name
    case.mkdir()
    block = motif(rate, channels, encoding, kind)
    payload = (block * math.ceil(seconds / 4))[:seconds * rate * channels * (2 if encoding == 1 else 4)]
    full = case / 'full.wav'
    write_wav(full, rate, channels, encoding, payload)
    boundaries = [1.5, 2.5, 3.5] if seconds == 4 else [1.5, 5.125, seconds / 2 + .031, seconds - .02]
    prefixes = []
    for j, t in enumerate(boundaries):
        path = case / f'prefix_{j}.wav'
        count = int(t * rate)
        write_wav(path, rate, channels, encoding, payload[:count * channels * (2 if encoding == 1 else 4)])
        prefixes.append(path)
    # A separately analysed EOF snapshot is an identity control, not proof of
    # a live incremental renderer or proof of all earlier published samples.
    prefixes.append(full)
    cmd = [str(binary), 'pcm' if pcm else 'map', str(full), *map(str, prefixes)]
    (case / 'command.json').write_text(json.dumps(cmd, indent=2) + '\n')
    with (case / 'rows.jsonl').open('w') as out, (case / 'stderr.log').open('w') as err:
        result = subprocess.run(cmd, stdout=out, stderr=err, timeout=1200)
    rows = [json.loads(line) for line in (case / 'rows.jsonl').read_text().splitlines()]
    expected = len(prefixes) * 7 * (2 if pcm else 1)
    summary = dict(name=name, exit=result.returncode, rate=rate, channels=channels,
                   encoding=encoding, kind=kind, seconds=seconds, pcm=pcm,
                   source_sha256=hashlib.sha256(full.read_bytes()).hexdigest(),
                   expected_rows=expected, rows=len(rows),
                   sealed_crop_checks=sum(r['sealed_pcm_frames'] > 0 for r in rows if not r['eof']),
                   map_counterexamples=sum(r['first_map_difference'] >= 0 for r in rows if not r['eof']),
                   pcm_counterexamples=sum(r['first_pcm_interleaved_sample'] >= 0 for r in rows if not r['eof']),
                   PASS=result.returncode == 0 and len(rows) == expected)
    (case / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--binary', type=Path, default=ROOT / 'build/phase55_analysis_probe')
    parser.add_argument('--suite', choices=['smoke', 'short', 'long', 'special', 'performance'], required=True)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    if args.suite == 'performance':
        if args.input is None:
            parser.error('--input required for performance')
        for preset in ('candidate', 'baseline'):
            for attempt in range(5):
                # Alternate order to reduce simple ordering/cache bias.
                for mode in (('sync', 'async') if attempt % 2 == 0 else ('async', 'sync')):
                    command = [str(args.binary), str(args.input), mode, preset, '.5']
                    proc = subprocess.run(command, text=True, capture_output=True, timeout=120)
                    (args.output / f'{preset}_{mode}_{attempt}.log').write_text(proc.stdout + proc.stderr)
                    if proc.returncode:
                        raise RuntimeError(f'performance command failed: {command}')
                    rows = [dict(json.loads(line), preset=preset, mode=mode, attempt=attempt)
                            for line in proc.stdout.splitlines()]
                    if len(rows) != 2:
                        raise RuntimeError('Cold/Warm records missing')
                    for warm, row in enumerate(rows):
                        if (row['warm_analysis_cache'] != warm or row['analysis_runs'] != 1
                                or bool(row['cache_hit']) != bool(warm)
                                or row['missing_frames'] != 0 or row['rejected_writes'] != 0):
                            raise RuntimeError('Performance cache/supply invariant failed')
                    results.extend(rows)
        summary = []
        for preset in ('candidate', 'baseline'):
            for mode in ('sync', 'async'):
                for warm in (0, 1):
                    rows = [r for r in results if r['preset'] == preset and r['mode'] == mode
                            and r['warm_analysis_cache'] == warm]
                    group = dict(preset=preset, mode=mode, warm_analysis_cache=warm, n=len(rows))
                    for metric in ('dispatch_seconds', 'playable_seconds', 'prepare_seconds',
                                   'analysis_seconds', 'identity_seconds', 'analysis_completed_by_prepare_seconds',
                                   'identity_analysis_stages_seconds',
                                   'first_offline_pull_seconds', 'prefill_seconds', 'process_cpu_seconds',
                                   'peak_rss_bytes', 'analysis_bytes', 'cache_resident_bytes', 'worker_max_seconds'):
                        values = [r[metric] for r in rows]
                        group[metric] = dict(median=statistics.median(values), maximum=max(values),
                                             population_stddev=statistics.pstdev(values))
                    summary.append(group)
        (args.output / 'raw.json').write_text(json.dumps(results, indent=2) + '\n')
        (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        return
    formats = [(r, c, e) for r in (44100, 48000) for c in (1, 2) for e in (1, 3)]
    if args.suite == 'smoke':
        formats = [(48000, 1, 3)]
    for rate, channels, encoding in formats:
        if args.suite == 'special':
            cases = [('silence', 4, True), ('impulse', 4, True), ('sustained', 4, True)]
            # The special corpus is one format, documented separately.
            if (rate, channels, encoding) != (48000, 1, 3):
                continue
        elif args.suite == 'long':
            cases = [('boundary', 180, False), ('sustained', 300, False)]
        elif args.suite == 'smoke':
            cases = [('boundary', 4, False), ('sustained', 4, False)]
        else:
            cases = [('boundary', 4, True)]
        for kind, seconds, pcm in cases:
            row = run_probe(args.binary.resolve(), args.output.resolve(), rate, channels, encoding, kind, seconds, pcm)
            results.append(row)
            (args.output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
            print(row['name'], 'PASS' if row['PASS'] else 'FAIL', flush=True)
            if not row['PASS']:
                raise SystemExit(2)
    if not results or not all(r['PASS'] for r in results):
        raise SystemExit(2)
    if args.suite == 'smoke' and not any(r['map_counterexamples'] for r in results):
        raise SystemExit('Expected non-local TimeMap counterexample was not observed')


if __name__ == '__main__':
    main()
