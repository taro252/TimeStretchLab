#!/usr/bin/env python3
"""Same TimeMap and density history, 1024/2048 PCM must match."""
import math,struct,subprocess,sys,tempfile,wave
from pathlib import Path
from phase45_store import parse_log
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);source=p/'input.wav'
    with wave.open(str(source),'wb') as f:
        f.setnchannels(2);f.setsampwidth(2);f.setframerate(48000)
        frames=bytearray()
        for i in range(48000*6):
            value=int(5000*math.sin(2*math.pi*437.3*i/48000))
            if i%48000<8:value+=12000
            frames.extend(struct.pack('<hh',value,value))
        f.writeframes(frames)
    subprocess.run([sys.argv[1],str(source),str(p/'sim.wav'),'.4','1:2','512',str(p/'replay.csv'),'2048','C','safe-density'],check=True,capture_output=True)
    for block in (1024,2048):
        subprocess.run([sys.argv[2],str(source),str(p/f'{block}.wav'),'.4',str(p/'replay.csv'),str(block)],check=True,capture_output=True)
    hashes=[]
    for file in ('sim.wav','1024.wav','2048.wav'):
        result=subprocess.run([sys.argv[3],str(p/file)],check=True,capture_output=True,text=True)
        values=parse_log(result.stdout);assert values['nonfinite']=='0';hashes.append((values['frames'],values['pcm_sha256']))
    assert hashes[0]==hashes[1]==hashes[2],hashes
print('Identical replay / analysis-density history: 1024/2048 PCM and EOS PASS')
