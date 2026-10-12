#!/usr/bin/env python3
"""Verify raw/audition identities, then copy unchanged clips into blind sets."""
import csv
import hashlib
from pathlib import Path
import random
import shutil

import numpy as np

from phase32_study import read, wav

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase33'
PHASE31 = ROOT / 'results/phase31'
PHASE32 = ROOT / 'results/phase32'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def table(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def csv_out(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'blind').mkdir(exist_ok=True)
    old = {(r['source'], r['speed']): r for r in table(PHASE31 / 'audio.csv')
           if r['mode'] == 'B' and r['speed'] in ('0.25', '0.30')}
    current = table(PHASE32 / 'renders.csv')
    raw_rows = []
    for row in current:
        speed = row['speed']
        name = row['source']
        mode = row['mode']
        path = PHASE32 / 'raw' / f'{name}_{mode}_{round(float(speed) * 100):03d}.wav'
        sha = digest(path)
        if sha != row['output_sha256']:
            raise RuntimeError(f'Phase 32 raw hash differs: {path}')
        baseline = old.get((name, speed)) if mode == 'baseline' else None
        baseline_sha = baseline['output_sha256'] if baseline else ''
        old_sha = digest(ROOT / baseline['path']) if baseline else ''
        if baseline and (old_sha != baseline_sha or old_sha != sha):
            raise RuntimeError(f'Phase 31 B identity differs: {path}')
        raw_rows.append(dict(source=name, speed=speed, mode=mode,
                             phase31_sha256=old_sha, phase32_sha256=sha,
                             baseline_equal=bool(baseline)))
    csv_out(OUT / 'raw_audit.csv', raw_rows)

    manifest = table(PHASE32 / 'audition.csv')
    clip_rows = []
    for row in manifest:
        raw = PHASE32 / row['source_raw']
        clip = PHASE32 / row['audition']
        rate, audio = read(raw)
        start = round(float(row['input_start']) / float(row['speed']) * rate)
        end = round(float(row['input_end']) / float(row['speed']) * rate)
        expected = audio[start:end].copy() * np.float32(0.5)
        ramp = min(len(expected) // 2, round(rate * 0.003))
        if ramp:
            fade = np.linspace(0, 1, ramp, dtype=np.float32)
            expected[:ramp] *= fade[:, None]
            expected[-ramp:] *= fade[::-1, None]
        reconstructed = OUT / 'blind' / 'verification.tmp.wav'
        wav(reconstructed, expected, rate)
        raw_sha = digest(raw)
        manifest_sha = row['sha256']
        actual_sha = digest(clip)
        generated_sha = digest(reconstructed)
        reconstructed.unlink()
        if actual_sha != manifest_sha or generated_sha != manifest_sha:
            raise RuntimeError(f'Phase 32 audition is not the stated crop: {clip}')
        clip_rows.append(dict(region=row['region'], mode=row['mode'],
                              raw_sha256=raw_sha, audition_sha256=actual_sha,
                              crop_recreated=True, gain=0.5, edge_ramp_ms=3))
    csv_out(OUT / 'audition_audit.csv', clip_rows)

    # Stable random ordering is reproducible, but the mode names are kept only
    # in the separate key table. Audio bytes are copied without processing.
    rng = random.Random(330025)
    key_rows = []
    for region in sorted({r['region'] for r in manifest}):
        entries = [r for r in manifest if r['region'] == region]
        rng.shuffle(entries)
        for letter, row in zip('ABCD', entries):
            original = PHASE32 / row['audition']
            blind = OUT / 'blind' / region / f'{letter}.wav'
            blind.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, blind)
            if digest(blind) != row['sha256']:
                raise RuntimeError(f'Blind copy changed audio: {blind}')
            key_rows.append(dict(region=region, blind_file=str(blind.relative_to(OUT)),
                                 mode=row['mode'], sha256=row['sha256']))
    csv_out(OUT / 'blind_key.csv', key_rows)
    print(f'{len(raw_rows)} raw, {len(clip_rows)} audition, {len(key_rows)} blind hashes verified')


if __name__ == '__main__':
    main()
