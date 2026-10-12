#!/usr/bin/env python3
"""Full-duration macOS device runs, including a late transition into 0.40x."""
import csv
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase36'
CASES=(
    ('180','results/phase27/input/mix_180s.wav',170,False),
    ('300','results/phase36/input/mix_300s.wav',290,True),
    ('600','results/phase27/input/mix_600s.wav',590,False),
)

def main():
    rows=[]
    for label,relative,when,stress in CASES:
        schedule=OUT/f'mac_long_{label}_schedule.csv'
        schedule.write_text(f'output_seconds,target_speed\n{when},0.40\n')
        command=(ROOT/'build/phase36_play',ROOT/relative,'1.00',schedule)
        env={**os.environ,'PHASE36_SILENT':'1'}
        if stress:env['PHASE36_STRESS']='1'
        result=subprocess.run(tuple(map(str,command)),capture_output=True,text=True,
                              env=env,timeout=850)
        (OUT/f'mac_long_{label}.log').write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError(f'{label}: {result.stderr}')
        data=dict(line.split('=',1) for line in result.stdout.splitlines()
                  if '=' in line and not line.startswith('change='))
        row=dict(input_seconds=label,stress=stress,**data)
        rows.append(row)
        for counter in ('underrun_frames','fifo_rejected_writes',
                        'callback_deadline_misses','callback_cpp_allocations',
                        'callback_format_errors'):
            if int(data[counter]):raise RuntimeError(f'{label}: {counter}={data[counter]}')
        if data['eos_drained']!='1':
            raise RuntimeError(f'{label}: EOS not drained')
        print(label,'EOS',data['presented_frames'],data['wall_seconds'],flush=True)
    with (OUT/'mac_long.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)

if __name__=='__main__':main()
