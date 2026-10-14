#!/usr/bin/env python3
"""Reconcile saved native evidence with final timing definition, no audio run."""
import csv,json,hashlib,shutil
from pathlib import Path
from statistics import median
from phase51_timing import analyze,distribution
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase51'
def main():
    rows=json.loads((OUT/'native/summary.json').read_text());final=[]
    for r in rows:
        path=Path(r['path']);previous=json.loads((path/'phase51_timing.json').read_text())
        archive=path/'phase51_timing_initial.json'
        if archive.exists():raise ValueError('Fresh postprocessing required')
        shutil.copyfile(path/'phase51_timing.json',archive)
        updated=analyze(path,ROOT/'results/phase49/input/drums30.wav',r['planning'],False)
        for old,new in zip(previous['operations'],updated['operations']):
            assert old['generation']==new['generation'] and old['state']==new['state']
            if 'first_raw_difference' in old:
                new['first_raw_difference']=old['first_raw_difference'];new['prepared_prefix_unchanged']=old['prepared_prefix_unchanged']
                new['raw_start_to_complete_ms']=old['raw_start_to_complete_ms']
                new['first_raw_difference']['worker_seen_to_estimated_ms']=(int(new['accepted_mach_ns'])-int(new['worker_seen_mach_ns']))/1e6+new['first_raw_difference']['estimated_hardware_presentation_ms']
        for direction,stats in updated['direction_stats'].items():
            ops=[o for o in updated['operations'] if o.get('direction')==direction and 'first_raw_difference' in o]
            stats['first_raw_difference_accepted_ms']=distribution([o['first_raw_difference']['estimated_hardware_presentation_ms'] for o in ops])
            stats['first_raw_difference_scheduled_ms']=distribution([o['first_raw_difference']['scheduled_to_estimated_ms'] for o in ops])
        (path/'phase51_timing_final.json').write_text(json.dumps(updated,indent=2,allow_nan=False))
        guards=list(csv.DictReader((path/'workers.csv.guard.csv').open()))
        r=dict(r,timing=updated,guard=dict(records=len(guards),wall_ms=distribution(list({float(g['guard_wall_s'])*1000 for g in guards})),
            weight_prediction_max_error=max((float(g[k]) for g in guards for k in ('weight_error_low','weight_error_mid','weight_error_high')),default=0)))
        final.append(r)
    (OUT/'native_verified.json').write_text(json.dumps(final,indent=2,allow_nan=False))
    groups={}
    for label in ('C','C_L1','C_L1_L2'):
        native=[r for r in final if r['label']==label and r['kind'] in ('t1p85','busy_stall')]
        ops=[o for r in native for o in r['timing']['operations'] if o.get('direction')]
        stats={}
        for direction in sorted({o['direction'] for o in ops}):
            subset=[o for o in ops if o['direction']==direction]
            stats[direction]={key:distribution([o[part][key] for o in subset]) for part,key in [('map_start','estimated_hardware_presentation_ms'),('ramp_complete','scheduled_to_estimated_ms')]}
            stats[direction]['scheduled_to_ready_ms']=distribution([o['scheduled_to_ready_observed_ms'] for o in subset if o['scheduled_to_ready_observed_ms'] is not None])
        groups[label]=dict(runs=len(native),AUDIO_PASS=sum(r['AUDIO_QUALITY']=='PASS' for r in native),measurement_PASS=sum(r['MEASUREMENT_QUALITY']=='PASS' for r in native),missing=sum(r['missing_frames'] for r in native),direction_stats=stats)
    (OUT/'native_grouped.json').write_text(json.dumps(groups,indent=2,allow_nan=False));print('14 native evidence/time definitions reconciled; initial derived files retained')
if __name__=='__main__':main()
