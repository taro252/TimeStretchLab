"""Bounded reference-EOS correction, common strict gate, new output only."""
import argparse,json
from pathlib import Path
from phase52_validate import ROOT,OUT
from phase53_sessions import verify_run

def recheck(root,output):
 root=Path(root);output=Path(output)
 if output.exists():raise ValueError('Fresh correction output required')
 output.mkdir(parents=True);rows=[]
 for folder in sorted(root.iterdir()):
  if not (folder/'validation.json').exists():continue
  old=json.loads((folder/'validation.json').read_text())
  inp=OUT/'input'/f"{old['source']}_{int(old['seconds'])}s.wav"
  result=verify_run(folder,inp,old['exit'],reference_dir=output/folder.name,legacy=True,original=old,
    correction_reason='Fixed reference EOS corrected to round(inputFrames/speed); native PCM and all non-PCM failures retained.')
  result['original_verification']=old;rows.append(result)
 (output/'summary.json').write_text(json.dumps(rows,indent=2))
 return 0 if rows and all(r['VERDICT']=='PASS' for r in rows) else 2
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=OUT/'native/20261014_134247');p.add_argument('--output',type=Path,required=True);a=p.parse_args();raise SystemExit(recheck(a.root,a.output))
