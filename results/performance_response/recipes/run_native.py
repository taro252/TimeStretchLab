"""新規run限定。同じhost/入力/期待IDで性能・機能・RTを別々に記録する。"""
import argparse,itertools,json,pathlib,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import identity
p=argparse.ArgumentParser();p.add_argument('--build-record',type=pathlib.Path,required=True)
p.add_argument('--output',type=pathlib.Path,required=True)
p.add_argument('--suite',choices=['ab-explore','stereo120'],required=True)
p.add_argument('--repeats',type=int,default=3);p.add_argument('--input',type=pathlib.Path)
p.add_argument('--modes',nargs='+',choices=['fresh','prewarm','early_on'],default=['fresh','prewarm','early_on'])
a=p.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False)
build=json.loads(a.build_record.read_text());assert build['status']=='PASS'
def save(n,v):(o/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
save('ENVIRONMENT.json',{k:subprocess.check_output(v,text=True) for k,v in {'OS':['sw_vers'],'CPU':['sysctl','hw.model','hw.memsize','hw.ncpu'],'device':['system_profiler','SPAudioDataType'],'UTC':['date','-u']}.items()})
if a.suite=='stereo120':
 from importlib.util import spec_from_file_location,module_from_spec
 spec=spec_from_file_location('audit',R/'results/progressive_adoption/recipes/audit_native_performance.py');audit=module_from_spec(spec);spec.loader.exec_module(audit)
 host=build['binaries']['phase61_interactive_native_tests'];assert identity(host['path'])==host
 inp=a.input or R/'build/phase61_fast_seek/music_300s.wav';cmd=[host['path'],str(inp),str(o/'data')]
 keys=[[s,c,r,at] for s in (400000,500000,1000000,2000000) for c in (True,False) for r in range(3) for at in (1323000,6615000,11907000,12568500,3672645)]
 save('EXPECTED.json',dict(schema='adoption-native-performance-v1',baseline='5674bd982d98caacaa3e87cdeae5bfc0b01c66ef',build=str(a.build_record.resolve()),candidate_source=build['source'],host_sha256=host['sha256'],input_sha256=identity(inp)['sha256'],expected_count=120,expected_keys=keys,command=cmd,driver=identity(__file__),allow_quality_pass=False,ready_target_p95_ms=200,normal_zero_fields=list(audit.DELTA_FIELDS)))
 start=time.monotonic();timed=False
 with (o/'native.log').open('w') as f:
  try:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=200).returncode
  except subprocess.TimeoutExpired:rc=None;timed=True
 save('EXECUTION.json',dict(returncode=rc,timed_out=timed,wall_s=time.monotonic()-start))
 result=subprocess.run([sys.executable,str(R/'results/progressive_adoption/recipes/audit_native_performance.py'),'--run-dir',str(o),'--output',str(o/'AUDIT.json')])
 raise SystemExit(result.returncode)
host=build['binaries']['progressive_adoption_ab_native'];assert identity(host['path'])==host
inp=a.input or R/'results/phase56/long/chain_300s.wav';jobs=[]
for repeat in range(a.repeats):
 for at,mode in itertools.product((30,270),a.modes):
  key=f'r{repeat}_A{at}_{mode}';jobs.append(dict(id=key,command=[host['path'],str(inp),'candidate',str(at),'.1','1',mode,'Playing','0',str(o/key)]))
save('EXPECTED.json',dict(suite=a.suite,source=build['source'],host=host,input=identity(inp),build=identity(a.build_record),driver=identity(__file__),expected=len(jobs),jobs=jobs,repeats=a.repeats,formal_performance_approval=False,quantile='(N-1)q linear',physical_audio=None))
rows=[]
for j in jobs:
 start=time.monotonic();timed=False
 with (o/(j['id']+'.log')).open('w') as f:
  try:rc=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=180).returncode
  except subprocess.TimeoutExpired:rc=None;timed=True
 s=o/j['id']/'SUMMARY.json';summary=json.loads(s.read_text()) if s.exists() else None
 rows.append(dict(id=j['id'],exit=rc,timeout=timed,wall_s=time.monotonic()-start,summary=summary))
 save('SUMMARY.json',dict(executed=len(rows),expected=len(jobs),complete=len(rows)==len(jobs),rows=rows));print(j['id'],rc,summary.get('accepted_to_first_A_ms') if summary else None,flush=True)
