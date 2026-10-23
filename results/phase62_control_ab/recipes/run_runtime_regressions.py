"""通知/待機/完全保存点の影響箇所だけ。通常Paused、worker取消、動的Clearを直列検証。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
from phase62_review_validation import verify
p=argparse.ArgumentParser();p.add_argument('--build-record',type=Path,required=True);p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);record=json.loads(a.build_record.read_text());source=source_manifest(ROOT);assert record['status']=='PASS' and record['source']==source['sha256'];b=record['binaries'];inputs=a.input_dir.resolve();fixed=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';assert identity(fixed)['sha256']=='de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748';kinds=['burst','reverse','cancel','seek','invalid','stop','route','close','input','failure','eof','tail','playing_pending','seek_speed','stable','double_cancel','limit'];control_cases=['switched_pause']
for k in kinds:
 if k in ['cancel','stable','double_cancel']:control_cases.append('idle_resources')
 control_cases.append(k)
assert len(control_cases)==21
jobs=[]
for preset in ['baseline','candidate']:
 for mode in ['applying_cancel','planner_cancel','proposal_cancel','cache_old_new']:
  key=mode+'_'+preset;jobs.append(dict(id=key,kind='worker',binary='phase62_worker_transaction_tests',command=[b['phase62_worker_transaction_tests']['path'],str(ROOT/'results/phase31/input/mix.wav'),preset,mode,str(out/key)],expected=6))
 jobs.append(dict(id='paused_controls_'+preset,kind='paused',binary='paused_speed_native_tests',command=[b['paused_speed_native_tests']['path'],str(inputs/'artificial_6s.wav'),str(out/'unused_reference_dir'),preset,'controls'],expected=21,required_cases=control_cases))
 jobs.append(dict(id='dynamic_clear_'+preset,kind='clear',binary='phase62_clear_pcm_native',preset=preset,expected=1))
def save(name,v):(out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
for j in jobs:assert identity(Path(b[j['binary']]['path']))==b[j['binary']]
save('EXPECTED.json',dict(expected_programs=12,expected_checks=92,reference_programs=2,source=source,build=identity(a.build_record),inputs=[identity(x) for x in [inputs/'artificial_6s.wav',inputs/'artificial_12s.wav',ROOT/'results/phase31/input/mix.wav']],reference_binary=identity(fixed),driver=identity(Path(__file__)),jobs=jobs,serial=True,RT_approval='NOT_ASSESSED'))
def run(cmd,label):
 log=out/(label+'.log');start=time.monotonic();timed=False
 with log.open('w') as f:
  try:code=subprocess.run(list(map(str,cmd)),stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 return dict(command=list(map(str,cmd)),exit=code,timeout=timed,seconds=time.monotonic()-start,log=identity(log))
refs={}
for preset in ['baseline','candidate']:
 raw=out/(preset+'_750000.f32');r=run([fixed,inputs/'artificial_12s.wav',750000,preset,raw,0,8*48000],preset+'_ref');assert r['exit']==0 and not r['timeout'];m=json.loads(Path(r['log']['path']).read_text());assert m['sha256']==identity(raw)['sha256'];r.update(meta=m,raw=identity(raw));refs[preset]=r;save('REFERENCES.json',refs)
rows=[]
for j in jobs:
 assert source_manifest(ROOT)==source
 if j['kind']=='clear':
  ref=refs[j['preset']];j['command']=[b[j['binary']]['path'],str(inputs/'artificial_12s.wav'),j['preset'],str(out/j['id']),ref['raw']['path'],*map(str,ref['meta']['positions']),str(fixed),ref['raw']['sha256']]
 r=run(j['command'],j['id']);stat={};reasons=[]
 if j['kind']=='worker':stat,reasons=verify(j,out/j['id'],r['exit'],r['timeout']);executed=stat.get('executed',0)
 elif j['kind']=='paused':
  try:
   lines=[json.loads(x) for x in Path(r['log']['path']).read_text().splitlines()];ok=len(lines)==21 and [x.get('case') for x in lines]==control_cases and all(x.get('PASS') is True and x['candidate']==(j['id'].endswith('candidate')) for x in lines);executed=len(lines);stat=dict(required_cases=control_cases,actual=lines,complete=ok)
   if not ok:reasons.append('paused full case sequence/21 results')
  except (ValueError,KeyError):executed=0;reasons.append('paused results incomplete')
 else:
  stat=json.loads((out/j['id']/'SUMMARY.json').read_text()) if (out/j['id']/'SUMMARY.json').exists() else {};executed=stat.get('executed',0)
  if stat.get('status')!='PASS' or stat.get('expected')!=executed or executed!=1 or stat.get('independent_DSP_RAW_and_final_PCM')!='PASS':reasons.append('dynamic Clear independent final PCM')
 if r['exit']!=0 or r['timeout']:reasons.append('process failure/timeout')
 r.update(id=j['id'],status='PASS' if not reasons else 'FAIL',expected=j['expected'],executed=executed,summary=stat,reasons=reasons);rows.append(r);done=len(rows)==len(jobs);save('SUMMARY.json',dict(status='PASS' if done and all(x['status']=='PASS' for x in rows) else 'INCOMPLETE',run_complete=done,expected_programs=12,executed_programs=len(rows),expected_checks=92,executed_checks=sum(x['executed'] for x in rows),rows=rows,public_go=False));print(j['id'],r['status'],round(r['seconds'],2),reasons,flush=True)
 if reasons:raise SystemExit(2)
