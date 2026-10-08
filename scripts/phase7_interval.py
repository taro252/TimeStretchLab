#!/usr/bin/env python3
"""Small 80/120/160 ms interval study on matched female/male vocal excerpts."""
import csv
import pathlib
from phase7_ab import ROOT,fields,run
from phase7_analyze import click_metrics
from phase6_analyze import paired_vocal,save

OUT=ROOT/'results/phase7'

def main():
    study=OUT/'interval'
    study.mkdir(parents=True,exist_ok=True)
    rows=[];modulation=[];click=[]
    for name in ('female','male'):
        sample=OUT/f'{name}_2_input.wav'
        off=OUT/f'{name}_2_050_off.wav'
        if not sample.exists() or not off.exists():raise FileNotFoundError(sample)
        rate=int(fields(run([str(ROOT/'build/wav_metrics'),str(off)]))['rate'])
        for interval in (80,120,160):
            output=study/f'{name}_{interval}.wav'
            diagnostic=study/f'{name}_{interval}_diagnostics'
            cmd=[str(ROOT/'build/timestretch'),str(sample),str(output),
                 '--speed','0.50','--phase-locking','on','--partial-tracking','off',
                 '--pvsola','on','--pvsola-interval-ms',str(interval),
                 '--pvsola-search-ms','10','--pvsola-min-correlation','0.65',
                 '--transient','on','--adaptive-time-map','on',
                 '--precise-anchoring','on','--stereo-coherence','on',
                 '--quality','high','--chunked','on','--debug-csv',str(diagnostic)]
            result=fields(run(cmd))
            rows.append({'name':name,'interval_ms':interval,'output':str(output),**result})
            for metric in paired_vocal(off,output,rate):
                modulation.append({'name':name,'interval_ms':interval,**metric})
            click.append({'name':name,'interval_ms':interval,
                          **click_metrics(off,output,diagnostic/'pvsola_resync.csv')})
            print(name,interval,'applied',result['resync_applied'],flush=True)
    save(study/'manifest.csv',rows)
    save(study/'vocal_modulation.csv',modulation)
    save(study/'click_metrics.csv',click)

if __name__=='__main__':main()
