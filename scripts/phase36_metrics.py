#!/usr/bin/env python3
"""Read-only attack, tail, pitch and band diagnostics on Phase 36 raw PCM."""
import csv
import subprocess
from pathlib import Path
import numpy as np
from phase32_study import read
from phase34_metrics import attack,spectral_variation,geometry
from phase33_analysis import stereo_band

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase36'
SOURCES={'mix':'phase31','drums':'phase31','vocal':'phase31',
         'bass':'phase31','guitar':'phase31','click':'phase31',
         'harmonic':'phase32','decay_noise':'phase32'}

def map_for(row):
    name=f"{row['source']}_{row['initial'].replace('.','')}_{row['target'].replace('.','')}"
    source=ROOT/f"results/{SOURCES[row['source']]}/input/{row['source']}.wav"
    plan=OUT/'trace'/f'{name}.csv'
    result=subprocess.run((str(ROOT/'build/phase36_reference'),str(source),'-',
                           row['initial'],str(plan)),capture_output=True,text=True,timeout=30)
    if result.returncode:raise RuntimeError(result.stderr)
    mapping=list(csv.DictReader(result.stdout.splitlines()))
    return np.array([float(x['input_sample']) for x in mapping]),\
           np.array([float(x['output_sample']) for x in mapping])

def modulation(audio,rate):
    mono=np.mean(audio,axis=1)
    size=4096;hop=512
    if len(mono)<size:return (0.0,0.0,0.0)
    frames=np.lib.stride_tricks.sliding_window_view(mono,size)[::hop]
    power=np.abs(np.fft.rfft(frames*np.hanning(size),axis=1))**2
    hz=np.fft.rfftfreq(size,1/rate)
    values=[]
    for begin,end in ((0,250),(250,3500),(3500,rate/2)):
        envelope=np.sqrt(np.mean(power[:,(hz>=begin)&(hz<end)],axis=1))
        db=20*np.log10(np.maximum(envelope,1e-9))
        values.append(float(np.std(db-np.median(db))))
    return values

def main():
    rows=[]
    geometry_rows=[]
    with (OUT/'transitions.csv').open(newline='') as file:
        conditions=list(csv.DictReader(file))
    for condition in conditions:
        name=f"{condition['source']}_{condition['initial'].replace('.','')}_{condition['target'].replace('.','')}"
        rate,audio=read(OUT/'raw'/f'{name}.wav')
        x,y=map_for(condition)
        _,input_audio=read(ROOT/f"results/{SOURCES[condition['source']]}/input/"
                           f"{condition['source']}.wav")
        density_input=int(condition['applied_frame'])*1024
        for fft,hop in ((8192,2048),(4096,1024),(1024,256)):
            positions=[];position=0
            while True:
                positions.append(position)
                if position>=len(input_audio)+fft//2:break
                half=float(condition['initial'])<0.50
                if position>=density_input:half=float(condition['target'])<0.50
                position+=hop//2 if half else hop
            mapped=np.interp(positions,x,y)
            beyond=np.asarray(positions)>x[-1]
            mapped[beyond]=y[-1]+(np.asarray(positions)[beyond]-x[-1])*\
                (y[-1]-y[-2])/(x[-1]-x[-2])
            starts=np.floor(mapped+.5).astype(np.int64)
            count,minimum,maximum,nonpositive,outside,weight=geometry(
                [{'outputSample':sample} for sample in starts],fft)
            geometry_rows.append(dict(source=condition['source'],
                initial=condition['initial'],target=condition['target'],
                fft=fft,frames=count,min_synthesis_hop=minimum,
                max_synthesis_hop=maximum,nonpositive_hops=nonpositive,
                outside_window_hops=outside,worst_hann2_weight=weight))
        at=int(condition['applied_output'])
        region=audio[max(0,at-rate//2):min(len(audio),at+rate//2)]
        low,mid,high=modulation(region,rate)
        ipd,ild,bins=stereo_band(region,rate,slice(1,None))
        row=dict(source=condition['source'],initial=condition['initial'],
                 target=condition['target'],low_envelope_std_db=low,
                 mid_envelope_std_db=mid,high_envelope_std_db=high,
                 ipd_rms_rad=ipd,ild_db=ild,stereo_valid_bins=bins,
                 spectral_variation=spectral_variation(region,rate,
                      float(condition['target'])))
        if condition['source']=='drums':
            at_attack=float(np.interp(3.865*rate,x,y))
            measured=attack(audio,rate,at_attack)
            row.update(drums_attack_peak=measured['peak'],
                       drums_attack_offset_ms=measured['peak_offset_ms'],
                       drums_attack_width_ms=measured['envelope_halfpower_width_ms'])
            a,b=np.interp(np.array([4.05,4.35])*rate,x,y).astype(int)
            tail=audio[max(0,a):min(len(audio),b)]
            row['drums_tail_spectral_variation']=spectral_variation(
                tail,rate,float(condition['target']))
        else:
            row.update(drums_attack_peak='',drums_attack_offset_ms='',
                       drums_attack_width_ms='',drums_tail_spectral_variation='')
        rows.append(row)
    with (OUT/'quality_metrics.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    with (OUT/'geometry.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=geometry_rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(geometry_rows)

if __name__=='__main__':main()
