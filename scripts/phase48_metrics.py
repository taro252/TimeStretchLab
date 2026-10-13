"""Native supply comparison: invalid measurement is never a stability PASS."""
import csv,json,math
from pathlib import Path
from statistics import median
from phase46_forensics import percentile
from phase46_operation import analyze

def distribution(values):
    return dict(count=len(values),p50=median(values) if values else None,max=max(values,default=None),p95=percentile(values,.95),p99=percentile(values,.99))

def validated_values(records,key,scale=1.0):
    values=[];excluded={};invalid={};examples=[]
    for index,row in enumerate(records):
        raw=row.get(key)
        reason=None
        if raw is None or (isinstance(raw,str) and not raw.strip()):reason='missing'
        else:
            try:value=float(raw)
            except (ValueError,TypeError):reason='not_numeric'
            else:
                if not math.isfinite(value):reason='nonfinite'
                elif key=='publication_interval_s' and index==0 and value==-1:
                    excluded['initial_publication_sentinel']=excluded.get('initial_publication_sentinel',0)+1
                    continue
                elif value<0:reason='unexpected_negative'
                elif not math.isfinite(value*scale):reason='scaled_overflow'
                else:values.append(value*scale)
        if reason:
            invalid[reason]=invalid.get(reason,0)+1
            if len(examples)<20:examples.append(dict(record_index=index,value=str(raw),reason=reason))
    audit=dict(records=len(records),valid_count=len(values),excluded_count=sum(excluded.values()),excluded_reasons=excluded,
        invalid_count=sum(invalid.values()),invalid_reasons=invalid,invalid_examples=examples)
    return values,audit

def stability_verdict(audio,valid,observed_shortage):
    return 'FAIL' if observed_shortage or audio=='FAIL' else 'PASS' if valid and audio=='PASS' else 'INDETERMINATE'

