"""Deterministic consumer waits; this is not a realtime deadline test."""
import json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture
check,reference=map(Path,sys.argv[1:3])
with tempfile.TemporaryDirectory(prefix='phase58_pcm_') as tmp:
    p=Path(tmp);source=p/'boundary.wav';fixture(source,48000,2,3,'boundary',1.5)
    count=0
    for speed in (400000,1000000,2000000):
        for preset in ('candidate','baseline'):
            raw=p/'reference.f32';a=subprocess.run([str(reference),str(source),str(speed),preset,str(raw)],capture_output=True,text=True,check=True);r=json.loads(a.stdout)
            for chunk in (7168,5003):
                b=subprocess.run([str(check),str(source),str(speed),preset,str(raw),str(r['output_frames']),r['pcm_sha256'],str(chunk)],capture_output=True,text=True)
                if b.returncode:raise RuntimeError(b.stdout+b.stderr)
                v=json.loads(b.stdout);assert v['PASS'] and v['output_frames']==r['output_frames'] and v['pcm_sha256']==r['pcm_sha256'];count+=1
    print('Phase58 complete FIFO PCM:',count,'PASS')
