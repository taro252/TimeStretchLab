#!/usr/bin/env python3
"""Silent device-callback matrix; raw DSP comparison is performed separately."""
import csv
import os
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase36'
PAIRS=(('0.40','0.50'),('0.50','0.40'),('0.45','0.50'),
       ('0.50','0.45'),('0.49','0.50'),('0.50','0.49'))
SOURCES=('mix','drums','vocal','bass','guitar')

def main():
    OUT.mkdir(exist_ok=True)
    schedule=OUT/'mac_matrix_schedule.csv'
    rows=[]
    for name in SOURCES:
        for initial,target in PAIRS:
            schedule.write_text(f'output_seconds,target_speed\n2.0,{target}\n')
            command=(ROOT/'build/phase36_play',
                     ROOT/f'results/phase31/input/{name}.wav',
                     initial,schedule,'6')
            result=subprocess.run(tuple(map(str,command)),capture_output=True,text=True,
                env={**os.environ,'PHASE36_SILENT':'1'},timeout=30)
            if result.returncode:
                raise RuntimeError(f'{name} {initial}->{target}: {result.stdout}\n{result.stderr}')
            data=dict(line.split('=',1) for line in result.stdout.splitlines()
                      if '=' in line and not line.startswith('change='))
            row=dict(source=name,initial=initial,target=target,**data)
            rows.append(row)
            for counter in ('underrun_frames','fifo_rejected_writes',
                            'callback_deadline_misses','callback_cpp_allocations',
                            'callback_format_errors'):
                if int(data[counter]):raise RuntimeError(f'{counter}: {row}')
            print(name,initial,target,data['apply_latency_median_ms'],flush=True)
    with (OUT/'mac_matrix.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)

if __name__=='__main__':main()
