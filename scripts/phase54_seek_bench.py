"""Limited CPU-only seek measurements; waiting consumer is not a realtime test."""
import argparse,csv,json,subprocess,io
from pathlib import Path
from phase53_sessions import ROOT
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
cases=[(name,30,speed,'candidate',15.,'once') for name in ('mix','drums','vocal','bass','guitar') for speed in (.4,.5,1.,1.5,2.)]
cases += [('drums',n,s,'candidate',n*.9,'once') for n in (180,300) for s in (.4,2.)]
cases += [('mix',30,.4,'candidate',15.,'repeat'),('drums',30,.5,'baseline',15.,'repeat'),('drums',30,.4,'candidate',15.,'no-cache')]
rows=[]
for ordinal,(name,length,speed,preset,position,mode) in enumerate(cases):
 label=f'{ordinal:02}_{name}_{length}_{speed}_{preset}_{mode}'
 command=list(map(str,[ROOT/'build/phase54_seek_study',ROOT/f'results/phase54/input/{name}_{length}s.wav',speed,preset,position,mode]))
 r=subprocess.run(command,capture_output=True,text=True,timeout=300)
 (a.output/(label+'.log')).write_text(r.stdout+r.stderr)
 values=list(csv.DictReader(io.StringIO(r.stdout))) if r.returncode==0 else []
 valid=r.returncode==0 and bool(values) and all(v['PCM_CORRECTNESS']=='PASS' for v in values)
 rows.append(dict(case=label,command=command,source=name,seconds=length,speed=speed,preset=preset,position=position,mode=mode,exit=r.returncode,PASS=valid,values=values))
 (a.output/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
 print(label,'PASS' if valid else 'FAIL',flush=True)
print('seek cases',sum(r['PASS'] for r in rows),'/',len(rows))
raise SystemExit(0 if all(r['PASS'] for r in rows) else 2)
