"""Phase62 Fixの追加台帳。大容量入力と記録は新規build配下に限る。"""
import argparse,ctypes,json,subprocess,sys,time,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture
from phase62_evidence import Ledger,aggregate,identity,source_manifest

def clock_run(rate,command,report):
    # Default output device only; restore in finally even when the host fails.
    class Property(ctypes.Structure):
        _fields_=[('selector',ctypes.c_uint32),('scope',ctypes.c_uint32),('element',ctypes.c_uint32)]
    four=lambda value:int.from_bytes(value.encode(),'big')
    audio=ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')
    def get(device,selector,typ):
        address=Property(four(selector),four('glob'),0);value=typ();size=ctypes.c_uint32(ctypes.sizeof(value))
        code=audio.AudioObjectGetPropertyData(device,ctypes.byref(address),0,None,ctypes.byref(size),ctypes.byref(value))
        if code:raise RuntimeError('CoreAudio get '+selector+': '+str(code))
        return value.value
    device=get(1,'dOut',ctypes.c_uint32);original=get(device,'nsrt',ctypes.c_double);changed=False;result=dict(device=device,original_rate=original,target_rate=rate,restored=False)
    def set_rate(value):
        address=Property(four('nsrt'),four('glob'),0);number=ctypes.c_double(value)
        code=audio.AudioObjectSetPropertyData(device,ctypes.byref(address),0,None,ctypes.sizeof(number),ctypes.byref(number))
        if code:raise RuntimeError('CoreAudio set rate: '+str(code))
        deadline=time.monotonic()+5
        while abs(get(device,'nsrt',ctypes.c_double)-value)>1:
            if time.monotonic()>deadline:raise TimeoutError('device rate confirmation')
            time.sleep(.01)
    try:
        changed=True;set_rate(rate);result['exit']=subprocess.run(command,cwd=ROOT).returncode
        result['PASS']=result['exit']==0
    except Exception as error:result.update(PASS=False,error=str(error),exit=77)
    finally:
        if changed:set_rate(original)
        result['restored']=abs(get(device,'nsrt',ctypes.c_double)-original)<1
        report.write_text(json.dumps(result,indent=2)+'\n')
    return result['exit']

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--suite',choices=['short','longA','offline','clock','deadline']);p.add_argument('--build',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--configuration',choices=['Release','Debug'],default='Release');p.add_argument('--at-device-rate',type=int);p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    if a.at_device_rate:return clock_run(a.at_device_rate,a.command,a.output)
    build=a.build.resolve();out=a.output.resolve();cases=[];jobs=[];sources=[]
    def plan(name,command,kind='exit',required=(),**fields):
        cases.append(dict(id=name,kind=kind,required=list(required),**fields));jobs.append((name,list(map(str,command))))
    plan('configure',['cmake','-S',ROOT,'-B',build,'-DCMAKE_BUILD_TYPE='+a.configuration,'-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON'])
    plan('build',['cmake','--build',build,'--target','phase62_native_tests','phase62_deadline_native','phase62_fix_render_tests','phase62_fix_clock_native','-j3'])
    plan('architecture',[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py',*[build/t for t in ('phase62_native_tests','phase62_deadline_native','phase62_fix_render_tests','phase62_fix_clock_native')]])
    def native(name,source,seconds,speed,count,preset,start=None,device_rate=None):
        cmd=[build/'phase62_native_tests',source,out/name,seconds,speed,count,preset,'normal']
        if start is not None:cmd.append(start)
        required=[name+'/result.json',name+'/boundaries.jsonl',name+'/last_boundary.json',name+'/clear_result.json',name+'/after_clear_callbacks_all_spans.jsonl',name+'/loop_final_reuse.json',name+'/callbacks_all_spans.jsonl']
        if device_rate:
            cmd=[sys.executable,'-B',__file__,'--at-device-rate',device_rate,'--output',out/(name+'_device.json'),*cmd]
            required.append(name+'_device.json')
        plan(name,cmd,'native',required,result=name+'/result.json',cycles=count,period_preserving=True,clear_contract=True)
        plan(name+'_clock_recompute',[sys.executable,'-B',ROOT/'scripts/phase62_clock_audit.py',out/name/'callbacks_all_spans.jsonl','--output',out/name/'clock_recomputed.json'],'json_pass',[name+'/clock_recomputed.json'],result=name+'/clock_recomputed.json')
    if a.suite=='short':
        for rate,ch,enc in [(44100,1,1),(44100,2,3),(48000,1,3),(48000,2,1)]:
            source=out/f'boundary_{rate}_{ch}_{enc}.wav';sources.append((source,rate,ch,enc))
            for preset in ('candidate','baseline'):
                for speed in (.4,.5,.75,1.,1.5,2.):native(f'{source.stem}_{preset}_{speed}',source,.1,speed,10,preset)
    elif a.suite=='longA':
        source=out/'same_300s_48000_2_pcm16.wav'
        for start in (0,30,270):
            for seconds in (.1,.5):
                for preset in ('candidate','baseline'):native(f'A{start}_{seconds}s_{preset}',source,seconds,2.,100,preset,start*48000)
    elif a.suite=='offline':
        for rate in (44100,48000):
            for ch in (1,2):
                for enc in (1,3):
                    source=out/f'boundary_{rate}_{ch}_{enc}.wav';sources.append((source,rate,ch,enc))
                    plan(source.stem,[build/'phase62_fix_render_tests',source])
        plan('boundaries_4100',[build/'phase62_fix_render_tests',ROOT/'results/phase31/input/mix.wav','--long'])
    elif a.suite=='clock':
        for rate in (44100,48000):
            source=out/f'boundary_{rate}_1_1.wav';sources.append((source,rate,1,1))
            for device in ((48000,44100) if rate==44100 else (48000,)):
                for repeat in range(3):native(f'clock_{rate}_to_{device}_{repeat}',source,.5,.4,10,'candidate',device_rate=device)
        for rate in (44100,48000):
            name=f'normal_startup_{rate}';source=out/f'boundary_{rate}_1_1.wav'
            plan(name,[build/'phase62_fix_clock_native',source,out/name,10],'json_pass',[name+'/summary.json',name+'/rows.jsonl'],result=name+'/summary.json')
            for repeat in range(10):
                plan(name+f'_clock_{repeat}',[sys.executable,'-B',ROOT/'scripts/phase62_clock_audit.py',out/name/str(repeat)/'callbacks_all_spans.jsonl','--output',out/name/str(repeat)/'clock_recomputed.json'],'json_pass',[name+f'/{repeat}/clock_recomputed.json'],result=name+f'/{repeat}/clock_recomputed.json')
    elif a.suite=='deadline':
        source=out/'boundary_48000_2_1.wav';sources.append((source,48000,2,1))
        for name,extra in [('supply_512_100_412',[]),('manual_speed',['--manual-speed']),('near_end',['--near-end'])]:
            plan(name,[build/'phase62_deadline_native',source,out/name,*extra])
        plan('physical_route',[build/'phase62_native_tests',source,out/'physical_route','--physical-loop'],'json_pass',['physical_route/result.json'],result='physical_route/result.json')
    source_hash=source_manifest(ROOT);ledger=Ledger(out,cases,dict(source=source_hash,configuration=a.configuration,architecture='arm64',build=str(build)))
    try:
        for path,rate,ch,enc in sources:fixture(path,rate,ch,enc,'boundary',3.)
        if a.suite=='longA':
            small=out/'recipe_2s.wav';fixture(small,48000,2,1,'boundary',2.)
            with wave.open(str(small),'rb') as wav:params=wav.getparams();block=wav.readframes(wav.getnframes())
            with wave.open(str(source),'wb') as wav:
                wav.setparams(params)
                for repeat in range(150):wav.writeframesraw(block)
            (out/'INPUT_RECIPE.json').write_text(json.dumps(dict(source=identity(source),block=identity(small),repeats=150,seconds=300),indent=2)+'\n')
        for name,command in jobs:
            inputs=[Path(x) for x in command[1:] if Path(x).is_file() and Path(x).suffix=='.wav']
            ok=ledger.run(name,command,cwd=ROOT,inputs=inputs,timeout=1800)
            if name in ('configure','build','architecture') and not ok:break
        if source_manifest(ROOT)['sha256']!=source_hash['sha256']:
            for row in ledger.rows.values():row.update(status='INCOMPLETE',source_changed_during_run=True)
    finally:ledger.save()
    result=aggregate(out);(out/'SUMMARY.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n');print(json.dumps(dict(PASS=result['PASS'],counts=result['counts']),ensure_ascii=False));return int(not result['PASS'])
if __name__=='__main__':raise SystemExit(main())
