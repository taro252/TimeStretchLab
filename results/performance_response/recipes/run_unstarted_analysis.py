"""未開始sourceを先に退役するC2端点。全8ID/最終共有診断固定。PCM/RT承認ではない。"""
import argparse,itertools,json,pathlib,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--build-record',type=pathlib.Path,required=True);p.add_argument('--inputs',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True)
p.add_argument('--workers',nargs='+',choices=['standard','workgroup'],default=['standard','workgroup']);a=p.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False)
b=json.loads(a.build_record.read_text());assert b['status']=='PASS' and source_manifest(R)['sha256']==b['source'];host=b['binaries']['performance_unstarted_analysis_tests'];assert identity(host['path'])==host
jobs=[]
for rate,ch,preset,worker in itertools.product([48000,44100],[1],['candidate','baseline'],a.workers):
 ch=1 if rate==48000 else 2;inp=a.inputs/f'boundary_{rate}_{ch}_30s.wav';key=f'{rate}_{ch}_{preset}_{worker}'
 jobs.append(dict(id=key,input=identity(inp),worker=worker,command=[host['path'],str(inp),preset,str(o/key),b['source'],*(['--worker=workgroup'] if worker=='workgroup' else [])]))
def save(n,v):(o/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
save('EXPECTED.json',dict(source=b['source'],binary=host,build=identity(a.build_record),driver=identity(__file__),expected_programs=len(jobs),expected_checks=len(jobs)*8,jobs=jobs,PCM_approval=False,realtime_approval=False))
rows=[]
for j in jobs:
 start=time.monotonic();timed=False
 with (o/(j['id']+'.log')).open('w') as f:
  try:rc=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=90).returncode
  except subprocess.TimeoutExpired:rc=None;timed=True
 path=o/j['id']/'SUMMARY.json';s=json.loads(path.read_text()) if path.exists() else {};ok=rc==0 and not timed and s.get('run_complete') is True and s.get('status')=='PASS' and s.get('expected')==s.get('executed')==8 and s.get('source')==b['source'] and s.get('binary_sha256')==host['sha256'] and s.get('worker')==j['worker']
 if ok:
  checks=[json.loads(x) for x in (o/j['id']/'checks.jsonl').read_text().splitlines()];expect=json.loads((o/j['id']/'EXPECTED.json').read_text());ok=len(checks)==8 and len({x['id'] for x in checks})==8 and {x['id'] for x in checks}==set(expect['required_ids']) and all(x['status']=='PASS' for x in checks)
  [json.loads(x) for x in (o/j['id']/'observations.jsonl').read_text().splitlines()]
 rows.append(dict(id=j['id'],PASS=bool(ok),returncode=rc,timeout=timed,wall_s=time.monotonic()-start,summary=s));save('SUMMARY.json',dict(status='PASS' if len(rows)==len(jobs) and all(x['PASS'] for x in rows) else 'INCOMPLETE_OR_FAIL',run_complete=len(rows)==len(jobs),expected_programs=len(jobs),executed_programs=len(rows),expected_checks=len(jobs)*8,executed_checks=sum(x['summary'].get('executed',0) for x in rows),rows=rows));print(j['id'],rc,ok,flush=True)
 if not ok:raise SystemExit(2)
assert identity(host['path'])==host and source_manifest(R)['sha256']==b['source']
