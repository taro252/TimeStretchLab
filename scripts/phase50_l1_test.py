#!/usr/bin/env python3
"""Small PCM/state proof for the opt-in L1 worker, no realtime claim."""
import csv,hashlib,os,struct,subprocess,tempfile,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def call(args,env):
    r=subprocess.run(list(map(str,args)),capture_output=True,text=True,env=env,timeout=90)
    if r.returncode:raise RuntimeError(r.stdout+r.stderr)
with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)
    for channels in (1,2):
        rate=48000;frames=rate*15;source=path/f'input{channels}.wav'
        data=bytearray()
        for i in range(frames):
            t=i/rate
            for c in range(channels):
                value=.12*math.sin(2*math.pi*437.3*t+c*.15)+.03*math.sin(2*math.pi*874.6*t)
                data.extend(struct.pack('<f',value))
        fmt=struct.pack('<HHIIHH',3,channels,rate,rate*channels*4,channels*4,32)
        source.write_bytes(b'RIFF'+struct.pack('<I',36+len(data))+b'WAVEfmt '+struct.pack('<I',16)+fmt+b'data'+struct.pack('<I',len(data))+data)
        env=os.environ.copy();env['PHASE50_PRECISE_BOUNDARY']='1'
        raw=path/f'raw{channels}.wav';ref=path/f'ref{channels}.wav';replay=path/f'replay{channels}.csv'
        call([ROOT/'build/phase50_sim',source,raw,.4,'1:2,6:.4,14:1',512,replay,2048,'C','safe-density'],env)
        call([ROOT/'build/phase39_reference',source,ref,.4,replay,'C','safe-density'],env)
        assert hashlib.sha256(raw.read_bytes()).digest()==hashlib.sha256(ref.read_bytes()).digest()
        rows=list(csv.DictReader(replay.open()));assert len(rows)==3 and all(r['state_preserved']=='1' for r in rows)
print('Mono/stereo L1 actual-history PCM/EOS PASS (unpaced consumer)')
