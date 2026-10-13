#!/usr/bin/env python3
"""Repeated native runs; capture, analysis, audio and PCM have distinct outcomes."""
import argparse
import csv
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from phase45_store import new_run,parse_log,save_result
from phase45_verdict import native_verdict
from phase46_trace import XCTRACE,validate_run
from phase46_forensics import investigate

ROOT=Path(__file__).resolve().parents[1]


def run(output,source='drums',minutes=3,trace=False,stress=True,candidate='A',stall=0,attach_after=80,trace_seconds=35):
    label=f'{source}_{minutes}m_{candidate}_trace{int(trace)}'
    path,identifier,at=new_run(output,label)
    input_path=ROOT/('results/phase40/long_input' if source=='drums' else 'results/phase14/benchmark')/f'{source}_repeat_{minutes*60}.wav'
    env=os.environ.copy()
    for key in ('PHASE44_WORKER_QOS','PHASE45_WORKER_STALL_MS','PHASE46_DSP_BLOCK','PHASE46_LEAD','PHASE45_ROUTE_AFTER_SECONDS'):
        env.pop(key,None)
    env.update(PHASE43_SILENT='1',PHASE46_PCM_SHA='1',PHASE45_LIVE_EVENTS=str(path/'callbacks.csv'),
        PHASE45_LIVE_WORKERS=str(path/'workers.csv'),PHASE45_LIVE_PLAN_CSV=str(path/'replay.csv'))
    if stress:env['PHASE43_STRESS']='1'
    else:env.pop('PHASE43_STRESS',None)
    if candidate=='B':env['PHASE44_WORKER_QOS']='1'
    if candidate=='C':env['PHASE46_DSP_BLOCK']='1024'
    if candidate=='E':env['PHASE46_LEAD']='14336'
    if stall:env['PHASE45_WORKER_STALL_MS']=str(stall)
    command=[str(ROOT/'build/phase43_play'),str(input_path),'0.4',str(ROOT/'results/phase45/repeated.csv')]
    trace_exit=-1
    with (path/'playback.log').open('x') as log:
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        pid=process.pid
        if trace:
            free=shutil.disk_usage(path).free
            (path/'trace_storage.json').write_text(json.dumps(dict(free_bytes=free,limit_seconds=trace_seconds),indent=2))
            if free<6*1024**3:
                (path/'xctrace.log').write_text('Recording failed: free disk below 6 GiB safety threshold')
            else:
                until=time.monotonic()+attach_after
                while time.monotonic()<until and process.poll() is None: time.sleep(.1)
                if process.poll() is None:
                    try:
                        recorder=subprocess.Popen(XCTRACE+['record','--template','System Trace','--time-limit',f'{trace_seconds}s',
                            '--window',f'{trace_seconds}s','--output',str(path/'system.trace'),'--attach',str(pid)],
                            cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                        try:
                            stdout,stderr=recorder.communicate(timeout=trace_seconds+90)
                        except subprocess.TimeoutExpired:
                            import signal
                            recorder.send_signal(signal.SIGINT)
                            try:stdout,stderr=recorder.communicate(timeout=30)
                            except subprocess.TimeoutExpired:
                                recorder.kill();stdout,stderr=recorder.communicate()
                            stderr+='\nRecording failed: xctrace timeout; graceful stop attempted\n'
                        trace_exit=recorder.returncode
                        (path/'xctrace.log').write_text(stdout+stderr)
                    except OSError as error:
                        (path/'xctrace.log').write_text(f'Recording failed: {error}')
                else:(path/'xctrace.log').write_text('Recording failed: target exited before attach')
        try:code=process.wait(timeout=minutes*240+120)
        except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10);code=124
    values=parse_log((path/'playback.log').read_text())
    row=dict(run_id=identifier,run_time=at,source=source,input_minutes=minutes,input_path=str(input_path),
        candidate=candidate,stress=int(stress),trace_requested=int(trace),profile=1,process_pid=pid,
        stall_injected_ms=stall,attach_after_seconds=attach_after,exit_code=code)
    row.update(values);row.update(native_verdict(values,code))
    if trace:row.update(validate_run(path,trace_exit,code,pid))
    else:row.update(TRACE_CAPTURE='NOT_REQUESTED',TRACE_ANALYSIS='NOT_REQUESTED')
    if (path/'workers.csv').exists() and (path/'callbacks.csv').exists():row.update(investigate(path,values))
    # No reference synthesis competes with the realtime workload: verify afterwards.
    reference=path/'reference.wav'
    ref=subprocess.run([str(ROOT/'build/phase39_reference'),str(input_path),str(reference),
        '0.4',str(path/'replay.csv'),'C','safe-density'],cwd=ROOT,capture_output=True,text=True,timeout=1800)
    (path/'reference.log').write_text(ref.stdout+ref.stderr)
    checked={}
    if ref.returncode==0:
        digest=subprocess.run([str(ROOT/'build/phase45_pcm_hash'),str(reference)],capture_output=True,text=True)
        checked=parse_log(digest.stdout);(path/'reference_hash.log').write_text(digest.stdout+digest.stderr)
    match=(ref.returncode==0 and values.get('worker_pcm_hash_enabled')=='1' and
        checked.get('pcm_sha256') is not None and values.get('worker_pcm_sha256')==checked['pcm_sha256'] and
        checked.get('frames')==values.get('output_length') and checked.get('nonfinite')=='0')
    row['PCM_CORRECTNESS']='PASS' if match else 'FAIL'
    if not match:row['AUDIO_QUALITY']='FAIL'
    save_result(output,path,row)
    print(identifier,row['AUDIO_QUALITY'],row['MEASUREMENT_QUALITY'],row['TRACE_CAPTURE'],row['TRACE_ANALYSIS'],flush=True)
    return row,path


def main(default_trace=False):
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'results/phase46/native')
    parser.add_argument('--repeat',type=int,default=3)
    parser.add_argument('--trace',action='store_true',default=default_trace)
    parser.add_argument('--no-stress',action='store_true')
    parser.add_argument('--source',choices=('mix','drums'),default='drums')
    parser.add_argument('--minutes',type=int,default=3)
    parser.add_argument('--candidate',choices=('A','B','C','E'),default='A')
    parser.add_argument('--stall-ms',type=float,default=0)
    parser.add_argument('--attach-after',type=float,default=80)
    parser.add_argument('--trace-seconds',type=int,default=35)
    args=parser.parse_args();failed=False
    for _ in range(args.repeat):
        row,_=run(args.output,args.source,args.minutes,args.trace,not args.no_stress,
            args.candidate,args.stall_ms,args.attach_after,args.trace_seconds)
        failed|=row['AUDIO_QUALITY']!='PASS' or row['MEASUREMENT_QUALITY']!='PASS' or (
            args.trace and (row['TRACE_CAPTURE']!='PASS' or row['TRACE_ANALYSIS']!='PASS'))
    if failed:raise SystemExit('Audio/measurement/trace FAIL or INDETERMINATE; individual evidence retained')

if __name__=='__main__':main()
