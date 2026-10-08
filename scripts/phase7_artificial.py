#!/usr/bin/env python3
"""PVSOLA synthetic vowel and non-tonal negative controls."""
import pathlib
import subprocess
import numpy as np
from phase7_ab import ROOT,fields,run
from phase7_analyze import click_metrics,audio
from phase6_analyze import paired_vocal,save
from phase6_artificial import metrics as sine_metrics

RATE=48000
OUT=ROOT/'results/phase7/artificial'

def write(path,stereo):
    raw=np.asarray(stereo,dtype='<f4').tobytes()
    subprocess.run(['ffmpeg','-v','error','-y','-f','f32le','-ar',str(RATE),
                    '-ac','2','-i','-','-c:a','pcm_f32le',str(path)],
                   input=raw,check=True,capture_output=True)

def signals():
    rng=np.random.default_rng(7)
    n=RATE*6;t=np.arange(n)/RATE
    phase=np.cumsum(2*np.pi*165*np.exp2(16*np.sin(2*np.pi*5.5*t)/1200)/RATE)
    vowel=np.zeros(n)
    for harmonic in range(1,20):
        f=165*harmonic
        formant=(np.exp(-0.5*((f-(650+100*t/6))/210)**2)+
                 0.7*np.exp(-0.5*((f-1300)/300)**2)+0.1)/harmonic
        vowel+=0.13*formant*np.sin(harmonic*phase)
    noise=rng.normal(0,0.045,n)
    snare=np.zeros(n)
    for at in (1,2.5,4):
        start=int(at*RATE);length=int(0.18*RATE)
        snare[start:start+length]+=0.22*rng.normal(size=length)*np.exp(-np.arange(length)/900)
    cymbal=np.zeros(n)
    for at in (0.8,3):
        start=int(at*RATE);length=int(1.2*RATE)
        raw=rng.normal(size=length)
        high=raw-np.convolve(raw,np.ones(9)/9,'same')
        cymbal[start:start+length]+=0.075*high*np.exp(-np.arange(length)/10000)
    distorted=np.tanh(5*(0.13*np.sin(2*np.pi*110*t)+
                          0.09*np.sin(2*np.pi*220*t))) * 0.25
    distorted*=0.7+0.3*np.sin(2*np.pi*2*t)**2
    decay=np.exp(-np.maximum(t-1,0)*1.2)*(t>=1)
    reverb=0.025*rng.normal(size=n)*decay
    vibrato_phase=np.cumsum(2*np.pi*440*np.exp2(20*np.sin(2*np.pi*6*t)/1200)/RATE)
    vibrato=0.22*np.sin(vibrato_phase)
    return {'vowel':vowel,'vibrato':vibrato,'noise':noise,'snare':snare,
            'cymbal':cymbal,'distorted':distorted,'reverb_tail':reverb}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[];click=[];modulation=[];vibrato=[]
    for name,signal in signals().items():
        input=OUT/f'{name}_input.wav'
        stereo=np.column_stack((signal,0.91*signal))
        write(input,stereo)
        for speed in ('0.75','0.50'):
            pair={}
            for mode in ('off','on'):
                output=OUT/f'{name}_{speed.replace(".","")}_{mode}.wav'
                diagnostic=OUT/'diagnostics'/f'{name}_{speed.replace(".","")}'
                cmd=[str(ROOT/'build/timestretch'),str(input),str(output),
                     '--speed',speed,'--phase-locking','on','--partial-tracking','off',
                     '--pvsola',mode,'--transient','on','--adaptive-time-map','on',
                     '--precise-anchoring','on','--stereo-coherence','on',
                     '--quality','high','--chunked','on']
                if mode=='on':cmd+=['--debug-csv',str(diagnostic)]
                detail=fields(run(cmd))
                rows.append({'signal':name,'speed':speed,'mode':mode,
                             'output':str(output),**detail})
                pair[mode]=output
                print(name,speed,mode,'applied',detail['resync_applied'],flush=True)
            click.append({'signal':name,'speed':speed,
                          **click_metrics(pair['off'],pair['on'],
                              diagnostic/'pvsola_resync.csv')})
            if name=='vowel':
                for detail in paired_vocal(pair['off'],pair['on'],RATE):
                    modulation.append({'signal':name,'speed':speed,**detail})
            if name=='vibrato':
                for mode in ('off','on'):
                    signal=audio(pair[mode]).mean(axis=1)
                    vibrato.append({'speed':speed,'mode':mode,
                                    **sine_metrics(signal,440,1)})
    save(OUT/'manifest.csv',rows)
    save(OUT/'click_metrics.csv',click)
    save(OUT/'vocal_modulation.csv',modulation)
    save(OUT/'vibrato_metrics.csv',vibrato)

if __name__=='__main__':main()
