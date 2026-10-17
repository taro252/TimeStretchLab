"""Offline local-seek experiment; preserves failures and independent reference PCM.

Requires NumPy. Every DSP instance starts afresh; analysis/resident bytes are
reused. Timing is offline Ready, NOT native callback or acoustic presentation.
"""
import argparse, hashlib, json, math, random, shutil, struct, subprocess, time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEEDS = [400000, 500000, 750000, 1000000, 1500000, 2000000]
# New experimental screening only; no existing Exact/Golden gate is replaced.
SCREEN = {'rms_gain_db': 1.5, 'weighted_spectral_error_db': 3.,
          'stereo_ipd_error_deg': 10., 'stereo_balance_error_db': 1.,
          'low_tone_envelope_cv_excess': .03, 'low_tone_pitch_error_cents': 5.}

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def wav_info(path):
    data = Path(path).read_bytes(); pos = 12; fmt = None; size = None
    while pos + 8 <= len(data):
        kind, n = struct.unpack_from('<4sI', data, pos); pos += 8
        if kind == b'fmt ': fmt = struct.unpack_from('<HHIIHH', data, pos)
        if kind == b'data': size = n
        pos += n + n % 2
    assert fmt and size is not None
    return fmt[2], fmt[1], size // fmt[4]

def write_wav(path, rate, values):
    values = np.asarray(values, dtype='<f4'); channels = values.shape[1]
    payload = values.tobytes(); fmt = struct.pack('<HHIIHH', 3, channels, rate, rate*channels*4, channels*4, 32)
    Path(path).write_bytes(b'RIFF'+struct.pack('<I', 36+len(payload))+b'WAVEfmt '+struct.pack('<I', 16)+fmt+b'data'+struct.pack('<I', len(payload))+payload)

