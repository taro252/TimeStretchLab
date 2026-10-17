"""Darwin記録開始通知を受けてから音声processを生成し、全processで観測する。"""
import ctypes
import json
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha
from phase59_fix2_trace import BUDGET, files, GiB


def main():
    previous=list(OUT.glob('trace_*/manifest.json'));assert len(previous)==4
    retained=set()
    for path in previous:
        m=json.loads(path.read_text());retained.update(p.resolve() for p in files(Path(m['trace_bundle']).parent))
        retained.update(Path(t['path']).resolve() for t in m['temporary_traces'] if Path(t['path']).exists())
    retained_bytes=sum(p.stat().st_size for p in retained);free=shutil.disk_usage(ROOT).free
    assert free>=BUDGET['admission_free_bytes'] and retained_bytes+4*GiB<=BUDGET['maximum_cumulative_bytes']
    revision=dict(**{**BUDGET,'maximum_captures':5},retained_before_bytes=retained_bytes,free_before_bytes=free,
                  reason='launch取得でも旧製品の初回とworkerが未観測。開始通知後にprocessを起動する追加1回。累積16GiB、1回4GiB、空き下限8GiBを維持。PCM/FIFO/品質基準は変更しない。')
    with (OUT/'TRACE_BUDGET_V2.json').open('x') as f:json.dump(revision,f,ensure_ascii=False,indent=2);f.write('\n')
    out=OUT/'trace_legacy_synced';out.mkdir();data=ROOT/'build/phase59_fix2_artifacts/trace_legacy_synced';data.mkdir()
    native=ROOT/'build/phase59_fix2_artifacts/legacy_synced_trace_native'
    target=[str(ROOT/'build/phase59_fix2_artifacts/legacy_diagnostic_build/legacy_probe'),
            str(ROOT/'results/phase31/input/mix.wav'),'candidate','2.0',str(native),'smoke','64']
    system=ctypes.CDLL('/usr/lib/libSystem.B.dylib');token=ctypes.c_int();changed=ctypes.c_int()
    system.mach_absolute_time.restype=ctypes.c_uint64
    name=('com.timestretchlab.phase59fix2.'+uuid.uuid4().hex).encode()
    assert system.notify_register_check(name,ctypes.byref(token))==0
    assert system.notify_check(token,ctypes.byref(changed))==0
    trace=data/'recording.trace'
    command=['xcrun','xctrace','record','--template','Audio System Trace','--all-processes','--time-limit','12s',
             '--notify-tracing-started',name.decode(),'--output',str(trace)]
    temp=Path(tempfile.gettempdir());before=set(temp.glob('instruments*.ktrace'))
    checks=[];interrupted=False;signal_at=None;child=None;notified_ticks=None;launch_ticks=None
    with (out/'record.log').open('x') as log,(data/'target.log').open('x') as target_log:
        recorder=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        while recorder.poll() is None:
            if child is None:
                assert system.notify_check(token,ctypes.byref(changed))==0
                if changed.value:
                    notified_ticks=int(system.mach_absolute_time());launch_ticks=int(system.mach_absolute_time())
                    child=subprocess.Popen(target,cwd=ROOT,stdout=target_log,stderr=subprocess.STDOUT)
            created=set(temp.glob('instruments*.ktrace'))-before
            temporary=sum(p.stat().st_size for p in created if p.exists());saved=sum(p.stat().st_size for p in files(data))
            free=shutil.disk_usage(ROOT).free;checks.append(dict(unix=time.time(),temporary_bytes=temporary,saved_bytes=saved,free_bytes=free))
            if not interrupted and (temporary+saved>4*GiB or retained_bytes+temporary+saved>16*GiB or free<8*GiB):
                recorder.send_signal(signal.SIGINT);interrupted=True;signal_at=time.monotonic()
            if interrupted and time.monotonic()-signal_at>30:recorder.terminate();break
            time.sleep(.01 if child is None else .2)
        recording_exit=recorder.wait(timeout=30)
        target_exit=child.wait(timeout=180) if child else None
    system.notify_cancel(token)
    created=set(temp.glob('instruments*.ktrace'))-before
    manifest=dict(command=command,target_command=target,target_pid=child.pid if child else None,
                  exit=recording_exit,native_exit=target_exit,capacity_interrupted=interrupted,
                  notified_mach_ticks=notified_ticks,launch_mach_ticks=launch_ticks,
                  notification_initial_check_drained=True,notification_name=name.decode(),budget=revision,
                  trace_bundle=str(trace),maximum_observed_bytes=max((r['temporary_bytes']+r['saved_bytes'] for r in checks),default=0),
                  minimum_free_bytes=min((r['free_bytes'] for r in checks),default=free),checkpoints=checks,
                  temporary_traces=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(created) if p.exists()],
                  artifacts=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in files(data)],
                  method='notify_register_checkの初回通知を読み捨て、xctraceの--notify-tracing-started通知を受けてから別processを起動。--all-processesを使用。実coverageは別に照合。',
                  originals_deleted=False)
    with (out/'manifest.json').open('x') as f:json.dump(manifest,f,ensure_ascii=False,indent=2);f.write('\n')
    assert child is not None and trace.exists() and not interrupted
    print('synced recording',recording_exit,'native',target_exit,'pid',child.pid,flush=True)


if __name__=='__main__':main()
