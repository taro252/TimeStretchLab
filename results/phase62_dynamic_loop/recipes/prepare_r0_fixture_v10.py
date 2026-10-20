import sys,json,subprocess,math,struct
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,sha
base=ROOT/'build/phase62_dynamic_20261020';out=base/'r0_fixture_v10';out.mkdir();ref=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';input=ROOT/'build/phase62/run_01/step1_release/mix_repeat_36s.wav';positions=list(range(44100*8,44100*8+65));rows=[]
assert sha(ref)=='de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
for preset in ['candidate','baseline']:
 raw=out/(preset+'.f32');command=list(map(str,[ref,input,2000000,preset,raw,*positions]));(out/(preset+'_EXPECTED.json')).write_text(json.dumps(dict(command=command,input=identity(input),reference=identity(ref),assertion='find adjacent equal old Map(C)==Map(B), B=C+1',expected_positions=len(positions)),indent=2)+'\n')
 with (out/(preset+'.log')).open('w') as log:code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
 assert code==0;data=json.loads((out/(preset+'.log')).read_text());assert len(data['positions'])==len(positions) and data['sha256']==sha(raw)
 with raw.open('rb') as stream:
  while block:=stream.read(1<<20):assert all(math.isfinite(v[0]) for v in struct.iter_unpack('<f',block))
 found=next((i for i in range(1,len(positions)) if data['positions'][i]==data['positions'][i-1]),None);assert found is not None
 rows.append(dict(preset=preset,input_B=positions[found],input_C=positions[found-1],output_B=data['positions'][found],output_C=data['positions'][found-1],R=0,raw=identity(raw),log=identity(out/(preset+'.log'))))
(out/'SUMMARY.json').write_text(json.dumps(dict(status='PASS',expected=2,executed=2,rows=rows,scope='independent old Map for fixture selection; native API PCM is separately audited'),indent=2)+'\n');print(rows)
