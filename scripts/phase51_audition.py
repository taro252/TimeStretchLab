#!/usr/bin/env python3
"""Identical full inputs and common 0.5 gain; no normalization or DSP edit."""
from pathlib import Path
import json,hashlib
import numpy as np
from phase32_study import read,wav
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase51/audition'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'manifest.json').exists():raise SystemExit('Fresh output required')
    rows=[]
    pairs=[('drums_t1p85_third',ROOT/'results/phase51/counterfactual/C_L1/L1.wav',ROOT/'results/phase51/counterfactual/C_L1/L1_L2.wav')]
    pairs += [(s+'_040_to_200',ROOT/f'results/phase51/audio/{s}_L1/raw.wav',ROOT/f'results/phase51/audio/{s}_L1_L2/raw.wav') for s in ('mix','drums','vocal','guitar','bass')]
    for name,old,new in pairs:
        for label,file in [('current_L1',old),('L1_L2',new)]:
            rate,data=read(file);output=OUT/f'{name}_{label}.wav';wav(output,data*np.float32(.5),rate)
            rows.append(dict(name=name,label=label,path=str(output),raw=str(file),raw_sha256=hashlib.sha256(file.read_bytes()).hexdigest(),gain=.5,frames=len(data),rate=rate,peak=float(np.max(np.abs(data))*.5),nonfinite=int(np.sum(~np.isfinite(data)))))
    (OUT/'manifest.json').write_text(json.dumps(rows,indent=2));print('12 common-gain audition WAVs generated')
if __name__=='__main__':main()
