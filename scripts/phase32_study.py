#!/usr/bin/env python3
"""Isolated Phase 32 render study. Run with the bundled NumPy Python."""
import csv
import hashlib
import math
from pathlib import Path
import struct
import subprocess
import sys
import time

import numpy as np

from phase31_study import chunks

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase32"
RATE = 48000


def wav(path, signal, rate=RATE):
    signal = np.asarray(signal, dtype='<f4')
    if signal.ndim == 1:
        signal = signal[:, None]
    channels = signal.shape[1]
    pcm = signal.tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' +
                     struct.pack('<IHHIIHH', 16, 3, channels, rate,
                                 rate * channels * 4, channels * 4, 32) +
                     b'data' + struct.pack('<I', len(pcm)) + pcm)


def read(path):
    parts = chunks(path)
    fmt = parts[b'fmt ']
    channels = struct.unpack_from('<H', fmt, 2)[0]
    rate = struct.unpack_from('<I', fmt, 4)[0]
    audio = np.frombuffer(parts[b'data'], dtype='<f4').reshape(-1, channels)
    return rate, audio


def synthetic():
    rng = np.random.default_rng(20261012)
    n = 6 * RATE
    t = np.arange(n, dtype=np.float64) / RATE
    # A true decaying tail begins at each isolated attack, without a second hit.
    hit = np.zeros(n)
    for onset in (int(0.6 * RATE), int(2.5 * RATE), int(4.4 * RATE)):
        length = min(RATE, n - onset)
        x = np.arange(length) / RATE
        hit[onset:onset + length] += np.exp(-x / 0.35)
    white = rng.standard_normal(n)
    # Shared noise seed makes the white/pink comparison deterministic.
    spectrum = np.fft.rfft(white)
    frequency = np.fft.rfftfreq(n, 1 / RATE)
    pink = np.fft.irfft(spectrum / np.sqrt(np.maximum(frequency, 25)), n=n)
    pink /= max(np.std(pink), 1e-12)
    envelope = np.zeros(n)
    for onset in (int(0.6 * RATE), int(2.5 * RATE), int(4.4 * RATE)):
        length = min(int(0.12 * RATE), n - onset)
        envelope[onset:onset + length] = np.hanning(length)
    harmonic = sum((0.45 / k) * np.sin(2 * np.pi * 110 * k * t)
                   for k in range(1, 9))
    signals = {
        'decay_noise': 0.22 * hit * white,
        'white_burst': 0.25 * envelope * white,
        'pink_burst': 0.25 * envelope * pink,
        'harmonic': harmonic,
    }
    for name, mono in signals.items():
        stereo = np.stack((mono, np.roll(mono, 3)), axis=1)
        stereo[:3, 1] = 0
        wav(OUT / 'input' / f'{name}.wav', stereo)


def main():
    for sub in ('input', 'raw', 'audition'):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    synthetic()
    sources = ('mix', 'drums', 'vocal', 'bass', 'guitar', 'click', 'sine',
               'decay_noise', 'white_burst', 'pink_burst', 'harmonic')
    renderer = ROOT / 'build/phase32_render'
    rows = []
    for source in sources:
        input_path = ((OUT / 'input' / f'{source}.wav') if source in
                      ('decay_noise', 'white_burst', 'pink_burst', 'harmonic') else
                      ROOT / 'results/phase31/input' / f'{source}.wav')
        rate, audio = read(input_path)
        input_sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
        for speed in ('0.25', '0.30'):
            modes = ['baseline', 'no_lock', 'no_reset']
            if source in ('mix', 'drums', 'decay_noise', 'harmonic'):
                modes.append('no_propagation')
            for mode in modes:
                key = f'{source}_{mode}_{speed.replace(".", "")}'
                output_path = OUT / 'raw' / f'{key}.wav'
                stems = mode in ('baseline', 'no_lock') and source in ('mix', 'drums')
                command = [str(renderer), str(input_path), str(output_path), speed, mode]
                if stems:
                    command.append('stems')
                started = time.monotonic()
                run = subprocess.run(command, capture_output=True, text=True, timeout=300)
                if run.returncode:
                    raise RuntimeError(f'{command}: {run.stderr}')
                info = dict(line.split('=', 1) for line in run.stdout.splitlines()
                            if '=' in line)
                output_rate, output = read(output_path)
                if (output_rate != rate or len(output) != round(len(audio) / float(speed))
                        or not np.isfinite(output).all()):
                    raise RuntimeError(f'Invalid output {output_path}')
                peak = float(np.max(np.abs(output)))
                sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
                rows.append(dict(source=source, speed=speed, mode=mode,
                                 input_sha256=input_sha, output_sha256=sha,
                                 input_frames=len(audio), output_frames=len(output),
                                 peak=peak, elapsed_wall_seconds=time.monotonic() - started,
                                 user_cpu_seconds=info['user_cpu_seconds'],
                                 system_cpu_seconds=info['system_cpu_seconds'],
                                 peak_rss_bytes=info['peak_rss_bytes'],
                                 events=info['events'], anchors=info['anchors'],
                                 map_hash=info['map_hash']))
                print(key, f'{rows[-1]["elapsed_wall_seconds"]:.2f}s', flush=True)
                if mode == 'baseline' and source in ('mix', 'drums', 'vocal',
                                                      'bass', 'guitar', 'click', 'sine'):
                    previous = ROOT / 'results/phase31/raw' / f'{source}_B_{speed.replace(".", "")}.wav'
                    if hashlib.sha256(previous.read_bytes()).hexdigest() != sha:
                        raise RuntimeError(f'Phase 31 baseline changed: {key}')
            with (OUT / 'renders.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator='\n')
                writer.writeheader()
                writer.writerows(rows)
    print(f'{len(rows)} research WAVs complete')


if __name__ == '__main__':
    main()
