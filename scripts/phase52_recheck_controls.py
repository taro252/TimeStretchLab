"""Explicit replay-unit correction; never overwrite native evidence."""
import argparse,csv,json
from pathlib import Path
from phase52_validate import OUT
from phase53_sessions import verify_run
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=OUT/'native/20261014_135001');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise ValueError('Fresh correction output required')
 a.output.mkdir(parents=True);rows=[]
 for folder in sorted(a.root.iterdir()):
  if not (folder/'validation.json').exists():continue
  old=json.loads((folder/'validation.json').read_text());out=a.output/folder.name;out.mkdir();plan=out/'plans_samples.csv'
  with (folder/'plans.csv').open() as f:r=csv.DictReader(f);fields=r.fieldnames;data=list(r)
  with plan.open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader()
   for row in data:row['density_input']=str(int(row['density_input'])*1024);w.writerow(row)
  inp=OUT/'input'/f"{old['source']}_{int(old['seconds'])}s.wav"
  result=verify_run(folder,inp,old['exit'],reference_dir=out,legacy=True,plan_override=plan,original=old,
   correction_reason='Replay density_input converted from Mid frame units to input samples; native PCM and non-PCM failures retained.')
  result['original_verification']=old;rows.append(result)
 (a.output/'summary.json').write_text(json.dumps(rows,indent=2));raise SystemExit(0 if rows and all(r['VERDICT']=='PASS' for r in rows) else 2)
