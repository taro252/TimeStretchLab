#!/usr/bin/env python3
"""Stable-ID resume; all saved results immutable, journal is append-only."""
import argparse,csv,hashlib,json,subprocess,time,uuid
from pathlib import Path
from phase46_native import run
from phase48_metrics import measure
from phase49_diagnostics import analyze
from phase45_store import parse_log
from phase51_resume import matrix,reconcile,register,finish
ROOT=Path(__file__).resolve().parents[1]
def buffer(n=None):
    r=subprocess.run([str(ROOT/'build/phase50_device_buffer')]+([] if n is None else [str(n)]),capture_output=True,text=True,check=True)
    return parse_log(r.stdout)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'results/phase50/resilience')
    parser.add_argument('--state-dir',type=Path,default=ROOT/'results/phase51/resume_audit')
    args=parser.parse_args();output=args.output;cases=matrix()
    input=ROOT/'results/phase49/input/drums30.wav';input_sha=hashlib.sha256(input.read_bytes()).hexdigest()
    if args.resume:
        states=reconcile(output,cases,input_sha)
    else:
        output.mkdir(parents=True,exist_ok=True)
        if (output/'manifest.json').exists():raise FileExistsError('Fresh output required')
        (output/'manifest.json').write_text(json.dumps(dict(matrix=cases,input_sha256=input_sha,
            native_sha256=hashlib.sha256((ROOT/'build/phase50_play').read_bytes()).hexdigest()),indent=2))
        states=reconcile(output,cases,input_sha)
    before_ids={s['case_id'] for s in states}
    pending=[s for s in states if s['status']=='NOT_RUN']
    needs_attention=[s for s in states if s['status'] in ('FAILED','RETRY_REQUIRED')]
    args.state_dir.mkdir(parents=True,exist_ok=True)
    audit=args.state_dir/(uuid.uuid4().hex+'.json')
    audit.write_text(json.dumps(dict(states=states,pending=len(pending),needs_attention=len(needs_attention)),indent=2))
    if needs_attention:return 3 # No automatic retry or duplicate registration.
    if not pending:
        print('RESUME_COMPLETE: no cases executed; completed and unsupported retained')
        return 0
    m=json.loads((output/'manifest.json').read_text())
    if m['native_sha256']!=hashlib.sha256((ROOT/'build/phase50_play').read_bytes()).hexdigest():
        raise ValueError('Executable changed; pending resume refused')
    original=int(buffer()['buffer_frames'])
    try:
      for state in pending:
        ordinal=state['ordinal'];case=state['case'];event=register(output,case)
        print('BEGIN',ordinal,case,flush=True)
        buffer(case['callback']);time.sleep(.5);actual=int(buffer()['buffer_frames'])
        if actual!=case['callback']:
            finish(event,'UNSUPPORTED',dict(ordinal=ordinal,**case,actual_frames=actual,status='UNSUPPORTED_DEVICE_QUANTUM'))
            continue
        row,path=run(output,minutes=.5,stress=case['stress'],candidate='A',stall=case['dose'],lead_frames=case['lead'],
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

        finish(event,'COMPLETED' if good else 'FAILED',item)
        if not good:break
    finally:
        buffer(original)
        with (output/('restored_device_'+uuid.uuid4().hex+'.json')).open('x') as f:json.dump(buffer(),f)
    after=reconcile(output,cases,input_sha)
    if {s['case_id'] for s in after}!=before_ids:raise RuntimeError('Case set changed during resume')
    with (args.state_dir/(uuid.uuid4().hex+'.json')).open('x') as f:json.dump(dict(states=after),f,indent=2)
    return 2 if any(s['status'] not in ('COMPLETED','UNSUPPORTED') for s in after) else 0
if __name__=='__main__':raise SystemExit(main())
