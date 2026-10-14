#!/usr/bin/env python3
"""Phase 53 isolated artifacts, strict gates; old results are read-only."""
import argparse,datetime,hashlib,json,os,subprocess
from pathlib import Path
import phase52_validate as v
from phase53_sessions import verify_run
ROOT=v.ROOT;OUT=ROOT/'results/phase53'
def fresh(kind):
 p=OUT/kind/datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f');p.mkdir(parents=True);return p
def native():
 v.OUT=OUT;root=fresh('native');rows=[]
 cases=[('mix',.5,{'verify_draining':True,'silent':False}),('drums',.5,{'verify_draining':True}),
       ('mix',.4,{'seconds':10,'actions':((1,'speed',2),(3,'speed',.4),(5,'pause',0),(5.25,'resume',0)),'silent':False}),
       ('drums',.5,{'actions':((.8,'stop',0),(1,'play',0))}),
       ('mix',.5,{'actions':((.8,'stop',0),(1,'play',0),(2,'stop',0),(2.2,'play',0))}),
       ('drums',.5,{'actions':((.5,'route',0),)}),('mix',.5,{'preset':'baseline','verify_draining':True})]
 for name,speed,kwargs in cases:
  try:r=v.run_case(root,name,speed,**kwargs)
  except Exception as e:r=dict(source=name,initial=speed,VERDICT='FAIL',error=repr(e))
  rows.append(r);(root/'summary.json').write_text(json.dumps(rows,indent=2));print(name,r.get('VERDICT'),r.get('error',''),flush=True)
 print(root,flush=True);return 0 if all(r['VERDICT']=='PASS' for r in rows) else 2

def golden():
 v.OUT=OUT;v.golden();return 0

def audit():
 import csv
 wavs=[]
 for phase in ('phase12','phase28'):
  for row in csv.DictReader((ROOT/f'results/{phase}/golden/manifest.csv').open()):
   if row['speed'] not in ('0.50','0.60','0.70','0.75','0.80'):continue
   p=ROOT/row['output_path'];wavs.append(dict(path=row['output_path'],match=v.sha(p)==row['output_sha256']))
 changes=[];records=[]
 tracked=subprocess.check_output(['git','ls-tree','-rz','65a8759','results']).split(b'\0')
 for entry in tracked:
  if not entry:continue
  meta,name=entry.split(b'\t',1);mode,kind,before=meta.split();name=os.fsdecode(name)
  if name=='results/phase53/REPORT.md':p=OUT/'PHASE5_3_REPORT.md'
  else:p=ROOT/name
  data=os.fsencode(os.readlink(p)) if mode==b'120000' else p.read_bytes()
  after=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest().encode()
  match=before==after;records.append(dict(path=name,match=match))
  if not match:changes.append(name)
 # All earlier protected audio references, including Phase 41/42.
 extra=json.loads((ROOT/'results/phase51/protected_wav_audit.json').read_text())['rows']
 extra_ok=all(v.sha(ROOT/r['path'])==r['sha256'] for r in extra)
 result=dict(golden_count=len(wavs),golden_match=all(r['match'] for r in wavs),protected_wav_count=len(extra),protected_wavs_match=extra_ok,tracked_count=len(records),changed=changes)
 p=fresh('audit');(p/'protected.json').write_text(json.dumps(result,indent=2));print(result);return 0 if len(wavs)==25 and result['golden_match'] and extra_ok and not changes else 2

def review():
 root=fresh('review_phase52');rows=[]
 for folder in sorted((ROOT/'results/phase52/native').glob('*/*')):
  if not (folder/'validation.json').exists():continue
  original=json.loads((folder/'validation.json').read_text());plan=None;ref=folder/'reference_round_eos.wav';reason=None
  if (folder/'validation_samples.json').exists():plan=folder/'plans_samples.csv';ref=folder/'reference_density_samples.wav';reason='Explicit saved replay-unit correction (no native PCM change)'
  elif (folder/'validation_round_eos.json').exists():reason='Explicit saved fixed reference EOS correction (no native PCM change)'
  if not ref.exists():
   rows.append(dict(case=str(folder.relative_to(ROOT)),VERDICT='FAIL',error='saved corrected reference unavailable'));continue
  inp=ROOT/'results/phase52/input'/f"{original['source']}_{int(original['seconds'])}s.wav"
  refs={'.':ref}
  # Closed sessions need their own original history, not final-session replay.
  # Legacy closed sessions lack mandatory native/CSV metrics: never invent them.
  result=verify_run(folder,inp,original['exit'],reference_dir=root/folder.parent.name/folder.name,legacy=True,reference_override=refs,plan_override=plan,original=original,correction_reason=reason)
  result['case']=str(folder.relative_to(ROOT));result['original_verdict']=original.get('VERDICT');rows.append(result)
 (root/'summary.json').write_text(json.dumps(rows,indent=2));print(root,len(rows),{s:sum(r['VERDICT']==s for r in rows) for s in ('PASS','FAIL')});return 0 if rows and all(r['VERDICT']=='PASS' for r in rows) else 2

def native_review():
 root=fresh('review_native');rows=[]
 source=sorted((OUT/'native').glob('*'))[-1]
 for folder in sorted(source.iterdir()):
  if not (folder/'summary.txt').exists():continue
  old=json.loads((folder/'validation.json').read_text())
  inp=OUT/'input'/f"{old['source']}_{int(old['seconds'])}s.wav"
  refs={'.':folder/'reference_sessions/final.wav'}
  for closed in folder.glob('closed_session_*'):refs[closed.name]=folder/'reference_sessions'/(closed.name+'.wav')
  result=verify_run(folder,inp,old['exit'],reference_override=refs)
  result['case']=str(folder.relative_to(ROOT));rows.append(result)
 (root/'summary.json').write_text(json.dumps(rows,indent=2));print(root,len(rows),{s:sum(r['VERDICT']==s for r in rows) for s in ('PASS','FAIL')});return 0 if len(rows)==7 and all(r['VERDICT']=='PASS' for r in rows) else 2
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('native','golden','audit','review','native_review'));a=p.parse_args();raise SystemExit(globals()[a.mode]())
