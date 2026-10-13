"""Native supply comparison: invalid measurement is never a stability PASS."""
import csv,json,math
from pathlib import Path
from statistics import median
from phase46_forensics import percentile
from phase46_operation import analyze

def distribution(values):
    return dict(count=len(values),max=max(values,default=None),p95=percentile(values,.95),p99=percentile(values,.99))

def measure(row,path,context):
    path=Path(path);integrity=json.loads((path/'csv_integrity.json').read_text())
    result=dict(row,**context)
    result['disk_free_after_bytes']=__import__('os').statvfs(path).f_bavail*__import__('os').statvfs(path).f_frsize
    problems=[];candidate=row['candidate']
    expected_block=1024 if candidate=='C' else 2048
    for key,expected in [('fifo_capacity_frames',16384),('lead_limit_frames',12288),('dsp_block_frames',expected_block),('cpu_stress_threads',2 if int(row['stress']) else 0)]:
        if int(row.get(key,-1))!=expected:problems.append(key)
    if row.get('worker_qos_requested')!=('user_initiated' if candidate=='B' else 'inherited'):problems.append('worker_qos_requested')
    if candidate=='B' and row.get('worker_qos_applied')!='1':problems.append('worker_qos_not_applied')
    if int(row['stress']) and int(row.get('cpu_stress_ticks',0))<=0:problems.append('cpu_stress_inactive')
    if integrity['CSV_INTEGRITY']=='PASS':
        workers=list(csv.DictReader((path/'workers.csv').open()));callbacks=list(csv.DictReader((path/'callbacks.csv').open()))
        if {int(r['render_requested_frames']) for r in callbacks}!={512}:problems.append('callback_frames_not_512')
        for key in ('dsp_wall_s','dsp_cpu_s','cycle_wall_s','cycle_cpu_s','publication_interval_s'):
            values=[float(r[key])*1000 for r in workers if float(r[key])>=0]
            if not all(math.isfinite(v) for v in values):problems.append('nonfinite_'+key)
            result[key+'_ms']=distribution(values)
        result['callback_wall_ms']=distribution([(int(r['callback_end_mach_ns'])-int(r['callback_start_mach_ns']))/1e6 for r in callbacks])
        result['callback_frames_observed']=512
        operations=analyze(path,Path(row['input_path']),first_changes=False)
        result['direction_latency']=operations['direction_stats']
        result['request_timing']=[dict(generation=r['generation'],direction=r['direction'],callback_entry_ms=r['map_node']['callback_entry_ms'],hal_frame_time_ms=r['map_node']['hal_frame_time_ms'],estimated_hardware_presentation_ms=r['map_node']['estimated_hardware_presentation_ms']) for r in operations['changes']]
    else:problems.append('csv_invalid')
    result['CONFIG_VALIDITY']='FAIL' if problems else 'PASS';result['configuration_faults']=problems
    valid=(row['MEASUREMENT_QUALITY']=='PASS' and integrity['CSV_INTEGRITY']=='PASS' and row.get('PCM_CORRECTNESS')=='PASS' and not problems)
    result['stability_evidence_valid']=valid
    observed=int(row.get('underrun_frames',0))>0
    result['observed_underrun']=observed
    result['NATIVE_STABILITY_VERDICT']='FAIL' if observed or row['AUDIO_QUALITY']=='FAIL' else 'PASS' if valid and row['AUDIO_QUALITY']=='PASS' else 'INDETERMINATE'
    (path/'comparison.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    return result

def aggregate(rows):
    groups={}
    for candidate in sorted({r['candidate'] for r in rows}):
        all_rows=[r for r in rows if r['candidate']==candidate];valid=[r for r in all_rows if r['stability_evidence_valid']]
        failures=sum(r['observed_underrun'] for r in all_rows);valid_failures=sum(r['observed_underrun'] for r in valid)
        group=dict(runs=len(all_rows),valid_runs=len(valid),measurement_invalid_runs=len(all_rows)-len(valid),
            verdict_counts={v:sum(r['NATIVE_STABILITY_VERDICT']==v for r in all_rows) for v in ('PASS','FAIL','INDETERMINATE')},
            observed_underrun_runs=failures,observed_underrun_rate=failures/len(all_rows),
            valid_underrun_runs=valid_failures,valid_underrun_rate=valid_failures/len(valid) if valid else None,
            missing_frames_all=sum(int(r.get('underrun_frames',0)) for r in all_rows),
            max_continuous_missing_ms_all=max((float(r.get('max_continuous_missing_ms',0)) for r in all_rows),default=None))
        for key in ('publication_gap_max_ms','publication_gap_p95_ms','publication_gap_p99_ms','fifo_minimum_active','peak_rss_mib','cpu_user_seconds','cpu_system_seconds','max_callback_ms'):
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
    fields=['ordinal','round','candidate','run_id','AUDIO_QUALITY','MEASUREMENT_QUALITY','CSV_INTEGRITY','PCM_CORRECTNESS','CONFIG_VALIDITY','NATIVE_STABILITY_VERDICT','stability_evidence_valid','underrun_frames','underrun_calls','max_continuous_missing_ms','fifo_minimum_active','publication_gap_max_ms','publication_gap_p95_ms','publication_gap_p99_ms','max_callback_ms','peak_rss_mib','cpu_user_seconds','cpu_system_seconds','disk_free_before_bytes','disk_free_after_bytes','eos_drained','output_device_id','output_device_rate','dsp_sample_rate','sample_timestamp_errors','host_timestamp_cadence_errors','worker_qos_requested','worker_qos_applied','dsp_block_frames']
    with (output/'comparison_summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader()
        writer.writerows({k:r.get(k,'unmeasured') for k in fields} for r in rows)
