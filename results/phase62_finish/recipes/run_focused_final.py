"""最終残件の試験を直列実行。closeの未観測をPASSへ変換しない。"""
import argparse,json,subprocess,sys,signal,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest

def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
 p=argparse.ArgumentParser();p.add_argument('--build-base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--build-provenance',type=Path,required=True);a=p.parse_args()
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);assert out.is_relative_to(ROOT/'build');base=a.build_base.resolve();build=base/'release';src=ROOT/'results/phase31/input/mix.wav';other=ROOT/'build/phase62/run_01/step1_release/mix_repeat_36s.wav';provenance=a.build_provenance.resolve();source=source_manifest(ROOT);assert json.loads(provenance.read_text())['source_inventory_sha256']==source['sha256'];jobs=[]
 for suite,count,programs in [('control',42,5),('cache',12,12),('playing',74,12),('api',16,16)]:
  folder=out/suite
  if suite=='control':cmd=[sys.executable,'-B',ROOT/'scripts/phase62_finish_control_validation.py','--build',build,'--input',src,'--output',folder]
  else:
   cmd=[sys.executable,'-B',ROOT/'scripts/phase62_finish_validation.py','--suite',suite,'--build',build,'--input',src,'--output',folder,'--build-provenance',provenance]
   if suite=='playing':cmd+=['--other-input',other]
  jobs.append(dict(id=suite,command=list(map(str,cmd)),expected_checks=count,expected_programs=programs))
 for preset in ['candidate','baseline']:jobs.append(dict(id='race_'+preset,command=list(map(str,[build/'phase62_race_native',src,preset,out/('race_'+preset),other])),expected_checks=8,expected_programs=1))
 save(out/'EXPECTED.json',dict(schema=2,required_ids=[j['id'] for j in jobs],jobs=jobs,source=source,build_provenance=identity(provenance),input=identity(src),other_input=identity(other),interpreter=identity(Path(sys.executable)),driver=identity(Path(__file__)),serial=True));rows=[]
 for job in jobs:
  assert source_manifest(ROOT)['sha256']==source['sha256'];began=time.monotonic();log=out/(job['id']+'.log');timed=False
  with log.open('w') as stream:
   child=subprocess.Popen(job['command'],stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
   try:code=child.wait(timeout=1800)
   except subprocess.TimeoutExpired:
    timed=True;os.killpg(child.pid,signal.SIGTERM)
    try:child.wait(timeout=15)
    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
    code=None
  path=out/job['id']/'SUMMARY.json';result=json.loads(path.read_text()) if path.exists() else {};state=result.get('status','INCOMPLETE');complete=result.get('run_complete') is True
  if job['id'].startswith('race_'):
   complete=result.get('expected')==result.get('executed')==job['expected_checks'];state='PASS' if complete and result.get('PASS')==job['expected_checks'] and code==0 else 'FAIL'
  elif result.get('executed_programs')!=job['expected_programs'] or result.get('expected_checks')!=job['expected_checks']:state='INCOMPLETE'
  if code!=0 and not (job['id']=='playing' and code==2 and state=='INCOMPLETE' and complete):state='INCOMPLETE' if timed else 'FAIL'
  if timed or not complete:state='INCOMPLETE'
  assert source_manifest(ROOT)['sha256']==source['sha256'];rows.append(dict(id=job['id'],status=state,exit=code,timed_out=timed,seconds=time.monotonic()-began,expected_checks=job['expected_checks'],expected_programs=job['expected_programs'],result=result,summary=identity(path) if path.exists() else None,log=identity(log)))
  done=len(rows)==len(jobs);save(out/'SUMMARY.json',dict(schema=2,run_complete=done,status='PASS' if done and all(r['status']=='PASS' for r in rows) else 'INCOMPLETE',expected=len(jobs),executed=len(rows),source_inventory_sha256=source['sha256'],rows=rows,local_overall_go=False));print(job['id'],state,round(rows[-1]['seconds'],2),flush=True)
  if timed or state=='FAIL':return 2
 return 0 if all(r['status']=='PASS' for r in rows) else 2
if __name__=='__main__':
 import os
 raise SystemExit(main())
