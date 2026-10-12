#!/usr/bin/env python3
"""Reproduce exact phase traces and the frozen crossover decomposition."""
import csv
import hashlib
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase33'
MODES = ('baseline', 'no_lock', 'no_reset', 'no_propagation')


def records(path):
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def write(path, rows):
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, check=True,
                            timeout=300)
    return dict(line.split('=', 1) for line in result.stdout.splitlines()
                if '=' in line)


def main():
    (OUT / 'trace').mkdir(parents=True, exist_ok=True)
    (OUT / 'crossover').mkdir(exist_ok=True)
    phase32 = {(r['source'], r['mode'], r['speed']): r
               for r in records(ROOT / 'results/phase32/renders.csv')}
    synthetic = {(r['source'], r['mode']): r
                 for r in records(OUT / 'synthetic_manifest.csv')}
    trace_rows = []
    crossover_rows = []
    with tempfile.TemporaryDirectory(prefix='phase33-measure-') as scratch:
        wav = Path(scratch) / 'trace.wav'
        for source in ('drums', 'mix', 'pink_decay', 'single_drum'):
            generated = source in ('pink_decay', 'single_drum')
            input_wav = ((OUT / 'input' / f'{source}.wav') if generated else
                         (ROOT / 'results/phase31/input' / f'{source}.wav'))
            for mode in MODES:
                key = f'{source}_{mode}_025'
                reference = ((OUT / 'synthetic' / f'{key}.wav') if generated else
                             (ROOT / 'results/phase32/raw' / f'{key}.wav'))
                expected = (synthetic[(source, mode)]['output_sha256'] if generated else
                            phase32[(source, mode, '0.25')]['output_sha256'])
                if digest(reference) != expected:
                    raise RuntimeError(f'Reference hash mismatch: {reference}')
                trace_dir = OUT / 'trace' / key
                stats = run(str(ROOT / 'build/phase33_trace'), str(input_wav),
                            str(wav), '0.25', mode, str(trace_dir))
                actual = digest(wav)
                if actual != expected:
                    raise RuntimeError(f'Trace altered PCM: {key}')
                if not generated:
                    old = phase32[(source, mode, '0.25')]
                    if stats['map_hash'] != old['map_hash'] or stats['events'] != old['events']:
                        raise RuntimeError(f'Trace changed event map: {key}')
                trace_rows.append(dict(source=source, mode=mode, speed='0.25',
                                       sha256=actual, matches_reference=True,
                                       frames=stats['output_frames'],
                                       events=stats['events'], map_hash=stats['map_hash']))
                if not generated:
                    raw = ROOT / 'results/phase32/raw'
                    prefix = OUT / 'crossover' / key
                    info = run(str(ROOT / 'build/phase33_crossover'),
                               str(raw / f'{key}_low.wav'),
                               str(raw / f'{key}_mid.wav'),
                               str(raw / f'{key}_high.wav'),
                               str(reference), str(prefix))
                    if float(info['max_reconstruction_difference']) >= 1e-5:
                        raise RuntimeError(f'Crossover error: {key}')
                    crossover_rows.append(dict(source=source, mode=mode, speed='0.25',
                                               **info))
                print(key, 'exact trace', flush=True)
    write(OUT / 'trace_audit.csv', trace_rows)
    write(OUT / 'crossover.csv', crossover_rows)


if __name__ == '__main__':
    main()
