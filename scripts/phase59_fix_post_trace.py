"""追加traceの途中時計異常・HALイベント・既知RTのVMを保存済み記録で照合する。"""
import csv
import json
from pathlib import Path
from phase57_study import ROOT,sha
from phase58_fix_trace_analyze import table,number,overlap


def main():
    out=ROOT/'results/phase59_fix';data=ROOT/'build/phase59_fix_artifacts'
    trace=data/'final_long_trace';native=data/'final_long_trace_native'
    summary=json.loads((native/'summary.json').read_text())
    epoch=json.loads((trace/'analysis/summary.json').read_text())['trace_epoch_ns']
    callbacks=list(csv.DictReader((native/'callbacks.csv').open()));jumps=[]
    for index,(a,b) in enumerate(zip(callbacks,callbacks[1:]),1):
        if a['epoch']!=b['epoch'] or not(int(a['flags'])&1 and int(b['flags'])&1):continue
        delta=float(b['sample_time'])-float(a['sample_time']);extra=delta-int(a['requested'])
        if delta<=0 or abs(extra)>2:
            jumps.append(dict(index=index,previous=a,current=b,extra_frames=extra,
                              entry_pipeline_s=(int(b['start_ns'])-summary['clock_mach_ns'])*1e-9+summary['clock_pipeline_s'],
                              actual_entry_delta_ns=int(b['start_ns'])-int(a['start_ns']),
                              timestamp_delta_ns=int(b['host_ns'])-int(a['host_ns'])))
    assert len(jumps)==summary['sample_errors']
    first=jumps[0];index=first['index'];nearby=callbacks[max(0,index-3):index+2]
    lo=int(nearby[0]['start_ns'])-epoch;hi=int(nearby[-1]['end_ns'])-epoch
    ioproc=table(trace/'xml/audio-hal-client-io-cycle-ioproc.xml')
    at=int(first['previous']['start_ns'])-epoch
    tids={r['thread']['tid'] for r in ioproc if number(r,'start')<=at<number(r,'start')+number(r,'duration')}
    assert len(tids)==1,'Callback IOProc thread not uniquely identified'
    tid=tids.pop()
    states=table(trace/'xml/thread-state.xml',{tid})
    selected=[r for r in states if overlap(lo,hi,number(r,'start'),number(r,'start')+number(r,'duration'))]
    calls=table(trace/'xml/syscall.xml',{tid});vm=table(trace/'xml/virtual-memory.xml',{tid})
    client_calls=[r for r in calls if overlap(lo,hi,number(r,'start'),number(r,'start')+number(r,'duration'))]
    client_vm=[r for r in vm if overlap(lo,hi,number(r,'start'),number(r,'start')+number(r,'duration'))]
    poi=table(trace/'xml/audio-hal-client-poi.xml')
    overloads=[r for r in poi if 'Overload' in str(r['description']['fmt'])]
    hardware=[r for r in table(trace/'xml/audio-hal-io-cycle-hardware.xml') if lo<=number(r,'start')<=hi]
    dsp_vm=table(trace/'xml/virtual-memory.xml',{summary['dsp_thread']})
    intervals=json.loads((trace/'exact_workgroup_intervals.json').read_text());known_vm=[]
    for interval in intervals:
        if not(interval['within_observed_window'] and interval['fully_observed']):continue
        for row in dsp_vm:
            if overlap(interval['trace_start_ns'],interval['trace_end_ns'],number(row,'start'),number(row,'start')+number(row,'duration')):
                known_vm.append(dict(interval=interval['interval'],vm=row))
    payload=dict(callbacks=nearby,clock_jumps=jumps,client_thread=tid,client_states=selected,
                 client_syscalls=client_calls,client_vm=client_vm,hal_events=poi,hardware=hardware,
                 known_realtime_vm=known_vm,trace_epoch_ns=epoch)
    path=trace/'post_trace_clock_vm_evidence.json';path.write_text(json.dumps(payload,indent=2)+'\n')
    vmops=[dict(output_start=r['interval']['output_start'],operation=r['vm']['operation']['fmt'],
                duration_ns=number(r['vm'],'duration'),address=r['vm'].get('address',{}).get('fmt'),
                frames=r['vm'].get('backtrace',{}).get('frames')) for r in known_vm]
    result=dict(clock_jumps=jumps,client_thread=tid,hal_client_overloads=len(overloads),hal_overloads=overloads,
                native_hal_window_misses=summary['hal_misses'],native_callback_deadlines=summary['callback_deadlines'],
                native_pcm_complete_exact=summary['pcm_complete_exact'],native_missing_frames=summary['missing_frames'],
                known_realtime_vm=vmops,client_vm_operations=len(client_vm),
                evidence=str(path),evidence_sha256=sha(path),script_sha256=sha(Path(__file__)),
                source_sha256={str(p):sha(p) for p in [native/'callbacks.csv',native/'summary.json',trace/'xml/audio-hal-client-poi.xml',trace/'xml/audio-hal-client-io-cycle-ioproc.xml',trace/'xml/audio-hal-io-cycle-hardware.xml']},
                interpretation='8016手前にHAL client threadが約11.2ms Blockedとなり、dtsecurityによる起床、遅れたIOProc、Client Overload、次のSourceNode timestamp跳躍という順序を観測。待機の全因果と計測器の関与は未証明。トレースなしの初回異常と同原因としない。',
                scope='追加の計測器付き1試行。正式274セッションと分離。Native HAL window 0をOS Client Overload 0へ一般化しない。元の72秒付近の対象7区間は未取得。')
    (out/'POST_TRACE_CLOCK_VM.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print('post trace',len(jumps),'clock jump;',len(overloads),'HAL overload;',len(known_vm),'known RT faults',flush=True)


if __name__=='__main__':main()
