#!/usr/bin/env python3
"""Fixed-gain listening excerpts; raw DSP files remain unmodified."""
import csv
import hashlib
from pathlib import Path
import numpy as np
from phase32_study import read,wav

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase36'
AUD=OUT/'audition';AUD.mkdir(exist_ok=True)
rows=[]
with (OUT/'transitions.csv').open(newline='') as file:
    transitions=list(csv.DictReader(file))
for row in transitions:
    if row['source'] not in ('mix','drums','vocal','bass','guitar'):continue
    name=f"{row['source']}_{row['initial'].replace('.','')}_{row['target'].replace('.','')}"
    rate,audio=read(OUT/'raw'/f'{name}.wav')
    at=int(row['applied_output'])
    left=max(0,at-2*rate);right=min(len(audio),at+3*rate)
    excerpt=np.array(audio[left:right]*0.5,dtype=np.float32,copy=True)
    fade=min(int(rate*0.003),len(excerpt)//2)
    if fade:
        ramp=np.linspace(0,1,fade,dtype=np.float32)
        excerpt[:fade]*=ramp[:,None]
        excerpt[-fade:]*=ramp[::-1,None]
    destination=AUD/f'{name}.wav'
    wav(destination,excerpt,rate)
    rows.append(dict(source=row['source'],initial=row['initial'],target=row['target'],
                     file=str(destination.relative_to(ROOT)),input_raw_sha=row['stream_sha'],
                     audition_sha=hashlib.sha256(destination.read_bytes()).hexdigest(),
                     gain=0.5,frames=len(excerpt),peak=float(np.max(np.abs(excerpt)))))
with (OUT/'audition.csv').open('w',newline='') as file:
    writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
    writer.writeheader();writer.writerows(rows)
