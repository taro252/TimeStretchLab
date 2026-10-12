#!/usr/bin/env python3
"""Deterministic single-hit and exponentially decaying pink-noise controls."""
import csv
import hashlib
from pathlib import Path
import subprocess

import numpy as np

from phase32_study import read, wav

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase33'
RATE = 48000


def main():
    (OUT / 'input').mkdir(parents=True, exist_ok=True)
    (OUT / 'synthetic').mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(330025)
    n = RATE * 3
    noise = rng.standard_normal(n)
    frequencies = np.fft.rfftfreq(n, 1 / RATE)
    pink = np.fft.irfft(np.fft.rfft(noise) /
                       np.sqrt(np.maximum(frequencies, 25)), n=n)
    pink /= np.std(pink)
    onset = round(0.8 * RATE)
    t = np.arange(n - onset, dtype=np.float64) / RATE
    envelope = np.exp(-t / 0.35)
    pink_decay = np.zeros(n)
    pink_decay[onset:] = 0.22 * pink[onset:] * envelope
    single_drum = np.zeros(n)
    single_drum[onset] = 0.8
    single_drum[onset:] += 0.10 * np.sin(2 * np.pi * 75 * t) * np.exp(-t / 0.22)
    single_drum[onset:] += 0.12 * noise[onset:] * envelope
    rows = []
    for name, mono in (('pink_decay', pink_decay), ('single_drum', single_drum)):
        # Shared time position and stereo offset are fixed for all modes.
        stereo = np.stack((mono, np.roll(mono, 2)), axis=1)
        stereo[:2, 1] = 0
        source = OUT / 'input' / f'{name}.wav'
        wav(source, stereo)
        for mode in ('baseline', 'no_lock', 'no_reset', 'no_propagation'):
            target = OUT / 'synthetic' / f'{name}_{mode}_025.wav'
            run = subprocess.run((str(ROOT / 'build/phase32_render'),
                                  str(source), str(target), '0.25', mode),
                                 text=True, capture_output=True, check=True)
            rate, audio = read(target)
            if rate != RATE or len(audio) != round(n / 0.25) or not np.isfinite(audio).all():
                raise RuntimeError(f'Invalid synthetic render: {target}')
            rows.append(dict(source=name, mode=mode, speed=0.25,
                             input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                             output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                             frames=len(audio), peak=float(np.max(np.abs(audio))),
                             **{key: value for key, value in
                                (line.split('=', 1) for line in run.stdout.splitlines()
                                 if '=' in line) if key in ('elapsed_seconds', 'peak_rss_bytes')}))
            print(name, mode, flush=True)
    with (OUT / 'synthetic_manifest.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


if __name__ == '__main__':
    main()
