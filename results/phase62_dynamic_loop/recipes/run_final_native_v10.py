import sys,json,subprocess,time
from pathlib import Path
ROOT=Path.cwd(); sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase57_study import fixture
base=ROOT/'build/phase62_dynamic_20261020'; build=base/'release'; out=base/'final_native_matrix_v10'; out.mkdir()
long=ROOT/'build/phase62/run_01/step1_release/mix_repeat_36s.wav'; fixed=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference'; dynamic=ROOT/'build/phase59_frozen/captured_reference'
formats=[(400000,48000,2,1),(750000,44100,2,3),(1000000,44100,1,1),(2000000,48000,1,3)]
for speed,rate,channels,encoding in formats: fixture(out/f'input_{speed}.wav',rate,channels,encoding,'boundary',3.)
jobs=[]
for preset in ['candidate','baseline']:
    folder=out/('controls_'+preset); jobs.append(('controls_'+preset,[build/'phase62_dynamic_controls_native',long,preset,folder],folder/'SUMMARY.json',3))
    folder=out/('probe_'+preset); jobs.append(('probe_'+preset,[build/'phase62_dynamic_loop_probe',long,preset,'--require-fixed',folder],None,3))
    jobs.append(('audit_'+preset,[sys.executable,'-B',ROOT/'scripts/phase62_dynamic_native_audit.py',long,preset,folder,dynamic,'--native-binary',build/'phase62_dynamic_loop_probe'],folder/'audit/SUMMARY.json',1))
    for speed,_,_,_ in formats:
        folder=out/f'paused_{speed}_{preset}'; jobs.append((folder.name,[build/'phase62_paused_pcm_tests',out/f'input_{speed}.wav',speed,preset,folder,fixed],folder/'SUMMARY.json',1))
source=source_manifest(ROOT); expected=dict(source=source,expected_programs=len(jobs),conditions=formats,commands=[dict(id=k,argv=list(map(str,c)),expected=e) for k,c,_,e in jobs],binaries=[identity(build/name) for name in ['phase62_dynamic_controls_native','phase62_dynamic_loop_probe','phase62_paused_pcm_tests']],inputs=[identity(long)]+[identity(out/f'input_{s}.wav') for s,*_ in formats],references=[identity(fixed),identity(dynamic)],configuration='Release arm64',serial_audio=True)
(out/'EXPECTED.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2)+'\n'); rows=[]
for key,command,result,count in jobs:
    if source_manifest(ROOT)['sha256']!=source['sha256']: raise RuntimeError('source changed')
    start=time.time(); timeout=False
    with (out/(key+'.log')).open('w') as stream:
        try: code=subprocess.run(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,timeout=600).returncode
        except subprocess.TimeoutExpired: code=None;timeout=True
    final=None; valid=code==0
    if result:
        if result.is_file():
            final=json.loads(result.read_text()); valid &= final.get('status')=='PASS' and final.get('expected')==final.get('executed')==count
        else: valid=False
    elif key.startswith('probe_'):
        parsed=[]
        for line in (out/(key+'.log')).read_text().splitlines():
            try: parsed.append(json.loads(line))
            except ValueError: pass
        valid &= len(parsed)==4 and parsed[-1].get('contract_observations_pass') is True and parsed[1].get('status')=='PASS' and parsed[2].get('resume_calls')==0 and parsed[2].get('status')=='PASS'
        final=parsed
    row=dict(id=key,exit=code,status='INCOMPLETE' if timeout else 'PASS' if valid else 'FAIL',seconds=time.time()-start,result=final)
    rows.append(row); (out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=len(jobs),executed_programs=len(rows),rows=rows,all_selected_pass=len(rows)==len(jobs) and all(r['status']=='PASS' for r in rows),local_overall_go=False),ensure_ascii=False,indent=2)+'\n')
    print(key,row['status'],round(row['seconds'],2),flush=True)
    if not valid: break
