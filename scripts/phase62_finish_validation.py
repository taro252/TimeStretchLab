"""Phase62残件の層別試験。全起動を直列化し、完了ID・件数・SHAを検査する。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
from phase62_evidence import identity,source_manifest,verify_architecture
from phase59_native_validation import wav_info
from phase55_study import write_wav

ROOT=Path(__file__).resolve().parents[1]
PLAYING_CHECK_IDS={
 'latest_noop':['75_cancelled_before_commit','100_completed_noop','40_replaced_before_commit','200_completed_actual_PCM','all_four_IDs_terminal','normal_supply_and_owner_cap'],
 'committed_replace':['75_committed_before_B','200_accepted_without_rewriting_75','required_fixed75_B_and_PCM','75_and_200_completed','past_immutable_all_IDs_terminal','normal_supply_and_owner_cap'],
 'committed_clear':['75_committed_before_B','100_transferred_to_Clear_before_B','Clear_rejects_speed_with_reason','required_fixed75_B_and_PCM','Clear_normal_continuation_no_extra_cycle','latest100_Clear_PCM_all_IDs_terminal_past_immutable','normal_supply_and_owner_cap'],
}
for _mode,_close_check in [('limit_stop','Stop_cancels_all_IDs'),('limit_reprepare','Stop_then_different_input_no_stale_revival'),('limit_close','direct_close_quiesces_and_retires')]:
 PLAYING_CHECK_IDS[_mode]=['three_Accepted_IDs_reserved','limit_rejection_preserves_latest_and_PCM','duplicate_keeps_ID_at_limit',_close_check,'post_close_owned_sink_exact_IDs_and_terminal_kinds' if _mode=='limit_close' else 'all_IDs_terminal_history_immutable','normal_supply_and_owner_cap']

def playing_jobs(build,source,other_input,out):
 jobs=[]
 for mode,wanted in PLAYING_CHECK_IDS.items():
  for preset in ['candidate','baseline']:
   key=mode+'_'+preset;command=[build/'phase62_playing_ledger_native',mode,source,preset,out/key]
   if mode=='limit_reprepare':command.append(other_input)
   jobs.append(dict(id=key,mode=mode,command=list(map(str,command)),expected=len(wanted),expected_IDs=list(wanted)))
 return jobs

def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def read(p):return json.loads(p.read_text())
def verify_build(provenance,source,binaries):
 if provenance.get('status')!='PASS' or provenance.get('source_inventory_sha256')!=source:raise ValueError('successful build/source provenance absent')
 if not provenance.get('compiler') or provenance.get('architecture')!='arm64' or not provenance.get('configuration'):raise ValueError('compiler/configuration/architecture absent')
 for path in binaries:
  if provenance.get('binaries',{}).get(path.name)!=identity(path)['sha256']:raise ValueError('executed binary not linked to built source: '+path.name)

def verify_close_audit(folder,stat):
 """close後は所有sinkだけを照合し、旧runの未完了を成功へ読み替えない。"""
 try:
  rows=lambda name:[json.loads(x) for x in (folder/name).read_text().splitlines()]
  receipts=rows('receipts.jsonl');accepted=[r['id'] for r in receipts if r.get('accepted') is True and r.get('duplicate') is False]
  if len(accepted)!=3 or any(type(i) is not int or i<=0 for i in accepted) or len(set(accepted))!=3:return False
  if stat.get('Accepted_IDs')!=accepted:return False
  sink=rows('sink.jsonl');prior=rows('pre_close_ledger.jsonl')
  if len(sink)!=5 or len(prior)!=3:return False
  delivery,marker=sink[0],sink[-1];operations=sink[1:-1]
  if delivery.get('record')!='audit_delivery' or type(delivery.get('calls')) is not int or delivery['calls']!=1:return False
  sequence=delivery.get('sequence')
  if type(sequence) is not int or sequence<=0 or delivery.get('copied_count')!=3:return False
  if any(delivery.get(k) is not True for k in ['received','workers_joined','retirement_complete']):return False
  if any(delivery.get(k) is not False for k in ['duplicate_delivery','oversized','copy_failed','invalid_marker']):return False
  if marker.get('record')!='FINAL_LOOP_SPEED_AUDIT_COMPLETE' or type(marker.get('sequence')) is not int or marker.get('sequence')!=sequence:return False
  if any(type(marker.get(k)) is not int or marker[k]!=v for k,v in [('expected_Accepted',3),('actual',3),('Completed',1),('Replaced',1),('Cancelled',1)]):return False
  if any(marker.get(k) is not True for k in ['all_workers_joined','retirement_complete','receipt_ID_set_exact','past_immutable','direct_close']):return False
  if {r['id'] for r in prior}!=set(accepted) or {r['id'] for r in operations}!=set(accepted):return False
  old={r['id']:r for r in prior};final={r['id']:r for r in operations}
  for index,request_id in enumerate(accepted):
   before,after=old[request_id],final[request_id]
   if after.get('state')!=['Completed','Replaced','Cancelled'][index]:return False
   if any(after.get(k)!=before.get(k) for k in ['id','loop_id','input_generation','source_session','source_epoch','accepted_ns','speed_micros']):return False
   if type(after.get('accepted_ns')) is not int or type(after.get('terminal_ns')) is not int or not 0<after['accepted_ns']<=after['terminal_ns']:return False
   if index<2:
    if after!=before:return False
   elif before.get('state') in ['Completed','Replaced','Cancelled','Failed'] or not after.get('reason'):return False
   if index==0:
    if any(after.get(k) is not True for k in ['committed','output_started']):return False
    if any(type(after.get(k)) is not int or after[k]<=0 for k in ['first_PCM_observed_ns','completed_ns','dynamic_session','dynamic_operation_id']):return False
   elif after.get('committed') is not False or after.get('output_started') is not False or not after.get('reason'):return False
   if index==2 and (after.get('first_PCM_observed_ns')!=0 or before.get('committed') is not False or before.get('output_started') is not False):return False
  return True
 except (OSError,ValueError,KeyError,TypeError,AttributeError):return False

def verify_result(suite,job,folder,code,timed,stat):
 valid=type(code) is int and code==0 and not timed and stat.get('status')=='PASS' and all(type(x) is int and x>0 for x in [stat.get('expected'),stat.get('executed'),job['expected']]) and stat.get('expected')==stat.get('executed')==job['expected'] and stat.get('run_complete') is True
 if suite in ('playing','paused-clear'):
  if not (folder/'checks.jsonl').is_file() or not (folder/'EXPECTED.json').is_file():return False
  try:
   checks=[json.loads(x) for x in (folder/'checks.jsonl').read_text().splitlines()];ids=[x['id'] for x in checks];wanted=read(folder/'EXPECTED.json')['expected_IDs']
   valid &= isinstance(wanted,list) and all(isinstance(i,str) and i for i in wanted+ids) and len(ids)==len(set(ids))==len(wanted)==len(set(wanted))==job['expected'] and set(ids)==set(wanted) and all(x['status']=='PASS' for x in checks)
   if 'expected_IDs' in job:valid &= set(wanted)==set(job['expected_IDs']) and len(wanted)==len(job['expected_IDs'])
  except (OSError,ValueError,KeyError,TypeError):return False
 if suite=='playing' and job.get('mode')=='limit_close':valid &= verify_close_audit(folder,stat)
 return valid

def main():
 p=argparse.ArgumentParser(__doc__);p.add_argument('--suite',choices=['api','cache','playing','paused-clear'],required=True)
 p.add_argument('--build',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--other-input',type=Path)
 p.add_argument('--output',type=Path,required=True);p.add_argument('--build-provenance',type=Path,required=True)
 a=p.parse_args();b=a.build.resolve();src=a.input.resolve();out=a.output.resolve()
 if not out.is_relative_to(ROOT/'build'):raise ValueError('新規build保存先が必要')
 out.mkdir(parents=True,exist_ok=False);m=wav_info(src);r=m['rate'];jobs=[];frozen=source_manifest(ROOT)
 def add(k,c,**kw):jobs.append(dict(id=k,command=list(map(str,c)),**kw))
 if a.suite=='api':
  if not a.build_provenance:raise ValueError('実ビルド来歴が必要')
  configurations=[('A0_cold',0,8*r,0,-1,'return',750000,0),('nonzeroA_cold',r,7*r,0,-1,'return',1250000,0),
   ('nonzeroA_warm3',r,7*r,3,-1,'return',750000,0),('partial_C',r,7*r,0,2*r,'return',750000,0),
   ('KeepPosition_C',0,m['frames'],0,3*r,'keep',750000,0)]
  configurations += [(f'partial_map_{length}',r,r+length,2,-1,'return',750000,length) for length in [95999,96000,96001]]
  for label,ia,ib,warm,entry,policy,target,required in configurations:
   for preset in ['candidate','baseline']:
    key=label+'_'+preset;cmd=[sys.executable,'-B',ROOT/'scripts/phase62_api_oracle_audit.py',src,preset,out/key,b/'phase62_api_oracle_native',ROOT/'build/phase59_frozen/captured_reference',ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference','--a',ia,'--b',ib,'--warm',warm,'--entry',entry,'--policy',policy,'--target',target,'--capture-seconds',100,'--build-provenance',a.build_provenance.resolve(),'--boundary-reference',b/'phase62_api_boundary_reference']
    if required:cmd+=['--required-initial-period',required]
    add(key,cmd,expected=1)
  binaries=[b/'phase62_api_oracle_native',b/'phase62_api_boundary_reference']
 elif a.suite=='cache':
  small=out/'whole500ms.wav'
  with src.open('rb') as f:f.seek(m['data_offset']);data=f.read(r//2*m['channels']*(m['bits']//8))
  write_wav(small,r,m['channels'],m['encoding'],data)
  save(out/'INPUT_RECIPE.json',dict(source=identity(src),generated=identity(small),recipe='先頭500msのPCM bytesを保持。全曲短区間非cacheの専用fixture。必須原本ゲートの代用ではない'))
  cases=[('nonzero_cache',src,17,17+r,1000000,750000,8192,512,'cache','either',0),('whole500ms',small,0,r//2,1000000,750000,512,512,'uncached','either',0),('short100ms_2x',src,17,17+r//10,2000000,750000,64,4096,'cache','fixed',0)]
  cases += [(f'map_{length}',src,r,r+length,1000000,750000,8192,512,'cache' if length<=96000 else 'uncached','dynamic',length) for length in [95999,96000,96001]]
  for label,input,ia,ib,initial,target,offset,cb,cache,decision,length in cases:
   for preset in ['candidate','baseline']:
    key=label+'_'+preset;add(key,[b/'phase62_cache_focus_tests',input,preset,out/key,ia,ib,initial,target,2,offset,cb,cache,decision,length],expected=1)
  binaries=[b/'phase62_cache_focus_tests']
 elif a.suite=='paused-clear':
  for mode in ['initial_return_clear','initial_started_clear','committed_preparing','manual_seek','ready','started_no_pcm']:
   for preset in ['candidate','baseline']:
    key=mode+'_'+preset;add(key,[b/'phase62_paused_clear_native',mode,src,preset,out/key],expected=2,allowed_incomplete=mode=='started_no_pcm')
  binaries=[b/'phase62_paused_clear_native']
 else:
  if not a.other_input or identity(a.other_input)['sha256']==identity(src)['sha256']:raise ValueError('別内容の入力が必要')
  jobs=playing_jobs(b,src,a.other_input.resolve(),out)
  binaries=[b/'phase62_playing_ledger_native']
 arches=verify_architecture(binaries)
 if not arches['PASS']:raise ValueError('arm64 binaryが必要')
 verify_build(read(a.build_provenance),frozen['sha256'],binaries)
 identities={str(x):identity(x) for x in binaries}
 save(out/'SOURCE.json',frozen);save(out/'EXPECTED.json',dict(schema=2,suite=a.suite,source_inventory_sha256=frozen['sha256'],expected_programs=len(jobs),expected_checks=sum(j['expected'] for j in jobs),required_ids=[j['id'] for j in jobs],jobs=jobs,binaries=list(identities.values()),input=identity(src),other_input=identity(a.other_input) if a.other_input else None,serial=True,architecture=arches))
 results=[]
 for j in jobs:
  if source_manifest(ROOT)['sha256']!=frozen['sha256']:raise ValueError('実行中のソース変更')
  timed=False;start=time.monotonic();log=out/(j['id']+'.log')
  with log.open('w') as f:
   try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=600).returncode
   except subprocess.TimeoutExpired:code=None;timed=True
  folder=out/j['id'];stat=read(folder/'SUMMARY.json') if (folder/'SUMMARY.json').exists() else {}
  valid=verify_result(a.suite,j,folder,code,timed,stat)
  same=source_manifest(ROOT)['sha256']==frozen['sha256'] and all(identity(Path(x))==y for x,y in identities.items())
  status='PASS' if valid and same else 'INCOMPLETE' if timed or j.get('allowed_incomplete') and code==3 and stat.get('status')=='INCOMPLETE' else 'FAIL'
  results.append(dict(id=j['id'],status=status,exit=code,timed_out=timed,expected=j['expected'],executed=stat.get('executed',0),seconds=time.monotonic()-start,source_and_binary_unchanged=same,result=stat,log=identity(log)))
  complete=len(results)==len(jobs);ok=complete and all(x['status']=='PASS' for x in results)
  save(out/'SUMMARY.json',dict(schema=2,run_complete=complete,status='PASS' if ok else 'INCOMPLETE',suite=a.suite,source_inventory_sha256=frozen['sha256'],required_ids=[j['id'] for j in jobs],executed_ids=[x['id'] for x in results],expected_programs=len(jobs),executed_programs=len(results),expected_checks=sum(x['expected'] for x in jobs),executed_checks=sum(x['executed'] for x in results),rows=results,local_overall_go=False))
  print(j['id'],status,round(results[-1]['seconds'],2),flush=True)
 return 0 if all(x['status']=='PASS' for x in results) else 2

if __name__=='__main__':raise SystemExit(main())
