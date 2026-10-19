"""周期Lを維持する境界加工を独立RAW・独立数式で全ビット検査する。"""
import argparse,ctypes,json,subprocess,sys,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import Ledger,aggregate,identity,source_manifest

NAMES=('mix','bass','drums','guitar','vocal','sine','low_sustain','stereo_phase','impulse_train','piano_synthetic','silence')
def input_rate(path):
    with Path(path).open('rb') as stream:
        header=stream.read(12)
        if header[:4]!=b'RIFF' or header[8:]!=b'WAVE':raise ValueError('WAV header required: '+str(path))
        while True:
            header=stream.read(8)
            if len(header)!=8:raise ValueError('WAV fmt missing: '+str(path))
            tag,size=struct.unpack('<4sI',header)
            if tag==b'fmt ':
                data=stream.read(min(size,16))
                if len(data)<16:raise ValueError('WAV fmt truncated: '+str(path))
                rate=struct.unpack_from('<I',data,4)[0]
                if rate not in (44100,48000):raise ValueError('Unsupported source rate: '+str(rate))
                return rate
            stream.seek(size+(size&1),1)

def fixtures(out):
    import numpy as np
    from phase55_study import write_wav
    out.mkdir();rows=[];rate=48000;t=np.arange(rate*3)/rate
    synthetic=dict(low_sustain=np.column_stack([.2*np.sin(2*np.pi*55*t)]*2),stereo_phase=np.column_stack([.2*np.sin(2*np.pi*437.3*t),.2*np.sin(2*np.pi*437.3*t+np.pi/2)]),impulse_train=np.column_stack([np.where(np.arange(len(t))%6001==17,.7,0.)]*2),piano_synthetic=np.column_stack([sum(.18/k*np.sin(2*np.pi*220*k*t)*np.exp(-np.mod(t,.31)*(7+k)) for k in range(1,9))]*2),silence=np.zeros((len(t),2)))
    for name in NAMES:
        if name in synthetic:
            path=out/(name+'.wav');write_wav(path,rate,2,3,synthetic[name].astype('<f4').tobytes());source_rate=rate;kind='人工音源。piano_syntheticは実録ピアノではない'
        else:path=ROOT/f'results/phase31/input/{name}.wav';source_rate=input_rate(path);kind='既存音源'
        rows.append(dict(name=name,rate=source_rate,kind=kind,**identity(path)))
    (out/'INPUTS.json').write_text(json.dumps(dict(numpy=np.__version__,sources=rows),indent=2,ensure_ascii=False)+'\n')

