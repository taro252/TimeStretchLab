"""cold/warmを別計測し、独立固定Exact RAW/Map/境界式で新入口を検証。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
FIXED=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';FIXED_SHA='de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
p=argparse.ArgumentParser();p.add_argument('--candidate-record',type=Path,required=True);p.add_argument('--baseline-record',type=Path,required=True);p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--references-from',type=Path);p.add_argument('--reuse-cold-from',type=Path);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);inputs=a.input_dir.resolve();current=source_manifest(ROOT);br=json.loads(a.baseline_record.read_text());cr=json.loads(a.candidate_record.read_text());assert br['status']==cr['status']=='PASS' and cr['source']==current['sha256'] and identity(FIXED)['sha256']==FIXED_SHA
refs=[dict(id='prefix_'+preset,input=inputs/'artificial_12s.wav',preset=preset,positions=[8*48000+31,8*48000+31+4800,11*48000+32,24011,28811,0,4800]) for preset in ['baseline','candidate']]+[dict(id='warm',input=inputs/'artificial_240s.wav',preset='candidate',positions=[30*48000,32*48000]),dict(id='cold',input=inputs/'artificial_300s.wav',preset='candidate',positions=[0,2*48000,30*48000,32*48000,270*48000,272*48000])];jobs=[]
for label,r in [('before',br),('after',cr)]:
 for index,A in enumerate([0,30,270]):
  key=f'{label}_cold_A{A}';binary=r['binaries']['phase62_initial_loop_native'];jobs.append(dict(id=key,kind='cold',ref='cold',indices=[index*2,index*2+1],binary=binary,command=[binary['path'],str(inputs/'artificial_300s.wav'),'candidate',str(A),'2','2','final','3','1',str(out/key)],expected=6,source=r['source']))
 for mode in ['serial','replace']:
  key=f'{label}_warm_{mode}';binary=r['binaries']['phase62_warm_reenable_native'];jobs.append(dict(id=key,kind='warm',ref='warm',indices=[0,1],binary=binary,command=[binary['path'],str(inputs/'artificial_240s.wav'),mode,'30',str(out/key),r['source']],expected=5,source=r['source']))
for preset in ['baseline','candidate']:jobs.append(dict(id='prefix_'+preset,kind='prefix',ref='prefix_'+preset,indices=[0,1,2,3,4,6],binary=cr['binaries']['phase62_prefix_checkpoint_tests'],preset=preset,expected=16,source=cr['source']))
def save(name,v):(out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n')
for j in jobs:assert identity(Path(j['binary']['path']))==j['binary']
save('EXPECTED.json',dict(expected_programs=12,expected_checks=88,expected_reference_programs=4,expected_initial_rounds=12,source=current,baseline_build=identity(a.baseline_record),candidate_build=identity(a.candidate_record),reference_binary=identity(FIXED),reference_groups=refs,jobs=jobs,inputs=[identity(inputs/n) for n in ['artificial_12s.wav','artificial_240s.wav','artificial_300s.wav']],driver=identity(Path(__file__)),serial=True,RT_approval='NOT_ASSESSED',physical_audio=False))
def run(cmd,label,timeout=420):
 cmd=list(map(str,cmd));timed=False;start=time.monotonic();log=out/(label+'.log')
 with log.open('w') as f:
  try:code=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 return dict(command=cmd,exit=code,timeout=timed,seconds=time.monotonic()-start,log=identity(log))
reference={}
for ref in refs:
 if a.references_from:
  oldspec=json.loads((a.references_from/'EXPECTED.json').read_text());assert oldspec['reference_binary']==identity(FIXED) and oldspec['reference_groups']==json.loads(json.dumps(refs,default=str))
  r=json.loads((a.references_from/'REFERENCES.json').read_text())[ref['id']];assert r['exit']==0 and not r['timeout'] and r['input']==identity(ref['input']) and r['raw']==identity(Path(r['raw']['path'])) and r['log']==identity(Path(r['log']['path']));r=dict(r,reused_reference=True)
 else:
  raw=out/(ref['id']+'.f32');r=run([FIXED,ref['input'],1000000,ref['preset'],raw,*ref['positions']],ref['id']+'_ref');assert r['exit']==0 and not r['timeout'];m=json.loads(Path(r['log']['path']).read_text());assert m['sha256']==identity(raw)['sha256'];r.update(meta=m,raw=identity(raw),input=identity(ref['input']))
 reference[ref['id']]=r;save('REFERENCES.json',reference);print('reference',ref['id'],'PASS',flush=True)
rows=[]
for j in jobs:
 assert source_manifest(ROOT)==current;ref=reference[j['ref']];m=dict(ref['meta']);m['positions']=[m['positions'][i] for i in j['indices']];mapfile=out/(j['id']+'_map.json');save(mapfile.name,m)
 if j['kind']=='prefix':cmd=[j['binary']['path'],str(inputs/'artificial_12s.wav'),j['preset'],ref['raw']['path'],FIXED,*m['positions'],out/j['id']]
 else:cmd=j['command']
 reused=None
 if j['kind']=='cold' and a.reuse_cold_from:
  oldspec=json.loads((a.reuse_cold_from/'EXPECTED.json').read_text());oldjob=next(x for x in oldspec['jobs'] if x['id']==j['id'])
 if j['kind']=='cold' and a.reuse_cold_from and oldjob['binary']==j['binary']:
  assert oldspec['inputs']==[identity(inputs/n) for n in ['artificial_12s.wav','artificial_240s.wav','artificial_300s.wav']]
  reused=next(x for x in json.loads((a.reuse_cold_from/'SUMMARY.json').read_text())['rows'] if x['id']==j['id']);assert reused['status']=='PASS' and reused['exit']==0 and not reused['timeout'] and reused['expected']==reused['executed']==6;assert identity(Path(reused['validator']['log']['path']))==reused['validator']['log']
  r=dict(reused,reused_native_and_validation=True,source_record=identity(a.reuse_cold_from/'SUMMARY.json'));rows.append(r);save('PARTIAL_REUSE.json',rows);print(j['id'],'PASS reused identical binary/input/reference',flush=True);continue
 r=run(cmd,j['id']);stat=json.loads((out/j['id']/'SUMMARY.json').read_text()) if (out/j['id']/'SUMMARY.json').exists() else {};ok=r['exit']==0 and not r['timeout'] and stat.get('status')=='PASS' and stat.get('run_complete') is True
 if j['kind']=='prefix':
  ex=json.loads((out/j['id']/'EXPECTED.json').read_text());checks=[json.loads(x) for x in (out/j['id']/'checks.jsonl').read_text().splitlines()];ok &= stat.get('expected')==stat.get('executed')==stat.get('passed')==j['expected']==len(checks) and all(x['pass'] for x in checks) and len(set(x['id'] for x in checks))==len(checks) and set(x['id'] for x in checks)==set(ex['required_ids']);executed=stat.get('executed',0)
 else:
  if j['kind']=='cold':
   validation=[sys.executable,'-B',Path(__file__).with_name('validate_initial_pcm.py'),'--capture',out/j['id'],'--input',inputs/'artificial_300s.wav','--host-binary',j['binary']['path'],'--reference-binary',FIXED,'--reference-raw',ref['raw']['path'],'--reference-map',mapfile,'--preset','candidate','--speed-micros',1000000,'--expected-rounds',2,'--min-cycles',3,'--require-cache-hit','--expected-cache-mode','raw','--case-id',j['id'],'--output',out/(j['id']+'_audit')]
  else:validation=[sys.executable,'-B',Path(__file__).with_name('validate_fixed_capture.py'),'--capture',out/j['id'],'--input',inputs/'artificial_240s.wav','--reference-binary',FIXED,'--reference-raw',ref['raw']['path'],'--reference-map',mapfile,'--output',out/(j['id']+'_audit')]
  if ok:
   v=run(validation,j['id']+'_validator');vs=json.loads((out/(j['id']+'_audit/SUMMARY.json')).read_text());ok &= v['exit']==0 and not v['timeout'] and vs.get('run_complete') is True and vs['status']=='PASS' and vs['expected']==vs['executed']==vs['passed']==j['expected'];r.update(validator=v,validation=vs);executed=vs['executed']
  else:executed=0
 r.update(id=j['id'],kind=j['kind'],source=j['source'],status='PASS' if ok else 'FAIL',expected=j['expected'],executed=executed,native_summary=stat);rows.append(r);done=len(rows)==len(jobs);save('SUMMARY.json',dict(status='PASS' if done and all(x['status']=='PASS' for x in rows) else 'INCOMPLETE',run_complete=done,expected_programs=12,executed_programs=len(rows),expected_checks=88,executed_checks=sum(x['executed'] for x in rows),rows=rows,public_go=False,RT_approval='NOT_ASSESSED'));print(j['id'],r['status'],round(r['seconds'],2),flush=True)
 if not ok:raise SystemExit(2)
