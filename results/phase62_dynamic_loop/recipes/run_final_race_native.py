import sys,json,subprocess,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_race_native';out.mkdir();source=source_manifest(ROOT);binary=base/'release/phase62_race_native';first=ROOT/'build/phase62/run_01/step1_release/mix_repeat_36s.wav';second=ROOT/'results/phase31/input/mix.wav';inputs=[identity(first),identity(second)];assert inputs[0]['sha256']!=inputs[1]['sha256'];jobs=[dict(preset=p,command=list(map(str,[binary,first,p,out/p,second]))) for p in ['candidate','baseline']]
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,expected_programs=2,observations_per_program=8,baseline_comparison_cases_per_program=7,additional_KeepPosition_defer_contract=1,binary=identity(binary),inputs=inputs,input_content_change_verified_by_SHA=True,serial_audio=True,commands=jobs,independent_PCM_comparison='NOT_RUN'),indent=2)+'\n');rows=[]
for job in jobs:
 assert source_manifest(ROOT)['sha256']==source['sha256'];start=time.time();log=out/(job['preset']+'.log');timed=False
 with log.open('w') as stream:
  try:code=subprocess.run(job['command'],stdout=stream,stderr=subprocess.STDOUT,timeout=180).returncode
  except subprocess.TimeoutExpired:code=None;timed=True
 p=out/job['preset']/'SUMMARY.json';final=json.loads(p.read_text()) if p.exists() else {};valid=code==0 and final.get('expected')==final.get('executed')==final.get('PASS')==8 and final.get('status')=='PASS' and not final.get('FAIL') and not final.get('INCOMPLETE') and not final.get('REPRODUCED') and final.get('product_owners_alive_after_final_stop')==0 and final.get('product_owners_peak')<=2
 rows.append(dict(preset=job['preset'],exit=code,status='INCOMPLETE' if timed else 'PASS' if valid else 'FAIL',expected=8,executed=final.get('executed',0),seconds=time.time()-start,result=final,log=identity(log)))
 (out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=2,executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(job['preset'],rows[-1]['status'],flush=True)
 if not valid:break
