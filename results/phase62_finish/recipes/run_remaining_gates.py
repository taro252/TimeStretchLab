"""既存の条件を新binaryで直列再実行。完了ID・件数と原本の来歴を別に保存する。"""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase62_aggregation import exact_ids,rows_complete
OLD=ROOT/'build/phase62_dynamic_20261020'
RECIPES=ROOT/'results/phase62_dynamic_loop/recipes'

def read(p):return json.loads(p.read_text())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def declared(e,name):
 if 'commands' in e:return [j['id'] for j in e['commands']]
 if 'jobs' in e:return [j.get('id',j.get('preset')) for j in e['jobs']]
 if name=='final_extra':
  return [f'boundary_{k}_{s}_{p}_{m}' for k,s,p,m in e['boundary']]+[f'handoff_{i}_{t}_{p}_{c}' for i,t,p,c in e['handoff']]
 if name=='final_uncached_boundary':return [f'uncached_{s}_{p}_{m}' for s,p,m in e['conditions']]
 raise ValueError('unknown explicit legacy condition plan: '+name)

def check_selected(folder,source):
 e,s=read(folder/'EXPECTED.json'),read(folder/'SUMMARY.json');wanted=[x['id'] for x in e['cases']];actual=[x['id'] for x in s['cases']]
 exact_ids(wanted,actual,'selected case IDs');allowed={x['id'] for x in e['cases'] if x.get('reason')}
 assert s['final_statistics_present'] is True and s['selected_suite_pass'] is True and not s['source_changed'] and s['source_before']==s['source_after']==source and not s.get('interruption')
 assert all(x['status']=='PASS' or x['id'] in allowed and x['status']=='NOT_RUN' for x in s['cases'])
 measured=s.get('measurements',{}).copy()
 if (folder/'exact/summary.json').exists():measured['exact_passed']=read(folder/'exact/summary.json')['passed']
 if (folder/'golden/summary.json').exists():measured['golden_passed']=len([x for x in read(folder/'golden/summary.json')['results'] if x['PASS'] is True])
 return dict(status='PASS',actual_case_ids=actual,measured=measured,explicit_not_run=sorted(allowed),scope='selected suite only; independent required gaps remain')

def check_rows(folder,ids,source):
 e,s=read(folder/'EXPECTED.json'),read(folder/'SUMMARY.json');rows=s['rows'];wanted=ids
 actual=[r.get('id',r.get('preset')) for r in rows]
 exact_ids(wanted,actual,'required program IDs')
 exp=s.get('expected_programs',s.get('expected'));done=s.get('executed_programs',s.get('executed'))
 assert exp==done==len(rows)==len(ids) and e.get('source',{}).get('sha256')==source
 assert all(x.get('status')=='PASS' and x.get('exit')==0 for x in rows)
 measurements=[];totals={}
 for row in rows:
  value=None;unit=None;field=None;data=row.get('final',row.get('result'))
  if type(row.get('executed')) is int:value=row['executed'];unit='checks';field='row.executed'
  elif isinstance(data,dict) and type(data.get('executed')) is int:value=data['executed'];unit='checks';field='result.executed'
  elif row.get('id')=='faults' and isinstance(data,list) and all(x.get('PASS') is True for x in data):value=len(data);unit='fault_checks';field='len(result)'
  elif isinstance(data,dict) and data.get('functional_pass') is True and type(data.get('cycles')) is int:value=data['cycles'];unit='cycles';field='result.cycles'
  elif str(row.get('id','')).startswith('probe_') and isinstance(data,list) and len(data)==4 and data[-1].get('contract_observations_pass') is True:value=3;unit='observations';field='len(result)-1'
  measurements.append(dict(id=row.get('id',row.get('preset')),unit=unit,count=value,source_field=field))
  if value is not None:totals[unit]=totals.get(unit,0)+value
 rt=[dict(id=r['id'],status=r['realtime_gate']) for r in rows if r.get('realtime_gate') not in (None,'NOT_ASSESSED')]
 return dict(status='PASS',scope='functional only',expected_programs=len(ids),executed_programs=len(rows),actual_program_ids=actual,measurements=measurements,measured_totals_by_unit=totals,realtime=rt,realtime_status='FAIL' if any(r['status']=='FAIL' for r in rt) else 'PASS' if rt else 'NOT_ASSESSED',rows=rows)

