"""署名したApp SandboxホストをNSOpenPanelで実行し、全期待結果を保存する。"""
import json,sys,time,subprocess,shutil,errno
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity,sha
F=ROOT/'build/phase62_fix/run_01/final_v9';OUT=F/'sandbox_evidence';IO=F/'sandbox_io';APP=F/'release/phase62_fix_sandbox_app.app';INPUT=ROOT/'build/phase62/run_01/native_release/boundary_48000_2_1.wav';ENT=ROOT/'tests/Phase61Sandbox.entitlements'
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
if len(sys.argv)>1:
 mode=sys.argv[1]
 if mode=='launch':
  IO.mkdir();denied=F/'SANDBOX_DENIED.txt';denied.write_text('検証専用。出力grantの外にあるファイル。\n');commands=[]
  for cmd in [['codesign','--force','--sign','-','--entitlements',str(ENT),str(APP)],['codesign','--verify','--strict',str(APP)],['codesign','--display','--entitlements','-',str(APP)]]:
   p=subprocess.run(cmd,capture_output=True,text=True);commands.append(dict(command=cmd,exit=p.returncode,stdout=p.stdout,stderr=p.stderr))
   if p.returncode:save(OUT/'SIGNATURE.json',dict(PASS=False,commands=commands));raise SystemExit(1)
  save(OUT/'SIGNATURE.json',dict(PASS=True,commands=commands,host=identity(APP/'Contents/MacOS/phase62_fix_sandbox_app'),entitlements=identity(ENT)))
  before=identity(INPUT);started=time.time_ns();save(OUT/'LAUNCH.json',dict(started_ns=started,input=before,output=str(IO),denied=identity(denied),source_sha256=source_manifest(ROOT)['sha256']))
  command=['open','-n','-W',str(APP)];p=subprocess.run(command,timeout=900)
  runs=[q for q in IO.glob('run_*') if q.is_dir() and q.stat().st_mtime_ns>=started]
  if len(runs)!=1:raise RuntimeError('新規App出力が一意でない: '+str(runs))
  run=runs[0];app=json.loads((run/'APP_RESULT.json').read_text());context=json.loads((run/'SANDBOX_CONTEXT.json').read_text())
  save(OUT/'RUN_CONTEXT.json',dict(run=str(run),context=context,app=app,decoded=identity(run/'sandbox_decoded_4s.wav')))
  good=p.returncode==0 and app['exit']==0 and not app['error_present'] and sha(INPUT)==before['sha256']
  save(OUT/'APP_RESULT.json',dict(PASS=bool(good),app=app,command=command,launch_exit=p.returncode,input_unchanged=sha(INPUT)==before['sha256']));raise SystemExit(int(not good))
 context=json.loads((OUT/'RUN_CONTEXT.json').read_text());run=Path(context['run']);c=context['context']
 if mode in ('candidate','baseline'):
  dest=OUT/mode;dest.mkdir()
  for name in ('result.json','boundaries.jsonl','last_boundary.json','callbacks_all_spans.jsonl','clock_anomaly_window.jsonl','loop_final_reuse.json','clear_result.json','after_clear_callbacks_all_spans.jsonl'):
   shutil.copyfile(run/'native'/mode/name,dest/name)
 elif mode=='faults':shutil.copyfile(run/'native/faults/checks.jsonl',OUT/'checks.jsonl')
 elif mode=='grants':
  good=c['input_scope_started'] and c['output_scope_started'];save(OUT/'GRANTS.json',dict(PASS=bool(good),context=c));raise SystemExit(int(not good))
 elif mode=='denied':
  good=c['outside_grant_open_fd']<0 and c['outside_grant_errno'] in (errno.EPERM,errno.EACCES);save(OUT/'DENIED.json',dict(PASS=bool(good),context=c,existing_denied_file=identity(F/'SANDBOX_DENIED.txt')));raise SystemExit(int(not good))
 else:raise SystemExit('unknown mode')
 raise SystemExit(0)
cases=[dict(id='app_runtime',kind='json_pass',required=['APP_RESULT.json','RUN_CONTEXT.json','SIGNATURE.json','LAUNCH.json'],result='APP_RESULT.json')]
for name in ('candidate','baseline'):cases.append(dict(id=name,kind='native',cycles=100,period_preserving=True,clear_contract=True,required=[name+'/result.json',name+'/boundaries.jsonl',name+'/last_boundary.json',name+'/callbacks_all_spans.jsonl',name+'/loop_final_reuse.json',name+'/clear_result.json',name+'/after_clear_callbacks_all_spans.jsonl'],result=name+'/result.json'))
checks=['opt_in_and_public_gates']+['reservation_budget_failure','ready_a_replace_reject_clear','before_workgroup_failure','before_publication_failure','route_safe_stop_and_explicit_replay','input_path_loss']*2
cases += [dict(id='faults',kind='checks',required=['checks.jsonl'],result='checks.jsonl',checks=checks),dict(id='security_scopes',kind='json_pass',required=['GRANTS.json'],result='GRANTS.json'),dict(id='outside_grant_denied',kind='json_pass',required=['DENIED.json'],result='DENIED.json')]
frozen=source_manifest(ROOT);ledger=Ledger(OUT,cases,dict(source=frozen,driver=identity(__file__),architecture='arm64',configuration='Release',input=identity(INPUT),limitations=['MerodoaのTCC拒否・期限切れbookmarkは代替しない','元音源をscope中に1回デコードし、ローカル検証WAVを全セッションへ共有']))
while not (F/'paired_1000/SUMMARY.json').is_file():time.sleep(5)
if source_manifest(ROOT)['sha256']!=frozen['sha256']:raise SystemExit('SOURCE CHANGED')
for case,mode in [('app_runtime','launch'),('candidate','candidate'),('baseline','baseline'),('faults','faults'),('security_scopes','grants'),('outside_grant_denied','denied')]:
 good=ledger.run(case,[sys.executable,'-B',__file__,mode],cwd=ROOT,timeout=1000,inputs=[INPUT,ENT]);print(case,ledger.rows[case]['status'],flush=True)
 if case=='app_runtime' and not good:break
ledger.save();r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
