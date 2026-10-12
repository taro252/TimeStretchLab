#!/usr/bin/env python3
"""Self-contained high-speed map, waveform and boundary regression."""
import csv
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

def write(path,frames,click_spacing=0):
    values=[]
    for i in range(frames):
        value=.15*math.sin(2*math.pi*437.3*i/48000)
        if click_spacing and i>=12000 and (i-12000)%click_spacing==0:value+=.8
        values.extend((value,value))
    payload=struct.pack('<'+str(len(values))+'f',*values)
    path.write_bytes(b'RIFF'+struct.pack('<I',36+len(payload))+b'WAVE'+
        b'fmt '+struct.pack('<IHHIIHH',16,3,2,48000,48000*8,8,32)+
        b'data'+struct.pack('<I',len(payload))+payload)

def run(*args):
    result=subprocess.run(tuple(map(str,args)),capture_output=True,text=True,timeout=60)
    if result.returncode:raise RuntimeError(f'{args}: {result.stderr}')
    return result.stdout

def data(path):
    raw=path.read_bytes()
    return struct.unpack('<'+str((len(raw)-44)//4)+'f',raw[44:])

def main():
    renderer,frozen=map(Path,sys.argv[1:3])
    with tempfile.TemporaryDirectory(prefix='phase37-') as directory:
        root=Path(directory)
        click=root/'click.wav';write(click,48000*6,24000)
        a=root/'a.wav';b=root/'b.wav';old=root/'old.wav'
        run(renderer,click,a,'2.00','A')
        run(frozen,click,old,'2.00','A')
        assert a.read_bytes()==old.read_bytes()
        result=run(renderer,click,b,'2.00','B')
        details=dict(line.split('=',1) for line in result.splitlines() if '=' in line)
        assert int(details['max_anchor_error_samples'])==0
        assert int(details['min_mid_hop'])>0 and int(details['max_mid_hop'])<4096
        assert len(data(b))==48000*3*2
        assert all(math.isfinite(x) for x in data(b))
        assert max(abs(x) for x in data(b))>max(abs(x) for x in data(a))
        points=list(csv.DictReader(run(renderer,click,'-','2.00','B').splitlines()))
        starts=[int(x['output_sample']) for x in points]
        assert all(y>x for x,y in zip(starts,starts[1:]))
        for frames,spacing in ((512,0),(48000*8,12000)):
            source=root/f'{frames}.wav';write(source,frames,spacing)
            for speed in ('1.00','1.50','2.00'):
                message=run(renderer,source,b,speed,'B')
                assert len(data(b))==round(frames/float(speed))*2
                assert all(math.isfinite(x) for x in data(b))
                if frames>512 and speed=='2.00':
                    details=dict(line.split('=',1) for line in message.splitlines() if '=' in line)
                    assert int(details['capacity_limited_segments'])>0
        run(renderer,click,a,'1.00','A')
        run(renderer,click,b,'1.00','B')
        assert a.read_bytes()==b.read_bytes()
    print('Phase 37 fixed A regression, click, dense/short input and 1.00 PV: passed')

if __name__=='__main__':main()
