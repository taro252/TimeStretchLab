#!/usr/bin/env python3
"""Phase 6 stereo, bass pitch, and paired vocal-modulation proxies."""
import csv
import pathlib
import subprocess
import numpy as np
from phase52_analyze import fields,run

ROOT=pathlib.Path(__file__).resolve().parent.parent
REAL=ROOT/'results/phase6/real'
BUILD=ROOT/'build'


def read_mid(path):
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-'],
                       check=True,capture_output=True).stdout
    stereo=np.frombuffer(raw,dtype='<f4').reshape(-1,2)
    return (stereo[:,0].astype(np.float64)+stereo[:,1])/2


def spectra(path,rate):
    signal=read_mid(path)
    size,hop=8192,2048
    starts=np.arange(rate,max(rate,len(signal)-rate-size),hop)
    window=np.hanning(size)
    result=np.empty((len(starts),size//2+1),dtype=np.complex64)
    rms=np.empty(len(starts))
    for i,start in enumerate(starts):
        frame=signal[start:start+size]
        rms[i]=np.sqrt(np.mean(frame*frame))
        result[i]=np.fft.rfft(frame*window)
    return result,rms


def paired_vocal(off,on,rate):
    reference,ref_rms=spectra(off,rate)
    alternative,on_rms=spectra(on,rate)
    size,hop=8192,2048
    freq=np.fft.rfftfreq(size,1/rate)
    low=np.flatnonzero((freq>=90)&(freq<=400))
    ref_mag=np.abs(reference)
    f0bin=low[np.argmax(ref_mag[:,low],axis=1)]
    peak=ref_mag[np.arange(len(ref_mag)),f0bin]
    local=np.mean(ref_mag[:,low],axis=1)
    voiced=(ref_rms>0.2*np.percentile(ref_rms,95)) & (peak>3*local)
    adjacent=voiced[1:]&voiced[:-1]
    harmonic_bins=np.minimum(f0bin[:,None]*np.arange(1,13)[None,:],size//2)
    base_harmonics=np.take_along_axis(ref_mag,harmonic_bins,axis=1)
    active_harmonics=base_harmonics>0.03*np.max(base_harmonics,axis=1,keepdims=True)
    result=[]
    for label,spectrum,rms in (('off',reference,ref_rms),('on',alternative,on_rms)):
        magnitude=np.abs(spectrum)
        harmonics=np.take_along_axis(magnitude,harmonic_bins,axis=1)
        normalized=harmonics/np.maximum(np.sum(harmonics,axis=1,keepdims=True),1e-12)
        amplitude_change=np.abs(20*np.log10(np.maximum(rms[1:],1e-12)/
                                            np.maximum(rms[:-1],1e-12)))
        harmonic_change=20/np.log(10)*np.diff(np.log(np.maximum(harmonics,1e-9)),axis=0)
        common=adjacent[:,None]&active_harmonics[1:]&active_harmonics[:-1]
        spectral_band=(freq>=100)&(freq<=6000)
        centroid=(np.sum(magnitude[:,spectral_band]*freq[spectral_band],axis=1)/
                  np.maximum(np.sum(magnitude[:,spectral_band],axis=1),1e-12))
        fundamental=np.take_along_axis(spectrum,f0bin[:,None],axis=1)[:,0]
        phase_change=(np.angle(fundamental[1:]/np.maximum(np.abs(fundamental[1:]),1e-12))-
                      np.angle(fundamental[:-1]/np.maximum(np.abs(fundamental[:-1]),1e-12))-
                      2*np.pi*f0bin[:-1]*hop/size)
        phase_residual=np.angle(np.exp(1j*phase_change))
        result.append({'tracking':label,'voiced_frames':int(np.sum(voiced)),
            'voiced_pairs':int(np.sum(adjacent)),
            'amplitude_frame_change_median_db':float(np.median(amplitude_change[adjacent])),
            'harmonic_frame_change_rms_db':float(np.sqrt(np.mean(harmonic_change[common]**2))),
            'spectral_centroid_frame_change_median_hz':float(
                np.median(np.abs(np.diff(centroid))[adjacent])),
            'spectral_envelope_frame_change_median':float(
                np.median(np.linalg.norm(np.diff(normalized,axis=0),axis=1)[adjacent])),
            'fundamental_phase_residual_rms_rad':float(np.sqrt(np.mean(phase_residual[adjacent]**2)))})
    return result


def save(path,rows):
    with path.open('w',newline='') as file:
        names=list(dict.fromkeys(key for row in rows for key in row))
        writer=csv.DictWriter(file,fieldnames=names,lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


def main():
    with (REAL/'manifest.csv').open() as file:
        manifest=list(csv.DictReader(file))
    metrics=[]
    for row in manifest:
        basic=fields(run([str(BUILD/'wav_metrics'),row['output']]))
        spectral=fields(run([str(BUILD/'stereo_spectral_metrics'),
                             row['input'],row['output'],row['speed']]))
        for detail in ('low_bins_per_window','low_window_ipd_deg','low_window_weight'):
            spectral.pop(detail)
        pitch=fields(run([str(BUILD/'bass_pitch_metrics'),row['output']])) \
            if row['name']=='bass' else {}
        metrics.append({**row,**basic,**spectral,**pitch})
        print(row['name'],row['speed'],row['tracking'],
              'side/mid',basic['side_mid_ratio'],flush=True)
    save(REAL/'metrics.csv',metrics)
    vocal=[]
    for name in ('female','male'):
        for speed in ('0.75','0.5'):
            pair=[row for row in manifest if row['name']==name and row['speed']==speed]
            off=next(row for row in pair if row['tracking']=='off')
            on=next(row for row in pair if row['tracking']=='on')
            rate=int(next(row for row in metrics if row['name']==name and
                          row['speed']==speed)['rate'])
            for data in paired_vocal(off['output'],on['output'],rate):
                vocal.append({'name':name,'speed':speed,**data})
                print(name,speed,data,flush=True)
    save(REAL/'vocal_modulation.csv',vocal)


if __name__=='__main__': main()
