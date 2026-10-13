#!/usr/bin/env python3
"""One 5-second, low-load native trace; no long trial until this fully succeeds."""
import argparse,json,os,subprocess,tempfile,time
from pathlib import Path
from phase45_store import new_run,parse_log,save_result
from phase45_verdict import native_verdict
from phase46_trace import XCTRACE,validate_run
from phase47_trace_storage import record,volume
from phase47_evidence import validate
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=int,default=5,choices=range(5,11))
args=parser.parse_args();out=root/'results/phase47/calibration_runs'
path,identifier,at=new_run(out,'short_trace')
env=dict(os.environ,PHASE43_SILENT='1',PHASE46_PCM_SHA='1',PHASE45_LIVE_EVENTS=str(path/'callbacks.csv'),
    PHASE45_LIVE_WORKERS=str(path/'workers.csv'),PHASE45_LIVE_PLAN_CSV=str(path/'replay.csv'))
env.pop('PHASE43_STRESS',None)
source=root/'results/phase31/input/drums.wav'
prepared=[volume(path),volume(path/'trace_tmp'),volume(Path(tempfile.gettempdir()))]
with (path/'playback.log').open('x') as log:
    target=subprocess.Popen([str(root/'build/phase43_play'),str(source),'1.0','-'],env=env,stdout=log,stderr=subprocess.STDOUT)
    time.sleep(.5)
    evidence=dict(max_temporary_bytes=4330593632,growth_bytes_per_second=4330593632/35,
        max_xml_bytes=324828396,source='Measured Phase46 maximum temporary size and Phase45 XML; provisional envelope, not validated rate')
    storage=record(XCTRACE+['record','--template','System Trace','--time-limit',f'{args.seconds}s','--window',f'{args.seconds}s',
        '--output',str(path/'system.trace'),'--attach',str(target.pid)],path/'system.trace',path/'trace_tmp',Path(tempfile.gettempdir()),args.seconds,evidence,prepared)
    try:code=target.wait(timeout=60)
    except subprocess.TimeoutExpired:target.terminate();code=target.wait(timeout=10)
values=parse_log((path/'playback.log').read_text())
row=dict(run_id=identifier,run_time=at,trace_seconds=args.seconds,exit_code=code,process_pid=target.pid,storage_status=storage['STORAGE_STATUS'])
row.update(values);row.update(native_verdict(values,code))
trace=validate_run(path,storage['record_exit'],code,target.pid) if (path/'system.trace').exists() else dict(TRACE_CAPTURE='FAIL',TRACE_ANALYSIS='FAIL')
row.update(trace)
integrity,tables=validate(path,values,(path/'playback.log').read_text())
(path/'csv_integrity.json').write_text(json.dumps(integrity,indent=2));row['CSV_INTEGRITY']=integrity['CSV_INTEGRITY']
remaining_ok=all(v['free']>=int(v['total']*.05) for v in storage.get('after',[]))
passed=(storage['STORAGE_STATUS']=='NORMAL_EXIT' and row['AUDIO_QUALITY']=='PASS' and row['MEASUREMENT_QUALITY']=='PASS' and
    row['TRACE_CAPTURE']=='PASS' and row['TRACE_ANALYSIS']=='PASS' and integrity['CSV_INTEGRITY']=='PASS' and remaining_ok)
row['CALIBRATION']='PASS' if passed else 'FAIL'
# Persist actual sizes even on failure. No failed trace is automatically deleted.
calibration=dict(CALIBRATION=row['CALIBRATION'],run_id=identifier,trace_seconds=args.seconds,
    storage=storage,trace=trace,csv=integrity,capacity_evidence=dict(
        max_temporary_bytes=max((v['bytes'] for v in storage.get('new_temporary_files',[])),default=0),
        growth_bytes_per_second=max((v['bytes'] for v in storage.get('new_temporary_files',[])),default=0)/args.seconds,
        global_free_decline_peak_bytes_per_second=max((v['observed_rate'] for v in storage.get('samples',[])),default=0),
        max_xml_bytes=(path/'states.xml').stat().st_size if (path/'states.xml').exists() else 0,
        source='Measured Phase47 calibration, including recorder finalization'))
(root/'results/phase47/calibration.json').write_text(json.dumps(calibration,indent=2))
save_result(out,path,row)
print(identifier,row['CALIBRATION'],row['AUDIO_QUALITY'],row['MEASUREMENT_QUALITY'],row['TRACE_CAPTURE'],row['TRACE_ANALYSIS'],flush=True)
if not passed:raise SystemExit('Short trace calibration FAIL: long traces and repeated native trace trials remain prohibited')
