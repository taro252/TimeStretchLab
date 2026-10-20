import sys,json,subprocess,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_seek_api_v10';out.mkdir();source=source_manifest(ROOT);binary=base/'release/phase62_dynamic_seek_native';input=ROOT/'build/phase62/run_01/step1_release/mix_repeat_36s.wav';fixture=json.loads((base/'r0_fixture_v10/SUMMARY.json').read_text());assert fixture['status']=='PASS';jobs=[]
for preset in ['candidate','baseline']:
 for r0 in [False,True]:
  chosen=next(r for r in fixture['rows'] if r['preset']==preset);key=preset+('_R0' if r0 else '_normal');cmd=[binary,input,preset,out/key]+([chosen['input_B']] if r0 else [])
  jobs.append(dict(id=key,command=list(map(str,cmd)),expected=1 if r0 else 21,preparations=1 if r0 else 3,r0=r0,independent_Map_fixture=chosen if r0 else None))
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,expected_programs=4,expected_cases=44,binary=identity(binary),input=identity(input),architecture=subprocess.check_output(['lipo','-archs',str(binary)],text=True).strip(),serial_audio=True,jobs=jobs),indent=2)+'\n');rows=[]
for job in jobs:
 assert source_manifest(ROOT)['sha256']==source['sha256'];start=time.time();log=out/(job['id']+'.log')
 with log.open('w') as stream:code=subprocess.run(job['command'],stdout=stream,stderr=subprocess.STDOUT,timeout=600).returncode
 path=out/job['id']/'SUMMARY.json';final=json.loads(path.read_text()) if path.exists() else {};casesPath=out/job['id']/'cases.jsonl';cases=[json.loads(line) for line in casesPath.read_text().splitlines()] if casesPath.exists() else []
 valid=code==0 and final.get('status')=='PASS' and final.get('expected')==final.get('executed')==len(cases)==job['expected'] and final.get('paused_Exact_speed_preparations_executed')==job['preparations'] and source_manifest(ROOT)['sha256']==source['sha256']
 if job['r0'] and cases:
  f=job['independent_Map_fixture'];c=cases[0];valid &= final.get('R0_cases')==1 and c.get('accepted_C')==c.get('observed_paused_C')==f['input_C'] and c.get('output_start')==c.get('actual_Map_L')==f['output_B'] and c.get('actual_Map_R')==0 and c.get('observed_natural_Bs')==0
 rows.append(dict(id=job['id'],exit=code,status='PASS' if valid else 'FAIL',seconds=time.time()-start,result=final,log=identity(log)))
 (out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=4,executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(job['id'],rows[-1]['status'],flush=True)
 if not valid:break
