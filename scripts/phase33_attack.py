#!/usr/bin/env python3
"""Use exact Mid TimeMap to measure attack and pre-echo separately from tail."""
import csv
from pathlib import Path

import numpy as np

from phase32_metrics import envelope, rms
from phase32_study import read

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase33'


def onset_from_input(audio,rate,begin,end):
    times,env=envelope(audio,rate,10)
    candidate=np.flatnonzero((times[:-1]>=begin)&(times[:-1]<end))
    selected=candidate[np.argmax(np.diff(env)[candidate])]
    return float(times[selected])


def main():
    rows=[]
    for source,begin,end,where in (
            ('drums',3.77,4.02,ROOT/'results/phase31/input/drums.wav'),
            ('single_drum',0.75,0.9,OUT/'input/single_drum.wav')):
        rate,original=read(where)
        onset=onset_from_input(original,rate,begin,end)
        for mode in ('baseline','no_lock','no_reset','no_propagation'):
            key=f'{source}_{mode}_025'
            path=(ROOT/'results/phase32/raw'/f'{key}.wav' if source=='drums'
                  else OUT/'synthetic'/f'{key}.wav')
            _,audio=read(path)
            with (OUT/'trace'/key/'mid.csv').open(newline='') as stream:
                trace=list(csv.DictReader(stream))
            xin=np.array([float(r['inputSample']) for r in trace])
            yout=np.array([float(r['outputSample']) for r in trace])
            center=np.interp(onset*rate,xin,yout)
            center_frame=round(center)
            mono=np.mean(audio,axis=1)
            search_start=max(0,center_frame-round(.08*rate))
            search_end=min(len(mono),center_frame+round(.12*rate))
            pos=search_start+int(np.argmax(np.abs(mono[search_start:search_end])))
            peak=float(abs(mono[pos]))
            pre20=mono[max(0,center_frame-round(.02*rate)):center_frame]
            post20=mono[center_frame:center_frame+round(.02*rate)]
            pre50=mono[max(0,center_frame-round(.05*rate)):center_frame]
            first50=mono[center_frame:center_frame+round(.05*rate)]
            # 10 ms RMS envelope width at half power (rather than the width of
            # one oscillation of the drum waveform).
            times,env=envelope(audio[max(0,center_frame-round(.15*rate)):
                                     center_frame+round(.20*rate)],rate,10)
            top=int(np.argmax(env))
            half=env[top]/np.sqrt(2)
            left=top
            right=top
            while left>0 and env[left-1]>=half:left-=1
            while right+1<len(env) and env[right+1]>=half:right+=1
            width=5*(right-left+1)
            rows.append(dict(source=source,mode=mode,input_onset_seconds=onset,
                             output_onset_sample=center,
                             peak_position_error_ms=1000*(pos-center)/rate,
                             peak=peak,envelope_halfpower_width_ms=width,
                             pre20ms_rms=rms(pre20),post20ms_rms=rms(post20),
                             pre50ms_rms=rms(pre50),first50ms_rms=rms(first50),
                             pre_post20_ratio=rms(pre20)/max(rms(post20),1e-12)))
    with (OUT/'attack.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    for r in rows:
        print(r['source'],r['mode'],'peak',round(r['peak'],3),
              'width',r['envelope_halfpower_width_ms'],'ms')


if __name__=='__main__':main()
