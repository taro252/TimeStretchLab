"""制御変更の新局所試験。有限通常worker gate、実音声は直列。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--build-record',type=Path,required=True);p.add_argument('--input-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();record=json.loads(a.build_record.read_text());assert record['status']=='PASS';source=source_manifest(ROOT);assert source['sha256']==record['source'];out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);inputs=a.input_dir.resolve();b=record['binaries'];jobs=[]
for preset in ['baseline','candidate']:
 key='summary_'+preset;jobs.append(dict(id=key,binary='phase62_control_summary_tests',command=[b['phase62_control_summary_tests']['path'],str(inputs/'artificial_10s.wav'),preset,str(out/key)],expected=24,ids_field='required_ids',checks_key='pass'))
 for dynamic in ['dynamic','standard']:
  key='watch_'+dynamic+'_candidate'
  # watch host uses Candidate; the optional last argument selects dynamic/standard.
  if preset!='candidate':continue
  jobs.append(dict(id=key,binary='phase62_input_watch_tests',command=[b['phase62_input_watch_tests']['path'],str(inputs/'artificial_6s.wav'),str(out/key),dynamic],expected=26,ids_field='expected_IDs',checks_key='status'))
 for mode in ['preparing','requested','started_done','paused_preparing','paused_adopted','latest_stop','latest_reprepare','latest_close','retained_stop','retained_close']:
  key='clear_'+mode+'_'+preset;jobs.append(dict(id=key,binary='phase62_clear_reenable_native',command=[b['phase62_clear_reenable_native']['path'],mode,str(inputs/'artificial_6s.wav'),preset,str(out/key),source['sha256']],expected=8 if mode.startswith(('latest_','retained_')) else 10,ids_field='expected_IDs',checks_key='status'))
def save(name,v):(out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
for j in jobs:assert identity(Path(b[j['binary']]['path']))==b[j['binary']]
save('EXPECTED.json',dict(source=source,build=identity(a.build_record),driver=identity(Path(__file__)),expected_programs=len(jobs),expected_checks=sum(j['expected'] for j in jobs),jobs=jobs,inputs=[identity(inputs/x) for x in ['artificial_6s.wav','artificial_10s.wav']],serial=True,RT_approval='NOT_ASSESSED'));rows=[]
for j in jobs:
 assert source_manifest(ROOT)==source;start=time.monotonic();timed=False
 with (out/(j['id']+'.log')).open('w') as f:
  try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 folder=out/j['id'];stat=json.loads((folder/'SUMMARY.json').read_text()) if (folder/'SUMMARY.json').exists() else {};ex=json.loads((folder/'EXPECTED.json').read_text()) if (folder/'EXPECTED.json').exists() else {};checkfile=folder/'checks.jsonl';checks=[json.loads(x) for x in checkfile.read_text().splitlines()] if checkfile.exists() else [];expected_ids=ex.get(j['ids_field'],[]);actual_ids=[x['id'] for x in checks];checkok=all(x.get(j['checks_key']) in [True,'PASS'] for x in checks);ok=code==0 and not timed and stat.get('status')=='PASS' and stat.get('run_complete') is True and j['expected']==stat.get('expected')==stat.get('executed')==len(checks)==len(set(actual_ids)) and actual_ids==expected_ids and checkok
 rows.append(dict(id=j['id'],status='PASS' if ok else 'FAIL',command=j['command'],exit=code,timeout=timed,seconds=time.monotonic()-start,expected=j['expected'],executed=stat.get('executed',0),check_ids_exact=actual_ids==expected_ids,summary=stat));done=len(rows)==len(jobs);save('SUMMARY.json',dict(status='PASS' if done and all(r['status']=='PASS' for r in rows) else 'INCOMPLETE',run_complete=done,expected_programs=len(jobs),executed_programs=len(rows),expected_checks=sum(j['expected'] for j in jobs),executed_checks=sum(r['executed'] for r in rows),rows=rows,public_go=False));print(j['id'],rows[-1]['status'],round(rows[-1]['seconds'],2),flush=True)
 if not ok:raise SystemExit(2)
