#!/usr/bin/env python3
"""Input-mapped, gain-independent diagnostics. No quality ranking by numbers."""
import csv,json,subprocess,math
from pathlib import Path
import numpy as np
from phase32_study import read
from phase32_metrics import stereo,envelope
from phase37_study import peak_region
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase51/audio'
def feature(data,rate):
    mono=np.mean(data,axis=1);n=1024;hop=256
    spec=np.fft.rfft(np.lib.stride_tricks.sliding_window_view(mono,n)[::hop]*np.hanning(n),axis=1) if len(mono)>=n+hop else None
    spectral=None
    if spec is not None:
        mag=np.abs(spec);weight=np.minimum(mag[1:],mag[:-1]);spectral=float(np.sum(np.abs(np.diff(np.log(np.maximum(mag,1e-8)),axis=0))*weight)/max(np.sum(weight),1e-12))
    side,corr=stereo(data)
    silent=np.all(np.abs(data)<1e-8,axis=1);bounds=np.flatnonzero(np.diff(np.r_[False,silent,False]))
    return dict(peak=float(np.max(np.abs(data))),rms=float(np.sqrt(np.mean(data.astype(float)**2))),max_step=float(np.max(np.abs(np.diff(data,axis=0)),initial=0)),side_mid=float(side),lr_correlation=float(corr),spectral_log_variation=spectral,near_zero_run=int(np.max(bounds[1::2]-bounds[::2],initial=0)))
def main():
    results=[]
    for row in json.loads((OUT/'summary.json').read_text()):
        path=Path(row['path']);source=row['source'];input=ROOT/f'results/phase31/input/{source}.wav'
        r=subprocess.run([str(ROOT/'build/phase51_reference'),str(input),'-','.4',str(path/'replay.csv'),row['planning'],'safe-density'],capture_output=True,text=True,check=True)
        mapfile=path/'map.csv'
        if mapfile.exists():assert mapfile.read_text()==r.stdout
        else:mapfile.write_text(r.stdout)
        nodes=list(csv.DictReader(r.stdout.splitlines()));x=np.array([int(n['input_sample']) for n in nodes]);y=np.array([int(n['output_sample']) for n in nodes])
        rate,audio=read(path/'raw.wav');_,original=read(input);plan=row['plans'][0]
        start=int(plan['applied_output']);end=int(plan['completion_output'])
        at=lambda t:math.floor(np.interp(t*rate,x,y)+.5) # Same positive-coordinate llround as C++.
        span=audio[max(0,start-rate//4):min(len(audio),end+rate//4)]
        item=dict(source=source,label=row['label'],frames=len(audio),finite=bool(np.isfinite(audio).all()),peak=float(np.max(np.abs(audio))),transition=feature(span,rate),ramp_ms=(end-start)*1000/rate,
            density_weights={band:float(plan['density_weight_'+band]) for band in ('low','mid','high')},map_monotonic=bool(np.all(np.diff(y)>0)),
            reference_eos_frames=math.floor(np.interp(len(original),x,y)+.5))
        hops=subprocess.run([str(ROOT/'build/phase51_reference'),str(input),'--hops','.4',str(path/'replay.csv'),row['planning'],'safe-density'],capture_output=True,text=True,check=True)
        item['whole_synthesis_hops']=[dict(band=b,min=int(lo),max=int(hi)) for b,lo,hi in csv.reader(hops.stdout.splitlines())]
        regions={'attack':(3.77,4.02),'tail':(4.05,4.35)} if source=='drums' else {'overlap':(2.9,4.2),'quiet':(4.2,4.8)} if source=='mix' else {'sustain':(2.9,4.2)}
        item['input_mapped_regions']={name:dict(input_seconds=[a,b],output_frames=[at(a),at(b)],metrics=feature(audio[at(a):at(b)],rate)) for name,(a,b) in regions.items()}
        if source=='drums':
            mono=np.mean(original,axis=1);lo=round(3.77*rate);hi=round(4.02*rate);input_peak=lo+int(np.argmax(abs(mono[lo:hi])))
            expected=np.interp(input_peak,x,y);p=peak_region(audio,rate,expected)
            item['attack']=dict(input_peak_frame=input_peak,mapped_expected_frame=expected,peak=p[0],offset_ms=p[1],half_amplitude_width_ms=p[2],pre_5_to_40ms_rms=p[3],secondary_peak_ratio=p[4])
            it,ie=envelope(original,rate,10);ot,oe=envelope(audio,rate,10);mapped=np.interp(ot*rate,y,x)/rate;mask=(mapped>=4.05)&(mapped<=4.35)
            expected_env=np.interp(mapped[mask],it,ie);observed_env=oe[mask];valid=expected_env>max(np.max(expected_env,initial=0)*.005,1e-8)
            delta=20*np.log10(np.maximum(observed_env[valid],1e-10)/expected_env[valid]);item['tail_envelope_centered_error_db']=float(np.std(delta)) if len(delta) else None
        assert item['finite'] and item['map_monotonic'] and item['frames']==item['reference_eos_frames']
        assert all(.15<=w for w in item['density_weights'].values())
        assert all(0<h['min']<=h['max']<dict(low=8192,mid=4096,high=1024)[h['band']] for h in item['whole_synthesis_hops'])
        results.append(item)
    (OUT/'quality.json').write_text(json.dumps(results,indent=2,allow_nan=False));print('10 input-mapped quality diagnostics PASS (no numerical quality ranking)')
if __name__=='__main__':main()
