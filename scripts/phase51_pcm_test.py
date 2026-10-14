#!/usr/bin/env python3
"""Mono/stereo raw reference + 1024/2048 partition and preserved prefix."""
import csv,hashlib,os,struct,subprocess,tempfile,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def call(args,env):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,env=env,timeout=90)
    if r.returncode:raise RuntimeError(r.stdout+r.stderr)
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)
    for channels in (1,2):
        rate=48000;frames=rate*15;source=path/f'input{channels}.wav';data=bytearray()
        for i in range(frames):
            t=i/rate
            for c in range(channels):
                value=.12*math.sin(2*math.pi*437.3*t+c*.15)+.03*math.sin(2*math.pi*874.6*t)
                for hit in (.8,3,6,9,12):
                    x=t-hit
                    if 0<=x<.25:value+=.22*math.exp(-x/.03)*math.sin(2*math.pi*90*x)
                data.extend(struct.pack('<f',value))
        fmt=struct.pack('<HHIIHH',3,channels,rate,rate*channels*4,channels*4,32)
        source.write_bytes(b'RIFF'+struct.pack('<I',36+len(data))+b'WAVEfmt '+struct.pack('<I',16)+fmt+b'data'+struct.pack('<I',len(data))+data)
        env=os.environ.copy();env['PHASE50_PRECISE_BOUNDARY']='1';env.pop('PHASE49_STALL_MS',None)
        raw=path/f'raw{channels}.wav';ref=path/f'ref{channels}.wav';replay=path/f'replay{channels}.csv'
        call([ROOT/'build/phase51_sim',source,raw,.4,'1:2,6:.4,14:1',512,replay,2048,'L2','safe-density'],env)
        call([ROOT/'build/phase51_reference',source,ref,.4,replay,'L2','safe-density'],env)
        expected=hashlib.sha256(ref.read_bytes()).digest();assert expected==hashlib.sha256(raw.read_bytes()).digest()
        for block in (1024,2048):
            output=path/f'partition{channels}_{block}.wav';call([ROOT/'build/phase51_replay_blocks',source,output,.4,replay,block,'L2'],env)
            assert expected==hashlib.sha256(output.read_bytes()).digest()
        rows=list(csv.DictReader(replay.open()));assert len(rows)==3 and all(r['state_preserved']=='1' for r in rows)
        assert all(float(r['density_weight_'+band])>=.15 for r in rows for band in ('low','mid','high'))
print('Mono/stereo L2 processed frontier / PCM / EOS / 1024/2048 PASS (not realtime)')
