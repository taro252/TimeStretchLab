import sys,json,subprocess,time,collections
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase59_native_validation import wav_info
base=ROOT/'build/phase62_dynamic_20261020';out=base/'final_native_gates';out.mkdir();release=base/'release';debug=base/'debug';source=source_manifest(ROOT)
long=ROOT/'build/phase62_fix/run_01/final_v9/evidence/release_longA/same_300s_48000_2_pcm16.wav';small=ROOT/'results/phase31/input/mix.wav';rate=wav_info(long)['rate'];jobs=[]
for label,build in [('release',release),('debug',debug)]:
    for preset in ['candidate','baseline']:
        jobs.append((label+'_paused_'+preset,[build/'paused_speed_loop_tests',small,preset],'paused',10))
jobs.append(('faults',[release/'phase62_native_tests',small,out/'faults','--faults'],'faults',13))
for preset in ['candidate','baseline']:
    for seconds in [0,30,270]:
        key=f'longA_{seconds}_{preset}';jobs.append((key,[release/'phase62_native_tests',long,out/key,3.0,1.0,4,preset,'normal',seconds*rate],'native',4))
    key='stress_4100_'+preset;jobs.append((key,[release/'phase62_native_tests',small,out/key,.1,2.0,4100,preset],'native',4100))
(out/'EXPECTED.json').write_text(json.dumps(dict(source=source,expected_programs=len(jobs),inputs=[identity(long),identity(small)],binaries=[identity(release/'phase62_native_tests'),identity(release/'paused_speed_loop_tests'),identity(debug/'paused_speed_loop_tests')],serial_audio=True,driver=identity(__file__),commands=[dict(id=k,argv=list(map(str,c)),kind=kind,expected=e) for k,c,kind,e in jobs]),indent=2)+'\n');rows=[]
for key,command,kind,expected in jobs:
    if source_manifest(ROOT)['sha256']!=source['sha256']:raise RuntimeError('source changed')
    start=time.time();timeout=False
    with (out/(key+'.log')).open('w') as stream:
        try:code=subprocess.run(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,timeout=1200).returncode
        except subprocess.TimeoutExpired:code=None;timeout=True
    valid=code==0;final=None;rt=None
    if kind=='paused':
        parsed=[]
        for line in (out/(key+'.log')).read_text().splitlines():
            try:parsed.append(json.loads(line))
            except ValueError:pass
        final=parsed[-1] if parsed else {};valid &= final.get('status')=='PASS' and final.get('expected')==final.get('executed')==expected
    elif kind=='faults':
        p=out/key/'checks.jsonl';final=[json.loads(line) for line in p.read_text().splitlines()] if p.is_file() else [];valid &= len(final)==expected and all(r.get('PASS') is True for r in final)
    else:
        p=out/key/'result.json';final=json.loads(p.read_text()) if p.is_file() else {};valid &= final.get('functional_pass') is True and final.get('cycles',0)>=expected and all(final.get(k)==0 for k in ['raw_mix_errors','nonfinite','missing_frames','underrun_calls','safety_stop_frames','output_affected_frames','failure_padding_frames','warm_fft_plans','final_missing_frames'])
        reuse=out/key/'loop_final_reuse.json';stat=json.loads(reuse.read_text()) if reuse.is_file() else {};valid &= type(stat.get('final_data_available')) in (int,bool) and stat.get('final_data_available')==1 and stat.get('warm_fft_plans')==0 and stat.get('workers_created')==2
        if key.startswith('longA_'):valid &= stat.get('cache_bytes')==0 and stat.get('seed_restores',0)>=expected-1 and stat.get('warm_discarded_frames',sys.maxsize)<=(stat.get('reuse_count',0)+1)*2048
        rt=all(final.get(k)==0 for k in ['callback_deadlines','worker_deadlines','final_worker_deadlines','host_errors','sample_errors','hal_window_misses','callback_new','callback_heap_calls','callback_frees','workgroup_errors','final_workgroup_errors'])
    row=dict(id=key,exit=code,status='INCOMPLETE' if timeout else 'PASS' if valid else 'FAIL',expected=expected,seconds=time.time()-start,realtime_gate='PASS' if rt is True else 'FAIL' if rt is False else 'NOT_ASSESSED',result=final);rows.append(row)
    (out/'SUMMARY.json').write_text(json.dumps(dict(expected_programs=len(jobs),executed_programs=len(rows),rows=rows,local_overall_go=False),indent=2)+'\n');print(key,row['status'],row['realtime_gate'],round(row['seconds'],2),flush=True)
