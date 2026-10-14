"""Application API fixed mono/stereo reference, independent synthesis oracle."""
import csv,hashlib,math,struct,subprocess,tempfile,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def call(args):
 r=subprocess.run(list(map(str,args)),capture_output=True,text=True,timeout=90)
 assert r.returncode==0,r.stdout+r.stderr
with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='phase52_pcm_') as directory:
 out=Path(directory)
 for channels in (1,2):
  rate=48000;pcm=bytearray()
  for i in range(rate*2):
   for c in range(channels):
    value=.12*math.sin(2*math.pi*437.3*i/rate+c*.3)
    if i in (rate//3,rate,rate*3//2):value+=.4
    pcm.extend(struct.pack('<f',value))
  source=out/f'input{channels}.wav';fmt=struct.pack('<HHIIHH',3,channels,rate,rate*channels*4,channels*4,32)
  source.write_bytes(b'RIFF'+struct.pack('<I',36+len(pcm))+b'WAVEfmt '+struct.pack('<I',16)+fmt+b'data'+struct.pack('<I',len(pcm))+pcm)
  for speed in (.4,.5,.75,1,1.5,2):
   target=out/f'{channels}_{speed}';call([ROOT/'build/playback_demo',source,target,'candidate',speed,'--offline'])
   reference=out/f'ref_{channels}_{speed}.wav';call([ROOT/'build/playback_reference',source,reference,speed,target/'plans.csv','L2','safe-density'])
   assert hashlib.sha256(reference.read_bytes()).digest()==hashlib.sha256((target/'raw.wav').read_bytes()).digest()
print('App API mono/stereo 12/12 byte-identical to independent reference (unpaced, not realtime)')
