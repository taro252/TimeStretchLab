"""Join shortages to the corresponding worker cycle and same-run OS evidence."""
import csv
import json
import math
from bisect import bisect_right
from pathlib import Path
from statistics import median
from phase47_evidence import validate


def percentile(values,q):
    values=sorted(values)
    return values[max(0,math.ceil(len(values)*q)-1)] if values else None


def investigate(path, values):
    log=(path/'playback.log').read_text() if (path/'playback.log').exists() else ''
    integrity,tables=validate(path,values,log,legacy='diagnostic_csv_save_ok' not in values)
    (path/'csv_integrity.json').write_text(json.dumps(integrity,indent=2))
    if integrity['CSV_INTEGRITY']!='PASS':
        return dict(complete_record=False,CSV_INTEGRITY='FAIL',MEASUREMENT_QUALITY='FAIL',evidence_faults=';'.join(integrity['faults']))
    callbacks=list(csv.DictReader((path/'callbacks.csv').open()))
    workers=list(csv.DictReader((path/'workers.csv').open()))
    ends=[int(w['published_mach_ns']) for w in workers]
    os_by_start={} # Only this run's validated join may be used.
    join_path=path/'thread_join.json'
    if join_path.exists():
        os_by_start={int(w['start_mach_ns']):w for w in json.loads(join_path.read_text())}
    trace=json.loads((path/'trace_validation.json').read_text()) if (path/'trace_validation.json').exists() else {}
    events=[]
    shortage_indices=[]
    for index,c in enumerate(callbacks):
        missing=int(c['wanted'])-int(c['received'])
        if missing<=0: continue
        shortage_indices.append(index)
        at=int(c['callback_start_mach_ns']);following=bisect_right(ends,at)
        worker=workers[following] if following<len(workers) else None
        previous=workers[following-1] if following else None
        evidence=os_by_start.get(int(worker['start_mach_ns'])) if worker else None
        os_valid=(trace.get('TRACE_CAPTURE')=='PASS' and trace.get('TRACE_ANALYSIS')=='PASS' and
                  evidence is not None and evidence['coverage_fraction']>=.99 and evidence['known_fraction']>=.95)
        states=evidence.get('states_ns',{}) if evidence else {}
        observed=[name for name,ns in states.items() if ns>0 and name!='Unknown'] if os_valid else []
        events.append(dict(callback_sequence=int(c['sequence']),callback_tid=int(c['thread_id']),
            start_mach_ns=at,end_mach_ns=int(c['callback_end_mach_ns']),
            host_mach_ns=int(c['host_mach_ns']),epoch=int(c['epoch']),generation=int(c['generation']),
            missing_frames=missing,fifo_available=int(c['available_before']),
            previous_publication=previous,next_publication=worker,
            same_run_trace_evidence=evidence,
            observed_os_states=observed,cause='UNRESOLVED',
            reason='No sufficient same-run OS coverage' if not os_valid else
                'OS states observed; underlying scheduler/wait mechanism requires causal interpretation'))
    episodes=[]
    for index in shortage_indices:
        c=callbacks[index]
        if not episodes or index!=episodes[-1]['last_index']+1:
            episodes.append(dict(first_index=index,last_index=index,first_sequence=int(c['sequence']),
                start_mach_ns=int(c['callback_start_mach_ns']),end_mach_ns=int(c['callback_end_mach_ns']),
                missing_frames=0,calls=0))
        e=episodes[-1];e['last_index']=index;e['end_mach_ns']=int(c['callback_end_mach_ns'])
        e['missing_frames']+=int(c['wanted'])-int(c['received']);e['calls']+=1
    for e in episodes:
        e['missing_audio_ms']=e['missing_frames']*1000/float(values['dsp_sample_rate'])
        lo=max(0,e['first_index']-50);hi=min(len(callbacks),e['last_index']+51)
        with (path/f"underrun_{e['first_sequence']}_timeline.csv").open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(callbacks[0]),lineterminator='\n')
            writer.writeheader();writer.writerows(callbacks[lo:hi])
    gaps=[float(w['publication_interval_s'])*1000 for w in workers if float(w['publication_interval_s'])>=0]
    fifo=[int(c['available_before']) for c in callbacks if int(c['pcm_before'])+int(values['lead_limit_frames'])<int(values['output_length'])]
    result=dict(CSV_INTEGRITY='PASS',missing_frames=sum(e['missing_frames'] for e in events),underrun_calls=len(events),
        episodes=episodes,events=events,max_continuous_missing_ms=max((e['missing_audio_ms'] for e in episodes),default=0),
        fifo_minimum_active=min(fifo,default=None),publication_gap_max_ms=max(gaps,default=None),
        publication_gap_p95_ms=percentile(gaps,.95),publication_gap_p99_ms=percentile(gaps,.99),
        callback_records_evicted=values.get('callback_records_evicted','unmeasured'),
        worker_records_dropped=values.get('worker_profile_records_dropped','unmeasured'),
        complete_record=values.get('callback_records_evicted')=='0' and values.get('worker_profile_records_dropped')=='0')
    (path/'forensics.json').write_text(json.dumps(result,indent=2))
    return {k:v for k,v in result.items() if k not in ('events','episodes')}
