#!/usr/bin/env python3
"""Read-only SHA-256 audit of the 25 frozen Golden and Phase 36 stream WAVs."""
import csv
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase37'

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1<<20),b''):digest.update(block)
    return digest.hexdigest()

def main():
    rows=[]
    for manifest in ('results/phase12/golden/manifest.csv',
                     'results/phase28/golden/manifest.csv'):
        for entry in csv.DictReader((ROOT/manifest).open()):
            if entry['speed'] not in ('0.50','0.60','0.70','0.75','0.80'):continue
            reference=ROOT/entry['output_path']
            stream=ROOT/'results/phase36/raw'/f'golden_{entry["name"]}_{entry["speed"].replace(".","")}.wav'
            expected=entry['output_sha256']
            golden=sha(reference)
            streamed=sha(stream)
            rows.append(dict(source=entry['name'],speed=entry['speed'],
                manifest_sha=expected,golden_sha=golden,stream_sha=streamed,
                equal=expected==golden==streamed))
            if not rows[-1]['equal']:
                raise RuntimeError(f'Golden mismatch: {reference}')
    if len(rows)!=25:raise RuntimeError(f'Expected 25 Golden WAVs, saw {len(rows)}')
    with (OUT/'golden_audit.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    print('25/25 Golden WAV and streamed SHA-256 matches')

if __name__=='__main__':main()
