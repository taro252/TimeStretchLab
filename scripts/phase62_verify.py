"""Phase62 evidence runner. Builds are explicit, outputs never overwritten.
Native hosts run serially; use outside the filesystem/audio sandbox.
"""
import argparse, hashlib, json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture
TARGETS='''phase54_analysis_tests phase54_seek_tests phase54_core_probe phase56_tests phase56_fixed_modes phase56_check phase56_reference phase57_tests phase57_check phase57_reference phase58_tests phase58_check phase58_product_reference phase58_fix_tests phase58_fix_mailbox_tests phase58_fix_worker_tests phase59_tests phase59_reference phase59_check phase59_progressive_replay phase59_captured_reference phase59_control_tests phase59_fix_vocoder_tests phase59_fix_stereo_tests phase60_contract_tests phase60_lifecycle_tests phase61_contract_tests phase61_fast_seek_tests phase61_fast_seek_study phase61_safety_tests phase61_checkpoint_tests phase61_seek_check phase61_seek_reference phase61_output_transition_tests phase61_pipeline_sync_tests phase61_sync_restart_native_tests phase61_interactive_native_tests phase61_interactive_eof_tests phase61_native_tests phase62_loop_tests phase62_render_tests phase62_native_tests phase62_loop_play phase62_deadline_native'''.split()
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--suite',required=True,choices=['targets','native','long','pcm','ctest','golden','exact','controls','step1','pcm161']);p.add_argument('--build',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    if a.suite=='targets':print(' '.join(TARGETS));return 0
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);binary=a.build.resolve();commands=[]
    (out/'provenance.json').write_text(json.dumps(dict(base_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),build=str(binary),binary_sha256={t:sha(binary/t) for t in TARGETS if (binary/t).is_file()},driver_sha256=sha(__file__)),indent=2)+'\n')
    def run(name,command,timeout=1800):
        command=list(map(str,command));start=time.monotonic();print('BEGIN',name,flush=True)
        with (out/(name+'.log')).open('x') as log:
            try:code=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout).returncode
            except subprocess.TimeoutExpired:code=-1
        commands.append(dict(name=name,command=command,exit=code,wall_s=time.monotonic()-start));(out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');print('END',name,code,flush=True);return code
    if a.suite=='ctest':run('ctest',['ctest','--test-dir',binary,'-R','^(phase54_|phase56_|phase57_|phase58_|phase59_|phase60_|phase61_|phase62_)','--output-on-failure','-j1'])
    elif a.suite=='golden':run('golden',['python3','-B',ROOT/'tests/Phase61Golden.py','--probe',binary/'phase54_core_probe','--output',out/'golden'])
    elif a.suite=='exact':run('exact',['python3','-B',ROOT/'tests/Phase61SeekSmoke.py',binary/'phase61_seek_check',ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference','--full','--output',out/'exact'])
    elif a.suite=='step1':
        from phase53_sessions import wav_pcm
        from phase55_study import write_wav
        pcm,ch,frames=wav_pcm(ROOT/'results/phase31/input/mix.wav');need=44100*36*ch*4;source=out/'mix_repeat_36s.wav';write_wav(source,44100,ch,3,(pcm*((need+len(pcm)-1)//len(pcm)))[:need])
        for seconds,speed in [(2,.4),(2,1),(2,2),(10,2),(30,2)]:
            name=f'compare_{seconds}s_{speed}';run(name,[binary/'phase62_native_tests',source,out/name,seconds,speed,4,'candidate','compare'],300)
    elif a.suite in ('native','controls','long'):
        sources=[]
        for rate,channels,encoding in [(44100,1,1),(44100,2,3),(48000,1,3),(48000,2,1)]:
            source=out/f'boundary_{rate}_{channels}_{encoding}.wav';fixture(source,rate,channels,encoding,'boundary',3.0);sources.append(source)
        if a.suite=='native':
            for source in sources:
                for preset in ('candidate','baseline'):
                    for speed in (.4,.5,.75,1.,1.5,2.):
                        name=f'{source.stem}_{preset}_{speed}';run(name,[binary/'phase62_native_tests',source,out/name,.5,speed,10,preset])
            for seconds in (1,2,10):
                name=f'music_{seconds}s';run(name,[binary/'phase62_native_tests',ROOT/'results/phase31/input/mix.wav',out/name,seconds,2,10,'candidate'])
            for mode in ('whole','end'):
                name='native_'+mode;run(name,[binary/'phase62_native_tests',sources[-1],out/name,1,2,10,'baseline',mode])
        elif a.suite=='controls':
            for source in (sources[0],sources[-1]):
                for preset in ('candidate','baseline'):
                    name=f'{source.stem}_{preset}';run(name,[binary/'phase62_native_tests',source,out/name,2,2,10,preset,'controls'])
            run('loop_faults',[binary/'phase62_native_tests',sources[-1],out/'loop_faults','--faults'],300)
            run('existing_controls',[binary/'phase61_interactive_native_tests',sources[-1],out/'existing_controls','--controls64'],600)
            run('existing_sync',[binary/'phase61_sync_restart_native_tests',sources[-1],out/'existing_sync'],300)
            run('lifecycle',[binary/'phase60_lifecycle_tests',ROOT/'results/phase31/input/mix.wav'],120)
        else:
            for count in (100,1000):
                name=f'cycles_{count}';run(name,[binary/'phase62_native_tests',sources[-1],out/name,.5,2,count,'candidate'],600)
    else:
        reference=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference'
        (out/'reference.json').write_text(json.dumps(dict(path=str(reference),sha256=sha(reference)))+'\n')
        for rate,channels,encoding in ([(48000,2,3)] if a.suite=='pcm161' else [(r,c,e) for r in (44100,48000) for c in (1,2) for e in (1,3)]):
            source=out/f'boundary_{rate}_{channels}_{encoding}.wav';fixture(source,rate,channels,encoding,'boundary',1.5)
            for speed in (range(400000,2000001,10000) if a.suite=='pcm161' else (400000,500000,750000,1000000,1500000,2000000)):
                for preset in ('candidate','baseline'):
                    name=f'{source.stem}_{speed}_{preset}';raw=out/(name+'.f32');a_frame=1023;b_frame=rate+1025
                    command=list(map(str,[reference,source,speed,preset,raw,a_frame,b_frame]));start=time.monotonic();r=subprocess.run(command,capture_output=True,text=True,timeout=120)
                    (out/(name+'_reference.log')).write_text(r.stdout+r.stderr);commands.append(dict(name=name+'_reference',command=command,exit=r.returncode,wall_s=time.monotonic()-start))
                    if r.returncode:continue
                    meta=json.loads(r.stdout);assert sha(raw)==meta['sha256'];run(name,[binary/'phase62_loop_tests',source,speed,preset,a_frame,b_frame,raw,meta['positions'][0],meta['positions'][1]])
    summary=dict(PASS=all(c['exit']==0 for c in commands),executions=len(commands),failed=sum(c['exit']!=0 for c in commands),suite=a.suite)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');return int(not summary['PASS'])
if __name__=='__main__':raise SystemExit(main())
