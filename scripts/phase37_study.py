#!/usr/bin/env python3
"""Reproducible Phase 37 offline A/B study; private WAVs stay Git-ignored."""
import argparse
import csv
import hashlib
import math
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from phase32_study import read,wav
from phase31_synthetic_metrics import clicks,sine
from phase34_metrics import geometry
from phase33_analysis import stereo_band

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase37'
SPEEDS=('1.00','1.10','1.25','1.50','1.75','2.00')
SOURCES={**{name:ROOT/'results/phase31/input'/f'{name}.wav'
            for name in ('mix','vocal','bass','drums','guitar','click','sine')},
         **{name:ROOT/'results/phase32/input'/f'{name}.wav'
            for name in ('harmonic','decay_noise','pink_burst','white_burst')}}

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1<<20),b''):
            digest.update(block)
    return digest.hexdigest()

def render(case):
    name,speed,mode=case
    source=SOURCES[name]
    target=OUT/'raw'/f'{name}_{mode}_{speed.replace(".","")}.wav'
    command=(ROOT/'build/phase37_render',source,target,speed,mode)
    result=subprocess.run(tuple(map(str,command)),capture_output=True,text=True,timeout=300)
    if result.returncode:
        raise RuntimeError(f'{case}: {result.stderr}')
    data=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    (OUT/'logs'/f'{name}_{mode}_{speed.replace(".","")}.log').write_text(result.stdout)
    rate,audio=read(target)
    _,input_audio=read(source)
    expected=round(len(input_audio)/float(speed))
    if len(audio)!=expected or not np.isfinite(audio).all():
        raise RuntimeError(f'{case}: invalid frames or NaN/Inf')
    baseline=ROOT/'results/phase31/raw'/f'{name}_A_{speed.replace(".","")}.wav'
    # Phase 31 at 1.00 takes a unity bypass. This study keeps the PV path.
    frozen_match=(target.read_bytes()==baseline.read_bytes()) if (
        mode=='A' and speed!='1.00' and baseline.exists()) else ''
    if frozen_match is False:raise RuntimeError(f'{case}: A differs from Phase 31')
    row=dict(data)
    row.update(source=name,speed=speed,mode=mode,input_sha=sha(source),
               output_sha=sha(target),output_path=str(target.relative_to(ROOT)),
               frozen_A_match=frozen_match,rate=rate,channels=audio.shape[1],
               frames=len(audio),peak=float(np.max(np.abs(audio))))
    return row

