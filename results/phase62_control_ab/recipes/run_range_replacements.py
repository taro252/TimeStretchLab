"""Ready/Playing/Paused/Clear後の各4連置換。旧保存点の不要保持と新prepareの速度要約初期化を回帰する。"""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--build-record',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);r=json.loads(a.build_record.read_text());source=source_manifest(ROOT);assert r['status']=='PASS' and r['source']==source['sha256'];binary=r['binaries']['phase62_range_replacement_native'];assert identity(Path(binary['path']))==binary;jobs=[dict(id=preset,command=[binary['path'],str(a.input.resolve()),preset,str(out/preset),source['sha256']]) for preset in ['baseline','candidate']]
def save(name,v):(out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
save('EXPECTED.json',dict(expected_programs=2,expected_checks=38,source=source,build=identity(a.build_record),binary=binary,input=identity(a.input),jobs=jobs,driver=identity(Path(__file__))));rows=[]
for j in jobs:
 timed=False
 with (out/(j['id']+'.log')).open('w') as f:
  try:code=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=120).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 folder=out/j['id'];s=json.loads((folder/'SUMMARY.json').read_text()) if (folder/'SUMMARY.json').exists() else {};ex=json.loads((folder/'EXPECTED.json').read_text()) if (folder/'EXPECTED.json').exists() else {};checks=[json.loads(x) for x in (folder/'checks.jsonl').read_text().splitlines()] if (folder/'checks.jsonl').exists() else [];ok=code==0 and not timed and s.get('status')=='PASS' and s.get('run_complete') is True and s['executed']==s['expected']==len(checks)==19 and [x['id'] for x in checks]==ex['required_ids'] and all(x['pass'] is True for x in checks);rows.append(dict(id=j['id'],status='PASS' if ok else 'FAIL',exit=code,timeout=timed,summary=s));save('SUMMARY.json',dict(status='PASS' if len(rows)==2 and all(x['status']=='PASS' for x in rows) else 'INCOMPLETE',run_complete=len(rows)==2,expected_programs=2,executed_programs=len(rows),expected_checks=38,executed_checks=sum(x['summary'].get('executed',0) for x in rows),rows=rows));print(j['id'],rows[-1]['status'],s,flush=True)
 if not ok:raise SystemExit(2)
