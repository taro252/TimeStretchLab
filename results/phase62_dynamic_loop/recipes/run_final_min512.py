import sys,json,subprocess,time,collections
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase62_dynamic_validation import boundary_expectations
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_min512_v9';out.mkdir();source=source_manifest(ROOT)
reference=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';binary=base/'release/phase62_dynamic_boundary_tests';input=ROOT/'results/phase31/input/mix.wav';jobs=[]
for preset in ['candidate','baseline']:
    folder=base/'final_boundary_strict_v8';key='boundary_1000000_'+preset
    oracle=json.loads((folder/(key+'_oracle.log')).read_text());positions=oracle['positions'][:513];assert positions==list(range(17,530))
    expected,_=boundary_expectations(positions,oracle['rate']);ob=positions[-1]
    for label,r in [('phase_first',1),('phase_last',511),('phase_middle_64',32),('phase_middle_128',64),('phase_middle_512',256)]:expected.append((label,ob-r,ob-r,r))
    command=[binary,input,1000000,preset,folder/(key+'.f32'),positions[0],positions[-1],100,'--period512','--old-near-b']
    jobs.append(dict(preset=preset,command=list(map(str,command)),cases=expected,oracle=identity(folder/(key+'.f32')),expected=len(expected)*4*2))
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,input=identity(input),binary=identity(binary),frozen_reference=identity(reference),expected_programs=2,internal_period_frames=512,public_minimum_input_millis_still=100,callbacks=[64,128,512,4096],required_B_callback_offsets=['1','callback/2','callback-1'],jobs=jobs),indent=2)+'\n');rows=[]
for job in jobs:
    assert source_manifest(ROOT)['sha256']==source['sha256'];start=time.time();log=out/(job['preset']+'.log')
    with log.open('w') as stream:code=subprocess.run(job['command'],stdout=stream,stderr=subprocess.STDOUT,timeout=600).returncode
    parsed=[]
    for line in log.read_text().splitlines():
        try:parsed.append(json.loads(line))
        except ValueError:pass
    measured=[r for r in parsed if r.get('status')=='PASS' and 'case' in r];phases=[r for r in parsed if r.get('status')=='PHASE_COVERAGE_PASS'];final=parsed[-1] if parsed else {}
    wanted=collections.Counter((label,c,529-o,cb,old) for label,c,o,_ in job['cases'] for cb in [64,128,512,4096] for old in [False,True]);actual=collections.Counter((r['case'],r['input'],r['R'],r['callback'],r['old_near_B']) for r in measured)
    valid=code==0 and wanted==actual and len(measured)==final.get('expected')==final.get('executed')==job['expected'] and final.get('independent_DSP_RAW') is True and len(phases)==4 and sorted(r['callback'] for r in phases)==[64,128,512,4096] and all(r['period_frames']==512 and r['phase_mask']==7 for r in phases) and source_manifest(ROOT)['sha256']==source['sha256']
    rows.append(dict(preset=job['preset'],exit=code,status='PASS' if valid else 'FAIL',expected=job['expected'],executed=len(measured),phase_coverage=phases,seconds=time.time()-start,log=identity(log)))
    (out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=2,executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(job['preset'],rows[-1]['status'],len(measured),flush=True)
