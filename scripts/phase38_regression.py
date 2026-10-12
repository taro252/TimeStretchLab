#!/usr/bin/env python3
"""Read-only Phase 37/Golden audit and independent long B rerenders."""
import csv
import hashlib
import subprocess

import numpy as np

from phase32_study import read
from phase37_study import ROOT, SOURCES
from phase38_burst_diagnostic import OUT


def digest(path):
    checksum=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1<<20),b''):
            checksum.update(block)
    return checksum.hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    audit=[]
    for item in csv.DictReader((ROOT/'results/phase37/renders.csv').open()):
        path=ROOT/item['output_path']
        current=digest(path)
        audit.append(dict(source=item['source'],speed=item['speed'],mode=item['mode'],
            expected_sha256=item['output_sha'],current_sha256=current,
            matched=current==item['output_sha']))
    golden=[]
    for item in csv.DictReader((ROOT/'results/phase37/golden_audit.csv').open()):
        golden_path=(ROOT/'results/phase12/golden'/f'{item["source"]}_{item["speed"]}.wav')
        # The exact manifest path is authoritative; older releases use a
        # different filename convention, so resolve it through the manifest.
        for manifest in ('results/phase12/golden/manifest.csv',
                         'results/phase28/golden/manifest.csv'):
            for entry in csv.DictReader((ROOT/manifest).open()):
                if entry['name']==item['source'] and entry['speed']==item['speed']:
                    golden_path=ROOT/entry['output_path']
        if digest(golden_path)!=item['manifest_sha']:
            raise RuntimeError(f'Golden changed: {golden_path}')
        golden.append(item)
    if len(golden)!=25:raise RuntimeError('Expected 25 Golden WAVs')
    if not all(x['matched'] for x in audit):
        raise RuntimeError('A Phase 37 comparison WAV has changed')
    with (OUT/'phase37_audit.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=audit[0],lineterminator='\n')
        writer.writeheader();writer.writerows(audit)

    cases=(('180','results/phase27/input/mix_180s.wav'),
           ('300','results/phase36/input/mix_300s.wav'),
           ('600','results/phase27/input/mix_600s.wav'))
    previous={r['input_seconds']:r for r in
              csv.DictReader((ROOT/'results/phase37/long.csv').open())}
    (OUT/'raw').mkdir(exist_ok=True)
    long=[]
    for seconds,relative in cases:
        source=ROOT/relative
        path=OUT/'raw'/f'mix_B_200_{seconds}s.wav'
        result=subprocess.run((str(ROOT/'build/phase37_render'),str(source),
            str(path),'2.00','B'),capture_output=True,text=True,check=True,timeout=300)
        details=dict(line.split('=',1) for line in result.stdout.splitlines()
                     if '=' in line)
        rate,x=read(source)
        _,y=read(path)
        matches=digest(path)==previous[seconds]['output_sha256']
        valid=len(y)==round(len(x)/2) and np.isfinite(y).all()
        if not matches or not valid:raise RuntimeError(f'{seconds}s long EOS regression')
        long.append(dict(input_seconds=seconds,sha256=digest(path),matched=matches,
            expected_frames=round(len(x)/2),finite=valid,**details))
    with (OUT/'long.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=long[0],lineterminator='\n')
        writer.writeheader();writer.writerows(long)
    print(f'{len(audit)} Phase 37 raw hashes, 25 Golden hashes, {len(long)} EOS cases passed')


if __name__=='__main__':main()
