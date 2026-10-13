#!/usr/bin/env python3
"""Finite pause-duration matrix. Fault detection PASS is not audio PASS."""
import csv,json,time,hashlib
from pathlib import Path
from phase46_native import run
from phase48_metrics import measure
from phase49_diagnostics import analyze
root=Path(__file__).resolve().parents[1]
out=root/'results/phase49/resilience';out.mkdir(parents=True,exist_ok=True)
if (out/'summary.json').exists():raise SystemExit('Use fresh experiment artifacts; results already exist')
matrix=[dict(candidate=q,dose=d,lead=12288,fifo=16384,label='standard') for d in (100,150,200,250,300,350) for q in ('A','B')]
matrix += [dict(candidate='A',dose=d,lead=14336,fifo=16384,label='lead14336') for d in (250,300,350)]
matrix += [dict(candidate='A',dose=d,lead=16384,fifo=16384,label='lead16384') for d in (300,350)]
matrix += [dict(candidate='A',dose=300,lead=12288,fifo=32768,label='capacity_only')]
(out/'experiment_manifest.json').write_text(json.dumps(dict(matrix=matrix,input='results/phase49/input/drums30.wav',
    input_sha256=hashlib.sha256((root/'results/phase49/input/drums30.wav').read_bytes()).hexdigest(),
    native_sha256=hashlib.sha256((root/'build/phase43_play').read_bytes()).hexdigest(),
    source_rate=48000,stall_output_threshold=216000,load='normal',nominal_callback=512,
    note='Controlled pause at exact FIFO stock, no concurrent DSP workload, no product default changes'),indent=2))
rows=[]
for index,case in enumerate(matrix,1):
    print('INJECTION_BEGIN',index,len(matrix),case,flush=True)
    row,path=run(out,minutes=.5,trace=False,stress=False,candidate=case['candidate'],stall=case['dose'],fifo_frames=case['fifo'],lead_frames=case['lead'],
                 stall_output=216000,stall_fifo=case['lead'],input_override=root/'results/phase49/input/drums30.wav')
    measured=measure(row,path,dict(ordinal=index,round=1,order='injection',**case),expected_fifo=case['fifo'],expected_lead=case['lead'])
    diagnostic=analyze(path,measured);pause=diagnostic['controlled_pause']
    # The functional test succeeds even when deliberately long pauses produce
    # correct AUDIO_QUALITY=FAIL; those failed audio records stay unchanged.
    detected=(pause['INJECTION_VALIDITY']=='PASS' and measured['METRIC_INTEGRITY']=='PASS' and measured['MEASUREMENT_QUALITY']=='PASS' and
              measured['PCM_CORRECTNESS']=='PASS' and pause['demand_balance_matches'] and
              (not int(measured['underrun_frames']) or measured['AUDIO_QUALITY']=='FAIL'))
    item=dict(ordinal=index,run_id=path.name,**case,AUDIO_QUALITY=measured['AUDIO_QUALITY'],MEASUREMENT_QUALITY=measured['MEASUREMENT_QUALITY'],
              METRIC_INTEGRITY=measured['METRIC_INTEGRITY'],FAULT_DETECTION='PASS' if detected else 'FAIL',missing_frames=int(measured['underrun_frames']),
              max_continuous_missing_ms=measured['max_continuous_missing_ms'],peak_rss_mib=measured['peak_rss_mib'],direction_latency=measured['direction_latency'],**pause)
    rows.append(item);(out/'summary.json').write_text(json.dumps(rows,indent=2,allow_nan=False))
    fields=['ordinal','run_id','label','candidate','dose','lead','fifo','AUDIO_QUALITY','MEASUREMENT_QUALITY','METRIC_INTEGRITY','FAULT_DETECTION','missing_frames','max_continuous_missing_ms','measured_ms','theoretical_stock_ms','effective_supply_stop_ms','first_missing_callback_ms','shortage_recovery_after_end_ms','full_stock_recovery_after_end_ms','demand_balance_matches','peak_rss_mib']
    with (out/'summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows({k:r.get(k) for k in fields} for r in rows)
    print('INJECTION_END',index,item['AUDIO_QUALITY'],item['missing_frames'],item['FAULT_DETECTION'],flush=True)
    time.sleep(2)
print('Resilience experiment complete; audio FAILs retained',flush=True)
if any(r['FAULT_DETECTION']!='PASS' for r in rows):raise SystemExit(2)
