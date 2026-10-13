#!/usr/bin/env python3
"""Phase42 metrics adapted to input-matched regions; diagnostic, never quality verdict."""
import csv,json,subprocess
from pathlib import Path
import numpy as np
from phase32_study import read,wav
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase50'
def map_for(row):
    path=Path(row['path']);input=ROOT/('results/phase50/input/mix30.wav' if row['source']=='mix' else 'results/phase49/input/drums30.wav')
    r=subprocess.run([str(ROOT/'build/phase39_reference'),str(input),'-','.4',str(path/'replay.csv'),'C','safe-density'],capture_output=True,text=True,check=True)
    (path/'final_map.csv').write_text(r.stdout)
    return np.array([int(p['output_sample']) for p in csv.DictReader(r.stdout.splitlines())])
def at(nodes,input):
    left=min(int(input//1024),len(nodes)-2);return nodes[left]+(input/1024-left)*(nodes[left+1]-nodes[left])
def metrics(audio,rate):
    x=np.asarray(audio,dtype=np.float64);mono=x.mean(axis=1);amp=np.abs(mono);peak=int(np.argmax(amp));thr=amp[peak]/np.sqrt(2)
    left=right=peak
    while left and amp[left-1]>=thr:left-=1
    while right+1<len(amp) and amp[right+1]>=thr:right+=1
    pre=float(np.sum(mono[max(0,left-round(.02*rate)):left]**2));first=float(np.sum(mono[left:left+round(.02*rate)]**2))
    n=max(1,rate//100);rms=np.array([np.sqrt(np.mean(mono[i:i+n]**2)) for i in range(0,len(mono)-n+1,n)])
    mid=(x[:,0]+x[:,1])/2;side=(x[:,0]-x[:,1])/2
    corr=float(np.corrcoef(x.T)[0,1]) if np.std(x[:,0]) and np.std(x[:,1]) else 0
    size=2048;window=np.hanning(size);spectra=[];weight_sum=weighted_ipd=0
    for start in range(0,len(x)-size+1,512):
        spectra.append(np.abs(np.fft.rfft(mono[start:start+size]*window)))
        l=np.fft.rfft(x[start:start+size,0]*window);r=np.fft.rfft(x[start:start+size,1]*window)
        weight=np.abs(l)*np.abs(r);weight_sum+=np.sum(weight);weighted_ipd+=np.sum(weight*np.angle(l*np.conj(r))**2)
    specs=np.array(spectra);flux=np.sum(np.maximum(0,np.diff(specs,axis=0)),axis=1)/np.maximum(np.sum(specs[1:],axis=1),1e-12) if len(specs)>1 else np.array([0])
    return dict(peak=float(np.max(np.abs(x))),derivative_max=float(np.max(np.abs(np.diff(x,axis=0)))),
        local_maximum_3db_width_ms=(right-left+1)*1000/rate,preecho_proxy_ratio=pre/max(first,1e-12),
        rms_min=float(rms.min()) if len(rms) else None,rms_modulation=float(rms.std()/max(rms.mean(),1e-12)) if len(rms) else None,
        spectral_flux_median=float(np.median(flux)),lr_corr=corr,side_mid=float(np.sqrt(np.mean(side**2))/max(np.sqrt(np.mean(mid**2)),1e-12)),
        ipd_rms=float(np.sqrt(weighted_ipd/max(weight_sum,1e-12))),finite=bool(np.isfinite(x).all()))
def main():
    rows=json.loads((OUT/'latency/summary.json').read_text());results=[];manifest=[]
    for source in ('drums','mix'):
        for time in (1,1.85):
            cases={r['label']:r for r in rows if r['source']==source and r['time']==time}
            for label in ('C','C_L1'):
                row=cases[label];rate,audio=read(Path(row['path'])/'reference.wav');nodes=map_for(row)
                whole=dict(peak=float(np.max(np.abs(audio))),finite=bool(np.isfinite(audio).all()),frames=len(audio))
                for index,plan in enumerate(cases['C']['plans']):
                    # Same source interval, referenced by the baseline's application input.
                    center=int(plan['applied_frame'])*1024
                    first=max(0,round(at(nodes,max(0,center-.20*rate))));last=min(len(audio),round(at(nodes,center+.20*rate)))
                    result=dict(source=source,time=time,label=label,generation=index+1,direction=f"{float(plan['from']):.2f}->{float(plan['target']):.2f}",
                        input_center=center,first_output=first,last_output=last,whole=whole,**metrics(audio[first:last],rate))
                    results.append(result)
                target=OUT/'audition'/f'{source}_t{str(time).replace(".","p")}_{"current" if label=="C" else "L1"}.wav'
                wav(target,audio*.5,rate)
                manifest.append(dict(file=str(target.relative_to(ROOT)),raw=str(Path(row['path'])/'reference.wav'),gain=.5,peak_after_gain=whole['peak']*.5))
    (OUT/'acoustics.json').write_text(json.dumps(results,indent=2,allow_nan=False))
    (OUT/'audition/manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Input-matched diagnostic regions',len(results),'audition files',len(manifest))
if __name__=='__main__':main()
