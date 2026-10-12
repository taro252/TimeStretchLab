#!/usr/bin/env python3
"""Noise-burst onset regression for the unchanged Phase 37 A/B engines."""
import csv
import math
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

RATE = 48000


def wave(path):
    rng=random.Random(38)
    payload=bytearray()
    for frame in range(RATE*2):
        offset=frame-round(.6*RATE)
        length=round(.12*RATE)
        window=.5*(1-math.cos(2*math.pi*offset/(length-1))) if 0<=offset<length else 0
        value=.25*window*rng.uniform(-1,1)
        payload+=struct.pack('<ff',value,value)
    path.write_bytes(b'RIFF'+struct.pack('<I',36+len(payload))+b'WAVE'+
        b'fmt '+struct.pack('<IHHIIHH',16,3,2,RATE,RATE*8,8,32)+
        b'data'+struct.pack('<I',len(payload))+payload)


def run(*args):
    result=subprocess.run(tuple(map(str,args)),capture_output=True,text=True,timeout=60)
    if result.returncode:raise RuntimeError(result.stderr)
    return result.stdout


def power(path):
    data=path.read_bytes()
    values=struct.unpack('<'+str((len(data)-44)//4)+'f',data[44:])
    assert len(values)==RATE*2
    assert all(math.isfinite(v) for v in values)
    return [(values[2*i]**2+values[2*i+1]**2)/2 for i in range(RATE)]


def energy(p,start,milliseconds):
    a=max(0,round(start));b=min(len(p),a+round(RATE*milliseconds/1000))
    return sum(p[a:b])


def main():
    renderer,events=sys.argv[1:3]
    with tempfile.TemporaryDirectory(prefix='phase38-') as directory:
        root=Path(directory);source=root/'input.wav';wave(source)
        modes={}
        for mode in 'AB':
            output=root/f'{mode}.wav'
            run(renderer,source,output,'2.00',mode)
            p=power(output)
            trace=list(csv.DictReader(run(events,source,'2.00',mode).splitlines()))
            assert len(trace)==1 and trace[0]['anchor_confident']=='0'
            assert trace[0]['mapped_peak_sample']==trace[0]['ideal_output_sample']
            modes[mode]=(p,trace)
        ideal=round(.6*RATE/2)
        a,b=modes['A'][0],modes['B'][0]
        # The initial nominal window can miss the time-shifted B attack,
        # whereas the complete event energy remains present.
        assert energy(b,ideal,20)<energy(a,ideal,20)
        assert energy(b,ideal-2400,270)>energy(a,ideal-2400,270)*.8
    print('Phase 38 burst onset and complete-event energy: passed')


if __name__=='__main__':main()
