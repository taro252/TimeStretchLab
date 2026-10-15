"""Frozen one-shot reference vs persistent incremental state; no product DSP."""
import argparse
import array
import csv
import hashlib
import json
from pathlib import Path
import statistics
import struct
import subprocess
import sys
import tempfile
from phase55_study import ROOT, motif, write_wav

CHUNKS = ['1024', '7168', '8192', '32768', '131072', 'irregular', '5003']


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def pulse_payload(rate, channels, encoding, seconds, chain):
    data = array.array('h' if encoding == 1 else 'f', [0]) * (rate * seconds * channels)
    step = 4096 if chain else int(rate * .2)
    for i in range(3073, rate * seconds, step):
        for c in range(channels):
            value = .7 if c == 0 else .53
            data[i * channels + c] = round(value * 32767) if encoding == 1 else value
    if sys.byteorder != 'little':
        data.byteswap()
    return data.tobytes()


def invoke(command, log):
    p = subprocess.run(list(map(str, command)), text=True, capture_output=True, timeout=600)
    log.write_text(p.stdout + p.stderr)
    if p.returncode:
        raise RuntimeError(f'Failed ({p.returncode}): {command}; {log}')
    return json.loads(p.stdout)


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    reference = args.reference.resolve()
    binary = args.binary.resolve()
    frozen_sha = digest(reference)
    ref_dir = ROOT / 'build/phase56_references' / frozen_sha
    ref_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    if args.suite in ('smoke', 'short'):
        formats = [(48000, 1, 3)] if args.suite == 'smoke' else [(r, c, e) for r in (44100, 48000) for c in (1, 2) for e in (1, 3)]
        for rate, channels, encoding in formats:
            for kind in (['boundary', 'sustained', 'chain'] if args.suite == 'smoke' else ['silence', 'impulse', 'train', 'sustained', 'boundary', 'chain']):
                name = f'{kind}_{encoding}_{channels}_{rate}'
                path = args.output / (name + '.wav')
                payload = pulse_payload(rate, channels, encoding, 4, kind == 'chain') if kind in ('chain', 'train') else motif(rate, channels, encoding, kind)
                write_wav(path, rate, channels, encoding, payload)
                cases.append((name, path, 'synthetic 4s'))
        if args.suite == 'short':
            for count in (0, 1, 17, 1023, 1024, 2047, 2048, 2049):
                path = args.output / f'tiny_{count}.wav'
                write_wav(path, 48000, 1, 3, array.array('f', [.5] * count).tobytes())
                cases.append((f'tiny_{count}', path, 'synthetic tiny'))
    elif args.suite == 'long':
        for case in json.loads((ROOT / 'results/phase55/long/summary.json').read_text()):
            path = ROOT / 'results/phase55/long' / case['name'] / 'full.wav'
            cases.append((case['name'], path, 'repeated synthetic'))
        path = args.output / 'chain_300s.wav'
        write_wav(path, 48000, 1, 3, pulse_payload(48000, 1, 3, 300, True))
        cases.append(('chain_300s', path, 'synthetic chain 300s'))
    elif args.suite == 'natural':
        for name in ('mix', 'drums', 'vocal', 'bass', 'guitar'):
            cases.append((name, ROOT / 'results/phase31/input' / (name + '.wav'), 'existing natural excerpt 10s'))
    elif args.suite == 'performance':
        cases = [('mix_290s', ROOT / 'results/phase55/input/mix_290_pcm16.wav', 'repeated real excerpt PCM16 290s'),
                 ('chain_300s', ROOT / 'results/phase56/long/chain_300s.wav', 'synthetic chain 300s')]
    elif args.suite == 'final':
        for suite in ('short_final', 'long_final', 'natural_final'):
            for case in json.loads((ROOT / 'results/phase56' / suite / 'summary.json').read_text()):
                m = json.loads((ROOT / 'results/phase56' / suite / case['name'] / 'reference_manifest.json').read_text())
                cases.append((case['name'], Path(m['input']), case['kind']))
    results = []
    for name, path, kind in cases:
        case_dir = args.output / name
        case_dir.mkdir()
        source_sha = digest(path)
        ref = ref_dir / (source_sha + '.bin')
        # Always regenerate using the frozen executable: no current-code oracle.
        ref_timing = invoke([reference, path, ref], case_dir / 'reference.log')
        ref_sha = digest(ref)
        (case_dir / 'reference_manifest.json').write_text(json.dumps(dict(
            baseline='14d30be6a7a2dc164eead5a5d747c60fba806b49', binary_sha256=frozen_sha,
            incremental_binary_sha256=digest(binary),
            input=str(path.resolve()), input_sha256=source_sha, reference=str(ref),
            reference_sha256=ref_sha, kind=kind, speed_micros=list(range(400000,2000001,10000))), indent=2) + '\n')
        chunks = CHUNKS if args.suite != 'smoke' else ['1024', 'irregular', '131072']
        repeats = 5 if args.suite == 'performance' else 1
        measurements = []
        if args.suite == 'performance':
            full_runs = [ref_timing]
            for repeat in range(1, repeats):
                full_runs.append(invoke([reference, path, ref], case_dir / f'reference_{repeat}.log'))
                assert digest(ref) == ref_sha
            (case_dir / 'full_runs.json').write_text(json.dumps(full_runs, indent=2) + '\n')
        for chunk in chunks:
            for repeat in range(repeats):
                trace = case_dir / f'{chunk}_{repeat}.csv'
                command = [binary, path, ref, chunk, trace]
                if args.suite == 'performance':
                    command.append('bench')
                row = invoke(command, case_dir / f'{chunk}_{repeat}.log')
                if not row['PASS'] or row['final_sha256'] != ref_sha or row['speed_count'] != 161:
                    raise RuntimeError(f'Bit/hash mismatch: {name} {chunk}')
                row.update(chunk=chunk, repeat=repeat)
                measurements.append(row)
        result = dict(name=name, kind=kind, input_sha256=source_sha, reference_sha256=ref_sha,
                      runs=len(measurements), PASS=True, measurements=measurements)
        (case_dir / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
        results.append(result)
        (args.output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
        print(name, len(measurements), 'PASS', flush=True)
    if not results:
        raise RuntimeError('No cases selected')
    if args.suite == 'performance':
        groups = []
        for case in results:
            for chunk in CHUNKS:
                rows = [r for r in case['measurements'] if r['chunk'] == chunk]
                item = dict(name=case['name'], chunk=chunk, n=len(rows))
                for metric in ('wall_seconds', 'thread_cpu_seconds', 'first_closed_event_seconds',
                               'first_map_interval_seconds', 'max_no_map_advance_seconds', 'peak_rss_bytes',
                               'snapshot_peak_bytes', 'snapshot_copy_bytes', 'pcm_copy_bytes', 'max_unclosed_input_frames'):
                    values = [r[metric] for r in rows]
                    item[metric] = dict(median=statistics.median(values), maximum=max(values), population_stddev=statistics.pstdev(values))
                groups.append(item)
        (args.output / 'statistics.json').write_text(json.dumps(groups, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--suite', choices=['smoke', 'short', 'long', 'natural', 'performance', 'final'], required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--binary', type=Path, default=ROOT / 'build/phase56_check')
    p.add_argument('--reference', type=Path, default=ROOT / 'build/phase56_frozen/reference_percent')
    run(p.parse_args())
