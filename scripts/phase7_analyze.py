#!/usr/bin/env python3
"""Paired Phase 7 vocal, stereo, pitch, and resync-boundary measurements."""
import csv
import pathlib
import subprocess
import numpy as np
from phase52_analyze import fields,run
from phase6_analyze import paired_vocal,save

ROOT=pathlib.Path(__file__).resolve().parent.parent
OUT=ROOT/'results/phase7'
BUILD=ROOT/'build'

def audio(path):
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-'],
                       check=True,capture_output=True).stdout
    return np.frombuffer(raw,dtype='<f4').reshape(-1,2).astype(np.float64)

def click_metrics(reference,alternative,diagnostics):
    a=audio(reference).mean(axis=1)
    b=audio(alternative).mean(axis=1)
    with open(diagnostics) as file:events=[row for row in csv.DictReader(file)
                                        if row['resyncApplied']=='1']
    positions=[int(row['outputSample'])-2048 for row in events]
    positions=[p for p in positions if p>2048 and p+2048<len(a)]
    if not positions:return {'resync_boundaries':0}
    window=np.hanning(1024)
    def measure(x):
        derivative=np.abs(np.diff(x))
        maxima=[];rmsJump=[];spectrumJump=[]
        for p in positions:
            maxima.append(float(np.max(derivative[p-480:p+1440])))
            before=x[p-1024:p]*window
            after=x[p:p+1024]*window
            rms1=np.sqrt(np.mean(x[p-960:p]**2))
            rms2=np.sqrt(np.mean(x[p:p+960]**2))
            rmsJump.append(float(abs(20*np.log10((rms2+1e-9)/(rms1+1e-9)))))
            u=np.abs(np.fft.rfft(before));v=np.abs(np.fft.rfft(after))
            spectrumJump.append(float(1-np.dot(u,v)/(np.linalg.norm(u)*np.linalg.norm(v)+1e-12)))
        return maxima,rmsJump,spectrumJump
    old=measure(a);new=measure(b)
    return {'resync_boundaries':len(positions),
            'derivative_p90_off':float(np.percentile(old[0],90)),
            'derivative_p90_on':float(np.percentile(new[0],90)),
            'derivative_max_off':float(np.max(old[0])),
            'derivative_max_on':float(np.max(new[0])),
            'rms_jump_median_db_off':float(np.median(old[1])),
            'rms_jump_median_db_on':float(np.median(new[1])),
            'spectral_discontinuity_median_off':float(np.median(old[2])),
            'spectral_discontinuity_median_on':float(np.median(new[2]))}

def main():
    with (OUT/'manifest.csv').open() as file:manifest=list(csv.DictReader(file))
    measurements=[]
    for row in manifest:
        basic=fields(run([str(BUILD/'wav_metrics'),row['output']]))
        spectral=fields(run([str(BUILD/'stereo_spectral_metrics'),
                             row['input'],row['output'],row['speed']]))
        for detail in ('low_bins_per_window','low_window_ipd_deg','low_window_weight'):
            spectral.pop(detail,None)
        pitch=fields(run([str(BUILD/'bass_pitch_metrics'),row['output']])) \
            if row['name']=='bass' else {}
        measurements.append({**row,**basic,**spectral,**pitch})
        print(row['name'],row['section'],row['speed'],row['mode'],flush=True)
    save(OUT/'metrics.csv',measurements)
    vocal=[];click=[]
    for on in (r for r in manifest if r['mode']=='on'):
        off=next(r for r in manifest if r['name']==on['name'] and
                 r['section']==on['section'] and r['speed']==on['speed'] and
                 r['mode']=='off')
        click.append({'name':on['name'],'section':on['section'],'speed':on['speed'],
                      **click_metrics(off['output'],on['output'],on['diagnostics'])})
        if on['name'] in ('female','male'):
            rate=int(next(m for m in measurements if m['name']==on['name'] and
                          m['section']==on['section'] and m['speed']==on['speed'])['rate'])
            for data in paired_vocal(off['output'],on['output'],rate):
                vocal.append({'name':on['name'],'section':on['section'],
                              'speed':on['speed'],'mode':data.pop('tracking'),**data})
    save(OUT/'vocal_modulation.csv',vocal)
    save(OUT/'click_metrics.csv',click)

if __name__=='__main__':main()
