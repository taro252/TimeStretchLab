"""e5 review機能試験を直列実行。窓不足・欠落統計・ID不一致をPASSにしない。"""
import argparse,json,subprocess,time
from pathlib import Path
from phase62_evidence import identity,source_manifest,verify_architecture
from phase62_finish_validation import verify_build
ROOT=Path(__file__).resolve().parents[1]
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def read(p):return json.loads(p.read_text())
def plan(build,inputs,out,source,suite):
 jobs=[]
 def add(id,binary,args,expected):jobs.append(dict(id=id,command=[str(build/binary),*map(str,args)],expected=expected,binary=binary))
 for preset in ['candidate','baseline']:
  if suite in ['all','adoption']:
   for mode in ['a1_cancel','a1_started','a2_initial_supply','a2_checkpoint_supply','a2_clear_started','b_internal4096']:
    id=mode+'_'+preset;input=inputs/('short240ms.wav' if mode=='a2_initial_supply' else 'one_second.wav' if mode in ['a2_checkpoint_supply','a2_clear_started'] else 'long120s.wav' if mode=='b_internal4096' else 'mix.wav')
    add(id,'phase62_adoption_review_native',[mode,input,preset,out/id,source],7 if mode in ['a2_checkpoint_supply','a2_clear_started','b_internal4096'] else 6)
  if suite in ['all','fault']:
   for mode in ['checkpoint','reservation','workgroup','deadline','paused_deadline']:
    id=mode+'_'+preset;add(id,'phase62_preparation_fault_native',[mode,inputs/'mix.wav',preset,out/id,source],7)
  if suite in ['all','worker']:
   for mode in ['applying_cancel','planner_cancel','proposal_cancel','cache_old_new']:
    id=mode+'_'+preset;add(id,'phase62_worker_transaction_tests',[inputs/'mix.wav',preset,mode,out/id],6)
  if suite in ['all','partial']:
   for mode in ['replace','clear','stop']:
    id='partial_'+mode+'_'+preset;add(id,'phase62_partial_mix_native',[mode,inputs/'mix.wav',preset,out/id],1)
 return jobs

def verify(job,folder,code,timed):
 reasons=[]
 try:
  summary=read(folder/'SUMMARY.json');spec=read(folder/'EXPECTED.json')
  if type(code) is not int or code!=0 or type(timed) is not bool or timed or summary.get('status')!='PASS':reasons.append('exit/timeout/status')
  if summary.get('run_complete',summary.get('complete')) is not True:reasons.append('completion marker')
  if any(type(summary.get(k)) is not int or summary[k]!=job['expected'] for k in ['expected','executed']) or type(spec.get('expected')) is not int or spec['expected']!=job['expected']:reasons.append('counts')
  wanted=spec.get('checks',spec.get('expected_IDs',spec.get('required_ids')))
  if not isinstance(wanted,list) or not all(type(x) is str and x for x in wanted) or len(wanted)!=job['expected'] or len(set(wanted))!=len(wanted):reasons.append('required IDs')
  if job['binary']=='phase62_partial_mix_native':
   actual=summary.get('executed_IDs',[])
  else:
   rows=[json.loads(x) for x in (folder/'checks.jsonl').read_text().splitlines()];actual=[x['id'] for x in rows]
   if not all((x.get('status')=='PASS' if 'status' in x else x.get('pass') is True) and ('pass' not in x or x['pass'] is True) for x in rows):reasons.append('failed checks')
  if not isinstance(actual,list) or not all(type(x) is str and x for x in actual) or set(actual)!=set(wanted) or len(actual)!=len(wanted):reasons.append('missing/duplicate ID')
 except (OSError,ValueError,KeyError,TypeError) as e:summary={};reasons.append(str(e))
 return summary,reasons

def main():
 p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--build-provenance',type=Path,required=True);p.add_argument('--suite',choices=['all','adoption','fault','worker','partial'],default='all');a=p.parse_args()
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);build=a.build.resolve();inputs=a.inputs.resolve();source=source_manifest(ROOT);jobs=plan(build,inputs,out,source['sha256'],a.suite);binaries=sorted({build/j['binary'] for j in jobs});verify_build(read(a.build_provenance),source['sha256'],binaries);arches=verify_architecture(binaries);assert arches['PASS']
 binary_ids={str(b):identity(b) for b in binaries}
 input_paths={Path(x) for j in jobs for x in j['command'] if str(inputs) in x and x.endswith('.wav')}
 save(out/'EXPECTED.json',dict(schema=1,suite='phase62_e5_review',source=source,driver=identity(Path(__file__)),build_provenance=identity(a.build_provenance),binaries=list(binary_ids.values()),inputs=[identity(x) for x in sorted(input_paths)],expected_programs=len(jobs),expected_checks=sum(j['expected'] for j in jobs),required_ids=[j['id'] for j in jobs],jobs=jobs,serial=True,RT_deadline_approval='NOT_ASSESSED'))
 rows=[]
 for j in jobs:
  if source_manifest(ROOT)!=source:raise RuntimeError('source changed during run')
  start=time.monotonic();log=out/(j['id']+'.log');timed=False
  with log.open('w') as f:
   try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
   except subprocess.TimeoutExpired:timed=True;code=None
  stat,reasons=verify(j,out/j['id'],code,timed)
  if source_manifest(ROOT)!=source or any(identity(Path(x))!=v for x,v in binary_ids.items()):reasons.append('source/binary changed')
  rows.append(dict(id=j['id'],status='FAIL' if reasons else 'PASS',exit=code,timeout=timed,expected=j['expected'],executed=stat.get('executed',0),seconds=time.monotonic()-start,reasons=reasons,log=identity(log),summary=stat))
  print(j['id'],rows[-1]['status'],round(rows[-1]['seconds'],2),reasons,flush=True)
  complete=len(rows)==len(jobs);save(out/'SUMMARY.json',dict(schema=1,suite='phase62_e5_review',run_complete=complete,status='PASS' if complete and all(x['status']=='PASS' for x in rows) else 'INCOMPLETE',source_inventory_sha256=source['sha256'],expected_programs=len(jobs),executed_programs=len(rows),expected_checks=sum(j['expected'] for j in jobs),executed_checks=sum(r['executed'] for r in rows),required_ids=[j['id'] for j in jobs],executed_ids=[r['id'] for r in rows],rows=rows,local_overall_go=False))
 return 0 if all(r['status']=='PASS' for r in rows) else 2
if __name__=='__main__':raise SystemExit(main())
