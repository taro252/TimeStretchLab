#!/usr/bin/env python3
"""Long-file high-speed TimeMap and DSP performance / EOS validation."""
import csv
import hashlib
import subprocess
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase37'
CASES=(('180','results/phase27/input/mix_180s.wav'),
       ('300','results/phase36/input/mix_300s.wav'),
       ('600','results/phase27/input/mix_600s.wav'))

def main():
    rows=[]
    for seconds,relative in CASES:
        source=ROOT/relative
        target=OUT/'raw'/f'mix_B_200_{seconds}s.wav'
        result=subprocess.run((str(ROOT/'build/phase37_render'),str(source),
                str(target),'2.00','B'),capture_output=True,text=True,timeout=900)
        (OUT/'logs'/f'mix_B_200_{seconds}s.log').write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError(f'{seconds}: {result.stderr}')
        data=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
        frames=int(data['output_frames'])
        if target.stat().st_size!=44+frames*8:
            raise RuntimeError(f'{seconds}: incorrect WAV bytes/EOS')
        audio=np.memmap(target,dtype='<f4',mode='r',offset=44,shape=(frames*2,))
        if not np.isfinite(audio).all():raise RuntimeError(f'{seconds}: NaN or Inf')
        digest=hashlib.sha256()
        with target.open('rb') as file:
            for block in iter(lambda:file.read(1<<20),b''):digest.update(block)
        row=dict(input_seconds=seconds,**data,output_sha256=digest.hexdigest(),
                 peak=float(np.max(np.abs(audio))))
        rows.append(row)
        print(seconds,'seconds:',data['output_frames'],'frames,',
              data['dsp_seconds'],'DSP seconds',flush=True)
    with (OUT/'long.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)

if __name__=='__main__':main()
