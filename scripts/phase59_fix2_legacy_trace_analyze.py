"""製品FIFOの生成・公開・消費とOSの実測区間を直接照合する。"""
import argparse
import csv
import json
import re
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha
from phase59_fix2_trace_analyze import export
from phase59_fix2_legacy_analyze import analyze
from phase58_fix_trace_analyze import table, number, IntervalIndex, classify


def publication_profiles(workers):
    unpublished=[];unique={};duplicates=[]
    for w in workers:
        if not int(w['thread_id']) or int(w['published_mach_ns'])<=int(w['start_mach_ns']) or not int(w['pcm_ready_mach_ns']):
            unpublished.append(w);continue
        key=(w['session'],w['thread_id'],w['published_mach_ns'])
        if key in unique:duplicates.append(w)
        else:unique[key]=w
    return list(unique.values()),unpublished,duplicates


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--name',required=True)
    parser.add_argument('--native',type=Path,required=True);parser.add_argument('--existing-xml',type=Path)
    parser.add_argument('--result-tag',default='')
    args=parser.parse_args();native=args.native.resolve()
    trace=ROOT/'build/phase59_fix2_artifacts'/('trace_'+args.name);xml=args.existing_xml or trace/'xml'
    assert (OUT/('trace_'+args.name)/'manifest.json').exists(),'Acquisition must finish before export'
    exports=json.loads((xml/'exports.json').read_text()) if args.existing_xml else export(trace/'recording.trace',xml)
    clock=table(xml/'time-info.xml')[0];numer,denom=map(int,clock['timebase-info']['fmt'].split('/'))
    epoch=number(clock,'mabs-epoch')*numer/denom
    summary=dict(line.split('=',1) for line in (native/'summary.txt').read_text().splitlines() if '=' in line)
    findings=analyze(native);workers=[]
    for path in [*native.glob('worker_*.csv'),*native.glob('retired_worker_*.csv')]:
        workers += [dict(r,source=str(path)) for r in csv.DictReader(path.open())]
    # A reconstruction hook without publication is not an observed OS interval.
    raw_profiles=len(workers);workers,unpublished,duplicates=publication_profiles(workers)
    tids={int(w['thread_id']) for w in workers}
    states=table(xml/'thread-state.xml',tids);calls=table(xml/'syscall.xml',tids);faults=table(xml/'virtual-memory.xml',tids)
    by_thread={tid:[IntervalIndex([r for r in rows if r['thread']['tid']==tid]) for rows in (states,calls,faults)] for tid in tids}
    pids={r['thread']['pid'] for r in states}
    acquisition=json.loads((OUT/('trace_'+args.name)/'manifest.json').read_text())
    if acquisition.get('target_pid') is not None:pids.add(acquisition['target_pid'])
    else:
        command=acquisition['command'];target=command[command.index('--')+1]
        log=trace/'target.log'
        if log.exists():pids.update(map(int,re.findall(re.escape(Path(target).name)+r'\[(\d+):',log.read_text())))
    joined=[]
    for w in workers:
        tid=int(w['thread_id']);begin=int(w['start_mach_ns'])-epoch;ready=int(w['pcm_ready_mach_ns'])-epoch
        writing=int(w['write_begin_mach_ns'])-epoch;end=int(w['published_mach_ns'])-epoch
        assert begin<=ready<=writing<=end,(w,begin,ready,writing,end)
        parts={label:classify(lo,hi,*by_thread[tid]) for label,lo,hi in
               [('produce_to_ready',begin,ready),('ready_to_write',ready,writing),('write_to_publication',writing,end),('full_cycle',begin,end)]}
        joined.append(dict(worker=w,trace_begin_ns=begin,trace_ready_ns=ready,trace_published_ns=end,os=parts,
                           fully_observed=parts['full_cycle']['unobserved_s']<=1e-9 and parts['full_cycle']['state_seconds'].get('Unknown',0)<=1e-9))
    all_io=table(xml/'audio-hal-client-io-cycle-ioproc.xml')
    io=[r for r in all_io if r.get('thread',{}).get('pid') in pids]
    callback_tids={r['thread']['tid'] for r in io}
    cb_states=table(xml/'thread-state.xml',callback_tids);cb_calls=table(xml/'syscall.xml',callback_tids);cb_vm=table(xml/'virtual-memory.xml',callback_tids)
    cb_indices={tid:[IntervalIndex([r for r in rows if r['thread']['tid']==tid]) for rows in (cb_states,cb_calls,cb_vm)] for tid in callback_tids}
    callback_coverage=[]
    for path in sorted(native.glob('callbacks_*.csv')):
        for cb in csv.DictReader(path.open()):
            start=int(cb['start_ns'])-epoch;end=int(cb['end_ns'])-epoch
            matching={r['thread']['tid'] for r in io if number(r,'start')<=start<number(r,'start')+number(r,'duration')}
            observed={tid:classify(start,end,*cb_indices[tid]) for tid in matching}
            known=len(matching)==1 and all(o['unobserved_s']<=1e-9 and o['state_seconds'].get('Unknown',0)<=1e-9 for o in observed.values())
            callback_coverage.append(dict(source=str(path),callback=cb,trace_start_ns=start,trace_end_ns=end,os=observed,fully_observed=known))
    for shortage in findings['shortages']:
        cb=shortage['callback'];start=int(cb['start_ns'])-epoch;end=int(cb['end_ns'])-epoch
        matching=[r for r in io if number(r,'start')<=start<number(r,'start')+number(r,'duration')]
        shortage['ioproc']=matching
        matching_tids={r['thread']['tid'] for r in matching}
        shortage['callback_os']={tid:classify(start,end,*cb_indices[tid]) for tid in matching_tids}
        shortage['next_producer_os']=[r for r in joined if shortage['next_publication'] and r['worker']['session']==cb['session'] and r['worker']['published_mach_ns']==shortage['next_publication']['published_mach_ns']]
    hal=table(xml/'audio-hal-client-poi.xml')
    overloads=[r for r in hal if 'Overload' in str(r.get('description',{}).get('fmt')) and any(v.get('pid') in pids for v in r.values())]
    suffix=('_'+args.result_tag) if args.result_tag else ''
    payload=trace/('legacy_os_timeline'+suffix+'.json')
    with payload.open('x') as f:json.dump(dict(trace_epoch_ns=epoch,target_pids=sorted(pids),findings=findings,workers=joined,callback_coverage=callback_coverage,non_publication_profiles=unpublished,duplicate_profiles=duplicates,hal=hal,target_overloads=overloads),f,ensure_ascii=False,indent=2);f.write('\n')
    known=[r for r in joined if r['fully_observed']]
    result=dict(native_summary=summary,raw_profile_records=raw_profiles,non_publication_profile_records=len(unpublished),duplicate_profile_records=len(duplicates),workers=len(joined),fully_observed_workers=len(known),
                unknown_or_unobserved_workers=len(joined)-len(known),missing_callbacks=len(findings['shortages']),
                target_pids=sorted(pids),callbacks=len(callback_coverage),fully_observed_callbacks=sum(r['fully_observed'] for r in callback_coverage),first_three_callback_coverage=[r['fully_observed'] for r in callback_coverage[:3]],
                missing_frames=sum(s['missing_frames'] for s in findings['shortages']),target_os_client_overloads=len(overloads),
                observed_priorities=sorted({r['priority']['fmt'] for r in states}),
                payload=str(payload),payload_sha256=sha(payload),exports=exports,
                scope='旧製品workerの周期は実時間Workgroup区間ではない。publish入口前の区間にはDSP/WAV/計画/前回後処理が含まれ、Wall-CPUだけでPreemptedと呼ばない。')
    with (OUT/('LEGACY_TRACE_ANALYSIS_'+args.name+suffix+'.json')).open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print('legacy trace',args.name,'missing',result['missing_frames'],'known cycles',len(known),'/',len(joined),flush=True)


if __name__=='__main__':main()
