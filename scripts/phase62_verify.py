"""Phase62の再現。期待台帳、全件状態、ソース/ビルド/入力/参照を結び付ける。"""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture
from phase62_evidence import Ledger,aggregate,identity,source_manifest
TARGETS='''phase54_analysis_tests phase54_seek_tests phase54_core_probe phase56_tests phase56_fixed_modes phase56_check phase56_reference phase57_tests phase57_check phase57_reference phase58_tests phase58_check phase58_product_reference phase58_fix_tests phase58_fix_mailbox_tests phase58_fix_worker_tests phase59_tests phase59_reference phase59_check phase59_progressive_replay phase59_captured_reference phase59_control_tests phase59_fix_vocoder_tests phase59_fix_stereo_tests phase60_contract_tests phase60_lifecycle_tests phase61_contract_tests phase61_fast_seek_tests phase61_fast_seek_study phase61_safety_tests phase61_checkpoint_tests phase61_seek_check phase61_seek_reference phase61_output_transition_tests phase61_pipeline_sync_tests phase61_sync_restart_native_tests phase61_interactive_native_tests phase61_interactive_eof_tests phase61_native_tests phase62_loop_tests phase62_render_tests phase62_native_tests phase62_loop_play phase62_deadline_native'''.split()

TARGETS += ['phase62_fix_safety_tests','phase62_fix_reuse_tests','phase62_fix_render_tests','phase62_fix_checkpoint_tests','phase62_fix_sandbox_app','phase62_fix_clock_native']
def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--suite',required=True,choices=['targets','native','long','pcm','ctest','golden','exact','controls','step1','pcm161','safety'])
    parser.add_argument('--build',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--configuration',choices=['Release','Debug'],default='Release')
    args=parser.parse_args()
    if args.suite=='targets':print(' '.join(TARGETS));return 0
    out=args.output.resolve();build=args.build.resolve();cases=[];jobs=[];fixtures=[]
    def plan(name,command,kind='exit',required=(),**extra):
        cases.append(dict(id=name,kind=kind,required=list(required),**extra));jobs.append((name,list(map(str,command))))
    plan('configure',['cmake','-S',ROOT,'-B',build,'-DCMAKE_BUILD_TYPE='+args.configuration,'-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON'])
    plan('build',['cmake','--build',build,'--target',*TARGETS,'-j','3'])
    reference=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference'
    binaries=[build/t if t!='phase62_fix_sandbox_app' else build/(t+'.app')/'Contents/MacOS'/t for t in TARGETS]
    plan('architecture',[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py',*binaries,reference])
    if args.suite=='ctest':
        pattern='^(phase54_|phase56_|phase57_|phase58_|phase59_|phase60_|phase61_|phase62_)'
        plan('ctest',['ctest','--test-dir',build,'-R',pattern,'--output-on-failure','--output-junit',out/'ctest.xml','-j1'],'ctest',['ctest.xml'],result='ctest.xml',test_names_file='CTEST_EXPECTED.json')
    elif args.suite=='safety':
        plan('safety',[build/'phase62_fix_safety_tests',ROOT/'results/phase31/input/mix.wav'])
        plan('evidence',[sys.executable,'-B',ROOT/'tests/Phase62EvidenceTests.py'])
    elif args.suite=='golden':
        plan('golden',[sys.executable,'-B',ROOT/'tests/Phase61Golden.py','--probe',build/'phase54_core_probe','--output',out/'golden'],'golden',['golden/summary.json'],result='golden/summary.json',expected_count=25)
    elif args.suite=='exact':
        plan('exact',[sys.executable,'-B',ROOT/'tests/Phase61SeekSmoke.py',build/'phase61_seek_check',reference,'--full','--output',out/'exact'],'exact',['exact/summary.json','exact/rows.jsonl','exact/manifest.json'],result='exact/summary.json',expected_count=896)
    elif args.suite in ('native','controls','long'):
        sources=[]
        for rate,channels,encoding in [(44100,1,1),(44100,2,3),(48000,1,3),(48000,2,1)]:
            source=out/f'boundary_{rate}_{channels}_{encoding}.wav';fixtures.append((source,rate,channels,encoding));sources.append(source)
        def native(name,source,seconds,speed,count,preset,mode='normal'):
            plan(name,[build/'phase62_native_tests',source,out/name,seconds,speed,count,preset,mode],'native',[name+'/result.json',name+'/boundaries.jsonl',name+'/last_boundary.json',name+'/loop_final_reuse.json',name+'/clear_result.json',name+'/after_clear_callbacks_all_spans.jsonl'],result=name+'/result.json',cycles=count,period_preserving=True,clear_contract=True)
            plan(name+'_clock_recompute',[sys.executable,'-B',ROOT/'scripts/phase62_clock_audit.py',out/name/'callbacks_all_spans.jsonl','--output',out/name/'clock_recomputed.json'],'json_pass',[name+'/clock_recomputed.json'],result=name+'/clock_recomputed.json')
        if args.suite=='native':
            for source in sources:
                for preset in ('candidate','baseline'):
                    for speed in (.4,.5,.75,1.,1.5,2.):native(f'{source.stem}_{preset}_{speed}',source,.5,speed,10,preset)
            for seconds in (1,2,10):native(f'music_{seconds}s',ROOT/'results/phase31/input/mix.wav',seconds,2,10,'candidate')
            for mode in ('whole','end'):native('native_'+mode,sources[-1],1,2,10,'baseline',mode)
        elif args.suite=='controls':
            for source in (sources[0],sources[-1]):
                for preset in ('candidate','baseline'):native(f'{source.stem}_{preset}',source,2,2,10,preset,'controls')
            checks=['opt_in_and_public_gates']+['reservation_budget_failure','ready_a_replace_reject_clear','before_workgroup_failure','before_publication_failure','route_safe_stop_and_explicit_replay','input_path_loss']*2
            plan('loop_faults',[build/'phase62_native_tests',sources[-1],out/'loop_faults','--faults'],'checks',['loop_faults/checks.jsonl'],result='loop_faults/checks.jsonl',checks=checks)
            plan('existing_controls',[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py','--guard-device-buffer',out/'existing_controls_device_buffer.json',build/'phase61_interactive_native_tests',sources[-1],out/'existing_controls','--controls64'],required=['existing_controls_device_buffer.json','existing_controls/sessions.jsonl'])
            plan('existing_sync',[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py','--guard-device-buffer',out/'existing_sync_device_buffer.json',build/'phase61_sync_restart_native_tests',sources[-1],out/'existing_sync'],required=['existing_sync_device_buffer.json','existing_sync/rows.jsonl'])
            plan('lifecycle',[build/'phase60_lifecycle_tests',ROOT/'results/phase31/input/mix.wav'])
        else:
            for count in (100,1000):native(f'cycles_{count}',sources[-1],.5,2,count,'candidate')
    elif args.suite=='step1':
        source=out/'mix_repeat_36s.wav'
        for seconds,speed in [(2,.4),(2,1),(2,2),(10,2),(30,2)]:
            name=f'compare_{seconds}s_{speed}'
            plan(name,[build/'phase62_native_tests',source,out/name,seconds,speed,4,'candidate','compare'],'native',[name+'/result.json',name+'/boundaries.jsonl',name+'/last_boundary.json',name+'/loop_final_reuse.json',name+'/clear_result.json',name+'/after_clear_callbacks_all_spans.jsonl'],result=name+'/result.json',cycles=4,period_preserving=True,clear_contract=True)
    else:
        formats=[(48000,2,3)] if args.suite=='pcm161' else [(r,c,e) for r in (44100,48000) for c in (1,2) for e in (1,3)]
        speeds=range(400000,2000001,10000) if args.suite=='pcm161' else (400000,500000,750000,1000000,1500000,2000000)
        for rate,channels,encoding in formats:
            source=out/f'boundary_{rate}_{channels}_{encoding}.wav';fixtures.append((source,rate,channels,encoding))
            for speed in speeds:
                for preset in ('candidate','baseline'):
                    name=f'{source.stem}_{speed}_{preset}';raw=out/(name+'.f32');a=1023;b=rate+1025
                    plan(name+'_reference',[reference,source,speed,preset,raw,a,b],required=[name+'.f32'])
                    plan(name,[build/'phase62_loop_tests',source,speed,preset,a,b,raw,'REFERENCE_A','REFERENCE_B'],'pcm',reference_case=name+'_reference')
                    plan(name+'_reuse',[build/'phase62_fix_reuse_tests',source,speed,preset,a,b,raw,'REFERENCE_A','REFERENCE_B'],'pcm',reference_case=name+'_reference')
    source=source_manifest(ROOT)
    provenance=dict(source=source,configuration=args.configuration,architecture='arm64',base_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),build=str(build))
    ledger=Ledger(out,cases,provenance)
    try:
        for path,rate,channels,encoding in fixtures:fixture(path,rate,channels,encoding,'boundary',1.5 if args.suite.startswith('pcm') else 3.)
        if args.suite=='step1':
            from phase53_sessions import wav_pcm
            from phase55_study import write_wav
            pcm,ch,frames=wav_pcm(ROOT/'results/phase31/input/mix.wav');need=44100*36*ch*4
            write_wav(out/'mix_repeat_36s.wav',44100,ch,3,(pcm*((need+len(pcm)-1)//len(pcm)))[:need])
        for name,command in jobs:
            if name=='ctest':
                selected=json.loads(subprocess.check_output(['ctest','--test-dir',str(build),'-R',pattern,'--show-only=json-v1'],text=True))
                (out/'CTEST_EXPECTED.json').write_text(json.dumps([test['name'] for test in selected['tests']])+'\n')
            if 'REFERENCE_A' in command:
                spec=next(c for c in cases if c['id']==name);ref=spec['reference_case']
                if ledger.rows[ref]['status']!='PASS':continue
                metadata=json.loads((out/(ref+'.log')).read_text());command=[str(metadata['positions'][0]) if x=='REFERENCE_A' else str(metadata['positions'][1]) if x=='REFERENCE_B' else x for x in command]
            inputs=[Path(item) for item in command[1:] if Path(item).is_file() and Path(item).suffix in ('.wav','.f32','.json')]
            if reference.is_file() and args.suite in ('exact','pcm','pcm161'):inputs.append(reference)
            if name=='ctest':inputs.append(out/'CTEST_EXPECTED.json')
            good=ledger.run(name,command,cwd=ROOT,inputs=inputs,timeout=1800)
            if name in ('configure','build','architecture') and not good:break
        current=source_manifest(ROOT)
        if current['sha256']!=source['sha256']:
            for row in ledger.rows.values():row.update(status='INCOMPLETE',source_changed_during_run=True)
        (out/'BUILD_PROVENANCE.json').write_text(json.dumps(dict(source_before=source['sha256'],source_after=current['sha256'],configuration=args.configuration,architecture='arm64',binaries=[identity(p) for p in binaries if p.is_file()]),indent=2)+'\n')
    finally:
        ledger.save()
    summary=aggregate(out);(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dict(PASS=summary['PASS'],counts=summary.get('counts'),gates=summary.get('gates')),ensure_ascii=False));return int(not summary['PASS'])
if __name__=='__main__':raise SystemExit(main())
