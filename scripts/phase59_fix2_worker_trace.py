"""保存済みの短尺動的トレースを実時間区間・バッファと照合する。"""
import csv
import json
from collections import Counter
from phase59_fix2_start_state import ROOT, OUT, sha
from phase58_fix_trace_analyze import table, number, IntervalIndex, classify


def main():
    native=ROOT/'build/phase59_fix2_artifacts/dynamic_no_request_trace_native'
    xml=ROOT/'build/phase59_fix2_artifacts/trace_dynamic_no_request/xml'
    summary=json.loads((native/'summary.json').read_text());tid=summary['dsp_thread']
    clock=table(xml/'time-info.xml')[0];numer,denom=map(int,clock['timebase-info']['fmt'].split('/'))
    epoch=number(clock,'mabs-epoch')*numer/denom
    states,calls,faults=[table(xml/(name+'.xml'),{tid}) for name in ('thread-state','syscall','virtual-memory')]
    indices=[IntervalIndex(rows) for rows in (states,calls,faults)]
    intervals=[]
    with (native/'intervals.csv').open() as file:
        for row in csv.DictReader(file):
            scale=int(row['timebase_numer'])/int(row['timebase_denom'])
            start=int(row['start_ticks'])*scale-epoch;end=int(row['end_ticks'])*scale-epoch
            os=classify(start,end,*indices)
            intervals.append(dict(record=row,trace_start_ns=start,trace_end_ns=end,os=os,
                                  fully_observed=os['unobserved_s']<=1e-9 and os['state_seconds'].get('Unknown',0)<=1e-9))
    with (native/'memory_regions.csv').open() as file:regions=list(csv.DictReader(file))
    observations=[]
    for fault in faults:
        # Export schema may omit an address. An omitted address is never a match.
        value=fault.get('address',{}).get('value');address=None
        if value is not None:
            try:address=int(value,0)
            except ValueError:pass
        matches=[r['name'] for r in regions if address is not None and int(r['address'])<=address<int(r['address'])+int(r['bytes'])]
        observations.append(dict(event=fault,registered_region_matches=matches,address_available=address is not None))
    destination=ROOT/'build/phase59_fix2_artifacts/trace_dynamic_no_request/worker_os_timeline.json'
    with destination.open('x') as file:json.dump(dict(intervals=intervals,worker_faults=observations,registered_regions=regions),file,ensure_ascii=False,indent=2);file.write('\n')
    result=dict(intervals=len(intervals),fully_observed=sum(r['fully_observed'] for r in intervals),
                unknown_or_unobserved=sum(not r['fully_observed'] for r in intervals),
                state_rows=len(states),syscall_rows=len(calls),fault_rows=len(faults),
                realtime_interval_fault_observations=sum(len(r['os']['faults']) for r in intervals),
                observed_priorities=sorted({r['priority']['fmt'] for r in states}),
                operations=dict(Counter(r.get('operation',{}).get('fmt','unknown') for r in faults)),
                address_registered_region_matches=sum(bool(r['registered_region_matches']) for r in observations),
                payload=str(destination),payload_sha256=sha(destination),
                scope='短尺・変更要求なしの28実時間区間だけ。登録領域は診断/capture配列のみ。DSP scratch/Accelerate全領域の帰属と、圧縮復帰の排除は未成立。')
    (OUT/'REALTIME_WORKER_TRACE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
