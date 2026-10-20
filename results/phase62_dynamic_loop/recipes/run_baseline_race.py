import sys,json,subprocess,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity
base=ROOT/'build/phase62_dynamic_20261020';out=base/'baseline_race_run_v1';out.mkdir();binary=base/'baseline_native/phase62_baseline_race_probe';first=ROOT/'build/phase62/run_01/step1_release/mix_repeat_36s.wav';second=ROOT/'results/phase31/input/mix.wav';command=list(map(str,[binary,first,'candidate',out/'native',second]));a=identity(first);b=identity(second);assert a['sha256']!=b['sha256']
(out/'EXPECTED.json').write_text(json.dumps(dict(base_sha='7c05319d8142ef53a70c95be4f214f293bb2428a',expected_observations=7,binary=identity(binary),probe=identity(base/'BaselineRaceProbe.cpp'),inputs=[a,b],input_content_change_verified_by_SHA=True,source_check=identity(base/'BASELINE_RACE_SOURCE.json'),command=command,scope='baseline observations only; baseline failures are not current product failures'),indent=2)+'\n');timeout=False;start=time.time()
with (out/'native.log').open('w') as log:
 try:code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=90).returncode
 except subprocess.TimeoutExpired:code=None;timeout=True
p=out/'native/SUMMARY.json';final=json.loads(p.read_text()) if p.exists() else {};complete=not timeout and final.get('executed')==final.get('expected')==7
(out/'SUMMARY.json').write_text(json.dumps(dict(status='INCOMPLETE' if not complete else 'REPRODUCED' if final.get('REPRODUCED',0) or final.get('FAIL',0) else 'OBSERVATIONS_COMPLETE',exit=code,seconds=time.time()-start,expected=7,executed=final.get('executed',0),observations=final,timeout=timeout,input_content_change_verified_by_SHA=True,log=identity(out/'native.log'),current_product_result=False),indent=2)+'\n');print(final)
