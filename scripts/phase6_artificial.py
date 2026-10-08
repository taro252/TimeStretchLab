#!/usr/bin/env python3
"""Deterministic Phase 6 vibrato, harmonic, and synthetic-vocal measurements."""
import csv
import pathlib
import subprocess
import numpy as np

RATE=48000
ROOT=pathlib.Path(__file__).resolve().parent.parent
OUT=ROOT/'results/phase6/artificial'
OUT.mkdir(parents=True,exist_ok=True)


def run(command,data=None):
    return subprocess.run(command,input=data,check=True,capture_output=True).stdout


def write(path,signal):
    run(['ffmpeg','-v','error','-y','-f','f32le','-ar',str(RATE),'-ac','1',
         '-i','-','-c:a','pcm_f32le',str(path)],
        np.asarray(signal,dtype='<f4').tobytes())


def read(path):
    return np.frombuffer(run(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-']),
                         dtype='<f4').astype(np.float64)


def log_peak(spectrum,frequency,size,radius=3):
    center=round(frequency*size/RATE)
    lo=max(2,center-radius); hi=min(len(spectrum)-2,center+radius+1)
    k=lo+int(np.argmax(spectrum[lo:hi]))
    a,b,c=np.log(np.maximum(spectrum[k-1:k+2],1e-12))
    denominator=a-2*b+c
    offset=np.clip(0.5*(a-c)/denominator,-0.5,0.5) if denominator else 0
    return (k+offset)*RATE/size,spectrum[k]


def metrics(signal,f0,harmonics,moving=False):
    size,hop=8192,1024
    frequencies=[]; magnitudes=[]; centroids=[]; envelope=[]
    for start in range(RATE,len(signal)-RATE-size,hop):
        frame=signal[start:start+size]*np.hanning(size)
        spectrum=np.abs(np.fft.rfft(frame))
        frequency,magnitude=log_peak(spectrum,f0,size,12 if moving else 3)
        frequencies.append(frequency);magnitudes.append(magnitude)
        bands=[]
        for h in range(1,harmonics+1):
            center=round(f0*h*size/RATE)
            bands.append(np.max(spectrum[max(1,center-4):center+5]))
        bands=np.asarray(bands)
        normalized=bands/max(np.sum(bands),1e-12)
        envelope.append(normalized)
        centroids.append(np.sum(normalized*np.arange(1,harmonics+1)*f0))
    frequencies=np.asarray(frequencies); magnitudes=np.asarray(magnitudes)
    centroids=np.asarray(centroids); envelope=np.asarray(envelope)
    cents=1200*np.log2(frequencies/np.median(frequencies))
    harmonic_change=20/np.log(10)*np.diff(np.log(np.maximum(envelope,1e-9)),axis=0)
    return {'median_f0_hz':float(np.median(frequencies)),
            'vibrato_half_p95_p05_cents':float((np.percentile(cents,95)-np.percentile(cents,5))/2),
            'magnitude_mod_cv':float(np.std(magnitudes)/np.mean(magnitudes)),
            'harmonic_frame_change_rms_db':float(np.sqrt(np.mean(harmonic_change**2))),
            'spectral_centroid_frame_change_hz':float(np.median(np.abs(np.diff(centroids)))),
            'spectral_envelope_frame_change':float(np.median(np.linalg.norm(np.diff(envelope,axis=0),axis=1)))}


def signals():
    length=RATE*6
    t=np.arange(length)/RATE
    glide=0.25*np.sin(2*np.pi*(400*t+50*t*t/6))
    vib_cents=20*np.sin(2*np.pi*6*t)
    phase=np.cumsum(2*np.pi*440*np.exp2(vib_cents/1200)/RATE)
    vibrato=0.25*np.sin(phase)
    harmonic_cents=8*np.sin(2*np.pi*5*t)
    harmonic_phase=np.cumsum(2*np.pi*120*np.exp2(harmonic_cents/1200)/RATE)
    harmonic=sum(0.25*np.sin(h*harmonic_phase)/h for h in range(1,13))
    vocal_phase=np.cumsum(2*np.pi*170*np.exp2(12*np.sin(2*np.pi*5.5*t)/1200)/RATE)
    formant1=650+180*t/6
    formant2=1250-140*t/6
    vocal=np.zeros(length)
    for h in range(1,21):
        frequency=170*h
        envelope=(np.exp(-0.5*((frequency-formant1)/200)**2)+
                  0.65*np.exp(-0.5*((frequency-formant2)/260)**2)+0.1)/h
        vocal+=0.14*envelope*np.sin(h*vocal_phase)
    return {'moving_sine':(glide,450,1),'vibrato_sine':(vibrato,440,1),
            'harmonic_stack':(harmonic,120,12),'synthetic_vocal':(vocal,170,20)}


def main():
    rows=[]
    for name,(signal,f0,harmonics) in signals().items():
        source=OUT/f'{name}_input.wav'
        write(source,signal)
        for speed in ('0.75','0.50'):
            for tracking in ('off','on'):
                output=OUT/f'{name}_{speed.replace(".","")}_{tracking}.wav'
                line=run([str(ROOT/'build/timestretch'),str(source),str(output),
                          '--speed',speed,'--phase-locking','on',
                          '--partial-tracking',tracking,'--transient','on',
                          '--adaptive-time-map','on','--precise-anchoring','on',
                          '--quality','high','--chunked','on']).decode().strip()
                fields=dict(item.split('=',1) for item in line.split() if '=' in item)
                audio=read(output)
                row={'signal':name,'speed':speed,'tracking':tracking,
                     'finite':bool(np.all(np.isfinite(audio))),
                     'frames':len(audio),'rms':float(np.sqrt(np.mean(audio**2))),
                     'peak':float(np.max(np.abs(audio))),
                     'time_map_hash':fields['time_map_hash'],
                     'track_continuity_ratio':fields['track_continuity_ratio'],
                     'average_track_lifetime_frames':fields['average_track_lifetime_frames'],
                     'average_track_count':fields['average_track_count'],
                     'track_switches_per_second':fields['track_switches_per_second'],
                     'peak_phase_discontinuity_max_rad':fields['peak_phase_discontinuity_max_rad'],
                     'cpu_seconds':fields['cpu_seconds'],
                     **metrics(audio,f0,harmonics,name=='moving_sine')}
                rows.append(row)
                print(name,speed,tracking,row,flush=True)
    with (OUT/'metrics.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    for name in signals():
        for speed in ('0.75','0.50'):
            pair=[r for r in rows if r['signal']==name and r['speed']==speed]
            if len({r['frames'] for r in pair})!=1 or \
               len({r['time_map_hash'] for r in pair})!=1 or \
               not all(r['finite'] for r in pair):
                raise AssertionError(f'Synthetic output mismatch: {name} {speed}')


if __name__=='__main__': main()
