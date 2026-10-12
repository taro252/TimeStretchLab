#!/usr/bin/env python3
"""Research trace must not change PCM; crossover parts must reconstruct it."""
import hashlib
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def run(*arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f'{arguments}: {result.stderr}')
    return result.stdout


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    phase31, phase32, phase33, crossover = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix='phase33-') as tmp:
        directory = Path(tmp)
        source = directory / 'input.wav'
        frames = 48000
        pcm = bytearray()
        for i in range(frames):
            value = 0.3 * math.sin(2 * math.pi * 220 * i / 48000)
            if i == 12000:
                value += 0.4
            pcm += struct.pack('<ff', value, value * 0.8)
        source.write_bytes(b'RIFF' + struct.pack('<I', 36 + len(pcm)) +
                           b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 3, 2,
                                                     48000, 384000, 8, 32) +
                           b'data' + struct.pack('<I', len(pcm)) + pcm)
        reference = directory / 'reference.wav'
        baseline = directory / 'baseline.wav'
        traced = directory / 'traced.wav'
        run(phase31, source, reference, '0.25', 'B')
        run(phase32, source, baseline, '0.25', 'baseline', 'stems')
        run(phase33, source, traced, '0.25', 'baseline', directory / 'trace')
        if not (sha(reference) == sha(baseline) == sha(traced)):
            raise RuntimeError('Trace changed Phase 31 B output')
        output = run(crossover,
                     directory / 'baseline_low.wav',
                     directory / 'baseline_mid.wav',
                     directory / 'baseline_high.wav',
                     baseline, directory / 'component')
        info = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        if float(info['max_reconstruction_difference']) >= 1e-5:
            raise RuntimeError(f'Crossover decomposition error: {output}')
        for band in ('low', 'mid', 'high'):
            if not (directory / f'component_{band}.wav').exists():
                raise RuntimeError(f'Missing {band} crossover contribution')
            if not (directory / 'trace' / f'{band}.csv').exists():
                raise RuntimeError(f'Missing {band} phase trace')
    print('Phase 33: byte-exact trace and crossover reconstruction')


if __name__ == '__main__':
    main()
