import sys,json,subprocess,time,math,struct
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest,sha
from phase62_dynamic_validation import boundary_expectations
from phase59_native_validation import wav_info
base=ROOT/'build/phase62_dynamic_20261020';build=base/'release';out=base/'final_extra';out.mkdir()
fixed=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';dynamic=ROOT/'build/phase59_frozen/captured_reference'; inputs=base/'final_native_matrix_v5'
boundary=[(400000,'candidate',500),(2000000,'baseline',1000),(750000,'candidate',1000),(750000,'baseline',500),(1000000,'baseline',500),(2000000,'candidate',1000)]
# Use only requested .40/1.00/2.00 boundary speeds; input key selects its format.
boundary=[(400000,400000,'candidate',500),(400000,2000000,'baseline',1000),(750000,1000000,'candidate',1000),(1000000,1000000,'baseline',500),(2000000,2000000,'candidate',1000),(2000000,400000,'baseline',500)]
handoff=[(1000000,750000,'candidate',64),(400000,2000000,'candidate',4096),(2000000,400000,'candidate',512),(1000000,750000,'baseline',4096),(400000,2000000,'baseline',64),(2000000,400000,'baseline',512)]
frozen=source_manifest(ROOT); rows=[]
(out/'EXPECTED.json').write_text(json.dumps(dict(source=frozen,boundary_programs=6,handoff_programs=6,boundary=boundary,handoff=handoff,references=[identity(fixed),identity(dynamic)],binaries=[identity(build/'phase62_dynamic_boundary_tests'),identity(build/'phase62_dynamic_handoff_tests')],inputs=[identity(inputs/f'input_{k}.wav') for k in [400000,750000,1000000,2000000]]),indent=2)+'\n')
def run(key,command):
    if source_manifest(ROOT)['sha256']!=frozen['sha256']:raise RuntimeError('source changed')
    start=time.time()
    with (out/(key+'.log')).open('w') as log:
        code=subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
    (out/(key+'_COMMAND.json')).write_text(json.dumps(list(map(str,command)),indent=2)+'\n')
    parsed=[]
    for line in (out/(key+'.log')).read_text().splitlines():
        try: parsed.append(json.loads(line))
        except ValueError:pass
    return code,parsed,time.time()-start
def save(row):
    rows.append(row);(out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=12,executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(row['id'],row['status'],flush=True)
for input_key,speed,preset,millis in boundary:
    key=f'boundary_{input_key}_{speed}_{preset}_{millis}';source=inputs/f'input_{input_key}.wav';meta=wav_info(source);a=17;b=a+meta['rate']*millis//1000;raw=out/(key+'.f32')
    code,parsed,seconds=run(key+'_oracle',[fixed,source,speed,preset,raw,*range(a,b+1)])
    assert code==0 and len(parsed)==1
    ref=parsed[0];positions=ref['positions'];assert len(positions)==b-a+1 and ref['sha256']==sha(raw) and raw.stat().st_size==ref['output_frames']*meta['channels']*4
    with raw.open('rb') as stream:
        while block:=stream.read(1<<20):assert all(math.isfinite(v[0]) for v in struct.iter_unpack('<f',block))
    cases,unavailable=boundary_expectations(positions,meta['rate']);expected=8*len(cases)
    (out/(key+'_EXPECTED.json')).write_text(json.dumps(dict(expected=expected,conditions=cases,not_representable=unavailable,input=identity(source),reference=identity(raw)),indent=2)+'\n')
    code,parsed,seconds=run(key,[build/'phase62_dynamic_boundary_tests',source,speed,preset,raw,positions[0],positions[-1],millis,'--old-near-b'])
    final=parsed[-1] if parsed else {}; actual=[r for r in parsed if r.get('status')=='PASS' and 'case' in r]
    valid=code==0 and final.get('status')=='PASS' and final.get('expected')==final.get('executed')==expected and final.get('independent_DSP_RAW') is True and len(actual)==expected
    wanted={(label,input,positions[-1]-output,cb,old) for label,input,output,_ in cases for cb in [64,128,512,4096] for old in [False,True]}
    got={(r['case'],r['input'],r['R'],r['callback'],r['old_near_B']) for r in actual};valid &= got==wanted
    save(dict(id=key,status='PASS' if valid else 'FAIL',expected=expected,executed=len(actual),seconds=seconds,final=final))
    if not valid:sys.exit(1)
source=base/'final_dynamic_priority_v2/dynamic_sustained_48000_mono_pcm16_9s.wav'
for initial,target,preset,callback in handoff:
    key=f'handoff_{initial}_{target}_{preset}_{callback}';folder=out/key
    code,parsed,seconds=run(key,[build/'phase62_dynamic_handoff_tests',source,initial,target,preset,folder,dynamic,fixed,callback])
    final=json.loads((folder/'SUMMARY.json').read_text()) if (folder/'SUMMARY.json').is_file() else {}
    valid=code==0 and final.get('status')=='PASS' and final.get('expected')==final.get('executed')==1
    save(dict(id=key,status='PASS' if valid else 'FAIL',expected=1,executed=final.get('executed',0),seconds=seconds,final=final))
    if not valid:sys.exit(1)
