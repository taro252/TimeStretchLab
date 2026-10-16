"""所有する短時間トレースだけを容量監視付きで取得し、原本を保持する。"""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from phase57_study import ROOT, sha


def size(path):
    total = 0
    for p in path.rglob('*'):
        try:
            if p.is_file(): total += p.stat().st_size
        except FileNotFoundError:
            pass
    return total


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--seconds', type=int, default=6)
    parser.add_argument('--template', choices=['System Trace','Audio System Trace'], default='Audio System Trace')
    parser.add_argument('--attach-pid',type=int)
    parser.add_argument('--wait-for-target-exit',action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    assert (bool(command)!=bool(args.attach_pid)) and 0 < args.seconds <= 20
    assert not args.wait_for_target_exit or args.attach_pid
    budget = json.loads((ROOT/'results/phase59_fix/TRACE_BUDGET.json').read_text())
    total_budget = json.loads((ROOT/'results/phase59_fix/TRACE_TOTAL_BUDGET.json').read_text())
    existing_files=set();existing_captures=[]
    for file in (ROOT/'results/phase59_fix').glob('*/manifest.json'):
        previous=json.loads(file.read_text())
        if 'trace_bundle' not in previous:continue
        existing_captures.append(str(file))
        for artifact in Path(previous['trace_bundle']).parent.rglob('*'):
            if artifact.is_file():existing_files.add(artifact.resolve())
        for artifact in previous.get('temporary_traces',[]):
            p=Path(artifact['path'])
            if p.exists():existing_files.add(p.resolve())
    retained_before=sum(p.stat().st_size for p in existing_files)
    assert len(existing_captures)<total_budget['maximum_captures']
    assert retained_before+budget['trace_peak_budget_bytes']<=total_budget['maximum_cumulative_bytes']
    assert shutil.disk_usage(ROOT).free >= budget['admission_required_free_bytes']
    out = ROOT/'results/phase59_fix'/args.name; out.mkdir()
    data = ROOT/'build/phase59_fix_artifacts'/args.name; data.mkdir()
    temp = Path(tempfile.gettempdir())
    before = {str(p) for p in temp.glob('instruments*.ktrace')}
    trace = data/'focused.trace'
    invocation = ['xcrun','xctrace','record','--template',args.template,'--time-limit',str(args.seconds)+'s','--output',str(trace)]
    if args.attach_pid:invocation+=['--attach',str(args.attach_pid)]
    else:invocation+=['--target-stdout',str(data/'target.log'),'--launch','--',*command]
    checkpoints=[]; interrupted=False; signal_at=None
    with (out/'record.log').open('x') as log:
        process=subprocess.Popen(invocation,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        while process.poll() is None:
            created=[p for p in temp.glob('instruments*.ktrace') if str(p) not in before]
            temporary=sum(p.stat().st_size for p in created if p.exists())
            retained=size(data);free=shutil.disk_usage(ROOT).free
            checkpoints.append(dict(at=time.time(),temporary_bytes=temporary,artifact_bytes=retained,free_bytes=free))
            exceeded=(temporary+retained>budget['trace_peak_budget_bytes'] or free<budget['minimum_free_during_trace']
                      or retained_before+temporary+retained>total_budget['maximum_cumulative_bytes'])
            if exceeded and not interrupted:
                process.send_signal(signal.SIGINT);interrupted=True;signal_at=time.time()
            if interrupted and time.time()-signal_at>30:
                process.terminate();break
            time.sleep(.2)
        exit_code=process.wait(timeout=30)
    if args.wait_for_target_exit:
        wait_started=time.time()
        while True:
            target=subprocess.run(['ps','-p',str(args.attach_pid),'-o','stat='],capture_output=True,text=True)
            if target.returncode==1 or target.stdout.strip().startswith('Z'):break
            if target.returncode or time.time()-wait_started>300:raise RuntimeError('Target exit not confirmed; defer large hashes/exports')
            time.sleep(1)
    created=[p for p in temp.glob('instruments*.ktrace') if str(p) not in before]
    manifest=dict(command=invocation,exit=exit_code,capacity_interrupted=interrupted,budget=budget,
        total_budget=total_budget,previous_captures=existing_captures,retained_trace_bytes_before=retained_before,
        maximum_observed_bytes=max((x['temporary_bytes']+x['artifact_bytes'] for x in checkpoints),default=0),
        minimum_observed_free_bytes=min((x['free_bytes'] for x in checkpoints),default=shutil.disk_usage(ROOT).free),
        checkpoints=checkpoints,temporary_traces=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in created],
        trace_bundle=str(trace),artifacts=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in data.rglob('*') if p.is_file()],
        originals_deleted=False,restore='原本は記載した絶対パスに保持。復元時にSHA-256を照合する。')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('trace',args.name,'exit',exit_code,'peak',manifest['maximum_observed_bytes'],'interrupted',interrupted)


if __name__=='__main__':main()