def measure(capture,reference,output):
    import numpy as np
    from phase55_study import write_wav
    m=json.loads((capture/'capture.json').read_text());ch=m['channels'];length=m['period_frames'];n=m['boundary_frames'];cycles=m['cycles'];rate=m['rate']
    original=np.fromfile(reference,dtype='<f4').reshape(-1,ch)[m['start']:m['end']]
    raw=np.fromfile(capture/'raw.f32',dtype='<f4').reshape(-1,ch);actual=np.fromfile(capture/'processed.f32',dtype='<f4').reshape(-1,ch)
    expected=np.tile(original,(cycles,1));expected_raw=expected.copy()
    fmaf=ctypes.CDLL('/usr/lib/libSystem.B.dylib').fmaf;fmaf.argtypes=[ctypes.c_float]*3;fmaf.restype=ctypes.c_float
    for cycle in range(cycles):
        for j in range(n):
            t=np.float32(j+1)/np.float32(n);w=np.float32(np.float32(t*t)*np.float32(np.float32(3)-np.float32(2)*t))
            x=np.float32(1)-np.float32(j)/np.float32(n);head_w=np.float32(np.float32(x*x)*np.float32(np.float32(3)-np.float32(2)*x))
            for channel in range(ch):
                last=original[-1,channel];first=original[0,channel];half=np.float32(np.float32(last-first)*np.float32(.5))
                middle=fmaf(float(last),.5,float(np.float32(first*np.float32(.5))))
                expected[cycle*length+length-n+j,channel]=middle if j+1==n else fmaf(float(-half),float(w),float(original[length-n+j,channel]))
                if cycle:expected[cycle*length+j,channel]=middle if not j else fmaf(float(half),float(head_w),float(original[j,channel]))
    condition=None;plan=capture.parent/'EXPECTED.json'
    if plan.is_file():
        condition=next((r for r in json.loads(plan.read_text())['cases'] if r['id']==capture.name and 'input_rate' in r),None)
    conditions_match=condition is None or (condition['input_rate']==rate and (condition['nominal_duration']!='100ms' or condition['input_b_exclusive']-condition['input_a']==rate//10))
    finite=all(np.isfinite(x).all() for x in (original,raw,actual,expected))
    exact=raw.shape==expected_raw.shape and raw.tobytes()==expected_raw.tobytes() and actual.shape==expected.shape and actual.tobytes()==expected.tobytes()
    rms=lambda values:np.sqrt(np.mean(values.astype(np.float64)**2,axis=0))
    windows=[]
    for milliseconds in (10,25,100):
        width=int(rate*milliseconds/2000)
        # A 100ms input at 2x can be shorter than a 100ms analysis window.
        # Extend the verified steady period in both directions, rather than
        # take an empty negative-index slice or silently shorten the window.
        indices=np.arange(-width,width)%length
        before=original[indices];after=actual[length:2*length][indices]
        original_rms=rms(before);new_rms=rms(after);ratio=[None if x==0 else float(20*np.log10(max(y,1e-30)/x)) for x,y in zip(original_rms,new_rms)]
        row=dict(milliseconds=milliseconds,context='verified steady-period extension around B/A',context_frames=2*width,raw_rms=original_rms.tolist(),processed_rms=new_rms.tolist(),rms_change_db=ratio)
        if ch==2:
            row['lr_rms_difference']=float(new_rms[1]-new_rms[0]);row['lr_correlation']=None if np.std(after[:,0])==0 or np.std(after[:,1])==0 else float(np.corrcoef(after[:,0],after[:,1])[0,1])
        windows.append(row)
    zero=np.all(actual==0,axis=1);expected_zero=np.all(expected==0,axis=1)
    peak=lambda values:float(np.max(np.abs(values)))
    result=dict(PASS=bool(exact and finite and conditions_match),input_conditions_match=conditions_match,input_condition=condition,bit_exact=bool(exact),finite=bool(finite),period_frames=length,cycles=cycles,output_frames=len(actual),expected_output_frames=length*cycles,raw_peak=peak(raw),processed_peak=peak(actual),output_peak_gain05=peak(actual)*.5,max_adjacent_jump=float(np.max(np.abs(np.diff(actual,axis=0)))),source_zero_frames=int(np.count_nonzero(np.all(expected_raw==0,axis=1))),output_zero_frames=int(zero.sum()),unexpected_zero_frames=int(np.count_nonzero(zero&~expected_zero)),windows=windows,subjective_listening=None,acoustic_loopback=None,public_approved=False,formula='float32 smoothstep with independent libm fmaf; fixed period L, no temporal overlap',raw=identity(capture/'raw.f32'),processed=identity(capture/'processed.f32'),reference=identity(reference))
    write_wav(capture/'playable_gain05.wav',int(rate),ch,3,(actual*np.float32(.5)).astype('<f4').tobytes())
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n');return int(not result['PASS'])

def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--build',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--configuration',choices=['Release','Debug'],default='Release');p.add_argument('--fixtures',action='store_true');p.add_argument('--measure',type=Path);p.add_argument('--reference',type=Path);a=p.parse_args()
    if a.fixtures:fixtures(a.output);return 0
    if a.measure:return measure(a.measure,a.reference,a.output)
    build=a.build.resolve();out=a.output.resolve();oracle=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';cases=[];jobs=[]
    def plan(name,cmd,kind='exit',required=(),**fields):cases.append(dict(id=name,kind=kind,required=list(required),**fields));jobs.append((name,list(map(str,cmd))))
    plan('configure',['cmake','-S',ROOT,'-B',build,'-DCMAKE_BUILD_TYPE='+a.configuration,'-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON'])
    plan('build',['cmake','--build',build,'--target','phase62_fix_render_tests','-j3'])
    plan('architecture',[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py',build/'phase62_fix_render_tests',oracle])
    plan('fixtures',[sys.executable,'-B',__file__,'--fixtures','--output',out/'inputs'],required=['inputs/INPUTS.json'])
    for duration,speeds in [('long',(400000,500000,750000,1000000,1500000,2000000)),('100ms',(400000,2000000))]:
        for name in NAMES:
            source=ROOT/f'results/phase31/input/{name}.wav' if name in NAMES[:6] else out/'inputs'/(name+'.wav')
            rate=input_rate(source) if name in NAMES[:6] else 48000
            start=1023;end=2*rate+17 if duration=='long' else start+rate//10
            for speed in speeds:
                for preset in ('candidate','baseline'):
                    key=f'{name}_{duration}_{speed}_{preset}';reference=out/(key+'.f32');folder=out/key
                    plan(key+'_reference',[oracle,source,speed,preset,reference,start,end],required=[key+'.f32'])
                    plan(key,[build/'phase62_fix_render_tests',source,speed,preset,start,end,reference,'OA','OB',folder],'period_capture',[key+'/capture.json',key+'/raw.f32',key+'/processed.f32'],reference_case=key+'_reference',result=key+'/capture.json',input_rate=rate,input_a=start,input_b_exclusive=end,input_duration_seconds=(end-start)/rate,nominal_duration=duration)
                    plan(key+'_measure',[sys.executable,'-B',__file__,'--measure',folder,'--reference',reference,'--output',folder/'metrics.json'],'quality',[key+'/metrics.json',key+'/playable_gain05.wav'],result=key+'/metrics.json',capture_case=key)
    source=source_manifest(ROOT);ledger=Ledger(out,cases,dict(source=source,configuration=a.configuration,architecture='arm64',oracle=identity(oracle)))
    try:
        for name,cmd in jobs:
            spec=next(x for x in cases if x['id']==name)
            if 'reference_case' in spec:
                if ledger.rows[spec['reference_case']]['status']!='PASS':continue
                meta=json.loads((out/(spec['reference_case']+'.log')).read_text());cmd=[str(meta['positions'][0]) if x=='OA' else str(meta['positions'][1]) if x=='OB' else x for x in cmd]
            if 'capture_case' in spec and ledger.rows[spec['capture_case']]['status']!='PASS':continue
            inputs=[Path(x) for x in cmd[1:] if Path(x).is_file() and Path(x).suffix in ('.wav','.f32')]
            good=ledger.run(name,cmd,cwd=ROOT,timeout=300,inputs=inputs)
            if name in ('configure','build','architecture','fixtures') and not good:break
        after=source_manifest(ROOT)
        if source['sha256']!=after['sha256']:
            for row in ledger.rows.values():row.update(status='INCOMPLETE',source_changed_during_run=True)
    finally:ledger.save()
    summary=aggregate(out);(out/'SUMMARY.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n');print(json.dumps(dict(PASS=summary['PASS'],counts=summary['counts']),ensure_ascii=False));return int(not summary['PASS'])
if __name__=='__main__':raise SystemExit(main())
