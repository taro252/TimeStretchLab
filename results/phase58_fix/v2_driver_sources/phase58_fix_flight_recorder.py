"""Keep the last 5 s of OS trace when an observed DSP stall triggers.

Every attempted session remains in rows.jsonl. Nontrigger sessions are not
discarded from native statistics; their older OS intervals may be unavailable.
"""
import argparse
import csv
import json
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path
from phase58_fix_repeat import ROOT, sha, utc


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--binary',type=Path,default=ROOT/'build/phase58_fix_frozen/sampled_diagnostic_native')
    p.add_argument('--max-repeats',type=int,default=100)
    p.add_argument('--stall-s',type=float,default=.05)
    a=p.parse_args()
    if not 1<=a.max_repeats<=200 or not .01<=a.stall_s<=1:
        p.error('bounded repetitions and diagnostic stall threshold required')
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    source=ROOT/'results/phase58/native_product/inputs/boundary_1_2_48000.wav'
    reference=ROOT/'results/phase58_fix/before_repeat100/reference.json'
    ref=json.loads(reference.read_text());raw=out/'reference.f32'
    shutil.copy2(reference.with_name('reference.f32'),raw)
    if sha(raw)!=ref['pcm_sha256']:
        raise RuntimeError('Independent reference SHA mismatch')
    binary=a.binary.resolve();trace=ROOT/'build/phase58_fix_frozen'/(out.name+'.trace')
    notification='com.timestretchlab.phase58fix.'+uuid.uuid4().hex
    cmd=['xcrun','xctrace','record','--template','Audio System Trace','--output',str(trace),
         '--all-processes','--time-limit','600s','--window','5s','--no-prompt',
         '--notify-tracing-started',notification]
    manifest=dict(start_utc=utc(),head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  binary=str(binary),binary_sha256=sha(binary),input=str(source),input_sha256=sha(source),
                  reference=ref,reference_sha256=sha(raw),requested=a.max_repeats,stall_trigger_s=a.stall_s,
                  trace_command=cmd,scope='Diagnostic trace, detailed stages and 1 ms sampled thread state; no root-cause fix')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    rows=[];trigger=None;status=dict(startup_notification_received=False)
    waiter=subprocess.Popen(['notifyutil','-1',notification],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    with (out/'record.log').open('w') as log:
        recorder=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT)
        try:
            stdout,stderr=waiter.communicate(timeout=60)
            (out/'notification.log').write_bytes(stdout+stderr)
            if waiter.returncode:
                raise RuntimeError('Recording startup notification failed')
            status['startup_notification_received']=True
            for i in range(a.max_repeats):
                folder=out/'runs'/f'run_{i:03}'
                native=list(map(str,[binary,source,2000000,'candidate',raw,ref['output_frames'],ref['pcm_sha256'],
                                     folder,'normal',0,0,0,0,0,'--profile=detail','--sample-thread=on']))
                row=dict(index=i,start_utc=utc(),command=native)
                r=subprocess.run(native,capture_output=True,text=True,timeout=90)
                row.update(exit=r.returncode,end_utc=utc(),stdout=r.stdout,stderr=r.stderr)
                (out/f'run_{i:03}.log').write_text(r.stdout+r.stderr)
                summary=folder/'summary.json'
                maximum=None
                if summary.exists():
                    row['summary']=s=json.loads(summary.read_text())
                    blocks=list(csv.DictReader((folder/'worker.csv').open()))
                    if blocks:
                        block=max(blocks,key=lambda b:float(b['wall_s'])-float(b['cpu_s']))
                        maximum=float(block['wall_s'])-float(block['cpu_s'])
                        row.update(max_block_non_cpu_s=maximum,worst_block=block)
                    if s['missing_frames'] or (maximum is not None and maximum>=a.stall_s):
                        trigger=dict(index=i,session=str(folder),missing_frames=s['missing_frames'],
                                     max_block_non_cpu_s=maximum,at_utc=utc())
                rows.append(row)
                with (out/'rows.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
                progress=dict(executions=len(rows),requested=a.max_repeats,
                              passed=sum(x.get('summary',{}).get('PASS',False) for x in rows),
                              failed=sum(not x.get('summary',{}).get('PASS',False) for x in rows),trigger=trigger)
                (out/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
                print(i,r.returncode,'non_cpu',maximum,'trigger',trigger is not None,flush=True)
                if trigger:
                    (out/'TRIGGER.json').write_text(json.dumps(trigger,indent=2)+'\n')
                    break
        finally:
            if waiter.poll() is None:
                waiter.terminate();waiter.communicate()
            if recorder.poll() is None:recorder.send_signal(signal.SIGINT)
            try:status['trace_exit']=recorder.wait(timeout=120)
            except subprocess.TimeoutExpired:
                recorder.terminate();status['trace_exit']=recorder.wait(timeout=30);status['save_timeout']=True
            status.update(end_utc=utc(),trace_path=str(trace),trigger=trigger,executions=len(rows))
            (out/'status.json').write_text(json.dumps(status,indent=2)+'\n')
    print(json.dumps(status),flush=True)
    return 0 if status['trace_exit']==0 else 2


if __name__=='__main__':
    raise SystemExit(main())
