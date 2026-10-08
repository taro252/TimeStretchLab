#!/usr/bin/env python3
"""Phase 9A numerical diagnostics. Listening conclusions are deliberately separate."""
import csv
import pathlib
import subprocess
import numpy as np
from phase6_artificial import metrics as harmonic_metrics
from phase6_analyze import save

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase9a'
RATE=48000

def audio(path):
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-'],
                       capture_output=True,check=True).stdout
    return np.frombuffer(raw,dtype='<f4').astype(np.float64)

def spectra(x,size=4096,hop=1024):
    starts=np.arange(0,len(x)-size+1,hop)
    window=np.hanning(size)
    return np.asarray([np.fft.rfft(x[s:s+size]*window) for s in starts])

def flatness(x):
    spec=np.abs(spectra(x))**2
    band=(np.fft.rfftfreq(4096,1/RATE)>=80)&(
        np.fft.rfftfreq(4096,1/RATE)<=8000)
    spec=spec[:,band]
    active=np.sum(spec,axis=1)>1e-7
    spec=spec[active]
    if len(spec)==0:return 0.0
    return float(np.median(np.exp(np.mean(np.log(spec+1e-14),axis=1))/
                           (np.mean(spec,axis=1)+1e-14)))

def concentration(x):
    spectrum=np.abs(spectra(x))**2
    frequencies=np.fft.rfftfreq(4096,1/RATE)
    spectrum=spectrum[:,(frequencies>=80)&(frequencies<=8000)]
    active=np.sum(spectrum,axis=1)>1e-7
    if not np.any(active):return 0.0
    spectrum=spectrum[active]
    top=np.partition(spectrum,-10,axis=1)[:,-10:]
    return float(np.median(np.sum(top,axis=1)/np.sum(spectrum,axis=1)))

def rms(x):return float(np.sqrt(np.mean(x*x))) if len(x) else 0.0

