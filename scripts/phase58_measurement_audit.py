"""Recompute native counters from callback CSV; run after all audio has stopped."""
import argparse,csv,json,math,statistics
from pathlib import Path
from phase57_study import ROOT
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert not a.output.exists()
base=ROOT/'results/phase58'
scopes=('startup_final','lifecycle_load_final','native_gate_product_final','native_long_final','notification_lifecycle_final','startup_after_ready_fix','reproduce_after_ready_fix')
expected=168+(60 if (base/'startup_after_ready_fix/summary.json').exists() else 0)+(20 if (base/'reproduce_after_ready_fix/summary.json').exists() else 0)
records=[]
for scope in scopes:
    for path in sorted((base/scope).rglob('summary.json')):
        d=json.loads(path.read_text());csvpath=path.parent/'callbacks.csv'
        if not csvpath.exists() or 'callback_calls' not in d:continue
        total=missing=calls=sequence=maximum=consecutive=0;durations=[]
        with csvpath.open() as stream:
            for r in csv.DictReader(stream):
                sequence+=1;received=int(r['received']);wanted=int(r['wanted']);gap=wanted-received
                assert int(r['sequence'])==sequence and int(r['output_before'])==total
                assert 0<=received<=wanted<=int(r['requested'])
                total+=received;missing+=gap;calls+=gap>0
                consecutive=(gap if received else consecutive+gap) if gap else 0;maximum=max(maximum,consecutive)
                duration=int(r['end_ns'])-int(r['start_ns']);assert duration>=0;durations.append(duration)
        durations.sort()
        q=lambda v:durations[min(len(durations)-1,math.ceil(len(durations)*v)-1)]
        exact=total==d['consumed_frames'] and missing==d['missing_frames'] and calls==d['missing_calls'] and maximum==d['max_consecutive_missing'] and sequence==d['callback_calls'] and max(durations)==d['callback_max_ns'] and q(.95)==d['callback_p95_ns'] and q(.99)==d['callback_p99_ns'] and not d['callback_records_dropped']
        records.append(dict(path=str(path.relative_to(base)),PASS=exact,frames=total,missing_frames=missing,missing_calls=calls,max_consecutive_missing=maximum,callbacks=sequence))
result=dict(PASS=len(records)==expected and all(r['PASS'] for r in records),expected_sessions=expected,sessions=len(records),callbacks=sum(r['callbacks'] for r in records),records=records)
a.output.write_text(json.dumps(result,indent=2)+'\n');print('Native CSV audit',result['sessions'],result['callbacks'],result['PASS']);raise SystemExit(0 if result['PASS'] else 2)
