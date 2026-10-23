"""Full ordinary terminal audit; rejection is an intentional separate mode."""
import argparse,json,pathlib,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'));from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--build-record',type=pathlib.Path,required=True);p.add_argument('--input',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();s=json.loads(a.build_record.read_text());source=source_manifest(R);assert s['status']=='PASS' and s['source']==source['sha256'];e=s['binaries']['progressive_adoption_epoch_audit_native'];assert identity(pathlib.Path(e['path']))==e;o=a.output;o.mkdir();jobs=[dict(id=p+'_'+m,mode=m,command=[e['path'],str(a.input),p,str(o/(p+'_'+m)),s['source'],m]) for p in ('candidate','baseline') for m in ('accept','reject')];(o/'EXPECTED.json').write_text(json.dumps(dict(source=s['source'],binary=e,input=identity(a.input),expected_programs=4,expected_checks=56,serial=True,jobs=jobs,normal_RT_approval='NOT_ASSESSED'),indent=2));rows=[]
for j in jobs:
 timed=False;t=time.monotonic()
 with (o/(j['id']+'.log')).open('w') as f:
  try:rc=subprocess.run(j['command'],stdout=f,stderr=subprocess.STDOUT,timeout=60).returncode
  except subprocess.TimeoutExpired:rc=None;timed=True
 folder=o/j['id'];path=folder/'SUMMARY.json';d=json.loads(path.read_text()) if path.exists() else {};ex=json.loads((folder/'EXPECTED.json').read_text()) if (folder/'EXPECTED.json').exists() else {};checks=[json.loads(x) for x in (folder/'checks.jsonl').read_text().splitlines()] if (folder/'checks.jsonl').exists() else [];ids=[x['id'] for x in checks];ok=rc==0 and not timed and d.get('run_complete') and d.get('expected')==d.get('executed')==d.get('passed')==len(ids)==len(set(ids))==14 and ids==ex.get('required_ids') and all(x.get('pass') is True for x in checks)
 rows.append(dict(id=j['id'],exit=rc,timeout=timed,PASS=bool(ok),wall_s=time.monotonic()-t,summary=d));(o/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=4,executed_programs=len(rows),expected_checks=56,executed_checks=sum(x['summary'].get('executed',0) for x in rows),PASS=len(rows)==4 and all(x['PASS'] for x in rows),rows=rows),indent=2));print(j['id'],rc,ok,flush=True)
 if not ok:raise SystemExit(2)
