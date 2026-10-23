"""最終ソースに対する必要な回帰を一担当で直列に集約する。"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--build-record',type=Path,required=True);p.add_argument('--run',default='03');a=p.parse_args();base=a.base.resolve();build=json.loads(a.build_record.read_text());source=source_manifest(ROOT);assert build['status']=='PASS' and source['sha256']==build['source'];out=base/('final_regression_sequence_'+a.run);out.mkdir(exist_ok=False);py=sys.executable;recipes=Path(__file__).parent.resolve();directory=str(base/'inputs');binary_dir=str(Path(build['binaries']['phase62_control_cpu_native']['path']).parent);jobs=[
 ['control',[py,str(recipes/'run_control_regressions.py'),'--build-record',str(a.build_record.resolve()),'--input-dir',directory,'--output',str(base/('control_regressions_'+a.run))]],
 ['history',[py,str(ROOT/'results/phase62_terminal_initial/recipes/run_history_regressions.py'),'--build-record',str(a.build_record.resolve()),'--output',str(base/('history_regressions_'+a.run)),'--fixture',str(base/'inputs/artificial_6s.wav')]],
 ['runtime',[py,str(recipes/'run_runtime_regressions.py'),'--build-record',str(a.build_record.resolve()),'--input-dir',directory,'--output',str(base/('runtime_regressions_'+a.run))]],
 ['partial',[py,str(recipes/'run_partial.py'),'--build-record',str(a.build_record.resolve()),'--output',str(base/('partial_regressions_'+a.run))]],
 ['dynamic',[py,str(ROOT/'scripts/phase62_dynamic_validation.py'),'--suite','dynamic-priority','--build',binary_dir,'--output',str(base/('dynamic_priority_'+a.run)),'--configuration','Release']],
 ['gates',[py,str(ROOT/'scripts/phase62_gate_runner.py'),'--root',str(ROOT),'--build-base',str(base/'gate_builds'),'--release-build',binary_dir,'--output',str(base/('final_gates_'+a.run))]]]
def save(name,v):(out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
save('EXPECTED.json',dict(source=source,build=identity(a.build_record),driver=identity(Path(__file__)),jobs=jobs,expected_stages=6,serial=True));rows=[]
for name,command in jobs:
 assert source_manifest(ROOT)==source;start=time.monotonic();timed=False
 with (out/(name+'.log')).open('w') as f:
  try:code=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=1800).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 rows.append(dict(id=name,command=command,exit=code,timeout=timed,seconds=time.monotonic()-start,log=identity(out/(name+'.log'))));done=len(rows)==6;save('SUMMARY.json',dict(status='PASS' if done and all(x['exit']==0 and not x['timeout'] for x in rows) else 'INCOMPLETE',run_complete=done,expected=6,executed=len(rows),rows=rows));print(name,code,timed,round(rows[-1]['seconds'],2),flush=True)
 if code!=0 or timed:raise SystemExit(2)
