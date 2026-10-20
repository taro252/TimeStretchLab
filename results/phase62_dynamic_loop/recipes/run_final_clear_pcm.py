import sys,json,subprocess,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_clear_pcm';out.mkdir();source=source_manifest(ROOT);host=base/'release/phase62_clear_pcm_native';input=ROOT/'build/phase62/run_01/step1_release/mix_repeat_36s.wav';oracle=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';manifest=ROOT/'results/phase62_fix/recipes/oracle_manifest.json';driver=base/'run_clear_pcm_native.py';jobs=[]
for preset in ['candidate','baseline']:
 cmd=[sys.executable,'-B',driver,'--host',host,'--input',input,'--oracle',oracle,'--oracle-manifest',manifest,'--preset',preset,'--output',out/preset];jobs.append(dict(preset=preset,command=list(map(str,cmd))))
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,expected_programs=2,expected_cases=2,host=identity(host),input=identity(input),oracle=identity(oracle),oracle_manifest=identity(manifest),driver=identity(driver),jobs=jobs,serial_audio=True),indent=2)+'\n');rows=[]
for job in jobs:
 assert source_manifest(ROOT)['sha256']==source['sha256'];start=time.time();log=out/(job['preset']+'.log')
 with log.open('w') as stream:code=subprocess.run(job['command'],stdout=stream,stderr=subprocess.STDOUT,timeout=900).returncode
 p=out/job['preset']/'SUMMARY.json';final=json.loads(p.read_text()) if p.exists() else {};valid=code==0 and final.get('expected')==final.get('executed')==1 and final.get('status')=='PASS' and source_manifest(ROOT)['sha256']==source['sha256']
 rows.append(dict(preset=job['preset'],exit=code,status='PASS' if valid else 'FAIL',expected=1,executed=final.get('executed',0),seconds=time.time()-start,result=final,log=identity(log)))
 (out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=2,executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(job['preset'],rows[-1]['status'],flush=True)
 if not valid:break
