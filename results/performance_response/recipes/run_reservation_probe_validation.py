"""予約見積の誤判定を修正したhostだけを05製品で直列検証する。旧FAILは保持。"""
import argparse
from pathlib import Path
import shutil
import sys
import tempfile
import run_pairs as c
R=Path(__file__).resolve().parents[3];B=R/'build/performance_response_20261023_01';S=Path(__file__).parent
SOURCE='0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e'
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();o=a.output.resolve()
c.require(o.is_relative_to(B),'new B output');o.mkdir(exist_ok=False)
q=c.load(B/'disk_recovery_queue_final07/SUMMARY.json');c.require(q.get('complete') is True and q['executed_steps']==q['expected_steps']==10,'all previous children reaped')
jobs=[]
def add(name,recipe,args,timeout,native=False):jobs.append({'id':name,'command':[sys.executable,str(S/recipe),*map(str,args)],'recipe':c.identity(S/recipe),'timeout_s':timeout,'native':native})
wc=B/'warm_ab_clients_final08/CLIENT.json';dc=B/'paused_deep_clients_final08/CLIENT.json';w=B/'warm_ab_pairs_final08'
for p in [wc,dc]:c.require(c.load(p)['status']=='PASS','new successful host build')
add('warm_12','run_generic_warm_ab_pairs_v3.py',['--client',wc,'--source-sha',SOURCE,'--output',w],1800,True)
add('paused_deep_6','run_paused_deep_pairs_v2.py',['--client',dc,'--output',B/'paused_deep_pairs_final08'],1800,True)
add('warm_independent_24','validate_warm_ab_captures_v3.py',['--run',w,'--client',wc,'--references',B/'ab_fixed_references_final_01/REFERENCES.json','--candidate-source',SOURCE,'--output',B/'warm_ab_capture_audit_final08'],1200)
c.save(o/'EXPECTED.json',{'driver':c.identity(__file__),'source':SOURCE,'jobs':jobs,'expected_steps':3,'serial':True,'normal_programs':18,'normal_checks':216,'probe_programs_separately':18,'probe_starts_audio':False,'primary_cost_excludes_probe':True,'external_wait4_includes_probe':True,'expected_warm_captures':24,'expected_PCM_checks':120})
rows=[]
for j in jobs:
 c.require(c.current_source_digest(R)==SOURCE and c.identity(j['recipe']['path'])==j['recipe'],'fixed source/recipe')
 if j['native']:c.require(min(shutil.disk_usage(B).free,shutil.disk_usage(tempfile.gettempdir()).free)>57600100+256*1024*1024+16*1024*1024,'space before native')
 print('START',j['id'],flush=True);x=c.execute(j['command'],o/(j['id']+'.log'),j['timeout_s']);rows.append({'id':j['id'],'execution':x})
 c.save(o/'PROGRESS.json',{'expected_steps':3,'executed_steps':len(rows),'rows':rows});print('END',j['id'],x['returncode'],flush=True)
 c.require(not x['timeout'] and not x['interrupted'],'native supervisor group stopped/reaped')
 if x['returncode'] not in (0,2):break
complete=len(rows)==3;good=complete and all(x['execution']['returncode']==0 for x in rows)
c.save(o/'SUMMARY.json',{'status':'PASS' if good else 'COMPLETE_WITH_FAILURES' if complete else 'INCOMPLETE','complete':complete,'expected_steps':3,'executed_steps':len(rows),'rows':rows,'source':SOURCE})
sys.exit(0 if good else 2)
