#!/usr/bin/env python3
"""Collect comparable pitch, stereo, and high-band proxies for Phase 5.2."""
import csv
import pathlib
import subprocess
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
REAL = ROOT / 'results/phase52/real'
BUILD = ROOT / 'build'


def run(args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def fields(line):
    return dict(part.split('=', 1) for part in line.split() if '=' in part)


def highband(path, rate):
    raw = subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-'],
                         check=True,capture_output=True).stdout
    samples=np.frombuffer(raw,dtype='<f4').reshape(-1,2)
    mid=(samples[:,0].astype(np.float64)+samples[:,1])/2
    size, hop=2048, 512
    windows=np.lib.stride_tricks.sliding_window_view(mid,size)[::hop]
    spectrum=np.abs(np.fft.rfft(windows*np.hanning(size),axis=1))**2
    freq=np.fft.rfftfreq(size,1/rate)
    voice=np.sum(spectrum[:,(freq>=300)&(freq<3500)],axis=1)
    high=np.sum(spectrum[:,(freq>=3500)&(freq<12000)],axis=1)
    fraction=float(np.sum(high)/max(np.sum(voice+high),1e-30))
    envelope=np.sqrt(high)
    active=envelope>np.percentile(envelope,50)
    flux=np.maximum(0,np.diff(envelope))
    return {'highband_energy_fraction':fraction,
            'highband_flux_p95':float(np.percentile(flux,95)),
            'highband_active_median':float(np.median(envelope[active])) if np.any(active) else 0}


def main():
    with (REAL/'manifest.csv').open() as file:
        records=list(csv.DictReader(file))
    rows=[]
    for record in records:
        name,speed,mode=record['name'],record['speed'],record['mode']
        output=record['output']
        basic=fields(run([str(BUILD/'wav_metrics'),output]))
        spectral=fields(run([str(BUILD/'stereo_spectral_metrics'),record['input'],output,speed]))
        pitch=fields(run([str(BUILD/'bass_pitch_metrics'),output])) if name=='bass' else {}
        high=highband(output,int(basic['rate']))
        rows.append({**record,**basic,**spectral,**pitch,**high})
        print(name,speed,mode,'pitch',pitch.get('median_frequency_hz',''),
              'side/mid',basic.get('side_mid_ratio',''),
              'highband',high['highband_energy_fraction'],flush=True)
    with (REAL/'metrics.csv').open('w',newline='') as file:
        names=list(dict.fromkeys(key for row in rows for key in row))
        writer=csv.DictWriter(file,fieldnames=names,lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


if __name__=='__main__': main()
