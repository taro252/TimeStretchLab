"""launch取得の実coverage、HAL、callbackをMach時刻で直接照合する。"""
import argparse
import csv
import json
import shutil
import subprocess
import time
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha
from phase59_fix2_trace import BUDGET, GiB
from phase58_fix_trace_analyze import table, number, IntervalIndex, classify, complete_export

SCHEMAS=('time-info','thread-state','syscall','virtual-memory',
         'audio-hal-client-poi','audio-hal-client-io-cycle-ioproc','audio-hal-io-cycle-hardware')


def export(trace, folder):
    folder.mkdir()
    rows=[]
    for schema in SCHEMAS:
        path=folder/(schema+'.xml')
        command=['xcrun','xctrace','export','--input',str(trace),'--xpath',
                 '/trace-toc/run[@number="1"]/data/table[@schema="'+schema+'"]']
        interrupted=False
        with path.open('x') as file, (folder/(schema+'.log')).open('x') as log:
            process=subprocess.Popen(command,stdout=file,stderr=log,cwd=ROOT)
            while process.poll() is None:
                total=sum(p.stat().st_size for p in folder.glob('*.xml'))
                if total>BUDGET['xml_export_budget_bytes'] or shutil.disk_usage(ROOT).free<8*GiB:
                    process.terminate();interrupted=True;break
                time.sleep(.2)
            result=process.wait(timeout=30)
        rows.append(dict(schema=schema,path=str(path),bytes=path.stat().st_size,sha256=sha(path),
                         exit=result,capacity_interrupted=interrupted,complete=complete_export(path)))
        (folder/'exports.json').write_text(json.dumps(rows,indent=2)+'\n')
        assert not interrupted and result==0 and complete_export(path),str(path)
        print('export',schema,path.stat().st_size,flush=True)
    return rows


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--name',required=True)
    parser.add_argument('--native',type=Path,required=True)
    parser.add_argument('--existing-xml',type=Path)
    parser.add_argument('--result-tag',default='')
    args=parser.parse_args();native=args.native.resolve()
    trace=ROOT/'build/phase59_fix2_artifacts'/('trace_'+args.name)
    assert (OUT/('trace_'+args.name)/'manifest.json').exists(),'Acquisition must finish before export'
    xml=args.existing_xml or trace/'xml'
    if args.existing_xml:
        exports=json.loads((xml/'exports.json').read_text())
        assert all(r['complete'] and sha(r['path'])==r['sha256'] for r in exports)
    else:exports=export(trace/'recording.trace',xml)
    clock=table(xml/'time-info.xml')[0]
    numer,denom=map(int,clock['timebase-info']['fmt'].split('/'))
    epoch=number(clock,'mabs-epoch')*numer/denom
    summary=json.loads((native/'summary.json').read_text())
    callbacks=list(csv.DictReader((native/'callbacks.csv').open()))
    minimal='begin_ticks' in callbacks[0]
    supplemental={}
    if (native/'callback_timestamps.csv').exists():
        supplemental={int(r['sequence']):r for r in csv.DictReader((native/'callback_timestamps.csv').open())}
    scale=summary.get('timebase_numer',numer)/summary.get('timebase_denom',denom)
    tids={int(r['thread']) for r in callbacks} if minimal else {int(r['thread']) for r in supplemental.values()}
    assert tids,'Native thread IDs are required for direct attribution'
    states=table(xml/'thread-state.xml',tids);calls=table(xml/'syscall.xml',tids);faults=table(xml/'virtual-memory.xml',tids)
    pids={r['thread']['pid'] for r in states if r.get('thread',{}).get('pid') is not None}
    indices=[IntervalIndex(r) for r in (states,calls,faults)]
    ioproc=table(xml/'audio-hal-client-io-cycle-ioproc.xml',tids)
    hal=table(xml/'audio-hal-client-poi.xml')
    overloads=[r for r in hal if 'Overload' in str(r.get('description',{}).get('fmt'))]
    target_overloads=[r for r in overloads if any(v.get('pid') in pids or v.get('tid') in tids for v in r.values())]
    joined=[]
    for row in callbacks:
        begin=(int(row['begin_ticks'])*scale if minimal else int(row['start_ns']))-epoch
        end=(int(row['end_ticks'])*scale if minimal else int(row['end_ns']))-epoch
        os=classify(begin,end,*indices)
        io=[r for r in ioproc if number(r,'start')<=begin<number(r,'start')+number(r,'duration')]
        joined.append(dict(callback=row,supplemental=supplemental.get(int(row['sequence'])),
                           trace_begin_ns=begin,trace_end_ns=end,os=os,ioproc=io,
                           fully_observed=os['unobserved_s']<=1e-9 and os['state_seconds'].get('Unknown',0)<=1e-9))
    startup_path=native/'startup.csv'
    startup=list(csv.DictReader(startup_path.open())) if startup_path.exists() else []
    process_entry=next((int(r['ticks'])*scale for r in startup if r.get('stage')=='process_entry'),None)
    run_entry=next((int(r['mach_ns']) for r in startup if r.get('event')=='process_run_entry'),None)
    payload=trace/('callback_os_timeline'+('_'+args.result_tag if args.result_tag else '')+'.json')
    payload.write_text(json.dumps(dict(trace_epoch_ns=epoch,callbacks=joined,hal=hal,overloads=overloads,
                                      target_overloads=target_overloads,startup=startup),ensure_ascii=False,indent=2)+'\n')
    result=dict(trace=str(trace/'recording.trace'),native=str(native),trace_epoch_ns=epoch,
                process_entry_ns=process_entry,trace_epoch_before_process_entry=epoch<=process_entry if process_entry else None,
                run_entry_ns=run_entry,trace_epoch_before_run_entry=epoch<=run_entry if run_entry else None,
                process_ids=sorted(pids),thread_ids=sorted(tids),callbacks=len(joined),fully_observed=sum(r['fully_observed'] for r in joined),
                first_three_fully_observed=[r['fully_observed'] for r in joined[:3]],
                first_callback_trace_ns=joined[0]['trace_begin_ns'],
                os_client_overloads_all_processes=len(overloads),os_client_overloads_target_attributed=len(target_overloads),
                os_client_overloads_unattributed=len(overloads)-len(target_overloads),
                callback_vm_observations=sum(len(r['os']['faults']) for r in joined),
                original_native_summary=summary,payload=str(payload),payload_sha256=sha(payload),exports=exports,
                physical_audio_continuity_verified=False,
                scope='コールバック実行区間のcoverage。待機中・全worker・物理出力の連続性とは別。未観測を0で補わない。',
                conversion='Mach absolute ticks × timebase_numer/timebase_denom − trace mabs-epoch(ns)。float変換誤差の1nsだけcoverage集計で許容。音声閾値は変更しない。')
    destination=OUT/('TRACE_ANALYSIS_'+args.name+('_'+args.result_tag if args.result_tag else '')+'.json')
    with destination.open('x') as file:json.dump(result,file,ensure_ascii=False,indent=2);file.write('\n')
    print('coverage',result['callbacks'],result['fully_observed'],'first3',result['first_three_fully_observed'],flush=True)


if __name__=='__main__':main()
