"""Independent RAW and actual callback mix captures; measured metrics, no acoustic approval.
Run with the bundled Python containing NumPy. All PCM stays under build/.
"""
import argparse,hashlib,json,subprocess,sys,time,ctypes
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase55_study import write_wav

# Apple arm64 Release contracts old*(1-w)+new*w into fmaf(old,1-w,new*w).
# Use independently rounded libm fmaf, preserving exact mix verification.
fmaf=ctypes.CDLL('/usr/lib/libSystem.B.dylib').fmaf
fmaf.argtypes=[ctypes.c_float,ctypes.c_float,ctypes.c_float];fmaf.restype=ctypes.c_float

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def longest_zero(values):
    boundaries=np.flatnonzero(np.diff(np.concatenate(([False],values,[False]))))
    return int(np.max(boundaries[1::2]-boundaries[::2],initial=0))
def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    build=a.build.resolve();reference=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference';sources=[(name,ROOT/f'results/phase31/input/{name}.wav','既存音源') for name in ('mix','bass','drums','guitar','vocal','sine')]
    rate=48000;t=np.arange(rate*3)/rate
    synthetic={
        'low_sustain':np.column_stack([.2*np.sin(2*np.pi*55*t)]*2),
        'stereo_phase':np.column_stack([.2*np.sin(2*np.pi*437.3*t),.2*np.sin(2*np.pi*437.3*t+np.pi/2)]),
        'impulse_train':np.column_stack([np.where(np.arange(len(t))%6001==17,.7,0.)]*2),
        'piano_synthetic':np.column_stack([sum(.18/k*np.sin(2*np.pi*220*k*t)*np.exp(-np.mod(t,.31)*(7+k)) for k in range(1,9))]*2),
    }
    for name,data in synthetic.items():
        source=out/(name+'.wav');write_wav(source,rate,2,3,data.astype('<f4').tobytes());sources.append((name,source,'人工音源。piano_syntheticは実録ピアノではない'))
    commands=[];rows=[]
    def run(name,command,timeout=180):
        command=list(map(str,command));start=time.monotonic();r=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=timeout);(out/(name+'.log')).write_text(r.stdout+r.stderr)
        commands.append(dict(name=name,command=command,exit=r.returncode,wall_s=time.monotonic()-start));(out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');return r
    for name,source,kind in sources:
        for speed in (400000,500000,750000,1000000,1500000,2000000):
            for preset in ('candidate','baseline'):
                key=f'{name}_{speed}_{preset}';raw=out/(key+'_reference.f32')
                # Existing music is 44.1kHz; synthetic fixtures above are 48kHz.
                input_rate=48000 if name in synthetic else 44100
                start_input=1023;end_input=2*input_rate+17
                r=run(key+'_reference',[reference,source,speed,preset,raw,start_input,end_input]);
                if r.returncode:rows.append(dict(name=key,kind=kind,PASS=False,stage='reference',error=r.stderr));continue
                meta=json.loads(r.stdout);oa,ob=meta['positions'];folder=out/key
                capture=run(key,[build/'phase62_render_tests',source,speed,preset,start_input,end_input,raw,oa,ob,folder])
                if capture.returncode:rows.append(dict(name=key,kind=kind,PASS=False,stage='capture',error=capture.stderr));continue
                m=json.loads((folder/'capture.json').read_text());ch=m['channels'];n=m['overlap'];length=ob-oa
                original=np.fromfile(raw,dtype='<f4').reshape(-1,ch)[oa:ob];old=np.fromfile(folder/'old_raw.f32',dtype='<f4').reshape(-1,ch);new=np.fromfile(folder/'new_raw.f32',dtype='<f4').reshape(-1,ch);mixed=np.fromfile(folder/'mixed.f32',dtype='<f4').reshape(-1,ch)
                w=(np.arange(1,n+1,dtype=np.float32)/np.float32(n))[:,None]
                overlap_reference=np.empty((n,ch),dtype=np.float32)
                new_product=(original[:n]*w).astype(np.float32)
                for frame in range(n):
                    for channel in range(ch):overlap_reference[frame,channel]=fmaf(float(original[-n+frame,channel]),float(np.float32(1)-w[frame,0]),float(new_product[frame,channel]))
                expected=np.concatenate((original[:-n],overlap_reference,original[n:-n]))
                exact=old.shape==original.shape and old.tobytes()==original.tobytes() and new.tobytes()==original[:len(new)].tobytes() and np.array_equal(mixed,expected)
                overlap=mixed[length-n:length];rms=lambda x:np.sqrt(np.mean(x.astype(np.float64)**2,axis=0))
                base_rms=np.sqrt((rms(original[-n:])**2+rms(original[:n])**2)/2)
                ratio=20*np.log10(np.maximum(rms(overlap),1e-30)/np.maximum(base_rms,1e-30))
                peak=lambda x:float(np.max(np.abs(x)))
                zero=np.all(mixed==0,axis=1);expected_zero=np.all(expected==0,axis=1)
                row=dict(name=key,kind=kind,PASS=exact,rate=m['rate'],channels=ch,raw_frames=length,overlap_frames=n,mixed_frames=len(mixed),raw_peak=peak(old),mixed_peak=peak(mixed),max_adjacent_jump=float(np.max(np.abs(np.diff(mixed,axis=0)))),overlap_rms_db=ratio.tolist(),mixed_channel_rms=rms(mixed).tolist(),source_zero_frames=int(np.count_nonzero(np.all(original==0,axis=1))),output_zero_frames=int(zero.sum()),unexpected_zero_frames=int(np.count_nonzero(zero&~expected_zero)),max_exact_zero_run=longest_zero(zero),source_max_exact_zero_run=longest_zero(np.all(original==0,axis=1)),raw_sha256=sha(folder/'old_raw.f32'),mixed_sha256=sha(folder/'mixed.f32'),reference_sha256=sha(raw),input_sha256=sha(source))
                if ch==2:
                    spec=np.fft.rfft(overlap.astype(np.float64),axis=0);k=int(np.argmax(np.abs(spec[:,0])));row['overlap_lr_phase_at_dominant_radians']=float(np.angle(spec[k,1]*np.conj(spec[k,0])));row['dominant_frequency_hz']=float(k*m['rate']/n);row['spectral_resolution_hz']=m['rate']/n
                # Playable inspection copy, fixed gain 0.5; never counted as a listening test.
                write_wav(folder/'mixed_gain05.wav',int(m['rate']),ch,3,(mixed*np.float32(.5)).astype('<f4').tobytes());rows.append(row)
                (out/'rows.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False)+'\n');print(key,'PASS' if exact else 'FAIL',flush=True)
    summary=dict(PASS=bool(rows) and all(r['PASS'] for r in rows),passed=sum(r['PASS'] for r in rows),total=len(rows),acoustic_loopback=False,subjective_listening=False,public_approved=False,mix_reference="libm fmaf(old, 1-w, float32(new*w)), bit exact on Apple arm64 Release",reference_sha256=sha(reference),capture_host_sha256=sha(build/'phase62_render_tests'),driver_sha256=sha(__file__),inputs=[dict(name=n,path=str(s),sha256=sha(s),kind=k) for n,s,k in sources])
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n');return int(not summary['PASS'])
if __name__=='__main__':raise SystemExit(main())
