#!/usr/bin/env python3
"""Preserve original failures. A later review may add faults, never silently clear them."""
import argparse
import csv
import json
import math
from pathlib import Path
from phase47_evidence import validate


def review_run(path,result,log=''):
    legacy='diagnostic_csv_save_ok' not in result
    integrity,tables=validate(path,result,log,legacy=legacy)
    faults=list(integrity['faults']);previous=None
    try:
        tolerance=float(result['host_continuity_tolerance_ns']);rate=float(result['dsp_sample_rate'])
        if not math.isfinite(tolerance) or tolerance<=0 or not math.isfinite(rate) or rate<=0:raise ValueError('invalid_clock_config')
        for e in tables.get('callbacks.csv',[]):
            start,end,host=int(e['callback_start_mach_ns']),int(e['callback_end_mach_ns']),int(e['host_mach_ns'])
            flags=int(e['timestamp_flags']);frames=int(e['render_requested_frames'])
            if not legacy and not start<=int(e['io_complete_mach_ns'])<=int(e['early_end_mach_ns'])<=end:
                faults.append('callback_timepoint_order')
            if not flags&2 or not host:faults.append('missing_host')
            if end>host+tolerance:faults.append('hal_ready_deadline')
            if abs(start-host)>1e9:faults.append('host_offset_outlier')
            if end<start or end-start>frames*1e9/rate:faults.append('callback_budget')
            if flags&1:
                sample=float(e['sample_time'])
                if not math.isfinite(sample):faults.append('sample_nonfinite')
                elif previous and int(e['epoch'])==int(previous['epoch']) and int(previous['timestamp_flags'])&1:
                    old=float(previous['sample_time']);delta=sample-old
                    if not math.isfinite(old) or delta<=0 or abs(delta-int(previous['render_requested_frames']))>2:faults.append('sample_progression')
            if previous and int(e['epoch'])==int(previous['epoch']):
                delta=host-int(previous['host_mach_ns']);expected=int(previous['render_requested_frames'])*1e9/rate
                if delta<=0 or abs(delta-expected)>tolerance:faults.append('host_progression')
            previous=e
        for key in ('sample_timestamp_errors','host_timestamp_missing_callbacks','host_timestamp_backwards','host_timestamp_cadence_errors','hal_window_deadline_misses','callback_deadline_misses'):
            if int(result[key])>0:faults.append('original_'+key)
        if int(result['callback_records_evicted']) or int(result['worker_profile_records_dropped']):faults.append('capture_overflow')
    except (KeyError,ValueError,TypeError):faults.append('invalid_or_missing_clock_evidence')
    original=result.get('MEASUREMENT_QUALITY','UNMEASURED')
    measurement='FAIL' if faults or original=='FAIL' else original
    audio=result.get('AUDIO_QUALITY','INDETERMINATE')
    try:
        if int(result['underrun_frames'])>0:audio='FAIL'
    except (KeyError,ValueError,TypeError):faults.append('underrun_count_missing');measurement='FAIL'
    return dict(original_measurement_quality=original,original_sample_timestamp_errors=result.get('sample_timestamp_errors','unmeasured'),
        original_audio_quality=result.get('AUDIO_QUALITY','unmeasured'),AUDIO_QUALITY=audio,
        MEASUREMENT_QUALITY=measurement,review_faults=sorted(set(faults)),csv_integrity=integrity,
        policy='Original FAIL is sticky. Promotions require a separate explicit correction with evidence.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,default=Path('results/phase46/native'))
    parser.add_argument('--output',type=Path,default=Path('results/phase47/review'))
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);summaries=[]
    for p in sorted((args.input/'runs').glob('*')):
        if not (p/'result.json').exists():continue
        result=json.loads((p/'result.json').read_text())
        review=review_run(p,result,(p/'playback.log').read_text())
        destination=args.output/p.name;destination.mkdir(exist_ok=True)
        (destination/'original_result.json').write_text(json.dumps(result,indent=2))
        (destination/'review.json').write_text(json.dumps(review,indent=2))
        summaries.append(dict(run_id=p.name,original_measurement=review['original_measurement_quality'],MEASUREMENT_QUALITY=review['MEASUREMENT_QUALITY'],AUDIO_QUALITY=review['AUDIO_QUALITY']))
    if summaries:
        with (args.output/'summary.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(summaries[0]),lineterminator='\n');w.writeheader();w.writerows(summaries)
    print('Reviewed',len(summaries),'runs; original FAILs retained')
if __name__=='__main__':main()
