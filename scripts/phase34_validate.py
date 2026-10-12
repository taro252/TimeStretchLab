#!/usr/bin/env python3
"""Audit Phase 34 hashes, boundary references, silence and finite samples."""
import csv
import hashlib
from pathlib import Path

import numpy as np

from phase32_study import read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase34'


def rows(path):
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def longest_true_run(mask):
    padded = np.r_[False, mask, False]
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return int(np.max(edges[1::2]-edges[::2], initial=0))


def main():
    manifest = rows(OUT/'renders.csv')
    old = {r['source']: r for r in rows(ROOT/'results/phase31/boundary.csv')
           if r['speed']=='0.49'}
    checked = []
    for row in manifest:
        key = f"{row['source']}_{row['mode']}_{row['speed'].replace('.', '')}"
        path = OUT/'raw'/f'{key}.wav'
        rate, audio = read(path)
        if sha(path) != row['output_sha256'] or not np.isfinite(audio).all():
            raise RuntimeError(f'Hash/finite failure: {key}')
        if len(audio) != round(int(row['input_frames'])/float(row['speed'])):
            raise RuntimeError(f'Output length failure: {key}')
        if row['previous_sha256'] and row['previous_sha256'] != row['output_sha256']:
            raise RuntimeError(f'Previous reference failure: {key}')
        if row['speed']=='0.49' and row['source'] in old:
            if old[row['source']]['sha256'] != row['output_sha256']:
                raise RuntimeError(f'Phase 31 boundary reference differs: {key}')
        active=audio[rate:min(len(audio)-rate,len(audio))]
        both_silent=np.all(np.abs(active)<1e-7,axis=1)
        checked.append(dict(source=row['source'],speed=row['speed'],mode=row['mode'],
                            sha256=row['output_sha256'],finite=True,
                            duration_correct=True,
                            raw_peak=float(np.max(np.abs(audio))),
                            samples_over_one=int(np.count_nonzero(np.abs(audio)>1)),
                            max_adjacent_derivative=float(np.max(np.abs(np.diff(audio,axis=0)))),
                            longest_interior_both_channel_silence_ms=
                            1000*longest_true_run(both_silent)/rate))
    audition=rows(OUT/'audition.csv')
    blind=rows(OUT/'blind_key.csv')
    for row in audition:
        path=OUT/'audition'/f"{row['region']}_{row['speed'].replace('.', '')}.wav"
        if sha(path)!=row['sha256'] or float(row['peak'])>=1.0:
            raise RuntimeError(f'Audition copy invalid: {path}')
        key=f"{row['source']}_{row['mode']}_{row['speed'].replace('.', '')}"
        rate,raw=read(OUT/'raw'/f'{key}.wav')
        trace=rows(OUT/'trace'/key/'mid.csv')
        x=np.array([float(t['inputSample']) for t in trace])
        y=np.array([float(t['outputSample']) for t in trace])
        a,b=np.rint(np.interp(
            [float(row['input_begin'])*rate,float(row['input_end'])*rate],
            x,y)).astype(int)
        if a!=int(row['output_begin']) or b!=int(row['output_end']):
            raise RuntimeError(f'Audition input interval differs: {path}')
        expected=raw[a:b].copy()*np.float32(.5)
        ramp=min(round(.003*rate),len(expected)//2)
        if ramp:
            fade=np.linspace(0,1,ramp,dtype=np.float32)
            expected[:ramp]*=fade[:,None]
            expected[-ramp:]*=fade[::-1,None]
        _,actual=read(path)
        if not np.array_equal(expected,actual):
            raise RuntimeError(f'Audition signal processing differs: {path}')
    for row in blind:
        if sha(OUT/row['blind_file'])!=row['sha256']:
            raise RuntimeError(f'Blind copy invalid: {row}')
    with (OUT/'safety.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(checked[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(checked)
    print(f'{len(checked)} raw, {len(audition)} audition, {len(blind)} blind verified')


if __name__=='__main__': main()
