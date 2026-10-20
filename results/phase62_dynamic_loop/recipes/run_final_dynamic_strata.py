import sys,json,subprocess,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase57_study import fixture
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_dynamic_strata';out.mkdir();binary=base/'release/phase62_dynamic_pcm_tests';oracle=ROOT/'build/phase59_frozen/captured_reference';source=source_manifest(ROOT)
formats=[(44100,1,1),(44100,1,3),(44100,2,1),(48000,2,3)]
for rate,channels,encoding in formats:fixture(out/f'input_{rate}_{channels}_{encoding}.wav',rate,channels,encoding,'boundary',9.)
pairs=[(400000,2000000),(2000000,400000),(1000000,750000),(490000,510000),(990000,1010000)]
jobs=[]
for rate,channels,encoding in formats:
    for initial,target in pairs:
        for preset in ['candidate','baseline']:
            key=f'format_{rate}_{channels}_{encoding}_{initial}_{target}_{preset}';jobs.append((key,out/f'input_{rate}_{channels}_{encoding}.wav',initial,target,preset,8192))
mono=base/'final_dynamic161/dynamic_sustained_48000_mono_pcm16_9s.wav'
for initial,target in [(400000,2000000),(2000000,400000),(1000000,750000)]:
    for preset in ['candidate','baseline']:
        key=f'midpoint_{initial}_{target}_{preset}';jobs.append((key,mono,initial,target,preset,round(432000/(initial/1000000)/2)))
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,expected=len(jobs),binary=identity(binary),reference=identity(oracle),formats=formats,pairs=pairs,fixture_generator=identity(ROOT/'scripts/phase57_study.py'),inputs=[identity(out/f'input_{r}_{c}_{e}.wav') for r,c,e in formats],commands=[dict(id=k,argv=list(map(str,[binary,p,i,t,preset,out/k,oracle,at]))) for k,p,i,t,preset,at in jobs]),indent=2)+'\n');rows=[]
for key,p,initial,target,preset,at in jobs:
    if source_manifest(ROOT)['sha256']!=source['sha256']:raise RuntimeError('source changed')
    command=list(map(str,[binary,p,initial,target,preset,out/key,oracle,at]));start=time.time()
    with (out/(key+'.log')).open('w') as log:code=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
    final=json.loads((out/key/'SUMMARY.json').read_text()) if (out/key/'SUMMARY.json').is_file() else {}
    valid=code==0 and final.get('status')=='PASS' and final.get('expected')==final.get('executed')==1 and all(final.get(k) is True for k in ['independent_planner','independent_DSP_RAW','map_bit_exact']) and final.get('nonfinite')==0
    rows.append(dict(id=key,exit=code,status='PASS' if valid else 'FAIL',seconds=time.time()-start,final=final));(out/'SUMMARY.json').write_text(json.dumps(dict(expected=len(jobs),executed=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(key,rows[-1]['status'],flush=True)
