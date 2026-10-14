"""Explicit replay-unit correction; never overwrite native evidence."""
import argparse,json
from pathlib import Path
from phase52_validate import OUT
from phase53_sessions import verify_run,integrity,kv,convert_density_units,DENSITY_CONVERSION_REASON
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=OUT/'native/20261014_135001');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists():raise ValueError('Fresh correction output required')
 a.output.mkdir(parents=True);rows=[]
 for folder in sorted(a.root.iterdir()):
  if not (folder/'validation.json').exists():continue
  old=json.loads((folder/'validation.json').read_text());out=a.output/folder.name;out.mkdir();plan=out/'plans_samples.csv'
  # Verify all original evidence first. Never repair truncation by rewriting CSV.
  before,tables=integrity(folder,kv(folder/'summary.txt'),legacy=True)
  (out/'original_integrity.json').write_text(json.dumps(before,indent=2))
  row=kv(folder/'summary.txt')
  if 'session' not in row:
   ids={op['session'] for op in tables.get('operations.csv',[])}
   if len(ids)==1:row['session']=next(iter(ids))
  correction_error=None
  try:convert_density_units(folder/'plans.csv',plan,row,tables.get('operations.csv',[]),legacy=True)
  except (OSError,ValueError) as error:correction_error=str(error)
  inp=OUT/'input'/f"{old['source']}_{int(old['seconds'])}s.wav"
  result=verify_run(folder,inp,old['exit'],reference_dir=out,legacy=True,plan_override=plan if plan.exists() else None,original=old,
   correction_reason=DENSITY_CONVERSION_REASON if not correction_error else None)
  result['original_integrity']=before
  if correction_error:result['correction_error']=correction_error
  result['original_verification']=old;rows.append(result)
 (a.output/'summary.json').write_text(json.dumps(rows,indent=2));raise SystemExit(0 if rows and all(r['VERDICT']=='PASS' for r in rows) else 2)
