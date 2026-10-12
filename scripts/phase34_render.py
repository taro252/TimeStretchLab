#!/usr/bin/env python3
"""Render the frozen 0.50 reference and Phase 31 B at 0.40–0.49."""
import csv
import hashlib
from pathlib import Path
import random
import subprocess
import tempfile
import time

import numpy as np

from phase32_study import read, wav

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase34'
SOURCES = ('mix', 'drums', 'vocal', 'bass', 'guitar', 'click',
           'decay_noise', 'harmonic')
SPEEDS = ('0.40', '0.45', '0.49', '0.50')
REGIONS = {
    'mix_busy': ('mix', 2.9, 4.2),
    'mix_quiet': ('mix', 4.2, 4.8),
    'drums_attack': ('drums', 3.77, 4.02),
    'drums_tail': ('drums', 4.05, 4.35),
    'vocal_vowel': ('vocal', 3.2, 3.85),
}
GAIN = np.float32(0.5)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path):
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def write(path, records):
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)


def run(*args):
    started = time.monotonic()
    result = subprocess.run(args, capture_output=True, text=True, check=True,
                            timeout=300)
    details = dict(line.split('=', 1) for line in result.stdout.splitlines()
                   if '=' in line)
    details['measured_wall_seconds'] = f'{time.monotonic()-started:.6f}'
    return details


def bass_sustain():
    rate, data = read(ROOT / 'results/phase31/input/bass.wav')
    mono = np.mean(data, axis=1)
    duration = round(.65 * rate)
    hop = round(.05 * rate)
    candidates = []
    for start in range(rate, min(len(mono)-duration, 9*rate), hop):
        segment = mono[start:start+duration]
        windows = segment[:(len(segment)//hop)*hop].reshape(-1, hop)
        rms = np.sqrt(np.mean(windows.astype(np.float64)**2, axis=1))
        overall = float(np.mean(rms))
        if overall < .015:
            continue
        variation = float(np.std(np.log(np.maximum(rms, 1e-7))))
        candidates.append((variation, -overall, start))
    if not candidates:
        raise RuntimeError('No audible bass sustain found')
    start = min(candidates)[2] / rate
    return 'bass', start, start + .65


def main():
    for folder in ('raw', 'trace', 'audition', 'blind'):
        (OUT / folder).mkdir(parents=True, exist_ok=True)
    regions = dict(REGIONS)
    regions['bass_sustain'] = bass_sustain()
    old = {(r['source'], r['mode'], f"{float(r['speed']):.2f}"): r
           for r in rows(ROOT / 'results/phase31/audio.csv')}
    manifest = []
    with tempfile.TemporaryDirectory(prefix='phase34-') as scratch:
        traced = Path(scratch) / 'trace.wav'
        for source in SOURCES:
            input_path = ((ROOT / 'results/phase32/input' / f'{source}.wav')
                          if source in ('decay_noise', 'harmonic') else
                          (ROOT / 'results/phase31/input' / f'{source}.wav'))
            rate, input_audio = read(input_path)
            for speed in SPEEDS:
                mode = 'A' if speed == '0.50' else 'B'
                key = f'{source}_{mode}_{speed.replace(".", "")}'
                target = OUT / 'raw' / f'{key}.wav'
                stats = run(str(ROOT / 'build/phase31_render'), str(input_path),
                            str(target), speed, mode)
                trace_dir = OUT / 'trace' / key
                trace_stats = run(str(ROOT / 'build/phase33_trace'), str(input_path),
                                  str(traced), speed, 'baseline', str(trace_dir))
                digest = sha(target)
                if sha(traced) != digest or stats['map_hash'] != trace_stats['map_hash']:
                    raise RuntimeError(f'Trace differs: {key}')
                previous = old.get((source, mode, speed))
                old_sha = previous['output_sha256'] if previous else ''
                if old_sha and old_sha != digest:
                    raise RuntimeError(f'Phase 31 changed: {key}')
                output_rate, audio = read(target)
                if output_rate != rate or len(audio) != round(len(input_audio)/float(speed)):
                    raise RuntimeError(f'Incorrect duration: {key}')
                if not np.isfinite(audio).all():
                    raise RuntimeError(f'Non-finite output: {key}')
                manifest.append(dict(source=source, speed=speed, mode=mode,
                                     input_sha256=sha(input_path), output_sha256=digest,
                                     previous_sha256=old_sha, rate=rate,
                                     input_frames=len(input_audio), output_frames=len(audio),
                                     peak=float(np.max(np.abs(audio))),
                                     events=stats['events'], map_hash=stats['map_hash'],
                                     user_cpu_seconds=stats['user_cpu_seconds'],
                                     system_cpu_seconds=stats['system_cpu_seconds'],
                                     dsp_elapsed_seconds=stats['elapsed_seconds'],
                                     measured_wall_seconds=stats['measured_wall_seconds'],
                                     peak_rss_bytes=stats['peak_rss_bytes']))
                print(key, 'verified', flush=True)
    write(OUT / 'renders.csv', manifest)

    # The same *input* performance interval is mapped through the exact Mid
    # TimeMap. A linear output-time crop would miss transient anchor shifts.
    audition = []
    blind_key = []
    rng = random.Random(340040)
    for region, (source, begin, end) in regions.items():
        files = []
        for speed in SPEEDS:
            mode = 'A' if speed == '0.50' else 'B'
            key = f'{source}_{mode}_{speed.replace(".", "")}'
            rate, audio = read(OUT / 'raw' / f'{key}.wav')
            trace = rows(OUT / 'trace' / key / 'mid.csv')
            input_positions = np.array([float(r['inputSample']) for r in trace])
            output_positions = np.array([float(r['outputSample']) for r in trace])
            a, b = np.rint(np.interp(np.array([begin, end])*rate,
                                     input_positions, output_positions)).astype(int)
            clip = audio[a:b].copy() * GAIN
            ramp = min(round(.003*rate), len(clip)//2)
            if ramp:
                fade = np.linspace(0, 1, ramp, dtype=np.float32)
                clip[:ramp] *= fade[:, None]
                clip[-ramp:] *= fade[::-1, None]
            dest = OUT / 'audition' / f'{region}_{speed.replace(".", "")}.wav'
            wav(dest, clip, rate)
            files.append((speed, dest))
            audition.append(dict(region=region, source=source, input_begin=begin,
                                 input_end=end, speed=speed, mode=mode,
                                 output_begin=int(a), output_end=int(b),
                                 frames=len(clip), gain=GAIN, edge_ramp_ms=3,
                                 peak=float(np.max(np.abs(clip))), sha256=sha(dest)))
        rng.shuffle(files)
        for letter, (speed, path) in zip('ABCD', files):
            blind = OUT / 'blind' / region / f'{letter}.wav'
            blind.parent.mkdir(parents=True, exist_ok=True)
            blind.write_bytes(path.read_bytes())
            blind_key.append(dict(region=region, blind_file=str(blind.relative_to(OUT)),
                                  speed=speed, sha256=sha(blind)))
    write(OUT / 'audition.csv', audition)
    write(OUT / 'blind_key.csv', blind_key)
    print(f'{len(manifest)} raw, {len(audition)} audition, {len(blind_key)} blind')


if __name__ == '__main__':
    main()
