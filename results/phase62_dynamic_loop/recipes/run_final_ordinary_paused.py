import sys,json,subprocess,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest,sha
base=ROOT/'build/phase62_dynamic_20261020';old=base/'final_paused';out=base/'final_ordinary_paused';out.mkdir();source=source_manifest(ROOT);binary=base/'release/paused_speed_native_tests';oracle=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';assert sha(oracle)=='de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748';jobs=[];references=[]
ledger=json.loads((old/'LEDGER.json').read_text());old_inputs={}
for row in ledger['cases']:
 for f in row.get('inputs',[]):
  if isinstance(f,dict) and 'path' in f:old_inputs[f['path']]=f
for rate,channels in [(48000,2),(44100,1)]:
 wav=old/f'paused_{rate}_{channels}.wav';assert old_inputs[str(wav)]['sha256']==sha(wav)
 for preset in ['candidate','baseline']:
  refs=old/f'paused_{rate}_{channels}_{preset}_refs'
  for speed in [750000,1250000,400000,2000000,490000,500000,990000,1000000,1010000]:
   raw=refs/f'{speed}_{preset}.f32';log=old/f'paused_{rate}_{channels}_{preset}_oracle_{speed}.log';result=json.loads(log.read_text());assert sha(raw)==result['sha256'] and raw.stat().st_size==result['output_frames']*channels*4;references.append(dict(raw=identity(raw),oracle_log=identity(log)))
  for kind,count in [('representative',9),('controls',21)]:
   jobs.append(dict(id=f'{rate}_{channels}_{preset}_{kind}',command=list(map(str,[binary,wav,refs,preset,kind])),expected=count,kind=kind))
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,expected_programs=8,expected_PCM=36,expected_controls=84,binary=identity(binary),frozen_oracle=identity(oracle),original_LEDGER=identity(old/'LEDGER.json'),verified_reference_RAW=references,jobs=jobs,serial_audio=True),indent=2)+'\n');rows=[]
for job in jobs:
 assert source_manifest(ROOT)['sha256']==source['sha256'];start=time.time();log=out/(job['id']+'.log')
 with log.open('w') as stream:code=subprocess.run(job['command'],stdout=stream,stderr=subprocess.STDOUT,timeout=600).returncode
 parsed=[]
 for line in log.read_text().splitlines():
  try:parsed.append(json.loads(line))
  except ValueError:pass
 valid=code==0 and len(parsed)==job['expected'] and all(r.get('PASS') is True for r in parsed) and source_manifest(ROOT)['sha256']==source['sha256']
 rows.append(dict(id=job['id'],exit=code,status='PASS' if valid else 'FAIL',expected=job['expected'],executed=len(parsed),seconds=time.time()-start,log=identity(log)))
 (out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=8,executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(job['id'],rows[-1]['status'],flush=True)
 if not valid:break
