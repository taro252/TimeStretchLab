#!/usr/bin/env python3
"""Bounded 3-way completion and simultaneous high-load pause study."""
import csv,json,hashlib,os
from pathlib import Path
from phase46_native import run
from phase48_metrics import measure
from phase51_timing import analyze
from phase49_diagnostics import analyze as stall_analyze
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase51/native'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'manifest.json').exists():raise SystemExit('Fresh native output required')
    cases=[dict(label=l,precise=p,planning=m,stress=False,dose=0,policy='defer',kind='t1p85') for l,p,m in [('C',False,'C'),('C_L1',True,'C'),('C_L1_L2',True,'L2')]]
    cases += [dict(label=l,precise=p,planning=m,stress=True,dose=d,policy='latest',kind='busy_stall',at=at) for d,at in [(200,4.5),(250,6.25),(300,13.5)] for l,p,m in [('C',False,'C'),('C_L1',True,'C'),('C_L1_L2',True,'L2')]]
    cases += [dict(label='C_L1_L2',precise=True,planning='L2',stress=False,dose=0,policy=p,kind='short200') for p in ('latest','defer')]
    input=ROOT/'results/phase49/input/drums30.wav'
    (OUT/'manifest.json').write_text(json.dumps(dict(cases=cases,input_sha256=hashlib.sha256(input.read_bytes()).hexdigest(),binary_sha256=hashlib.sha256((ROOT/'build/phase51_play').read_bytes()).hexdigest(),lead=16384,fifo=16384,block=2048,trace=False,device_quantum=512),indent=2))
    rows=[]
    for ordinal,case in enumerate(cases,1):
        seq=[(1.85,2),(6.85,.4),(14.85,1),(22.85,2)] if case['kind']=='t1p85' else [(1.85,2),(2.05,.4),(14.85,1),(15.05,2)] if case['kind']=='busy_stall' else [(1.85,2),(2.05,.75),(2.25,1.5)]
        schedule=OUT/f'schedule_{ordinal}.csv';schedule.write_text('output_seconds,target_speed\n'+''.join(f'{at},{speed}\n' for at,speed in seq))
        print('BEGIN',ordinal,case,flush=True)
        row,path=run(OUT,minutes=.5,stress=case['stress'],lead_frames=16384,input_override=input,executable=ROOT/'build/phase51_play',precise_boundary=case['precise'],schedule_override=schedule,
            planning=case['planning'],control_policy=case['policy'],wall_schedule=True,stall=case['dose'],stall_output=round(case.get('at',4.5)*48000),stall_fifo=16384)
        metric=measure(row,path,dict(ordinal=ordinal,**case),expected_lead=16384)
        timing=analyze(path,input,case['planning'])
        pause=None
        if case['dose']:
            # Phase49 budget identity only describes its legacy boundary. Pass
            # an empty-replay staging directory for the unchanged pause physics.
            scratch=path/'pause_analysis';scratch.mkdir();(scratch/'replay.csv').write_text('generation\n')
            for name in ('callbacks.csv','workers.csv'):os.symlink('../'+name,scratch/name)
            pause=stall_analyze(scratch,row)['controlled_pause']
        states=timing['states'];terminal=all(s in ('Completed','Replaced','Duplicate','BusyRejected','Rejected','Stopped') for s in states)
        item=dict(ordinal=ordinal,path=str(path),**case,AUDIO_QUALITY=metric['AUDIO_QUALITY'],MEASUREMENT_QUALITY=metric['MEASUREMENT_QUALITY'],CSV_INTEGRITY=metric['CSV_INTEGRITY'],METRIC_INTEGRITY=metric['METRIC_INTEGRITY'],PCM_CORRECTNESS=metric['PCM_CORRECTNESS'],NATIVE_STABILITY_VERDICT=metric['NATIVE_STABILITY_VERDICT'],
            missing_frames=int(row['underrun_frames']),underrun_calls=int(row['underrun_calls']),fifo_minimum=int(row['fifo_minimum_active']),continuous_ms=float(row['max_continuous_missing_ms']),callback_ms=metric['callback_wall_ms'],publication_ms=metric['publication_interval_s_ms'],dsp_ms=metric['dsp_wall_s_ms'],rss_mib=float(row['peak_rss_mib']),cpu_user=float(row['cpu_user_seconds']),cpu_system=float(row['cpu_system_seconds']),timing=timing,pause=pause,
            CONTROL_TERMINAL='PASS' if terminal else 'FAIL',eos=row['eos_drained'])
        if pause:item['FAULT_DETECTION']='PASS' if pause['INJECTION_VALIDITY']=='PASS' and pause['demand_balance_matches'] and (not item['missing_frames'] or item['AUDIO_QUALITY']=='FAIL') else 'FAIL'
        rows.append(item);(OUT/'summary.json').write_text(json.dumps(rows,indent=2,allow_nan=False))
        print('END',ordinal,item['NATIVE_STABILITY_VERDICT'],states,item['missing_frames'],flush=True)
    # Experiment completion never promotes intentionally failed audio.
    print('EXPERIMENT_COMPLETE; all trial qualities saved',flush=True)
    if any(r['NATIVE_STABILITY_VERDICT']!='PASS' for r in rows):raise SystemExit(2)
if __name__=='__main__':main()