def execute(command,log,timeout=7200):
 with log.open('w') as stream:
  child=subprocess.Popen(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
  try:return child.wait(timeout=timeout),False
  except subprocess.TimeoutExpired:
   os.killpg(child.pid,signal.SIGTERM)
   try:child.wait(timeout=15)
   except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
   return None,True

def main():
 p=argparse.ArgumentParser(__doc__);p.add_argument('--group',choices=['offline','renderer','native'],required=True);p.add_argument('--build-base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 build=a.build_base.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);assert out.is_relative_to(ROOT/'build')
 source=source_manifest(ROOT);jobs=[]
 if a.group=='offline':
  for suite,name in [('dynamic161','final_dynamic161'),('dynamic-priority','final_priority'),('regression','final_regression'),('boundary','final_boundary_strict_v8')]:
   jobs.append(dict(id=name,mode='selected',command=[sys.executable,'-B',str(ROOT/'scripts/phase62_dynamic_validation.py'),'--suite',suite,'--build',str(build/'release'),'--output',str(out/name)],directory=name))
  copies=[('run_final_dynamic_strata.py','final_dynamic_strata'),('run_final_dynamic_remaining_formats.py','final_dynamic_remaining_formats'),('run_final_extra.py','final_extra'),('run_final_uncached_boundary.py','final_uncached_boundary'),('run_final_min512.py','final_min512_v9')]
 elif a.group=='renderer':
  jobs.append(dict(id='final_boundary_strict_v8',mode='selected',command=[sys.executable,'-B',str(ROOT/'scripts/phase62_dynamic_validation.py'),'--suite','boundary','--build',str(build/'release'),'--output',str(out/'final_boundary_strict_v8')],directory='final_boundary_strict_v8'))
  copies=[('run_final_extra.py','final_extra'),('run_final_uncached_boundary.py','final_uncached_boundary'),('run_final_min512.py','final_min512_v9')]
 else:
  copies=[('run_final_native_v10.py','final_native_matrix_v10'),('run_final_ordinary_paused.py','final_ordinary_paused'),('run_final_seek_api_v10.py','final_seek_api_v10'),('run_final_clear_pcm.py','final_clear_pcm'),('run_final_native_gates_v10.py','final_native_gates_v10')]
 for recipe,name in copies:
  src=RECIPES/recipe;text=src.read_text().replace("base=ROOT/'build/phase62_dynamic_20261020'",'base=Path('+repr(str(out))+')')
  for var,cfg in [('build','release'),('release','release'),('debug','debug')]:text=text.replace(var+"=base/'"+cfg+"'",var+'=Path('+repr(str(build/cfg))+')')
  # 個別binaryを直接指す旧レシピも、今回buildの絶対位置へ接続する。
  import re
  text=re.sub(r"base/'release/([^']+)'",lambda m:'Path('+repr(str(build/'release'/m[1]))+')',text)
  if recipe in ('run_final_extra.py','run_final_uncached_boundary.py'):
   text=text.replace("dict(id=key,status=", "dict(id=key,exit=code,status=")
  if recipe=='run_final_native_gates_v10.py':
   # 故障試験の子が異常終了しても親が装置bufferを復元する。
   old="jobs.append(('faults',[release/'phase62_native_tests',small,out/'faults','--faults'],'faults',13))"
   new="jobs.append(('faults',[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py','--guard-device-buffer',out/'fault_device_restore.json',release/'phase62_native_tests',small,out/'faults','--faults'],'faults',13))"
   assert old in text;text=text.replace(old,new)
  text=text.replace("old=base/'final_paused'",'old=Path('+repr(str(OLD/'final_paused'))+')')
  text=text.replace("inputs=base/'final_native_matrix_v5'",'inputs=Path('+repr(str(OLD/'final_native_matrix_v5'))+')')
  text=text.replace("source=base/'final_dynamic_priority_v2/dynamic_sustained_48000_mono_pcm16_9s.wav'",'source=Path('+repr(str(OLD/'final_dynamic_priority_v2/dynamic_sustained_48000_mono_pcm16_9s.wav'))+')')
  text=text.replace("base/'r0_fixture_v10/SUMMARY.json'",'Path('+repr(str(OLD/'r0_fixture_v10/SUMMARY.json'))+')')
  if a.group=='renderer':text=text.replace("base/'final_dynamic161/dynamic_sustained_48000_mono_pcm16_9s.wav'",'Path('+repr(str(OLD/'final_dynamic161/dynamic_sustained_48000_mono_pcm16_9s.wav'))+')')
  text=text.replace("driver=base/'run_clear_pcm_native.py'",'driver=ROOT/\'results/phase62_dynamic_loop/recipes/run_clear_pcm_native.py\'')
  driver=out/recipe;driver.write_text(text);ids=declared(read(OLD/name/'EXPECTED.json'),name)
  jobs.append(dict(id=name,mode='rows',directory=name,command=[sys.executable,'-B',str(driver)],required_program_ids=ids,original_recipe=identity(src),adapted_recipe=identity(driver),conditions_only_from=identity(OLD/name/'EXPECTED.json')))
 binary_names=['phase62_dynamic_pcm_tests','phase61_seek_check','phase54_core_probe','phase62_loop_tests','phase62_fix_reuse_tests','phase62_dynamic_boundary_tests','phase62_dynamic_handoff_tests'] if a.group=='offline' else ['phase62_dynamic_boundary_tests','phase62_dynamic_handoff_tests','phase62_loop_tests'] if a.group=='renderer' else ['phase62_dynamic_controls_native','phase62_dynamic_loop_probe','phase62_paused_pcm_tests','paused_speed_native_tests','paused_speed_loop_tests','phase62_dynamic_seek_native','phase62_clear_pcm_native','phase62_native_tests']
 binaries={name:identity(build/'release'/name) for name in binary_names};debug_binary=identity(build/'debug/paused_speed_loop_tests') if a.group=='native' else None;refs=[identity(ROOT/'build/phase59_frozen/captured_reference'),identity(ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference')]
 save(out/'SOURCE.json',source);save(out/'EXPECTED.json',dict(schema=2,group=a.group,expected=len(jobs),required_ids=[j['id'] for j in jobs],jobs=jobs,binaries=binaries,debug_paused_binary=debug_binary,references=refs,source_inventory_sha256=source['sha256'],driver=identity(Path(__file__)),serial=True))
 rows=[]
 for job in jobs:
  assert source_manifest(ROOT)['sha256']==source['sha256'];began=time.monotonic();log=out/(job['id']+'.driver.log');code,timed=execute(job['command'],log)
  try:
   assert code==0 and not timed
   certificate=check_selected(out/job['directory'],source['sha256']) if job['mode']=='selected' else check_rows(out/job['directory'],job['required_program_ids'],source['sha256'])
   assert source_manifest(ROOT)['sha256']==source['sha256'] and all(identity(build/'release'/name)==item for name,item in binaries.items())
   assert debug_binary is None or identity(build/'debug/paused_speed_loop_tests')==debug_binary
   status='INCOMPLETE' if certificate.get('realtime_status')=='FAIL' else 'PASS';reason='functional PASS; realtime FAIL' if status=='INCOMPLETE' else ''
  except (ValueError,AssertionError,OSError,KeyError) as error:certificate={};status='INCOMPLETE' if timed else 'FAIL';reason=str(error)
  rows.append(dict(id=job['id'],status=status,exit=code,timed_out=timed,seconds=time.monotonic()-began,reason=reason,certificate=certificate,log=identity(log)))
  done=len(rows)==len(jobs);save(out/'SUMMARY.json',dict(schema=2,run_complete=done,status='PASS' if done and all(r['status']=='PASS' for r in rows) else 'INCOMPLETE',expected=len(jobs),executed=len(rows),source_inventory_sha256=source['sha256'],rows=rows,local_overall_go=False))
  print(job['id'],status,round(rows[-1]['seconds'],2),flush=True)
  if status!='PASS':return 2
 return 0

if __name__=='__main__':raise SystemExit(main())