def vocal_modulation(reference,alternative):
    size,hop=8192,2048
    starts=np.arange(RATE,min(len(reference),len(alternative))-RATE-size,hop)
    if len(starts)<3:return []
    window=np.hanning(size)
    spectra=[];levels=[]
    for signal in (reference,alternative):
        frames=np.asarray([signal[s:s+size]*window for s in starts])
        spectra.append(np.fft.rfft(frames,axis=1))
        levels.append(np.sqrt(np.mean(frames*frames,axis=1)))
    frequencies=np.fft.rfftfreq(size,1/RATE)
    low=np.flatnonzero((frequencies>=90)&(frequencies<=400))
    referenceMagnitude=np.abs(spectra[0])
    f0=low[np.argmax(referenceMagnitude[:,low],axis=1)]
    peak=referenceMagnitude[np.arange(len(f0)),f0]
    voiced=(levels[0]>0.2*np.percentile(levels[0],95)) & (
        peak>3*np.mean(referenceMagnitude[:,low],axis=1))
    adjacent=voiced[1:] & voiced[:-1]
    harmonicBins=np.minimum(f0[:,None]*np.arange(1,13)[None,:],size//2)
    base=np.take_along_axis(referenceMagnitude,harmonicBins,axis=1)
    active=base>0.03*np.max(base,axis=1,keepdims=True)
    common=adjacent[:,None]&active[1:]&active[:-1]
    result=[]
    for label,spectrum,level in zip(('phase53','phase9a'),spectra,levels):
        magnitude=np.abs(spectrum)
        harmonics=np.take_along_axis(magnitude,harmonicBins,axis=1)
        normalized=harmonics/np.maximum(np.sum(harmonics,axis=1,keepdims=True),1e-12)
        harmonicChange=20/np.log(10)*np.diff(np.log(np.maximum(harmonics,1e-9)),axis=0)
        amplitudeChange=np.abs(20*np.log10(np.maximum(level[1:],1e-12)/
                                           np.maximum(level[:-1],1e-12)))
        centroidBand=(frequencies>=100)&(frequencies<=6000)
        centroid=np.sum(magnitude[:,centroidBand]*frequencies[centroidBand],axis=1)/(
            np.sum(magnitude[:,centroidBand],axis=1)+1e-12)
        result.append({'mode':label,'voiced_frame_count':int(np.sum(voiced)),
            'amplitude_change_median_db':float(np.median(amplitudeChange[adjacent])) if np.any(adjacent) else 0,
            'harmonic_change_rms_db':float(np.sqrt(np.mean(harmonicChange[common]**2))) if np.any(common) else 0,
            'centroid_change_median_hz':float(np.median(np.abs(np.diff(centroid))[adjacent])) if np.any(adjacent) else 0,
            'envelope_change_median':float(np.median(np.linalg.norm(np.diff(normalized,axis=0),axis=1)[adjacent])) if np.any(adjacent) else 0})
    return result

def main():
    with (OUT/'unity_manifest.csv').open() as file:unity=list(csv.DictReader(file))
    unity_metrics=[];residual_metrics=[]
    for row in unity:
        x=audio(row['input']);y=audio(row['output']);difference=y-x
        spectral_error=float(np.linalg.norm(np.abs(np.fft.rfft(y))-
                np.abs(np.fft.rfft(x)))/(np.linalg.norm(np.abs(np.fft.rfft(x)))+1e-12))
        unity_metrics.append({'name':row['name'],'frames':len(x),
            'rms_error':rms(difference),'max_abs_error':float(np.max(np.abs(difference))),
            'relative_spectral_error':spectral_error,
            'average_active_tracks':row['averageActiveTracks'],
            'median_track_lifetime_s':row['medianLifetimeSeconds'],
            'births_per_second':row['birthsPerSecond'],
            'deaths_per_second':row['deathsPerSecond'],
            'sinusoidal_energy_over_input':row['explainedEnergyRatio'],
            'residual_rms_over_input':row['residualInputRmsRatio']})
        diagnostic=OUT/'diagnostics'/f"{row['name']}_100"
        if diagnostic.exists():
            sinusoidal=audio(diagnostic/'sinusoidal_input.wav')
            residual=audio(diagnostic/'residual_input.wav')
            residual_metrics.append({'name':row['name'],
                'residual_over_input_rms':rms(residual)/(rms(x)+1e-12),
                'input_flatness':flatness(x),'sinusoidal_flatness':flatness(sinusoidal),
                'residual_flatness':flatness(residual),
                'input_top10_power_fraction':concentration(x),
                'residual_top10_power_fraction':concentration(residual)})
            arrays=[np.mean(np.abs(spectra(z)),axis=0) for z in (x,sinusoidal,residual)]
            with (diagnostic/'spectrum.csv').open('w',newline='') as file:
                writer=csv.writer(file,lineterminator='\n')
                writer.writerow(('frequencyHz','inputMagnitude','sinusoidalMagnitude','residualMagnitude'))
                for k,freq in enumerate(np.fft.rfftfreq(4096,1/RATE)):
                    writer.writerow((freq,*[a[k] for a in arrays]))
        print('unity',row['name'],flush=True)
    save(OUT/'unity_metrics.csv',unity_metrics)
    save(OUT/'residual_metrics.csv',residual_metrics)
    with (OUT/'manifest.csv').open() as file:manifest=list(csv.DictReader(file))
    outputs=[];synthetic=[];vocal=[]
    for row in manifest:
        source=audio(row['input'])
        expected=round(len(source)/float(row['speed']))
        for mode,path in (('phase53',row['phase53']),('phase9a',row['phase9a'])):
            x=audio(path)
            if len(x)!=expected or not np.isfinite(x).all():
                raise RuntimeError(f"Duration/finite failure: {path}")
            outputs.append({'name':row['name'],'speed':row['speed'],'mode':mode,
                'frames':len(x),'duration_error_samples':len(x)-expected,
                'rms':rms(x),'peak':float(np.max(np.abs(x))),
                'output_over_input_rms':rms(x)/(rms(source)+1e-12),
                'spectral_flatness':flatness(x),'top10_power_fraction':concentration(x),
                'processing_seconds':row['processingSeconds'] if mode=='phase9a' else row['phase53CpuSeconds'],
                'peak_rss_bytes':row['peakRSSBytes'] if mode=='phase9a' else row['phase53PeakRssBytes']})
            if row['name'] in ('pure_vowel','breathy_vowel'):
                synthetic.append({'name':row['name'],'speed':row['speed'],'mode':mode,
                                  **harmonic_metrics(x,165,19)})
        if row['name'].startswith(('female','male')):
            for detail in vocal_modulation(audio(row['phase53']),audio(row['phase9a'])):
                vocal.append({'name':row['name'],'speed':row['speed'],**detail})
        print(row['name'],row['speed'],flush=True)
    save(OUT/'output_metrics.csv',outputs)
    save(OUT/'synthetic_metrics.csv',synthetic)
    save(OUT/'vocal_modulation.csv',vocal)

if __name__=='__main__':main()