def fixtures(out):
    out.mkdir(); rate = 48000; t = np.arange(rate*10)/rate
    paths = [ROOT/'results/phase31/input'/f'{name}.wav' for name in ('mix','bass','drums','guitar','vocal')]
    signals = {}
    for name, tones in [('low_tone', [55.3]), ('crossovers', [249.2, 3501.3]), ('stereo', [82.41, 220.7, 431.3])]:
        left = sum(.18/len(tones)*np.sin(2*np.pi*f*t) for f in tones)
        right = sum(.126/len(tones)*np.sin(2*np.pi*f*t+.6) for f in tones)
        signals[name] = np.column_stack([left, right])
    x = .04*np.sin(2*np.pi*55.3*t)
    for at in range(rate//2, len(t)-1000, rate//2):
        dt=np.arange(1000)/rate
        x[at:at+1000] += .5*np.exp(-dt*350)*np.cos(2*np.pi*1700*dt)
    signals['transients'] = np.column_stack([x,.7*x])
    for name, samples in signals.items():
        path=out/(name+'.wav'); write_wav(path,rate,samples); paths.append(path)
    return paths

def spectrum(x, n=4096, hop=512):
    if len(x)<n: x=np.pad(x,((0,n-len(x)),(0,0)))
    frames=np.lib.stride_tricks.sliding_window_view(x,n,axis=0)[::hop]
    return np.fft.rfft(frames*np.hanning(n),axis=-1)

def metrics(actual, ref, rate, kind):
    assert actual.shape == ref.shape and np.all(np.isfinite(actual))
    eps=1e-20; ar=np.sqrt(np.mean(actual**2)); rr=np.sqrt(np.mean(ref**2))
    a=spectrum(actual); r=spectrum(ref); am=np.abs(a); rm=np.abs(r)
    weights=rm**2; weights[rm<max(float(rm.max())*1e-4,1e-8)]=0
    db=20*np.log10((am+1e-10)/(rm+1e-10))
    spectral=float(np.sqrt(np.sum(weights*db**2)/(weights.sum()+eps)))
    mismatch=int(np.count_nonzero(actual.astype('<f4').view('<u4')!=ref.astype('<f4').view('<u4')))
    result={'pcm_different_samples':mismatch,'pcm_relative_rmse_db':float(10*np.log10((np.mean((actual-ref)**2)+eps)/(np.mean(ref**2)+eps))),
            'rms_gain_db':float(20*np.log10((ar+eps)/(rr+eps))),'weighted_spectral_error_db':spectral,
            'peak':float(np.max(np.abs(actual))), 'reference_peak':float(np.max(np.abs(ref))),
            'first_sample_abs':float(np.max(np.abs(actual[0]))),
            'max_adjacent_step':float(np.max(np.abs(np.diff(actual,axis=0)))),
            'reference_max_adjacent_step':float(np.max(np.abs(np.diff(ref,axis=0))))}
    audible=np.flatnonzero(np.max(np.abs(actual),axis=1)>1e-5)
    result['leading_below_1e_5_frames']=int(audible[0]) if len(audible) else len(actual)
    if actual.shape[1]==2:
        ac=a[:,1]*a[:,0].conj(); rc=r[:,1]*r[:,0].conj()
        w=np.minimum(np.abs(ac),np.abs(rc)); err=np.angle(ac*rc.conj())
        result['stereo_ipd_error_deg']=float(np.sqrt(np.sum(w*err**2)/(w.sum()+eps))*180/np.pi)
        balances=lambda x:20*np.log10((np.sqrt(np.mean(x[:,1]**2))+eps)/(np.sqrt(np.mean(x[:,0]**2))+eps))
        result['stereo_balance_error_db']=float(balances(actual)-balances(ref))
    if kind=='low_tone':
        def tone(y):
            y=y[:,0]; z=np.fft.rfft(y); f=np.fft.rfftfreq(len(y),1/rate)
            z[(f<30)|(f>100)]=0; analytic=np.zeros(len(y),complex); analytic[:len(z)]=z; analytic[1:len(z)-1]*=2
            env=np.abs(np.fft.ifft(analytic))[rate//10:-rate//10]
            # Unwrapped analytic phase slope, trim circular boundary effects.
            phase=np.unwrap(np.angle(np.fft.ifft(analytic)))[rate//10:-rate//10]
            pitch=float(np.polyfit(np.arange(len(phase))/rate,phase,1)[0]/(2*np.pi))
            return float(env.std()/(env.mean()+eps)),pitch
        cv,pitch=tone(actual); rcv,rpitch=tone(ref)
        result.update(low_tone_envelope_cv=cv,reference_low_tone_envelope_cv=rcv,
                      low_tone_envelope_cv_excess=cv-rcv,low_tone_pitch_error_cents=float(1200*np.log2(pitch/rpitch)))
    if kind=='transients':
        # Energy peaks are descriptive, not a substitute for listening to attacks.
        win=rate//1000
        def env(y): return np.mean(y[:len(y)//win*win].reshape(-1,win,y.shape[1])**2,axis=(1,2))
        ae,re=env(actual),env(ref); result['strongest_attack_offset_ms']=int(np.argmax(ae)-np.argmax(re))
        result['attack_peak_energy_db']=float(10*np.log10((ae.max()+eps)/(re.max()+eps)))
    failed=[key for key,limit in SCREEN.items() if key in result and (result[key] if key.endswith('excess') else abs(result[key]))>limit]
    result['screen_failures']=failed; result['screen_pass']=not failed
    return result

def main():
    p=argparse.ArgumentParser(__doc__); p.add_argument('--binary',type=Path,required=True); p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--suite',choices=['quality','performance'],required=True)
    p.add_argument('--source',type=Path,action='append');p.add_argument('--preroll-ms',type=int,nargs='+',default=[500,1000,2000]);p.add_argument('--repeats',type=int,default=3);args=p.parse_args()
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False); commands=[]; rows=[]
    def call(name,cmd):
        if shutil.disk_usage(ROOT).free<8*1024**3: raise RuntimeError('Free space below 8 GiB; no evidence removed')
        cmd=list(map(str,cmd)); start=time.monotonic()
        log=out/(name+'.log'); err=out/(name+'.err')
        with log.open('x') as f,err.open('x') as e: run=subprocess.run(cmd,stdout=f,stderr=e,cwd=ROOT)
        commands.append({'name':name,'command':cmd,'exit':run.returncode,'wall_s':time.monotonic()-start,'stdout':str(log),'stderr':str(err)})
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if run.returncode: raise RuntimeError(f'{name}: exit {run.returncode}; {err.read_text()}')
        return log
    if args.suite=='quality': paths=fixtures(out/'inputs')
    else: paths=args.source or [ROOT/'results/phase56/long/chain_300s.wav']
    manifest={'suite':args.suite,'binary':str(args.binary.resolve()),'binary_sha256':sha(args.binary),'reference':str(args.reference.resolve()),'reference_sha256':sha(args.reference),'driver_sha256':sha(__file__),'speeds':SPEEDS,'screening_thresholds':SCREEN,'subjective_listening':'separate user evaluation, not inferred here','offline_only':True,'sources':[]}
    for source in paths:
        rate,channels,n=wav_info(source); manifest['sources'].append({'path':str(source),'sha256':sha(source),'rate':rate,'channels':channels,'frames':n})
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        if args.suite=='quality': positions=[n//2+17,3*n//4+31]; repeats=1
        else:
            assert n==rate*300,'Performance requires exactly 300s'
            rng=random.Random(61061); positions=[round(s*rate) for s in (0,30,150,270,285)]+[rng.randrange(rate,n-rate) for _ in range(5)]; repeats=args.repeats
        assert all(ms in (500,1000,2000) for ms in args.preroll_ms) and args.repeats>0
        warms=[rate*ms//1000 for ms in args.preroll_ms]
        local_dir=out/(source.stem+'_local')
        log=call(source.stem+'_local',[args.binary.resolve(),source,local_dir,','.join(map(str,SPEEDS)),','.join(map(str,warms)),','.join(map(str,positions)),rate,repeats,'local'])
        local_rows=[json.loads(line) for line in log.read_text().splitlines()]
        # Full independent render once per speed/preset. Keep all reference PCM.
        for speed in SPEEDS:
            for candidate in (True,False):
                subset=[r for r in local_rows if r['speed']==speed and r['candidate']==candidate]
                preset='candidate' if candidate else 'baseline'; name=f'{source.stem}_{speed}_{preset}'
                raw=out/(name+'_reference.f32')
                reference=json.loads(call(name+'_reference',[args.reference.resolve(),source,speed,preset,raw,*positions]).read_text())
                assert sha(raw)==reference['sha256']
                reference_values=np.memmap(raw,dtype='<f4',mode='r').reshape(-1,channels)
                for row in subset:
                    assert row['output_start']==reference['positions'][positions.index(row['input'])]
                    path=local_dir/(row['name']+'.f32'); actual=np.fromfile(path,dtype='<f4').reshape(-1,channels).astype(float)
                    ref=np.asarray(reference_values[row['output_start']:row['output_start']+row['captured']],dtype=float)
                    row.update(source=source.stem,pcm_sha256=sha(path),reference_pcm_sha256=reference['sha256'],metrics=metrics(actual,ref,rate,source.stem))
                    rows.append(row)
                    with (out/'rows.jsonl').open('a') as f: f.write(json.dumps(row)+'\n')
                del reference_values
        print(source.stem,len(local_rows),'complete',flush=True)
        (out/'progress.json').write_text(json.dumps({'completed':len(rows),'last':source.stem})+'\n')
    summary={'case_count':len(rows),'coordinate_pass':all(r['input_error_frames']==r['output_gaps']==r['output_duplicates']==0 for r in rows),'screen_passed':sum(r['metrics']['screen_pass'] for r in rows),'subjective_listening':'UNMEASURED','offline_only':True,'groups':[]}
    for warm in sorted(set(r['preroll_input_frames']/r['rate'] for r in rows)):
        group=[r for r in rows if r['preroll_input_frames']/r['rate']==warm]
        summary['groups'].append({'preroll_input_s':warm,'cases':len(group),'p50_ready_ms':float(np.percentile([r['ready_s']*1000 for r in group],50)),'p95_ready_ms':float(np.percentile([r['ready_s']*1000 for r in group],95)),'max_ready_ms':max(r['ready_s']*1000 for r in group),'screen_failed':sum(not r['metrics']['screen_pass'] for r in group)})
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n'); print(json.dumps(summary),flush=True)
if __name__=='__main__': main()
