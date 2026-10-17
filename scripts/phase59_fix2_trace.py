"""正式なlaunch記録で対象起動前から取得し、一時ktraceも含めて容量監視する。"""
import argparse
import json
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha

GiB = 1024**3
BUDGET = dict(maximum_captures=4, maximum_simultaneous_capture_bytes=4*GiB,
              maximum_cumulative_bytes=16*GiB, admission_free_bytes=12*GiB,
              minimum_free_bytes=8*GiB, maximum_seconds=12,
              xml_export_budget_bytes=2*GiB)


def files(folder):
    return [p for p in folder.rglob('*') if p.is_file()]


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--name',required=True)
    parser.add_argument('--seconds',type=int,default=6)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args();command=args.command[1:] if args.command[:1]==['--'] else args.command
    assert command and 1 <= args.seconds <= BUDGET['maximum_seconds']
    budget_file=OUT/'TRACE_BUDGET.json'
    if not budget_file.exists():
        with budget_file.open('x') as file:json.dump(BUDGET,file,indent=2);file.write('\n')
    assert json.loads(budget_file.read_text()) == BUDGET
    manifests=list(OUT.glob('trace_*/manifest.json'))
    assert len(manifests)<BUDGET['maximum_captures']
    retained=set()
    for path in manifests:
        old=json.loads(path.read_text())
        retained.update(p for p in files(Path(old['trace_bundle']).parent))
        retained.update(Path(t['path']) for t in old['temporary_traces'] if Path(t['path']).exists())
    retained_bytes=sum(p.stat().st_size for p in retained)
    assert retained_bytes+BUDGET['maximum_simultaneous_capture_bytes']<=BUDGET['maximum_cumulative_bytes']
    assert shutil.disk_usage(ROOT).free>=BUDGET['admission_free_bytes']
    out=OUT/('trace_'+args.name);out.mkdir()
    data=ROOT/'build/phase59_fix2_artifacts'/out.name;data.mkdir()
    temp=Path(tempfile.gettempdir());before=set(temp.glob('instruments*.ktrace'))
    trace=data/'recording.trace'
    invocation=['xcrun','xctrace','record','--template','Audio System Trace','--time-limit',str(args.seconds)+'s',
                '--output',str(trace),'--target-stdout',str(data/'target.log'),'--launch','--',*command]
    checks=[];interrupted=False;signal_at=None
    with (out/'record.log').open('x') as log:
        process=subprocess.Popen(invocation,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        while process.poll() is None:
            created=set(temp.glob('instruments*.ktrace'))-before
            temporary=sum(p.stat().st_size for p in created if p.exists())
            saved=sum(p.stat().st_size for p in files(data))
            free=shutil.disk_usage(ROOT).free
            checks.append(dict(unix=time.time(),temporary_bytes=temporary,saved_bytes=saved,free_bytes=free))
            exceeded=(temporary+saved>BUDGET['maximum_simultaneous_capture_bytes'] or free<BUDGET['minimum_free_bytes']
                      or retained_bytes+temporary+saved>BUDGET['maximum_cumulative_bytes'])
            if exceeded and not interrupted:
                process.send_signal(signal.SIGINT);interrupted=True;signal_at=time.monotonic()
            if interrupted and time.monotonic()-signal_at>30:
                process.terminate();break
            time.sleep(.2)
        result=process.wait(timeout=30)
    created=set(temp.glob('instruments*.ktrace'))-before
    manifest=dict(command=invocation,exit=result,capacity_interrupted=interrupted,budget=BUDGET,
                  recording_method='xctrace record --launch。実際のtime-info epochと最初のcallbackで開始前coverageを検証する。',
                  trace_bundle=str(trace),previous_retained_bytes=retained_bytes,
                  maximum_observed_bytes=max((c['temporary_bytes']+c['saved_bytes'] for c in checks),default=0),
                  minimum_free_bytes=min((c['free_bytes'] for c in checks),default=shutil.disk_usage(ROOT).free),
                  checkpoints=checks,temporary_traces=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(created) if p.exists()],
                  artifacts=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in files(data)],
                  original_deleted=False,restore='原本は絶対パスに保持。SHA-256を照合して読む。既存使用中ktraceや他プロセスには触れない。')
    with (out/'manifest.json').open('x') as file:json.dump(manifest,file,indent=2,ensure_ascii=False);file.write('\n')
    print('trace',args.name,'exit',result,'capacity_interrupted',interrupted,flush=True)
    return result


if __name__=='__main__':raise SystemExit(main())
