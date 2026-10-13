"""Post-audit final host thresholds and fail-closed corrections without rewriting raw run records."""
import csv,json
from pathlib import Path
from statistics import median
from phase46_forensics import percentile
root=Path(__file__).resolve().parents[1]
base=root/'results/phase46'
output=[]
for p in sorted((base/'native/runs').glob('*')):
    if not (p/'result.json').exists():continue
    r=json.loads((p/'result.json').read_text());events=list(csv.DictReader((p/'callbacks.csv').open()))
    tolerance=float(r['host_continuity_tolerance_ns']);rate=float(r['dsp_sample_rate'])
    faults=[];previous=None
    for e in events:
        start,end,host=int(e['callback_start_mach_ns']),int(e['callback_end_mach_ns']),int(e['host_mach_ns'])
        flags=int(e['timestamp_flags'])
        if not flags&2 or not host:faults.append('missing_host')
        if end>host+tolerance:faults.append('hal_ready_deadline')
        if abs(start-host)>1e9:faults.append('host_offset_outlier')
        if end<start or end-start>int(e['render_requested_frames'])*1e9/rate:faults.append('callback_budget')
        if previous and int(e['epoch'])==int(previous['epoch']):
            delta=host-int(previous['host_mach_ns']);expected=int(previous['render_requested_frames'])*1e9/rate
            if delta<=0 or abs(delta-expected)>tolerance:faults.append('host_progression')
        previous=e
    complete=(r.get('callback_records_evicted')=='0' and r.get('worker_profile_records_dropped')=='0' and len(events)==int(r['callback_records_retained']))
    audio=r['AUDIO_QUALITY']
    if int(r['underrun_frames'])>0:audio='FAIL'
    review=dict(original_audio_quality=r['AUDIO_QUALITY'],AUDIO_QUALITY=audio,
        MEASUREMENT_QUALITY='PASS' if not faults and complete else 'FAIL',
        final_host_threshold_faults=sorted(set(faults)),complete_record=complete,
        note='Final first-frame HAL deadline, 1-second local-route offset sanity limit; observed shortages always FAIL even when exit missing')
    (p/'final_measurement_review.json').write_text(json.dumps(review,indent=2))
    if audio!=r['AUDIO_QUALITY']:(p/'quality_correction.json').write_text(json.dumps(review,indent=2))
    output.append(dict(run_id=r['run_id'],trace_requested=r['trace_requested'],attach_after=r.get('attach_after_seconds',0),
        AUDIO_QUALITY=audio,MEASUREMENT_QUALITY=review['MEASUREMENT_QUALITY'],TRACE_CAPTURE=r['TRACE_CAPTURE'],TRACE_ANALYSIS=r['TRACE_ANALYSIS'],
        PCM_CORRECTNESS=r['PCM_CORRECTNESS'],missing_frames=r['missing_frames'],missing_calls=r['underrun_calls'],
        max_missing_ms=r['max_continuous_missing_ms'],fifo_minimum=r['fifo_minimum_active'],
        publication_max_ms=r['publication_gap_max_ms'],publication_p95_ms=r['publication_gap_p95_ms'],publication_p99_ms=r['publication_gap_p99_ms'],
        callback_max_ms=r['max_callback_ms'],cpu_user_s=r['cpu_user_seconds'],cpu_system_s=r['cpu_system_seconds'],rss_mib=r['peak_rss_mib']))
with (base/'summary_reviewed.csv').open('w',newline='') as stream:
    w=csv.DictWriter(stream,fieldnames=list(output[0]),lineterminator='\n');w.writeheader();w.writerows(output)
print('Reviewed',len(output),'runs; audio failures',sum(r['AUDIO_QUALITY']=='FAIL' for r in output))
