"""最終180秒Baselineの既知遅延位置を6秒だけ観測し、実区間ticksで照合する。"""
import collections
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from phase57_study import ROOT, sha
from phase58_fix_trace_analyze import IntervalIndex, classify, number, table


def main():
    out=ROOT/'results/phase59_fix'; data=ROOT/'build/phase59_fix_artifacts'
    while (out/'.storage_maintenance').exists():time.sleep(.2)
    assert (out/'device_final/summary.json').exists()
    assert (out/'eos_after/summary.json').exists()
    budget=json.loads((out/'TRACE_BUDGET.json').read_text())
    assert shutil.disk_usage(ROOT).free>=budget['admission_required_free_bytes']+64*1024**2
    binary=data/'final/phase59_fix_fixed_probe'
    source=ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav'
    raw=data/'phase_before/reference.f32'
    reference=json.loads((out/'phase_before/reference.json').read_text())
    assert sha(raw)==reference['pcm_sha256']
    native=data/'final_long_trace_native'
    command=[str(binary),str(source),'2000000','baseline',str(raw),str(reference['output_frames']),reference['pcm_sha256'],
             str(native),'normal','0','2','0','0','0','--worker=workgroup','--resident-input=on',
             '--profile=detail','--sample-thread=on','--phase-probe=3186688:3201024']
    manifest=dict(command=command, binary_sha256=sha(binary),input_sha256=sha(source),reference=reference,
                  script_sha256=sha(Path(__file__)), free_before_bytes=shutil.disk_usage(ROOT).free,
                  plan='起動約68秒後にattachし、準備を含め約70〜76秒の6秒取得。取得窓は推定時刻でなく実際のMach epochで照合する。')
    record=out/'FINAL_TRACE_NATIVE.json'
    assert not record.exists()
    with (data/'final_long_trace_native.log').open('x') as log:
        process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        manifest['pid']=process.pid;manifest['started_unix']=time.time()
        record.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        trace_process=None
        try:
            while time.time()-manifest['started_unix']<68 and process.poll() is None:time.sleep(.5)
            if process.poll() is None:
                trace_command=[sys.executable,'-B',str(ROOT/'scripts/phase59_fix_trace.py'),'--name','final_long_trace',
                               '--seconds','6','--template','Audio System Trace','--attach-pid',str(process.pid),'--wait-for-target-exit']
                with (data/'final_long_trace_driver.log').open('x') as trace_log:
                    trace_process=subprocess.Popen(trace_command,cwd=ROOT,stdout=trace_log,stderr=subprocess.STDOUT)
                    manifest['trace_command']=trace_command
                    # 大きいSHA計算・XML出力は音声processの終了後。
                    manifest['native_exit']=process.wait(timeout=180)
                    manifest['trace_driver_exit']=trace_process.wait(timeout=360)
            else:manifest['native_exit']=process.wait()
        finally:
            if process.poll() is None:
                process.terminate();process.wait(timeout=30)
            if trace_process is not None and trace_process.poll() is None:
                trace_process.terminate();trace_process.wait(timeout=30)
            manifest['finished_unix']=time.time()
            if (native/'summary.json').exists():manifest['native']=json.loads((native/'summary.json').read_text())
            record.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    trace=data/'final_long_trace'; capture=out/'final_long_trace/manifest.json'
    if not capture.exists() or not (trace/'focused.trace').exists():
        raise RuntimeError('Final trace unavailable; native and driver evidence retained')
    analyze=[sys.executable,'-B',str(ROOT/'scripts/phase58_fix_trace_analyze.py'),'--trace',str(trace/'focused.trace'),
             '--sessions',str(native),'--output',str(trace/'analysis'),'--existing-xml',str(trace/'xml')]
    with (trace/'analysis_driver.log').open('x') as log:
        analyzed=subprocess.run(analyze,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    assert analyzed.returncode==0,'OS export/analysis failed; all evidence retained'
    summary=manifest['native'];tid=summary['dsp_thread']
    clock=table(trace/'xml/time-info.xml')[0]
    numer,denom=map(int,clock['timebase-info']['fmt'].split('/'))
    epoch=number(clock,'mabs-epoch')*numer/denom
    states=table(trace/'xml/thread-state.xml',{tid})
    calls=table(trace/'xml/syscall.xml',{tid});faults=table(trace/'xml/virtual-memory.xml',{tid})
    indices=[IntervalIndex(rows) for rows in (states,calls,faults)]
    low=min(number(r,'start') for r in states);high=max(number(r,'start')+number(r,'duration') for r in states)
    rows=[]
    with (native/'intervals.csv').open() as file:
        for interval in csv.DictReader(file):
            scale=int(interval['timebase_numer'])/int(interval['timebase_denom'])
            begin=int(interval['start_ticks'])*scale-epoch;end=int(interval['end_ticks'])*scale-epoch
            observed=classify(begin,end,*indices)
            rows.append(dict(interval=interval,trace_start_ns=begin,trace_end_ns=end,
                             within_observed_window=begin>=low and end<=high,
                             intersects_observed_window=end>low and begin<high,
                             fully_observed=observed['unobserved_s']<=1e-9 and observed['state_seconds'].get('Unknown',0)<=1e-9,
                             os=observed))
    in_window=[r for r in rows if r['within_observed_window']]
    known=[r for r in in_window if r['fully_observed']]
    target=[r for r in rows if 3186688<=int(r['interval']['output_start'])<3201024]
    operations=collections.Counter(f['operation'] for r in known for f in r['os']['faults'])
    deadline_misses=sum(r['interval']['deadline_miss']=='1' for r in rows)
    assert deadline_misses==summary['workgroup_deadline_misses']
    payload=trace/'exact_workgroup_intervals.json'
    payload.write_text(json.dumps(rows,indent=2)+'\n')
    result=dict(native_pass=summary['PASS'],native_pcm_complete_exact=summary['pcm_complete_exact'],
                native_summary=str(native/'summary.json'),native_summary_sha256=sha(native/'summary.json'),
                capture_manifest=str(capture),all_realtime_intervals=len(rows),
                wholly_in_observed_window=len(in_window),fully_observed_within_window=len(known),
                unknown_within_window=len(in_window)-len(known),
                outside_or_partial_window=len(rows)-len(in_window),
                window_output_starts=[int(r['interval']['output_start']) for r in in_window],
                targeted_intervals=len(target),targeted_intervals_within_window=sum(r['within_observed_window'] for r in target),
                targeted_intervals_fully_observed=sum(r['within_observed_window'] and r['fully_observed'] for r in target),
                workgroup_deadline_misses=deadline_misses,known_vm_operations=dict(operations),
                known_fault_intervals=sum(bool(r['os']['faults']) for r in known),
                interval_payload=str(payload),interval_payload_sha256=sha(payload),
                alignment='保存された実時間区間のstart/end Mach ticksとtime-info mabs-epochを直接照合。',
                floating_time_conversion_uncertainty_ns=1,
                scope='1nsは大きいMach値の浮動小数点変換誤差用。音声期限・時計判定の閾値は変更しない。取得窓外/部分/Unknownはfault 0へ補完しない。')
    (out/'FINAL_TRACE_OBSERVATIONS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('final focused trace',len(known),'known /',len(in_window),'in window;',len(rows),'all',flush=True)


if __name__=='__main__':main()
