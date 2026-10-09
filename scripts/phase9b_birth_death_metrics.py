#!/usr/bin/env python3
"""Measure local changes around dense track birth/death examples."""
import csv
import numpy as np
from phase9b_components import OUT,read,save

def main():
    with (OUT/'birth_death_clips.csv').open() as file:clips=list(csv.DictReader(file))
    rows=[]
    for clip in clips:
        for component in ('sinusoidal','residual','combined'):
            signal=read(clip[component]).astype(np.float64)
            center=len(signal)//2
            before=signal[center-1200:center]
            after=signal[center:center+1200]
            rms1=np.sqrt(np.mean(before*before))
            rms2=np.sqrt(np.mean(after*after))
            derivative=np.abs(np.diff(signal))
            rows.append({'name':clip['name'],'event':clip['event'],
                'output_second':clip['output_second'],
                'events_within_10ms':clip['events_within_10ms'],
                'component':component,'rms_jump_db':20*np.log10((rms2+1e-9)/(rms1+1e-9)),
                'nearby_max_sample_derivative':float(np.max(derivative[center-48:center+48])),
                'clip_derivative_p99':float(np.percentile(derivative,99))})
    save(OUT/'birth_death_metrics.csv',rows)

if __name__=='__main__':main()