def measure(row,path,context,expected_fifo=16384,expected_lead=12288):
    path=Path(path);integrity=json.loads((path/'csv_integrity.json').read_text())
    result=dict(row,**context)
    result['disk_free_after_bytes']=__import__('os').statvfs(path).f_bavail*__import__('os').statvfs(path).f_frsize
    problems=[];metric_faults=[];audits={};candidate=row['candidate']
    expected_block=1024 if candidate=='C' else 2048
    for key,expected in [('fifo_capacity_frames',expected_fifo),('lead_limit_frames',expected_lead),('dsp_block_frames',expected_block),('cpu_stress_threads',2 if int(row['stress']) else 0)]:
        if int(row.get(key,-1))!=expected:problems.append(key)
    if row.get('worker_qos_requested')!=('user_initiated' if candidate=='B' else 'inherited'):problems.append('worker_qos_requested')
    if candidate=='B' and row.get('worker_qos_applied')!='1':problems.append('worker_qos_not_applied')
    if int(row['stress']) and int(row.get('cpu_stress_ticks',0))<=0:problems.append('cpu_stress_inactive')
    if integrity['CSV_INTEGRITY']=='PASS':
        workers=list(csv.DictReader((path/'workers.csv').open()));callbacks=list(csv.DictReader((path/'callbacks.csv').open()))
        observed_frames=sorted({int(r['render_requested_frames']) for r in callbacks})
        hardware_frames=int(row.get('output_device_buffer_frames',512))
        expected_frames=math.ceil(hardware_frames*float(row['dsp_sample_rate'])/float(row['output_device_rate']))
        if hardware_frames!=512 or observed_frames!=[expected_frames]:problems.append('callback_frames_not_expected_source_quantum')
        for key in ('dsp_wall_s','dsp_cpu_s','cycle_wall_s','cycle_cpu_s','publication_interval_s'):
            values,audits[key]=validated_values(workers,key,1000)
            if audits[key]['invalid_count']:metric_faults.append(key)
            result[key+'_ms']=distribution(values)
        durations=[]
        for r in callbacks:
            try:duration=(int(r['callback_end_mach_ns'])-int(r['callback_start_mach_ns']))/1e6
            except (ValueError,TypeError,KeyError):duration=None
            durations.append(dict(callback_wall_ms=duration))
        values,audits['callback_wall_ms']=validated_values(durations,'callback_wall_ms')
        if audits['callback_wall_ms']['invalid_count']:metric_faults.append('callback_wall_ms')
        result['callback_wall_ms']=distribution(values)
        publication=result['publication_interval_s_ms']
        for stat in ('p50','p95','p99','max'):result['publication_gap_'+stat+'_ms']=publication[stat]
        result['callback_frames_observed']=observed_frames
        result['callback_source_frames_expected']=expected_frames
        operations=analyze(path,Path(row['input_path']),first_changes=False)
        result['direction_latency']=operations['direction_stats']
        result['request_timing']=[dict(generation=r['generation'],direction=r['direction'],callback_entry_ms=r['map_node']['callback_entry_ms'],hal_frame_time_ms=r['map_node']['hal_frame_time_ms'],estimated_hardware_presentation_ms=r['map_node']['estimated_hardware_presentation_ms']) for r in operations['changes']]
    else:problems.append('csv_invalid');metric_faults.append('csv_invalid')
    result['METRIC_INTEGRITY']='FAIL' if metric_faults else 'PASS'
    result['metric_faults']=metric_faults;result['metric_value_audits']=audits
    result['original_measurement_quality']=row['MEASUREMENT_QUALITY']
    if metric_faults:result['MEASUREMENT_QUALITY']='FAIL'
    result['CONFIG_VALIDITY']='FAIL' if problems else 'PASS';result['configuration_faults']=problems
    valid=(result['MEASUREMENT_QUALITY']=='PASS' and integrity['CSV_INTEGRITY']=='PASS' and row.get('PCM_CORRECTNESS')=='PASS' and not problems and not metric_faults)
    result['stability_evidence_valid']=valid
    observed=int(row.get('underrun_frames',0))>0
    result['observed_underrun']=observed
    result['NATIVE_STABILITY_VERDICT']=stability_verdict(row['AUDIO_QUALITY'],valid,observed)
    (path/'comparison.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    return result

def aggregate(rows):
    # Fail closed even when an externally cached row still claims PASS.
    rows=[dict(r) for r in rows]
    for r in rows:
        if r.get('METRIC_INTEGRITY')!='PASS':
            r['stability_evidence_valid']=False
            if r['NATIVE_STABILITY_VERDICT']=='PASS':r['NATIVE_STABILITY_VERDICT']='INDETERMINATE'
    groups={}
    for candidate in sorted({r['candidate'] for r in rows}):
        all_rows=[r for r in rows if r['candidate']==candidate];valid=[r for r in all_rows if r['stability_evidence_valid'] and r.get('METRIC_INTEGRITY')=='PASS']
        failures=sum(r['observed_underrun'] for r in all_rows);valid_failures=sum(r['observed_underrun'] for r in valid)
        group=dict(runs=len(all_rows),valid_runs=len(valid),measurement_invalid_runs=len(all_rows)-len(valid),
            verdict_counts={v:sum(r['NATIVE_STABILITY_VERDICT']==v for r in all_rows) for v in ('PASS','FAIL','INDETERMINATE')},
            observed_underrun_runs=failures,observed_underrun_rate=failures/len(all_rows),
            valid_underrun_runs=valid_failures,valid_underrun_rate=valid_failures/len(valid) if valid else None,
            missing_frames_all=sum(int(r.get('underrun_frames',0)) for r in all_rows),
            max_continuous_missing_ms_all=max((float(r.get('max_continuous_missing_ms',0)) for r in all_rows),default=None))
        for key in ('publication_gap_max_ms','publication_gap_p50_ms','publication_gap_p95_ms','publication_gap_p99_ms','fifo_minimum_active','peak_rss_mib','cpu_user_seconds','cpu_system_seconds','max_callback_ms'):
            values=[float(r[key]) for r in valid if r.get(key) is not None]
            group[key]=dict(median=median(values) if values else None,min=min(values,default=None),max=max(values,default=None))
        for key in ('dsp_wall_s_ms','dsp_cpu_s_ms','cycle_wall_s_ms','cycle_cpu_s_ms'):
            group[key]={stat:dict(median=median([r[key][stat] for r in valid]) if valid else None,max=max((r[key][stat] for r in valid),default=None)) for stat in ('max','p95','p99')}
        latency={}
        for direction in sorted({d for r in valid for d in r.get('direction_latency',{})}):
            values=[t['estimated_hardware_presentation_ms'] for r in valid for t in r['request_timing'] if t['direction']==direction and t['estimated_hardware_presentation_ms'] is not None]
            latency[direction]=dict(count=len(values),median_ms=median(values) if values else None,p95_ms=percentile(values,.95),max_ms=max(values,default=None))
        group['direction_latency']=latency;groups[candidate]=group
    verdict='FAIL' if any(r['NATIVE_STABILITY_VERDICT']=='FAIL' for r in rows) else 'INDETERMINATE' if any(r['NATIVE_STABILITY_VERDICT']!='PASS' for r in rows) else 'PASS'
    return dict(candidates=groups,all_runs=len(rows),NATIVE_QUALITY=verdict,policy='All measured runs retained; stability PASS requires valid measurement, CSV, configuration and PCM. Observed shortages remain FAIL even with invalid measurement.',percentile='nearest rank ceil(q*N); median averages two middle values for even N')

def save_summaries(output,rows):
    output=Path(output)
    (output/'comparison_summary.json').write_text(json.dumps(aggregate(rows),indent=2,allow_nan=False))
    fields=['ordinal','round','candidate','run_id','AUDIO_QUALITY','MEASUREMENT_QUALITY','CSV_INTEGRITY','METRIC_INTEGRITY','PCM_CORRECTNESS','CONFIG_VALIDITY','NATIVE_STABILITY_VERDICT','stability_evidence_valid','underrun_frames','underrun_calls','max_continuous_missing_ms','fifo_minimum_active','publication_gap_max_ms','publication_gap_p50_ms','publication_gap_p95_ms','publication_gap_p99_ms','max_callback_ms','peak_rss_mib','cpu_user_seconds','cpu_system_seconds','disk_free_before_bytes','disk_free_after_bytes','eos_drained','output_device_id','output_device_rate','dsp_sample_rate','sample_timestamp_errors','host_timestamp_cadence_errors','worker_qos_requested','worker_qos_applied','dsp_block_frames']
    with (output/'comparison_summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader()
        writer.writerows({k:r.get(k,'unmeasured') for k in fields} for r in rows)
