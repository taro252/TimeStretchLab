"""入力複製容量で再生前に停止した条件だけを別runへ直列再収録する。

主19step/CPU追加12が終了済みであることを要求する。元失敗は保持する。
freshは元70完了+新2を明示した回収台帳、nonfresh/warm/deep/sampleは全件新規。
製品の空き容量基準は変更しない。測定間の保存共有は全byte/SHA/パスを保持する。
"""
import argparse
import datetime
import os
from pathlib import Path
import shutil
import sys
import tempfile
import run_pairs as c
R=Path(__file__).resolve().parents[3]
B=R/'build/performance_response_20261023_01'
S=Path(__file__).parent
SOURCE='0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e'
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args(); out=a.output.resolve()
c.require(out.is_relative_to(B),'new evidence under B'); out.mkdir(exist_ok=False)
q=c.load(B/'final_response_queue_02/SUMMARY.json')
f=c.load(B/'steady_followup_final07/SUMMARY.json')
c.require(q.get('complete') is True and q['executed_steps']==q['expected_steps']==19,'primary closed')
c.require(f.get('executed_new_programs')==12 and f.get('expected_new_programs')==12,'CPU followup reaped all12')
c.require(c.current_source_digest(R)==SOURCE,'source05')
jobs=[]
def add(key,script,args,timeout=1800,native=False):
 jobs.append({'id':key,'command':[sys.executable,str(S/script),*map(str,args)],'timeout_s':timeout,
              'driver':c.identity(S/script),'native':native})
def share(key,roots):
 rec=out/(key+'_QUIESCENCE.json')
 add(key,'share_capture_prefixes.py',['--roots',*roots,'--quiescence-record',rec,'--output',out/(key+'_SHARING.json')],300)
 jobs[-1]['quiescence_roots']=list(map(str,roots));jobs[-1]['quiescence_record']=str(rec)
build=B/'build_timer_candidate_05/BUILD.json';base=B/'frozen_clients_02/CLIENT.json'
main=B/'ab_main_recovered_final07'; nonfresh=B/'ab_nonfresh_pairs_final07';warm=B/'warm_ab_pairs_final07'
add('fresh_recover_2','recover_ab_main_pairs.py',['--baseline-client',base,'--candidate-build',build,'--observation-clients',B/'ab_observation_clients_final06/CLIENT.json','--mono-input',R/'results/phase56/long/chain_300s.wav','--stereo-input',B/'ab_stereo48_input_01/music_48000_2_300s.wav','--recover-run',B/'ab_main_pairs_final06','--output',main],900,True)
share('share_fresh',[B/'ab_main_pairs_final06',main])
add('nonfresh_36','run_pairs.py',['--baseline-client',base,'--candidate-build',build,'--suite','ab','--only','A30_prewarm_candidate','A270_prewarm_candidate','A30_early0_candidate','A270_early0_candidate','A30_mid_candidate','A270_mid_candidate','--output',nonfresh],2400,True)
share('share_nonfresh',[B/'ab_main_pairs_final06',main,nonfresh])
add('warm_12','run_generic_warm_ab_pairs_v2.py',['--client',B/'warm_ab_clients_final06/CLIENT.json','--source-sha',SOURCE,'--output',warm],1800,True)
share('share_warm',[nonfresh,warm])
add('paused_deep_6','run_paused_deep_pairs.py',['--client',B/'paused_deep_clients_final06/CLIENT.json','--output',B/'paused_deep_pairs_final07'],1800,True)
add('diagnostic_sample_2','run_generic_diagnostic_sample.py',['--candidate-build',build,'--source-sha',SOURCE,'--output',B/'diagnostic_sample_final07'],300,True)
add('independent_AB_108','validate_ab_captures_v2.py',['--main-run',main,'--nonfresh-run',nonfresh,'--references',B/'ab_fixed_references_final_01/REFERENCES.json','--host-manifest',B/'ab_observation_clients_final06/CLIENT.json','--candidate-source',SOURCE,'--output',B/'ab_capture_audit_final07'],1800)
add('independent_warm_24','validate_warm_ab_captures_v2.py',['--run',warm,'--client',B/'warm_ab_clients_final06/CLIENT.json','--references',B/'ab_fixed_references_final_01/REFERENCES.json','--candidate-source',SOURCE,'--output',B/'warm_ab_capture_audit_final07'],1800)
expected={'source':SOURCE,'driver':c.identity(__file__),'jobs':jobs,'expected_steps':len(jobs),'primary':c.identity(B/'final_response_queue_02/SUMMARY.json'),'CPU_followup':c.identity(B/'steady_followup_final07/SUMMARY.json'),'serial':True,'fresh_reused70_not_counted_as_new':True,'preserve_failures':True,'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
c.save(out/'EXPECTED.json',expected)
rows=[]
for job in jobs:
 c.require(c.current_source_digest(R)==SOURCE and c.identity(job['driver']['path'])==job['driver'],'fixed source/recipe')
 if job['native']:
  c.require(min(shutil.disk_usage(B).free,shutil.disk_usage(tempfile.gettempdir()).free)>115200100+256*1024*1024+16*1024*1024,'space before native stage; stop queue safely')
 if 'quiescence_roots' in job:
  c.save(Path(job['quiescence_record']),{'status':'WRITERS_QUIESCENT','native_measurement_in_progress':False,'roots':job['quiescence_roots'],'evidence':'each previous direct driver reaped; no next launch until sharing returns; lsof pre/post also required'})
 print('START',job['id'],flush=True)
 e=c.execute(job['command'],out/(job['id']+'.log'),job['timeout_s'])
 rows.append({'id':job['id'],'execution':e,'status_scope':'driver completion only; numeric/RT/latency separate'})
 c.save(out/'PROGRESS.json',{'expected_steps':len(jobs),'executed_steps':len(rows),'rows':rows})
 print('END',job['id'],e['returncode'],flush=True)
 c.require(not e['timeout'] and not e['interrupted'],'interrupted driver; group terminated/reaped')
 if e['returncode'] not in (0,2):break
complete=len(rows)==len(jobs)
c.save(out/'SUMMARY.json',{'status':'PASS' if complete and all(r['execution']['returncode']==0 for r in rows) else 'COMPLETE_WITH_FAILURES' if complete else 'INCOMPLETE','complete':complete,'expected_steps':len(jobs),'executed_steps':len(rows),'rows':rows,'source':SOURCE})
sys.exit(0 if complete and all(r['execution']['returncode']==0 for r in rows) else 2)
