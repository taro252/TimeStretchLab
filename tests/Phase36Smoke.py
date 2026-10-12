#!/usr/bin/env python3
"""Synthetic callback, replay and lifecycle regression without private audio."""
import math
import csv
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

def write_float_wav(path,rate=48000,seconds=6):
    values=[]
    for i in range(rate*seconds):
        t=i/rate
        burst=0.2*math.exp(-350*max(0,t-2.4)) if 2.4<=t<2.5 else 0
        values.extend((0.15*math.sin(2*math.pi*437.3*t)+burst,
                       0.12*math.sin(2*math.pi*437.3*t+0.3)+burst))
    payload=struct.pack('<'+str(len(values))+'f',*values)
    fmt=struct.pack('<HHIIHH',3,2,rate,rate*8,8,32)
    riff_size=4+8+len(fmt)+8+len(payload)
    path.write_bytes(b'RIFF'+struct.pack('<I',riff_size)+b'WAVE'+
                     b'fmt '+struct.pack('<I',len(fmt))+fmt+
                     b'data'+struct.pack('<I',len(payload))+payload)

def run(*args):
    result=subprocess.run(tuple(map(str,args)),capture_output=True,text=True,timeout=90)
    if result.returncode:
        raise RuntimeError(f'{args}: {result.stdout}\n{result.stderr}')
    return result.stdout

def main():
    sim,reference,api=map(Path,sys.argv[1:4])
    with tempfile.TemporaryDirectory(prefix='phase36-') as temporary:
        root=Path(temporary);source=root/'input.wav';write_float_wav(source)
        run(api,source)
        for speed in ('0.40','0.50'):
            output=root/f'fixed_{speed}.wav'
            text=run(sim,source,output,speed,'-',256)
            assert 'underrun=0' in text and 'rejected_writes=0' in text
        for initial,target,request in (('0.40','0.50','4:0.50'),
                                       ('0.50','0.40','3.2:0.40')):
            actual=root/f'{initial}_{target}.wav'
            expected=root/f'{initial}_{target}_reference.wav'
            plan=root/f'{initial}_{target}.csv'
            run(sim,source,actual,initial,request,256,plan)
            run(reference,source,expected,initial,plan)
            assert actual.read_bytes()==expected.read_bytes()
            partition=root/'partition.wav';partition_plan=root/'partition.csv'
            assert 'underrun=0' in run(sim,source,partition,
                                       initial,request,1024,partition_plan)
            partition_reference=root/'partition_reference.wav'
            run(reference,source,partition_reference,initial,partition_plan)
            assert partition.read_bytes()==partition_reference.read_bytes()
            with plan.open(newline='') as file:
                first=list(csv.DictReader(file))[0]
            with partition_plan.open(newline='') as file:
                second=list(csv.DictReader(file))[0]
            if first['applied_frame']==second['applied_frame']:
                assert actual.read_bytes()==partition.read_bytes()
    print('Phase 36 synthetic callback, replay, lifecycle: passed')

if __name__=='__main__':main()
