#!/usr/bin/env python3
"""Input-event-aligned attack observations for short real audio."""
import csv
import subprocess
from pathlib import Path
import numpy as np
from phase32_study import read
from phase37_study import ROOT,OUT,SOURCES,peak_region,rms

def main():
    rows=[]
    for source in ('mix','drums','vocal','bass','guitar'):
        path=SOURCES[source]
        input_rate,input_audio=read(path)
        input_mono=np.mean(input_audio,axis=1)
        for speed in ('1.50','2.00'):
            for mode in 'AB':
                result=subprocess.run((str(ROOT/'build/phase37_render'),str(path),'-',
                    speed,mode),capture_output=True,text=True,timeout=90)
                if result.returncode:raise RuntimeError(result.stderr)
                points=list(csv.DictReader(result.stdout.splitlines()))
                rate,audio=read(OUT/'raw'/f'{source}_{mode}_{speed.replace(".","")}.wav')
                for index,point in enumerate(points):
                    if point['event_peak']!='1':continue
                    original=int(point['input_sample'])
                    left=max(0,original-input_rate//20)
                    right=min(len(input_mono),original+input_rate//20)
                    input_peak=left+int(np.argmax(np.abs(input_mono[left:right])))
                    expected=round(input_peak/float(speed))
                    if expected<rate//10 or expected+rate//10>=len(audio):continue
                    peak,offset,width,pre,secondary=peak_region(audio,rate,expected)
                    begin=max(0,expected-int(.005*rate))
                    end=min(len(audio),expected+int(.020*rate))
                    rows.append(dict(source=source,speed=speed,mode=mode,
                        event_frame=index,input_sample=original,
                        input_peak_sample=input_peak,
                        ideal_output_sample=expected,mapped_output_sample=point['output_sample'],
                        local_peak=peak,peak_offset_ms=offset,width_ms=width,
                        pre_echo_rms=pre,pre_echo_to_peak=pre/max(peak,1e-9),
                        secondary_to_primary=secondary,
                        first_20ms_rms=rms(audio[begin:end])))
    with (OUT/'event_attacks.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    summary=[]
    for source in ('mix','drums','vocal','bass','guitar'):
        for speed in ('1.50','2.00'):
            for mode in 'AB':
                q=[r for r in rows if r['source']==source and r['speed']==speed and r['mode']==mode]
                summary.append(dict(source=source,speed=speed,mode=mode,count=len(q),
                    median_peak=float(np.median([r['local_peak'] for r in q])),
                    median_abs_offset_ms=float(np.median([abs(r['peak_offset_ms']) for r in q])),
                    p90_pre_echo_to_peak=float(np.percentile([r['pre_echo_to_peak'] for r in q],90)),
                    median_first_20ms_rms=float(np.median([r['first_20ms_rms'] for r in q]))))
    with (OUT/'event_summary.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=summary[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(summary)
    print(len(rows),'event observations')

if __name__=='__main__':main()
