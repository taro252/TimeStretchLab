#!/usr/bin/env python3
"""Bounded real-device pause/lead study; detection PASS never replaces audio FAIL."""
import csv,hashlib,json,subprocess,time
from pathlib import Path
from phase46_native import run
from phase48_metrics import measure
from phase49_diagnostics import analyze
from phase45_store import parse_log
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase50/resilience'
OUT.mkdir(parents=True,exist_ok=True)
resume=__import__('sys').argv[1:]==['--resume']
if (OUT/'manifest.json').exists() and not resume:raise SystemExit('Fresh results directory required')
helper=ROOT/'build/phase50_device_buffer'
def buffer(n=None):
    result=subprocess.run([str(helper)]+([] if n is None else [str(n)]),capture_output=True,text=True,check=True)
    return parse_log(result.stdout)
original=int(buffer()['buffer_frames'])
matrix=[dict(label=label,lead=lead,stock=lead,dose=d,callback=512,stress=False,at=216000,drain=False)
        for d in (200,250,300,350) for label,lead in [('A',12288),('B',14336),('C',16384)]]
matrix += [dict(label='C',lead=16384,stock=16384,dose=300,callback=n,stress=True,at=648000,drain=False) for n in (64,128,256,1024)]
matrix += [dict(label='A',lead=12288,stock=8192,dose=250,callback=512,stress=True,at=300000,drain=True),
           dict(label='C',lead=16384,stock=12288,dose=300,callback=512,stress=True,at=300000,drain=True)]
matrix.append(dict(label='C',lead=16384,stock=16384,dose=300,callback=512,stress=True,at=648000,drain=False))
input=ROOT/'results/phase49/input/drums30.wav'
if not resume:(OUT/'manifest.json').write_text(json.dumps(dict(matrix=matrix,original_buffer=original,
    input_sha256=hashlib.sha256(input.read_bytes()).hexdigest(),native_sha256=hashlib.sha256((ROOT/'build/phase50_play').read_bytes()).hexdigest(),
    note='A/B/C labels denote lead only; inherited QoS/block2048/FIFO16384 are unchanged. Two preparatory-drain trials have extra supply gaps and are identified separately.'),indent=2))
rows=json.loads((OUT/'summary.json').read_text()) if resume else []
unsupported=[]
try:
    for ordinal,case in enumerate(matrix,1):
        if ordinal<=len(rows):continue
        print('BEGIN',ordinal,len(matrix),case,flush=True)
        buffer(case['callback']);time.sleep(.5)
        actual=int(buffer()['buffer_frames'])
        if actual!=case['callback']:
            unsupported.append(dict(ordinal=ordinal,**case,actual_frames=actual,status='UNSUPPORTED_DEVICE_QUANTUM'))
            (OUT/'unsupported.json').write_text(json.dumps(unsupported,indent=2))
            print('UNSUPPORTED',ordinal,actual,flush=True);continue
        row,path=run(OUT,minutes=.5,stress=case['stress'],candidate='A',stall=case['dose'],lead_frames=case['lead'],
            stall_output=case['at'],stall_fifo=case['stock'],input_override=input,executable=ROOT/'build/phase50_play',drain_stock=case['drain'])
        m=measure(row,path,dict(ordinal=ordinal,**case),expected_lead=case['lead'],expected_hardware_frames=case['callback'])
        diag=analyze(path,m);pause=diag['controlled_pause']
        good=(pause['INJECTION_VALIDITY']=='PASS' and m['METRIC_INTEGRITY']=='PASS' and m['MEASUREMENT_QUALITY']=='PASS'
              and m['PCM_CORRECTNESS']=='PASS' and m['CONFIG_VALIDITY']=='PASS' and pause['demand_balance_matches']
              and (not int(m['underrun_frames']) or m['AUDIO_QUALITY']=='FAIL'))
        # phase49 full-stock recovery reports the controlled starting stock;
        # separately measure the requested lead for reduced-stock experiments.
        workers=list(csv.DictReader((path/'workers.csv').open()))
        end=int(row['controlled_stall_end_mach_ns'])
        full=next((w for w in workers if int(w['published_mach_ns'])>=end and int(w['fifo_after_write'])>=case['lead']),None)
        pause['target_lead_recovery_ms']=(int(full['published_mach_ns'])-end)/1e6 if full else None
        item=dict(ordinal=ordinal,path=str(path),native_sha256=hashlib.sha256((ROOT/'build/phase50_play').read_bytes()).hexdigest(),**case,FAULT_DETECTION='PASS' if good else 'FAIL',
            AUDIO_QUALITY=m['AUDIO_QUALITY'],MEASUREMENT_QUALITY=m['MEASUREMENT_QUALITY'],CONFIG_VALIDITY=m['CONFIG_VALIDITY'],
            CSV_INTEGRITY=m['CSV_INTEGRITY'],METRIC_INTEGRITY=m['METRIC_INTEGRITY'],PCM_CORRECTNESS=m['PCM_CORRECTNESS'],
            missing_frames=int(m['underrun_frames']),missing_calls=int(m['underrun_calls']),
            max_continuous_missing_ms=float(m['max_continuous_missing_ms']),fifo_minimum_active=int(m['fifo_minimum_active']),
            publication_ms=m['publication_interval_s_ms'],dsp_ms=m['dsp_wall_s_ms'],cycle_cpu_ms=m['cycle_cpu_s_ms'],
            callback_ms=m['callback_wall_ms'],cpu=float(m['cpu_user_seconds'])+float(m['cpu_system_seconds']),rss_mib=float(m['peak_rss_mib']),
            direction_latency=m['direction_latency'],pause=pause)
        rows.append(item);(OUT/'summary.json').write_text(json.dumps(rows,indent=2,allow_nan=False))
        print('END',ordinal,item['AUDIO_QUALITY'],item['missing_frames'],item['FAULT_DETECTION'],flush=True)
finally:
    buffer(original)
    (OUT/'restored_device.json').write_text(json.dumps(buffer(),indent=2))
if any(r['FAULT_DETECTION']!='PASS' for r in rows):raise SystemExit(2)
