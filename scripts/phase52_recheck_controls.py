"""Restore sample units in replay metadata, keeping originating files intact."""
import csv,json,subprocess,hashlib
from pathlib import Path
from phase52_validate import ROOT,OUT,BUILD,kv,source
from phase52_verdict import classify
root=OUT/'native/20261014_135001';rows=[]
for folder in sorted(root.iterdir()):
 if not (folder/'validation.json').exists():continue
 old=json.loads((folder/'validation.json').read_text());row=dict(old);plan=folder/'plans_samples.csv'
 with (folder/'plans.csv').open() as f:
  r=csv.DictReader(f);fields=r.fieldnames;data=list(r)
 with plan.open('w') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
  for entry in data:entry['density_input']=str(int(entry['density_input'])*1024);w.writerow(entry)
 inp=source(old['source'],int(old['seconds']));ref=folder/'reference_density_samples.wav'
 r=subprocess.run(list(map(str,[BUILD/'playback_reference',inp,ref,old['initial'],plan,'L2' if old['preset']=='candidate' else 'C','safe-density'])),capture_output=True,text=True,timeout=120)
 (folder/'reference_density_samples.log').write_text(r.stdout+r.stderr)
 assert r.returncode==0,(folder,r.stderr)
 body=ref.read_bytes();at=12
 while body[at:at+4]!=b'data':at+=8+int.from_bytes(body[at+4:at+8],'little')
 frames=int(row['produced_frames']);expected=hashlib.sha256(body[at+8:at+8+frames*8]).hexdigest()
 row['PCM_CORRECTNESS']='PASS' if expected==row['raw_pcm_sha256'] else 'FAIL'
 life=kv(folder/'lifecycle.txt');row.update(classify(old,old['exit'],expected_route=life['route_expected']=='1',remaining_actions=int(life['remaining_actions'])))
 row['pcm_scope']='all worker output; route stop compares only worker-produced prefix' if life['route_expected']=='1' else 'entire raw output'
 callbacks=list(csv.DictReader((folder/'callbacks.csv').open()));cursor=0;valid=True
 for cb in callbacks:
  if int(cb['wanted'])==0:continue
  valid&=int(cb['output'])==cursor;cursor+=int(cb['received'])
 valid&=cursor==int(row['consumed_frames']) and len(callbacks)==int(row['callback_calls'])
 row['CSV_INTEGRITY']='PASS' if valid else 'FAIL';row['VERDICT']='PASS' if row['PCM_CORRECTNESS']==row['AUDIO_QUALITY']==row['MEASUREMENT_QUALITY']==row['CSV_INTEGRITY']=='PASS' and row['exit']==0 else 'FAIL'
 row['original_pcm_verdict']=old['PCM_CORRECTNESS'];row['correction_reason']='density_input was exported in Mid frame units instead of input samples; multiplied by 1024 for reference replay only; native audio untouched'
 row['hal_operation_delays']=None;row['timing_scope']='UNAVAILABLE_CLOCK_BRIDGE in this initial batch; source and steady clock must not be subtracted'
 if old.get('intentional_stall'):row['FAULT_DETECTION']='PASS' if int(row['missing_frames'])>0 and row['AUDIO_QUALITY']=='FAIL' and row['exit']==2 else 'FAIL'
 for closed in folder.glob('closed_session_*'):
  c=kv(closed/'summary.txt');n=int(c['produced_frames']);
  if c['raw_pcm_sha256']:assert c['raw_pcm_sha256']==hashlib.sha256(body[at+8:at+8+n*8]).hexdigest()
 row['closed_session_pcm']='PASS' if not any(not kv(c/'summary.txt')['raw_pcm_sha256'] for c in folder.glob('closed_session_*')) else 'NOT_MEASURED_IN_ORIGINAL_RUN';(folder/'validation_samples.json').write_text(json.dumps(row,indent=2));rows.append(row);print(folder.name,row['VERDICT'],row['PCM_CORRECTNESS'],flush=True)
(root/'summary_samples.json').write_text(json.dumps(rows,indent=2));print('rows',len(rows))
assert all(r['VERDICT']=='PASS' for r in rows if not r.get('intentional_stall') and r['reason']!='RouteChanged')
