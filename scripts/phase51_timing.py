"""Five-stage control timeline. All audible times are HAL-based estimates."""
import csv,json,subprocess
from pathlib import Path
from statistics import median
from phase45_store import parse_log
from phase46_operation import mapped_response,run_command
from phase46_forensics import percentile
ROOT=Path(__file__).resolve().parents[1]
def distribution(values):
    return dict(count=len(values),median=median(values) if values else None,p95=percentile(values,.95),max=max(values,default=None))
def analyze(path,input_path,planning='C',first_changes=True):
    path=Path(path);values=parse_log((path/'playback.log').read_text())
    operations=list(csv.DictReader((path/'operations.csv').open()))
    events=list(csv.DictReader((path/'callbacks.csv').open()));plans=list(csv.DictReader((path/'replay.csv').open()))
    if len({r['operation'] for r in operations})!=len(operations):raise ValueError('Duplicate operation')
    rate=float(values['dsp_sample_rate']);device=float(values['device_presentation_latency_ms']);source=float(values['source_output_presentation_latency_ms'])
    def at(frame):
        matches=[e for e in events if int(e['pcm_before'])<=frame<int(e['pcm_before'])+int(e['received'])]
        if len(matches)!=1:raise ValueError('Frame was not consumed exactly once')
        return matches[0]
    rows=[];active_intervals=[]
    for op in operations:
        item=dict(op);num=lambda key:int(op[key]);scheduled=num('scheduled_mach_ns');accepted=num('accepted_mach_ns')
        if op['state']=='Completed':
            if not all(num(k)>0 for k in ('generation','scheduled_mach_ns','observed_mach_ns','sent_mach_ns','accepted_mach_ns','worker_seen_mach_ns')):
                raise ValueError('Completed operation lacks mandatory timestamps')
            if not scheduled<=num('observed_mach_ns')<=num('sent_mach_ns')<=accepted:
                raise ValueError('Non-monotonic control timestamps')
        item['scheduled_to_observed_ms']=(num('observed_mach_ns')-scheduled)/1e6 if num('observed_mach_ns') else None
        item['scheduled_to_send_ms']=(num('sent_mach_ns')-scheduled)/1e6 if num('sent_mach_ns') else None
        item['send_to_api_accepted_ms']=(accepted-num('sent_mach_ns'))/1e6 if accepted else None
        item['api_accepted_to_worker_seen_ms']=(num('worker_seen_mach_ns')-accepted)/1e6 if accepted and num('worker_seen_mach_ns') else None
        item['busy_wait_ms']=num('busy_ns')/1e6
        item['E_ready_status']='OBSERVED' if num('ready_observed_mach_ns') else 'UNAVAILABLE_OR_STOPPED'
        generation=num('generation');matching=[(i,p) for i,p in enumerate(plans) if int(p['generation'])==generation]
        if generation and len(matching)==1:
            index,p=matching[0];item['plan']=p;item['direction']=f"{float(p['from']):.2f}->{float(p['target']):.2f}"
            for label,key in [('map_start','applied_output'),('ramp_complete','completion_output')]:
                frame=int(p[key]);event=at(frame)
                item[label]=mapped_response(event,accepted,frame,rate,device,source)
                item[label]['estimated_mach_ns']=accepted+round(item[label]['estimated_hardware_presentation_ms']*1e6)
                item[label]['scheduled_to_estimated_ms']=(item[label]['estimated_mach_ns']-scheduled)/1e6
            item['map_start_to_ramp_complete_ms']=(int(p['completion_output'])-int(p['applied_output']))*1000/rate
            worker=num('worker_seen_mach_ns')
            for label in ('map_start','ramp_complete'):
                item[label]['worker_seen_to_estimated_ms']=(item[label]['estimated_mach_ns']-worker)/1e6 if worker else None
            ready=num('ready_observed_mach_ns');complete_event=at(int(p['completion_output']))
            item['E_callback_completion_bracket_ns']=[int(complete_event['callback_start_mach_ns']),int(complete_event['io_complete_mach_ns'])]
            item['accepted_to_ready_observed_ms']=(ready-accepted)/1e6 if ready else None
            item['scheduled_to_ready_observed_ms']=(ready-scheduled)/1e6 if ready else None
            item['hal_completion_to_ready_observed_ms']=(ready-item['ramp_complete']['estimated_mach_ns'])/1e6 if ready else None
            # Ready can precede estimated device presentation. The API has
            # consumed the samples into HAL; it is not an acoustic completion.
            if ready:active_intervals.append((accepted,ready))
            if first_changes:
                prefix=path/f'phase51_prefix_{generation}.csv'
                with prefix.open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=list(plans[0]),lineterminator='\n');w.writeheader();w.writerows(plans[:index])
                before=path/f'phase51_before_{generation}.wav'
                run_command([ROOT/'build/phase51_reference',input_path,before,values['initial_speed'],prefix,planning,'safe-density'],path/f'phase51_before_{generation}.log')
                got=subprocess.run([str(ROOT/'build/phase45_pcm_hash'),str(path/'reference.wav'),str(before)],capture_output=True,text=True,check=True)
                first=parse_log(got.stdout)['first_changed_pcm_frame']
                if first=='none':raise ValueError('Applied change has no raw difference')
                first=int(first);item['first_raw_difference']=mapped_response(at(first),accepted,first,rate,device,source)
                item['first_raw_difference']['scheduled_to_estimated_ms']=(accepted-scheduled)/1e6+item['first_raw_difference']['estimated_hardware_presentation_ms']
                item['first_raw_difference']['worker_seen_to_estimated_ms']=(accepted-worker)/1e6+item['first_raw_difference']['estimated_hardware_presentation_ms'] if worker else None
                item['prepared_prefix_unchanged']=first>=int(p['prepared'])
                if not item['prepared_prefix_unchanged']:raise ValueError('Prepared PCM changed')
                item['raw_start_to_complete_ms']=item['ramp_complete']['estimated_hardware_presentation_ms']-item['first_raw_difference']['estimated_hardware_presentation_ms']
        elif generation and op['state']=='Completed':raise ValueError('Completed generation missing replay')
        rows.append(item)
    stats={}
    for direction in sorted({r.get('direction') for r in rows if r.get('direction')}):
        selected=[r for r in rows if r.get('direction')==direction]
        stats[direction]={key:distribution([r[key] for r in selected if r.get(key) is not None]) for key in ('scheduled_to_send_ms','api_accepted_to_worker_seen_ms','map_start_to_ramp_complete_ms','accepted_to_ready_observed_ms','scheduled_to_ready_observed_ms','busy_wait_ms')}
        for label in ('map_start','ramp_complete','first_raw_difference'):
            stats[direction][label+'_accepted_ms']=distribution([r[label]['estimated_hardware_presentation_ms'] for r in selected if label in r])
            stats[direction][label+'_scheduled_ms']=distribution([r[label]['scheduled_to_estimated_ms'] for r in selected if label in r])
    result=dict(OPERATION_TIMING_INTEGRITY='PASS',operations=rows,direction_stats=stats,states={s:sum(r['state']==s for r in rows) for s in sorted({r['state'] for r in rows})},
        busy_active_total_ms=sum(b-a for a,b in active_intervals)/1e6,
        busy_wait_sum_ms=sum(r['busy_wait_ms'] for r in rows),
        measurement_model='A=scheduled wall mach; B=worker steady clock converted by recorded clock bridge; C/D=HAL host+source offset+device-only presentationLatency; E=first control observation of readiness (nominal 1ms polling, OS wake delay is not bounded). Busy active includes accepted through observed ready. Per-operation waiting overlaps and must not be added as elapsed busy time.',
        acoustic_loopback=False,ready_may_precede_hal_presentation=True,
        percentile='usual median; nearest rank p95 ceil(.95*N)',planning=planning)
    (path/'phase51_timing.json').write_text(json.dumps(result,indent=2,allow_nan=False));return result
