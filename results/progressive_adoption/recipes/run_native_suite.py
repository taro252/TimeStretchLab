#!/usr/bin/env python3
"""Serial native v3 admission/preparation regression. Full IDs fixed before run."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
MODES=['prewarm_ready','cancel_preparing','cancel_ready','pause_preparing','pause_ready','stop_preparing','stop_ready','speed_preparing','speed_ready','seek_preparing','seek_ready','replace_preparing','replace_ready','close_preparing','close_ready','invalid_context','legacy_disabled','policy_precedence','reservation_delta','legacy_api','play_preparing','resume_preparing']
CHECKS=['feature_configuration','initial_ready_lead','preparation_receipt','action_state','preparation_history','stationary_or_adoption','resources','final_owned_audit']
p=argparse.ArgumentParser();p.add_argument('--build-record',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--modes',nargs='+',choices=MODES,default=MODES);p.add_argument('--presets',nargs='+',choices=['candidate','baseline'],default=['candidate','baseline']);a=p.parse_args()
build=json.loads(a.build_record.read_text());source=source_manifest(ROOT);assert build['status']=='PASS' and build['source']==source['sha256'];binary=build['binaries']['progressive_adoption_native_tests'];assert identity(Path(binary['path']))==binary
out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
def save(n,v):(out/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
full=a.modes==MODES and set(a.presets)=={'candidate','baseline'} and len(a.presets)==2
jobs=[{'id':mode+'_'+preset,'mode':mode,'preset':preset,'required_ids':[mode+'.'+k for k in CHECKS],'command':[binary['path'],mode,str(a.input.resolve()),preset,str(out/(mode+'_'+preset)),source['sha256']]} for preset in a.presets for mode in a.modes]
save('EXPECTED.json',{'source':source,'build':identity(a.build_record),'binary':binary,'input':identity(a.input),'driver':identity(Path(__file__)),'expected_programs':len(jobs),'expected_checks':len(jobs)*8,'full_suite':full,'jobs':jobs,'serial':True,'quality_gate':False,'RT_gate':False});rows=[]
for j in jobs:
 assert source_manifest(ROOT)==source
 started=time.monotonic();timed=False
 with (out/(j['id']+'.log')).open('w') as log:
  try:code=subprocess.run(j['command'],stdout=log,stderr=subprocess.STDOUT,timeout=60).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 folder=out/j['id'];summary=json.loads((folder/'SUMMARY.json').read_text()) if (folder/'SUMMARY.json').exists() else {}
 ex=json.loads((folder/'EXPECTED.json').read_text()) if (folder/'EXPECTED.json').exists() else {};checks=[json.loads(x) for x in (folder/'checks.jsonl').read_text().splitlines()] if (folder/'checks.jsonl').exists() else []
 ids=[x['id'] for x in checks];ok=code==0 and not timed and summary.get('status')=='PASS' and summary.get('run_complete') is True and summary.get('executed')==summary.get('expected')==8 and ids==j['required_ids']==ex.get('required_ids') and len(set(ids))==8 and all(x.get('pass') is True for x in checks) and summary.get('owner_alive')==0 and summary.get('owner_peak',999)<=2 and summary.get('source')==source['sha256']
 rows.append({**j,'status':'PASS' if ok else 'FAIL','returncode':code,'timeout':timed,'wall_s':time.monotonic()-started,'summary':summary,'check_ids_exact':ids==j['required_ids']})
 complete=len(rows)==len(jobs);save('SUMMARY.json',{'status':('PASS' if full else 'PARTIAL_PASS') if complete and all(x['status']=='PASS' for x in rows) else 'INCOMPLETE','execution_complete':complete,'full_suite_complete':complete and full,'expected_programs':len(jobs),'executed_programs':len(rows),'expected_checks':len(jobs)*8,'executed_checks':sum(x['summary'].get('executed',0) for x in rows),'rows':rows,'quality_gate':False,'RT_gate':False});print(j['id'],rows[-1]['status'],flush=True)
 if not ok:raise SystemExit(2)
assert identity(Path(binary['path']))==binary and source_manifest(ROOT)==source