def render_all():
    (OUT/'raw').mkdir(parents=True,exist_ok=True)
    (OUT/'logs').mkdir(parents=True,exist_ok=True)
    cases=[(name,speed,mode) for name in SOURCES for speed in SPEEDS for mode in 'AB']
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows=list(pool.map(render,cases))
    with (OUT/'renders.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    print(f'{len(rows)} Phase 37 raw WAVs verified')

def peak_region(audio,rate,expected):
    mono=np.mean(audio,axis=1)
    left=max(0,int(expected-rate*.05));right=min(len(mono),int(expected+rate*.05))
    if right<=left:return (0.,0.,0.,0.,0.)
    local=mono[left:right]
    index=left+int(np.argmax(np.abs(local)))
    peak=float(abs(mono[index]))
    half=peak*.5
    a=b=index
    while a>left and abs(mono[a-1])>=half:a-=1
    while b+1<right and abs(mono[b+1])>=half:b+=1
    pre=mono[max(0,index-int(.04*rate)):max(0,index-int(.005*rate))]
    before=float(np.sqrt(np.mean(pre**2))) if len(pre) else 0.
    secondary=float(np.max(np.abs(local[np.abs(np.arange(left,right)-index)>int(.005*rate)]),
                           initial=0))
    return (peak,(index-expected)*1000/rate,(b-a+1)*1000/rate,
            before,secondary/max(peak,1e-9))

def spectrum_peak(audio,rate):
    x=np.mean(audio,axis=1)
    begin=min(len(x)//4,rate)
    x=x[begin:len(x)-begin]
    if len(x)<4096:return 0.
    n=min(131072,1<<(len(x).bit_length()-1))
    spectrum=np.abs(np.fft.rfft(x[:n]*np.hanning(n)))
    k=int(np.argmax(spectrum[1:]))+1
    alpha,beta,gamma=np.log(np.maximum(spectrum[k-1:k+2],1e-20))
    shift=.5*(alpha-gamma)/(alpha-2*beta+gamma) if alpha-2*beta+gamma else 0
    return float((k+np.clip(shift,-1,1))*rate/n)

def rms(audio):return float(np.sqrt(np.mean(np.square(audio,dtype=np.float64))))

def measure():
    rows=[]
    for row in csv.DictReader((OUT/'renders.csv').open()):
        source=row['source'];speed=float(row['speed'])
        rate,audio=read(ROOT/row['output_path'])
        values=dict(source=source,speed=row['speed'],mode=row['mode'],
            finite=bool(np.isfinite(audio).all()),peak=float(np.max(np.abs(audio))),
            rms=rms(audio),exact_length=len(audio)==round(
                len(read(SOURCES[source])[1])/speed))
        if source=='click':values.update(clicks(ROOT/row['output_path'],speed))
        if source=='sine':values.update(sine(ROOT/row['output_path']))
        if source=='harmonic':values['dominant_hz']=spectrum_peak(audio,rate)
        if source in ('decay_noise','white_burst','pink_burst'):
            before=[];after=[];onset_peak=[]
            mono=np.mean(audio,axis=1)
            for event_time in (.6,2.5,4.4):
                center=round(event_time*rate/speed)
                pre=mono[max(0,center-round(.04*rate)):max(0,center-round(.005*rate))]
                first=mono[center:min(len(mono),center+round(.02*rate))]
                onset=mono[center:min(len(mono),center+round(.05*rate))]
                before.append(rms(pre) if len(pre) else 0.)
                after.append(rms(first) if len(first) else 0.)
                onset_peak.append(float(np.max(np.abs(onset),initial=0)))
            values.update(pre_echo_rms_mean=float(np.mean(before)),
                          first_20ms_rms_mean=float(np.mean(after)),
                          onset_peak_min=min(onset_peak))
        if source in ('drums','mix'):
            expected=round(3.865*rate/speed)
            peak,error,width,pre,secondary=peak_region(audio,rate,expected)
            values.update(attack_peak=peak,attack_offset_ms=error,
                attack_width_ms=width,pre_echo_rms=pre,
                secondary_to_primary=secondary)
        if audio.shape[1]==2:
            l=audio[:,0].astype(np.float64);r=audio[:,1].astype(np.float64)
            mid=(l+r)*.5;side=(l-r)*.5
            values['side_mid']=rms(side)/max(rms(mid),1e-9)
            values['lr_correlation']=float(np.corrcoef(l,r)[0,1]) if len(l)>1 else 0.
            values['ild_db']=20*math.log10(max(rms(l),1e-9)/max(rms(r),1e-9))
            part=audio[len(audio)//4:min(len(audio),len(audio)//4+rate*2)]
            if len(part)>=4096:
                ipd,_,bins=stereo_band(part,rate,slice(1,None))
                values['ipd_rms_rad']=ipd
                values['ipd_valid_bins']=bins
        rows.append(values)
    fields=list(dict.fromkeys(key for row in rows for key in row))
    with (OUT/'metrics.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=fields,lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    print(f'{len(rows)} metric rows')

def audition():
    (OUT/'audition').mkdir(exist_ok=True)
    rows=[]
    for source in ('mix','drums','vocal','guitar','bass','click'):
        for speed in ('1.50','2.00'):
            tag=f'{source}_{speed.replace(".","")}'
            # Pseudorandom but reproducible label assignment; key remains
            # separate from the WAV filenames so the player sees only A/B.
            modes='AB' if int(hashlib.sha256(tag.encode()).hexdigest(),16)%2 else 'BA'
            for label,mode in zip('AB',modes):
                src=OUT/'raw'/f'{source}_{mode}_{speed.replace(".","")}.wav'
                rate,audio=read(src)
                target=OUT/'audition'/f'{tag}_{label}.wav'
                scaled=audio*.45
                if np.max(np.abs(scaled))>=1:
                    raise RuntimeError(f'Fixed audition gain clips: {src}')
                wav(target,scaled,rate)
                rows.append(dict(source=source,speed=speed,blind_label=label,
                    mode=mode,gain=.45,sha256=sha(target),
                    path=str(target.relative_to(ROOT))))
    with (OUT/'blind_key.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    print(f'{len(rows)} blind audition WAVs at one fixed gain')

def map_geometry():
    rows=[]
    for source,path in SOURCES.items():
        _,input_audio=read(path)
        for speed in SPEEDS:
            for mode in 'AB':
                result=subprocess.run((str(ROOT/'build/phase37_render'),str(path),'-',
                    speed,mode),capture_output=True,text=True,timeout=90)
                if result.returncode:raise RuntimeError(result.stderr)
                points=np.array([[int(item) for item in line.split(',')]
                    for line in result.stdout.splitlines()[1:]],dtype=np.int64)
                x,y=points[:,0],points[:,1]
                for fft,hop in ((8192,2048),(4096,1024),(1024,256)):
                    positions=np.arange(0,len(input_audio)+fft//2+hop,hop,dtype=np.int64)
                    mapped=np.interp(positions,x,y)
                    beyond=positions>x[-1]
                    mapped[beyond]=y[-1]+(positions[beyond]-x[-1])*(y[-1]-y[-2])/(x[-1]-x[-2])
                    starts=np.floor(mapped+.5).astype(np.int64)
                    frames,minimum,maximum,nonpositive,outside,weight=geometry(
                        [{'outputSample':p} for p in starts],fft)
                    if nonpositive or outside:
                        raise RuntimeError(f'{source} {speed} {mode}: unsafe {fft} hop')
                    rows.append(dict(source=source,speed=speed,mode=mode,fft=fft,
                        frames=frames,min_synthesis_hop=minimum,max_synthesis_hop=maximum,
                        nonpositive_hops=nonpositive,outside_window_hops=outside,
                        worst_hann2_weight=weight))
    with (OUT/'geometry.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    print(f'{len(rows)} safe resolution geometry rows')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('task',choices=('render','metrics','audition','geometry'))
    task=parser.parse_args().task
    {'render':render_all,'metrics':measure,'audition':audition,
     'geometry':map_geometry}[task]()
