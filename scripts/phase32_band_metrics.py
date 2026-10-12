#!/usr/bin/env python3
"""Frequency-band measurements of final output; separate from raw STFT stems."""
import csv
from pathlib import Path

import numpy as np

from phase32_regions import REGIONS
from phase32_study import OUT, read


def main():
    rows=[]
    for region,(source,begin,end) in REGIONS.items():
        for speed in (0.25,0.30):
            for mode in ('baseline','no_lock','no_reset','no_propagation'):
                path=OUT/'raw'/f'{source}_{mode}_{round(speed*100):03d}.wav'
                if not path.exists(): continue
                rate,audio=read(path)
                mono=np.mean(audio[round(begin/speed*rate):round(end/speed*rate)],axis=1)
                size,hop=4096,512
                if len(mono)<size+hop:continue
                frame=np.lib.stride_tricks.sliding_window_view(mono,size)[::hop]
                spec=np.fft.rfft(frame*np.hanning(size),axis=1)
                freq=np.fft.rfftfreq(size,1/rate)
                for band,select in (('low',freq<250),
                                    ('mid',(freq>=250)&(freq<3500)),
                                    ('high',freq>=3500)):
                    power=np.abs(spec[:,select])**2
                    band_rms=np.sqrt(np.mean(power,axis=1))
                    db=20*np.log10(np.maximum(band_rms,1e-9))
                    log=np.log(np.maximum(np.abs(spec[:,select]),1e-6))
                    diff=np.abs(np.diff(log,axis=0))
                    weights=np.minimum(np.abs(spec[1:,select]),np.abs(spec[:-1,select]))
                    rows.append(dict(region=region,source=source,speed=speed,
                                     mode=mode,band=band,
                                     band_energy=float(np.sum(power)),
                                     envelope_std_db=float(np.std(db)),
                                     adjacent_log_spectrum_variation=float(
                                         np.sum(diff*weights)/max(np.sum(weights),1e-12))))
    with (OUT/'frequency_bands.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


if __name__=='__main__':main()
