"""F01比較/修正を事前宣言して直列実行。旧不具合は実採用不一致まで要求する。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase62_review_validation import verify
BASE=ROOT/'build/phase62_f01_20261021_01';INPUTS=ROOT/'build/phase62_e5_review_20261021_01/inputs'
MAIN=['F01.normal_no_self_repeat_condition','F01.selected_job_then_latest_B_window','F01.actual_initial_B_session_epoch_PCM','F01.latest_B_Completed_and_A_past_immutable','F01.required_A_protected_and_Completed','F01.exact_IDs_and_terminal_types','normal_supply_heap_owner_audit']
CANCEL=['F01_CANCEL.normal_no_self_repeat_and_selected_A','F01_CANCEL.latest_B_accepted_no_false_facts','F01_CANCEL.action_effective_no_A_or_B_PCM','F01_CANCEL.prepared_owner_joined_and_followup_recovers','F01_CANCEL.direct_close_exact_IDs_reasoned_terminal','normal_supply_heap_owner_audit']
def read(p):return json.loads(p.read_text())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def reproduce(folder,code,timed):
 s=read(folder/'SUMMARY.json');w=read(folder/'F01_selected_window.json');a=read(folder/'F01_actual_adoption.json');checks=[json.loads(x) for x in (folder/'checks.jsonl').read_text().splitlines()]
 receipts=[json.loads(x) for x in (folder/'receipts.jsonl').read_text().splitlines()];ids=[x['id'] for x in receipts if x['accepted'] and not x['duplicate']]
 assert code==1 and not timed and s['status']=='FAIL' and s['run_complete'] is False and s['expected']==7 and s['executed']==4
 assert [r['id'] for r in checks]==MAIN[:4] and all(r['status']=='PASS' for r in checks)
 assert '初回Bで実際に採用したA' in s['reason']
 assert len(ids)==len(set(ids))==2 and ids==[a['old_external_ID'],a['latest_external_ID']]
 assert w['A_after_B']['state']==a['A_after_actual_adoption']['state']=='Replaced'
 assert w['next_constructed'] is True and w['next_started'] is False and w['engine_mutex_held'] is False and w['callback_gate'] is False
 assert a['actual_A_RAW_observed'] is True and a['A_identity_matches_adoption'] is False and a['protected_before_output'] is False and a['A_past_immutable_after_B'] is True
 assert a['actual_A_session'] and a['actual_A_epoch'] and a['actual_A_RAW_end']>a['actual_A_RAW_first'] and a['actual_initial_B_callback_frame']==w['input_B']
 assert a['B_Completed']['state']=='Completed' and a['B_Completed']['output_started'] is True
 return s,dict(selected=w,actual_adoption=a)
def main():
 p=argparse.ArgumentParser();p.add_argument('--kind',choices=['baseline','fixed'],required=True);p.add_argument('--build-record',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);assert out.is_relative_to(ROOT/'build')
 root_source=source_manifest(ROOT);record=read(a.build_record)
 assert record['status']=='PASS'
 if a.kind=='baseline':
  binary=Path(record['binary']['path']);source=record['source'];snapshot=BASE/'baseline_01/source';assert source_manifest(snapshot)['sha256']==source
 else:
  source=root_source['sha256'];assert record['source_inventory_sha256']==source;binary=Path(record['build_log']['path']).parent.parent/'candidate_build/phase62_adoption_review_native'
  assert identity(binary)['sha256']==record['binaries'][binary.name]
 binary_id=identity(binary);modes=['f01_dsp_done','f01_checkpoint']+([] if a.kind=='baseline' else ['f01_selected_stop','f01_selected_clear','f01_selected_failure']);jobs=[]
 for preset in ['candidate','baseline']:
  for mode in modes:
   input=INPUTS/('short240ms.wav' if mode=='f01_dsp_done' else 'one_second.wav');key=mode+'_'+preset;wanted=MAIN if mode in ['f01_dsp_done','f01_checkpoint'] else CANCEL
   jobs.append(dict(id=key,mode=mode,expected=len(wanted),required_checks=wanted,binary=binary.name,command=list(map(str,[binary,mode,input,preset,out/key,source])),input=identity(input)))
 save(out/'EXPECTED.json',dict(kind=a.kind,source=source,root_source=root_source,build_record=identity(a.build_record),binary=binary_id,driver=identity(Path(__file__)),expected_programs=len(jobs),expected_checks=sum(j['expected'] for j in jobs),required_ids=[j['id'] for j in jobs],jobs=jobs,serial_audio=True,RT_deadline_approval='NOT_ASSESSED',baseline_expected_child_exit=1 if a.kind=='baseline' else None,baseline_expected_completed_checks_before_failure=4 if a.kind=='baseline' else None))
 rows=[]
 for job in jobs:
  assert source_manifest(ROOT)==root_source and identity(binary)==binary_id
  start=time.monotonic();log=out/(job['id']+'.log');timed=False
  with log.open('w') as f:
   try:code=subprocess.run(job['command'],stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
   except subprocess.TimeoutExpired:code=None;timed=True
  try:
   child=out/job['id'];spec=read(child/'EXPECTED.json');assert spec['checks']==job['required_checks'] and spec['source_list_sha256']==source and spec['binary_sha256']==binary_id['sha256']
   if a.kind=='baseline':summary,observations=reproduce(child,code,timed);status='EXPECTED_FAILURE_REPRODUCED';reasons=[]
   else:
    summary,reasons=verify(job,child,code,timed);status='PASS' if not reasons else 'FAIL';observations={}
   assert source_manifest(ROOT)==root_source and identity(binary)==binary_id
   if a.kind=='baseline':assert source_manifest(snapshot)['sha256']==source
  except (AssertionError,ValueError,OSError,KeyError,TypeError) as e:summary={};observations={};status='FAIL';reasons=[str(e)]
  rows.append(dict(id=job['id'],status=status,exit=code,timed_out=timed,seconds=time.monotonic()-start,expected=job['expected'],executed=summary.get('executed',0),reasons=reasons,summary=summary,observations=observations,log=identity(log)))
  complete=len(rows)==len(jobs);ok=all(r['status'] in ['PASS','EXPECTED_FAILURE_REPRODUCED'] for r in rows)
  save(out/'SUMMARY.json',dict(status='PASS' if complete and ok else 'INCOMPLETE',meaning='旧不具合の再現成功（子FAIL保持）' if a.kind=='baseline' else 'F01修正版の機能検証',run_complete=complete,expected_programs=len(jobs),executed_programs=len(rows),expected_checks=sum(j['expected'] for j in jobs),executed_checks=sum(r['executed'] for r in rows),source=source,root_source=root_source['sha256'],rows=rows,local_overall_go=False));print(job['id'],status,round(rows[-1]['seconds'],2),reasons,flush=True)
 return 0 if all(r['status'] in ['PASS','EXPECTED_FAILURE_REPRODUCED'] for r in rows) else 2
if __name__=='__main__':raise SystemExit(main())
