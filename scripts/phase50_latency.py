#!/usr/bin/env python3
"""Bounded native lead/L1 study, isolated from resilience trials and DSP tests."""
import csv,json,hashlib
from pathlib import Path
from phase46_native import run
from phase48_metrics import measure
from phase46_operation import analyze
from phase49_diagnostics import analyze as budget
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase50/latency'
def main():
    proof=json.loads((ROOT/'results/phase50/l1_offline/summary.json').read_text())
    if len(proof)!=8 or any(r['PCM_CORRECTNESS']!='PASS' for r in proof):raise SystemExit('L1 offline proof incomplete')
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'manifest.json').exists():raise SystemExit('Fresh output required')
    matrix=[dict(source=s,time=t,label=l,lead=lead,precise=precise) for s in ('drums','mix') for t in (1,1.85)
            for l,lead,precise in [('A',12288,False),('C',16384,False),('C_L1',16384,True)]]
    (OUT/'manifest.json').write_text(json.dumps(dict(matrix=matrix,callback_hardware=512,load='normal',
        binary_sha256=hashlib.sha256((ROOT/'build/phase50_play').read_bytes()).hexdigest(),
        note='Four directions per trial, requests at t/t+5/t+13/t+21. Existing DSP and TimeMap ramp/guard unchanged. No trace.'),indent=2))
    rows=[]
    for ordinal,case in enumerate(matrix,1):
        input=ROOT/('results/phase50/input/mix30.wav' if case['source']=='mix' else 'results/phase49/input/drums30.wav')
        schedule=OUT/f'schedule_{ordinal}.csv'
        schedule.write_text('output_seconds,target_speed\n'+''.join(f'{at+case["time"]-1},{target}\n' for at,target in [(1,2),(6,.4),(14,1),(22,2)]))
        print('BEGIN',ordinal,case,flush=True)
        row,path=run(OUT,source=case['source'],minutes=.5,stress=False,candidate='A',lead_frames=case['lead'],input_override=input,
                     executable=ROOT/'build/phase50_play',precise_boundary=case['precise'],schedule_override=schedule)
        measured=measure(row,path,dict(ordinal=ordinal,**case),expected_lead=case['lead'])
        # Compare each change against the preceding independent history to
        # locate the first raw change; these replays run only after audio stops.
        operations=analyze(path,input,first_changes=True)
        if not case['precise']:budgets=budget(path,measured)
        else:budgets=None # legacy max-budget identity does not describe L1.
        plans=list(csv.DictReader((path/'replay.csv').open()))
        item=dict(ordinal=ordinal,path=str(path),**case,verdict=measured['NATIVE_STABILITY_VERDICT'],
            missing=int(measured['underrun_frames']),fifo_minimum=int(measured['fifo_minimum_active']),
            callback_ms=measured['callback_wall_ms'],rss_mib=measured['peak_rss_mib'],cpu_user=measured['cpu_user_seconds'],
            operations=operations,plans=plans,PCM_CORRECTNESS=measured['PCM_CORRECTNESS'])
        assert all(p['phase50_state_preserved']=='1' for p in plans)
        for p,op in zip(plans,operations['changes']):
            if op['first_raw_difference']['frame']<int(p['prepared']):raise RuntimeError('Already prepared PCM changed')
        rows.append(item);(OUT/'summary.json').write_text(json.dumps(rows,indent=2,allow_nan=False))
        print('END',ordinal,item['verdict'],flush=True)
    if any(r['verdict']!='PASS' for r in rows):raise SystemExit(2)
if __name__=='__main__':main()
