#!/usr/bin/env python3
"""Measure tonal leakage in input and stretched residual components."""
import csv
import pathlib
import subprocess
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase9b'
RATE=48000
SIZE=8192
HOP=2048
FREQUENCIES=np.fft.rfftfreq(SIZE,1/RATE)
BAND=(FREQUENCIES>=80)&(FREQUENCIES<=8000)

def audio(path):
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-'],
                       capture_output=True,check=True).stdout
    return np.frombuffer(raw,dtype='<f4').astype(np.float64)

def frames(signal):
    centers=np.arange(SIZE//2,len(signal)-SIZE//2+1,HOP)
    window=np.hanning(SIZE)
    spectrum=np.asarray([np.fft.rfft(signal[c-SIZE//2:c+SIZE//2]*window)
                         for c in centers])
    return centers,np.abs(spectrum)**2

def estimate_f0(centers,power):
    candidates=np.arange(80,401,2,dtype=float)
    scores=np.zeros((len(power),len(candidates)))
    for harmonic in range(1,13):
        bins=np.rint(candidates*harmonic*SIZE/RATE).astype(int)
        valid=bins<len(FREQUENCIES)-2
        bins=np.clip(bins,1,len(FREQUENCIES)-2)
        neighboring=np.maximum.reduce((power[:,bins-1],power[:,bins],power[:,bins+1]))
        scores+=neighboring*valid/harmonic
    return candidates[np.argmax(scores,axis=1)]

def metric(signal,source_centers,source_f0,ratio,name,source_rms):
    centers,power=frames(signal)
    if name.startswith(('pure_vowel','breathy_vowel')):
        source_t=centers/RATE/ratio
        f0=165*np.exp2(16*np.sin(2*np.pi*5.5*source_t)/1200)
        method='known synthetic F0'
    else:
        f0=np.interp(centers/ratio,source_centers,source_f0)
        method='harmonic-comb input estimate'
    harmonicEnergy=0;totalEnergy=0;flatness=[];top10=[]
    for spectrum,frequency in zip(power,f0):
        band=spectrum[BAND]
        total=float(np.sum(band))
        if total<1e-9:continue
        mask=np.zeros(len(spectrum),dtype=bool)
        for harmonic in range(1,int(8000/frequency)+1):
            center=harmonic*frequency
            lo=max(1,int(np.floor((center-12)*SIZE/RATE)))
            hi=min(len(mask),int(np.ceil((center+12)*SIZE/RATE))+1)
            mask[lo:hi]=True
        harmonicEnergy+=float(np.sum(spectrum[mask&BAND]));totalEnergy+=total
        flatness.append(float(np.exp(np.mean(np.log(band+1e-14)))/
                              (np.mean(band)+1e-14)))
        top10.append(float(np.sum(np.partition(band,-10)[-10:])/total))
    return {'f0_method':method,'f0_median_hz':float(np.median(f0)),
            'valid_frames':len(flatness),
            'harmonic_energy_ratio':harmonicEnergy/totalEnergy if totalEnergy else 0,
            'spectral_flatness_median':float(np.median(flatness)) if flatness else 0,
            'top10_power_ratio_median':float(np.median(top10)) if top10 else 0,
            'rms':float(np.sqrt(np.mean(signal*signal))),
            'rms_over_source':float(np.sqrt(np.mean(signal*signal))/(source_rms+1e-12)),
            'peak':float(np.max(np.abs(signal)))}

def main():
    with (OUT/'component_manifest.csv').open() as file:manifest=list(csv.DictReader(file))
    rows=[];balance=[]
    for item in manifest:
        name=item['name'];speed=float(item['speed']);ratio=1/speed
        source=audio(item['input']);sourceRms=float(np.sqrt(np.mean(source*source)))
        centers,power=frames(source)
        f0=estimate_f0(centers,power) if not name.startswith((
            'pure_vowel','breathy_vowel')) else np.zeros(len(centers))
        variants=[('input_residual',item['residual_input'],1),
                  ('random_stretched',item['random_residual'],ratio)]
        if item.get('analysis_phase_residual'):
            variants.append(('analysis_phase_stretched',item['analysis_phase_residual'],ratio))
        for variant,path,variantRatio in variants:
            signal=audio(path)
            rows.append({'name':name,'speed':speed,'variant':variant,'file':path,
                         **metric(signal,centers,f0,variantRatio,name,sourceRms)})
        sine=audio(item['sinusoidal_output'])
        randomResidual=audio(item['random_residual'])
        combined=audio(item['random_combined'])
        sineRms=float(np.sqrt(np.mean(sine*sine)))
        residualRms=float(np.sqrt(np.mean(randomResidual*randomResidual)))
        balance.append({'name':name,'speed':speed,'sinusoidal_rms':sineRms,
            'random_residual_rms':residualRms,
            'residual_over_sinusoidal_rms':residualRms/(sineRms+1e-12),
            'combined_rms':float(np.sqrt(np.mean(combined*combined)))})
        print(name,speed,flush=True)
    with (OUT/'residual_tonality.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    with (OUT/'component_balance.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=balance[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(balance)

if __name__=='__main__':main()
