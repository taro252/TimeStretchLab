#!/usr/bin/env python3
"""Analyze Phase 5.3 outputs, including one-second low-IPD bin distributions."""
import csv
import pathlib
from phase52_analyze import fields, highband, run

ROOT=pathlib.Path(__file__).resolve().parent.parent
REAL=ROOT/'results/phase53/real'
BUILD=ROOT/'build'


def save(path,rows):
    with path.open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(dict.fromkeys(k for row in rows for k in row)),
                              lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


def main():
    with (REAL/'manifest.csv').open() as file:
        manifest=list(csv.DictReader(file))
    metrics=[]
    windows=[]
    for row in manifest:
        basic=fields(run([str(BUILD/'wav_metrics'),row['output']]))
        spectral=fields(run([str(BUILD/'stereo_spectral_metrics'),
                             row['input'],row['output'],row['speed']]))
        pitch=fields(run([str(BUILD/'bass_pitch_metrics'),row['output']])) \
            if row['name']=='bass' else {}
        counts=spectral.pop('low_bins_per_window').split(',')
        errors=spectral.pop('low_window_ipd_deg').split(',')
        weights=spectral.pop('low_window_weight').split(',')
        for second,(count,error,weight) in enumerate(zip(counts,errors,weights),start=1):
            windows.append({'name':row['name'],'speed':row['speed'],
                            'quality':row['quality'],'input_second':second,
                            'valid_low_bins':int(count),'ipd_rms_deg':float(error),
                            'magnitude_weight':float(weight)})
        metrics.append({**row,**basic,**spectral,**pitch,
                        **highband(row['output'],int(basic['rate']))})
        print(row['name'],row['speed'],row['quality'],
              'low bins',spectral['low_bins'],
              'effective',spectral['low_magnitude_effective_bins'],
              'zero windows',spectral['low_window_zero'],flush=True)
    save(REAL/'metrics.csv',metrics)
    save(REAL/'low_ipd_windows.csv',windows)


if __name__=='__main__': main()
