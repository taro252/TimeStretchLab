#!/usr/bin/env python3
"""Compare isolated attack/decay controls with their natural input envelopes."""
import csv
from pathlib import Path

import numpy as np

from phase32_metrics import envelope, rms, stable_tone
from phase32_study import read
from phase33_analysis import envelope_error, stft

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase33'


def flatness(audio, rate):
    spectrum=np.abs(stft(np.mean(audio,axis=1),rate))**2
    power=np.mean(spectrum,axis=0)[1:]
    return float(np.exp(np.mean(np.log(np.maximum(power,1e-15)))) /
                 np.mean(power))


def main():
    rows=[]
    for source in ('pink_decay','single_drum'):
        rate,original=read(OUT/'input'/f'{source}.wav')
        for mode in ('baseline','no_lock','no_reset','no_propagation'):
            key=f'{source}_{mode}_025'
            _,audio=read(OUT/'synthetic'/f'{key}.wav')
            with (OUT/'trace'/key/'mid.csv').open(newline='') as stream:
                trace=list(csv.DictReader(stream))
            tail_region=(0.92,1.28)
            error,corr,gain,modulation=envelope_error(original,audio,rate,trace,*tail_region)
            input_map=np.array([float(r['inputSample']) for r in trace])
            output_map=np.array([float(r['outputSample']) for r in trace])
            onset=np.interp(0.8*rate,input_map,output_map)
            center=round(onset)
            mono=np.mean(audio,axis=1)
            lo=max(0,center-round(.03*rate))
            hi=min(len(mono),center+round(.08*rate))
            peak_index=lo+np.argmax(np.abs(mono[lo:hi]))
            peak=float(abs(mono[peak_index]))
            pre=mono[max(0,center-round(.02*rate)):center]
            post=mono[center:center+round(.02*rate)]
            a,b=round(tail_region[0]/.25*rate),round(tail_region[1]/.25*rate)
            itail=original[round(tail_region[0]*rate):round(tail_region[1]*rate)]
            otail=audio[a:b]
            times,env=envelope(otail,rate,40)
            slope=float(np.polyfit(times,20*np.log10(np.maximum(env,1e-10)),1)[0])
            rows.append(dict(source=source,mode=mode,speed=.25,
                             expected_decay_slope_db_s=-8.685889638*.25/.35 if source=='pink_decay' else '',
                             observed_decay_slope_db_s=slope,
                             tail_envelope_error_db=error,
                             tail_envelope_correlation=corr,
                             gain_offset_db=gain,
                             envelope_error_modulation_hz=modulation,
                             input_tail_spectral_flatness=flatness(itail,rate),
                             output_tail_spectral_flatness=flatness(otail,rate),
                             attack_peak=peak,
                             attack_position_error_ms=1000*(peak_index-onset)/rate,
                             pre20ms_rms=rms(pre),first20ms_rms=rms(post)))
    with (OUT/'synthetic_diagnostics.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    for r in rows:
        print(r['source'],r['mode'],'tailerr',round(r['tail_envelope_error_db'],3),
              'corr',round(r['tail_envelope_correlation'],3))


if __name__=='__main__':main()
