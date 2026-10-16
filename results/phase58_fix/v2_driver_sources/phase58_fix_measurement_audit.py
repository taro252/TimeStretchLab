"""Recompute native callback/FIFO evidence after all device trials stop."""
import argparse
import csv
import json
import math
from pathlib import Path
from phase57_study import ROOT

def main(a):
    base=ROOT/'results/phase58_fix'; records=[]
    for path in sorted(base.rglob('summary.json')):
        d=json.loads(path.read_text()); source=path.with_name('callbacks.csv')
        if not isinstance(d,dict) or 'dsp_thread' not in d or not source.exists():continue
        total=missing=calls=sequence=maximum=consecutive=0; durations=[]; valid=True
        for r in csv.DictReader(source.open()):
            sequence+=1; received=int(r['received']); wanted=int(r['wanted']); gap=wanted-received
            valid &= int(r['sequence'])==sequence and int(r['output_before'])==total
            valid &= 0<=received<=wanted<=int(r['requested'])
            total+=received; missing+=gap; calls+=gap>0
            consecutive=(gap if received else consecutive+gap) if gap else 0; maximum=max(maximum,consecutive)
            duration=int(r['end_ns'])-int(r['start_ns']); valid &= duration>=0; durations.append(duration)
        durations.sort()
        q=lambda v:durations[min(len(durations)-1,math.ceil(len(durations)*v)-1)]
        exact=valid and bool(durations) and total==d['consumed_frames'] and missing==d['missing_frames'] and calls==d['missing_calls'] and maximum==d['max_consecutive_missing'] and sequence==d['callback_calls'] and max(durations)==d['callback_max_ns'] and q(.95)==d['callback_p95_ns'] and q(.99)==d['callback_p99_ns'] and not d['callback_records_dropped']
        records.append(dict(path=str(path.relative_to(base)),PASS=bool(exact),audio_trial_pass=bool(d['PASS']),
                            frames=total,missing_frames=missing,missing_calls=calls,max_consecutive_missing=maximum,callbacks=sequence))
    result=dict(PASS=bool(records) and all(r['PASS'] for r in records),sessions=len(records),
                callbacks=sum(r['callbacks'] for r in records),records=records,
                scope='CSV counter consistency; an audio FAIL is retained and is not converted to audio PASS')
    a.output.write_text(json.dumps(result,indent=2)+'\n'); print('Native CSV audit',result['sessions'],result['callbacks'],result['PASS'])
    return 0 if result['PASS'] else 2

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():p.error('Fresh output required')
    raise SystemExit(main(a))
