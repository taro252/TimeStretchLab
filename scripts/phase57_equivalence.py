"""Current legacy entry vs independent frozen DSP; full raw PCM bytes."""
import argparse,hashlib,json,subprocess,tempfile
from pathlib import Path
from phase55_study import ROOT
from phase57_study import REPRESENTATIVE,sha
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--current',type=Path,default=ROOT/'build/phase57_reference');a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
sources=list((ROOT/'results/phase57/stage1_final/inputs').glob('boundary_*.wav'));assert len(sources)==8
frozen=ROOT/'build/phase57_frozen/reference';rows=[]
with tempfile.TemporaryDirectory(dir=ROOT/'build',prefix='phase57_equivalence_') as temp:
    paths=[Path(temp)/'old.f32',Path(temp)/'current.f32']
    for source in sorted(sources):
        for speed in REPRESENTATIVE:
            for preset in ('candidate','baseline'):
                data=[]
                for executable,path in zip((frozen,a.current.resolve()),paths):
                    r=subprocess.run([str(executable),str(source),str(speed),preset,str(path)],capture_output=True,text=True,check=True);data.append(json.loads(r.stdout))
                old,new=(p.read_bytes() for p in paths)
                if old!=new:
                    i=next((i for i,(x,y) in enumerate(zip(old,new)) if x!=y),min(len(old),len(new)))
                    raise RuntimeError(f'Legacy refactor PCM mismatch {source} speed={speed} preset={preset} byte={i}')
                assert data[0]['output_frames']==data[1]['output_frames'] and data[0]['pcm_sha256']==data[1]['pcm_sha256']
                rows.append(dict(input=str(source),input_sha256=sha(source),speed_micros=speed,preset=preset,pcm_sha256=data[0]['pcm_sha256'],frames=data[0]['output_frames'],PASS=True))
        print(source.name,'PASS',flush=True)
(a.output/'summary.json').write_text(json.dumps(dict(PASS=True,cases=len(rows),frozen_sha256=sha(frozen),current_sha256=sha(a.current),rows=rows),indent=2)+'\n')
