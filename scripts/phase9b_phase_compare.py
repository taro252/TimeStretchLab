#!/usr/bin/env python3
"""Level-match random/analysis residual-phase diagnostic outputs."""
import csv
import math
from phase9b_loudness import OUT,metrics,gain_copy

def match(a,b,kind,name,code):
    original={'random':metrics(a),'analysis':metrics(b)}
    key='rms' if kind=='residual_rms' else 'integrated_lufs'
    target=min(item[key] for item in original.values())
    files={};measurements={};gains={}
    for mode,source in (('random',a),('analysis',b)):
        destination=OUT/'phase_compare'/kind/f'{name}_{code}_{mode}.wav'
        gain=20*math.log10(target/original[mode]['rms']) if key=='rms' else \
            target-original[mode]['integrated_lufs']
        for _ in range(3):
            gain_copy(source,destination,gain)
            measured=metrics(destination)
            correction=20*math.log10(target/measured['rms']) if key=='rms' else \
                target-measured['integrated_lufs']
            if abs(correction)<.025:break
            gain+=correction
        files[mode]=str(destination);measurements[mode]=measured;gains[mode]=gain
    return {'name':name,'speed':.75 if code=='075' else .5,'comparison':kind,
            'random_source':str(a),'analysis_source':str(b),
            'random_file':files['random'],'analysis_file':files['analysis'],
            'random_original_rms':original['random']['rms'],
            'analysis_original_rms':original['analysis']['rms'],
            'random_original_lufs':original['random']['integrated_lufs'],
            'analysis_original_lufs':original['analysis']['integrated_lufs'],
            'random_gain_db':gains['random'],'analysis_gain_db':gains['analysis'],
            'post_rms_difference_db':20*math.log10(
                measurements['random']['rms']/measurements['analysis']['rms']),
            'post_lufs_difference':abs(measurements['random']['integrated_lufs']-
                                       measurements['analysis']['integrated_lufs'])}

def main():
    with (OUT/'component_manifest.csv').open() as file:manifest=list(csv.DictReader(file))
    rows=[]
    for item in manifest:
        if not item.get('analysis_phase_residual'):continue
        name=item['name'];code='075' if float(item['speed'])==.75 else '050'
        rows.append(match(item['random_residual'],item['analysis_phase_residual'],
                          'residual_rms',name,code))
        rows.append(match(item['random_combined'],item['analysis_phase_combined'],
                          'combined_lufs',name,code))
        print(name,code,flush=True)
    if any(row['post_lufs_difference']>.1 for row in rows
           if row['comparison']=='combined_lufs'):
        raise RuntimeError('Phase comparison LUFS mismatch')
    with (OUT/'phase_compare.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)

if __name__=='__main__':main()
