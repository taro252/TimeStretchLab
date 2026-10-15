"""Caller wall, thread CPU, worker stages; no unpaced drain treated as realtime."""
import argparse,json,subprocess
from pathlib import Path
from phase53_sessions import ROOT
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
rows=[]
for source in ('mix','drums','vocal','bass','guitar'):
 for seconds in (30,180,300):
  for speed in (.4,.5,1.,1.5,2.):
   input=ROOT/f'results/phase54/input/{source}_{seconds}s.wav';name=f'{source}_{seconds}_{speed}'
   r=subprocess.run([str(ROOT/'build/phase54_startup_probe'),str(input),str(input),'startup-only',str(speed)],capture_output=True,text=True,timeout=180)
   (a.output/(name+'.log')).write_text(r.stdout+r.stderr)
   rows.append(dict(source=source,seconds=seconds,speed=speed,exit=r.returncode,PASS=r.returncode==0))
   (a.output/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
 print(source,'finished',flush=True)
raise SystemExit(0 if all(r['PASS'] for r in rows) else 2)
