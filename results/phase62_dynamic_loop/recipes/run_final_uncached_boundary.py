import sys,json,subprocess,time,bisect
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest,sha
from phase59_native_validation import wav_info
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_uncached_boundary';out.mkdir();binary=base/'release/phase62_dynamic_boundary_tests';oracle=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';input=base/'final_dynamic161/dynamic_sustained_48000_mono_pcm16_9s.wav';rate=wav_info(input)['rate'];source=source_manifest(ROOT)
programs=[(400000,'candidate',3000),(2000000,'baseline',5000)]
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,expected_programs=2,conditions=programs,input=identity(input),binary=identity(binary),reference=identity(oracle),comparison='independent RAW and queried integer Map near B; independent period/entry formula, old and new B wrap; full period >96000'),indent=2)+'\n');rows=[]
for speed,preset,millis in programs:
 key=f'uncached_{speed}_{preset}_{millis}';a=17;b=a+rate*millis//1000;n=rate//200;mid=a+(b-a)//2;tail=list(range(b-4096,b+1));points=[a,mid,*tail];raw=out/(key+'.f32')
 command=list(map(str,[oracle,input,speed,preset,raw,*points]));(out/(key+'_oracle_COMMAND.json')).write_text(json.dumps(command)+'\n')
 with (out/(key+'_oracle.log')).open('w') as log:code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
 assert code==0
 ref=json.loads((out/(key+'_oracle.log')).read_text());positions=ref['positions'];assert ref['sha256']==sha(raw) and len(positions)==len(points);oa,om=positions[:2];near=positions[2:];ob=near[-1];assert ob-oa>96000
 cases=[];unavailable=[]
 for remaining,label in [(0,'R0'),(n-1,'R_N_minus_1'),(n,'R_N'),(n+1,'R_N_plus_1')]:
  target=ob-remaining;assert near[0]<target;low=bisect.bisect_left(near,target)
  if low<len(tail)-1 and near[low]==target:cases.append((label,tail[low],near[low]))
  else:
   unavailable.append(label)
   if low:cases.append((label+'_below_input',tail[low-1],near[low-1]))
   if low<len(tail)-1:cases.append((label+'_above_input',tail[low],near[low]))
 cases += [('B_minus_1',b-1,near[-2]),('A',a,oa),('midpoint',mid,om)];expected=8*len(cases)
 command=list(map(str,[binary,input,speed,preset,raw,oa,ob,millis,'--old-near-b']));(out/(key+'_EXPECTED.json')).write_text(json.dumps(dict(expected=expected,cases=cases,unavailable=unavailable,period=ob-oa,command=command),indent=2)+'\n')
 assert source_manifest(ROOT)['sha256']==source['sha256'];start=time.time()
 with (out/(key+'.log')).open('w') as log:code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=1200).returncode
 parsed=[]
 for line in (out/(key+'.log')).read_text().splitlines():
  try:parsed.append(json.loads(line))
  except ValueError:pass
 final=parsed[-1] if parsed else {};actual=[r for r in parsed if r.get('status')=='PASS' and 'case' in r];wanted={(label,c,ob-o,cb,old) for label,c,o in cases for cb in [64,128,512,4096] for old in [False,True]};got={(r['case'],r['input'],r['R'],r['callback'],r['old_near_B']) for r in actual}
 valid=code==0 and final.get('status')=='PASS' and final.get('independent_DSP_RAW') is True and final.get('expected')==final.get('executed')==expected and len(actual)==expected and got==wanted
 rows.append(dict(id=key,status='PASS' if valid else 'FAIL',expected=expected,executed=len(actual),period_frames=ob-oa,seconds=time.time()-start,final=final));(out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=2,executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(key,rows[-1]['status'],expected,flush=True)
 if not valid:sys.exit(1)
