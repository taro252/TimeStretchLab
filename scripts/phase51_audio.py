#!/usr/bin/env python3
"""Bounded L2 audio safety before native integration; original files untouched."""
import csv,hashlib,json,os,subprocess
from pathlib import Path
from phase45_store import parse_log
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase51/audio'
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if (OUT/'summary.json').exists():raise SystemExit('Fresh output required')
 rows=[]
 for source in ('mix','drums','vocal','guitar','bass'):
  input=ROOT/f'results/phase31/input/{source}.wav'
  for label,planning in [('L1','C'),('L1_L2','L2')]:
   path=OUT/f'{source}_{label}';path.mkdir()
   env=os.environ.copy();env['PHASE50_PRECISE_BOUNDARY']='1'
   result=subprocess.run([str(ROOT/'build/phase51_sim'),str(input),str(path/'raw.wav'),'.4','1.85:2', '512',str(path/'replay.csv'),'2048',planning,'safe-density'],capture_output=True,text=True,env=env,timeout=180)
   (path/'render.log').write_text(result.stdout+result.stderr)
   if result.returncode:raise RuntimeError(str(path/'render.log'))
   ref=subprocess.run([str(ROOT/'build/phase51_reference'),str(input),str(path/'reference.wav'),'.4',str(path/'replay.csv'),planning,'safe-density'],capture_output=True,text=True,timeout=180)
   (path/'reference.log').write_text(ref.stdout+ref.stderr)
   assert ref.returncode==0
   hashes=[hashlib.sha256((path/f).read_bytes()).hexdigest() for f in ('raw.wav','reference.wav')];assert hashes[0]==hashes[1]
   plans=list(csv.DictReader((path/'replay.csv').open()));assert all(p['state_preserved']=='1' for p in plans)
   rows.append(dict(source=source,label=label,planning=planning,path=str(path),PCM_CORRECTNESS='PASS',sha256=hashes[0],plans=plans))
   (OUT/'summary.json').write_text(json.dumps(rows,indent=2));print(source,label,'PASS',flush=True)
if __name__=='__main__':main()
