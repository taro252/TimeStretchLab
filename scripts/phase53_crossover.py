#!/usr/bin/env python3
"""Optional 200/250/300 Hz low-crossover comparison on Bass and Male Vocal."""
import concurrent.futures
import csv
import pathlib
from phase52_analyze import fields, run

ROOT=pathlib.Path(__file__).resolve().parent.parent
REAL=ROOT/'results/phase53/real'
BUILD=ROOT/'build'


def main():
    jobs=[]
    for name in ('bass','male'):
        for speed in ('0.75','0.50'):
            for cutoff in (200,250,300):
                source=REAL/f'{name}_input.wav'
                output=(REAL/f'{name}_{speed.replace(".","")}_high.wav') if cutoff==250 else \
                    REAL/f'{name}_{speed.replace(".","")}_high_lp{cutoff}.wav'
                jobs.append((name,speed,cutoff,source,output))

    def process(job):
        name,speed,cutoff,source,output=job
        if cutoff==250:
            with (REAL/'manifest.csv').open() as file:
                manifest=list(csv.DictReader(file))
            recorded=next(row for row in manifest if row['name']==name and
                          row['speed']==str(float(speed)) and row['quality']=='high')
            runtime={key:recorded[key] for key in ('cpu_seconds','processing_seconds','max_rss_bytes')}
        else:
            line=run([str(BUILD/'timestretch'),str(source),str(output),
                '--speed',speed,'--phase-locking','on','--transient','on',
                '--adaptive-time-map','on','--precise-anchoring','on',
                '--stereo-coherence','on','--quality','high','--chunked','on',
                '--low-crossover-hz',str(cutoff)])
            result=fields(line)
            runtime={key:result[key] for key in ('cpu_seconds','processing_seconds','max_rss_bytes')}
        spectral=fields(run([str(BUILD/'stereo_spectral_metrics'),
                             str(source),str(output),speed]))
        for detail in ('low_bins_per_window','low_window_ipd_deg','low_window_weight'):
            spectral.pop(detail)
        basic=fields(run([str(BUILD/'wav_metrics'),str(output)]))
        pitch=fields(run([str(BUILD/'bass_pitch_metrics'),str(output)])) \
            if name=='bass' else {}
        print(name,speed,cutoff,'low IPD',spectral['low_ipd_weighted_rms_deg'],flush=True)
        return {'name':name,'speed':str(float(speed)),'cutoff_hz':cutoff,
                'output':str(output),**runtime,**spectral,
                'side_mid_ratio':basic['side_mid_ratio'],
                'lr_correlation':basic['lr_correlation'],**pitch}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows=list(pool.map(process,jobs))
    with (REAL/'crossover_study.csv').open('w',newline='') as file:
        names=list(dict.fromkeys(key for row in rows for key in row))
        writer=csv.DictWriter(file,fieldnames=names,lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


if __name__=='__main__': main()
