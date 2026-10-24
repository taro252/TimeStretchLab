"""有限の局所機能試験。通常worker gateの結果は性能/RT承認へ転記しない。"""
import argparse,json,pathlib,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--build-record',type=pathlib.Path,required=True)
p.add_argument('--input',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True)
p.add_argument('--suite',choices=['preparation','input'],required=True);p.add_argument('--only',nargs='+')
a=p.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False)
build=json.loads(a.build_record.read_text());assert build['status']=='PASS'
assert source_manifest(R)['sha256']==build['source']
if a.suite=='preparation':
 target='performance_preparation_native'
 modes=['on_early','on_mid','on_before_ready','on_ready','mismatch_range','mismatch_context','pause_transferred','stop_transferred','speed_transferred','replace_transferred','input_transferred','close_transferred','unclaimed_pause','unclaimed_play','unclaimed_resume','unclaimed_cancel','resume_retiring','speed_transferred_play','speed_transferred_resume','speed_transferred_latest_A']
else:
 target='performance_input_preparation_tests';modes=['pipeline','engine_stop','engine_close','engine_new_input','engine_deadline','engine_ready_deadline']
host=build['binaries'][target];assert identity(host['path'])==host;jobs=[]
for preset in ['candidate','baseline']:
 for mode in modes:
  key=mode+'_'+preset
  if a.only and key not in a.only:continue
  jobs.append(dict(id=key,checks=15 if mode=='pipeline' else 8,command=[host['path'],mode,str(a.input.resolve()),preset,str(o/key),build['source']]))
if a.only:assert {j['id'] for j in jobs}==set(a.only)
def save(n,v):(o/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
save('EXPECTED.json',dict(source=build['source'],build=identity(a.build_record),binary=host,input=identity(a.input),driver=identity(__file__),jobs=jobs,expected_programs=len(jobs),expected_checks=sum(j['checks'] for j in jobs),callback_gate=False,quality_approval=False,performance_approval=False))
rows=[]
for j in jobs:
 start=time.monotonic();timed=False
 with (o/(j['id']+'.log')).open('w') as f:
  try:rc=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=60).returncode
  except subprocess.TimeoutExpired:rc=None;timed=True
 path=o/j['id']/'SUMMARY.json';s=json.loads(path.read_text()) if path.exists() else {}
 ok=not timed and rc==0 and s.get('status')=='PASS' and s.get('run_complete') and s.get('expected')==s.get('executed')==j['checks']
 rows.append(dict(id=j['id'],PASS=bool(ok),returncode=rc,timeout=timed,wall_s=time.monotonic()-start,summary=s));save('SUMMARY.json',dict(status='PASS' if len(rows)==len(jobs) and all(r['PASS'] for r in rows) else 'INCOMPLETE_OR_FAIL',expected_programs=len(jobs),executed_programs=len(rows),expected_checks=sum(j['checks'] for j in jobs),rows=rows));print(j['id'],rc,ok,flush=True)
 if not ok:raise SystemExit(2)
assert source_manifest(R)['sha256']==build['source']
