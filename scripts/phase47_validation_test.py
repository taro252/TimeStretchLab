#!/usr/bin/env python3
"""Failure-injection tests: no disk-full experiment, no FAIL-to-PASS promotion."""
import csv
import json
import tempfile
from pathlib import Path
from phase47_evidence import validate
from phase46_review import review_run
from phase47_trace_storage import estimate,grouped

with tempfile.TemporaryDirectory() as directory:
    p=Path(directory)
    callback_header=['sequence','epoch','timestamp_flags','sample_time','callback_start_mach_ns','callback_end_mach_ns','host_mach_ns','render_requested_frames','wanted','received','io_complete_mach_ns','early_end_mach_ns']
    cb=[dict(zip(callback_header,[i+1,1,3,i*480,1000000+i*10000000,1001000+i*10000000,2000000+i*10000000,480,480,480,1000500+i*10000000,1000900+i*10000000])) for i in range(2)]
    worker_header=['cycle_sequence','output_start','publication_frames','start_mach_ns','published_mach_ns','cycle_wall_s','cycle_cpu_s']
    workers=[dict(zip(worker_header,[1,0,2048,0,1000000,.001,.0005]))]
    replay_header=['generation','from','target','applied_frame','applied_output','completion_output']
    guards=['generation','safe','guard_wall_s','guard_cpu_s']
    def write(name,header,rows):
        with (p/name).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=header,lineterminator='\n');w.writeheader();w.writerows(rows)
    def reset():
        write('callbacks.csv',callback_header,cb);write('workers.csv',worker_header,workers)
        write('replay.csv',replay_header,[]);write('workers.csv.guard.csv',guards,[])
    v=dict(callback_records_retained='2',callback_records_total='2',callback_records_evicted='0',worker_records_retained='1',worker_records_total='1',worker_profile_records_dropped='0',replay_records_expected='0',guard_records_expected='0',diagnostic_csv_save_ok='1',host_continuity_tolerance_ns='100000',dsp_sample_rate='48000',sample_timestamp_errors='0',host_timestamp_missing_callbacks='0',host_timestamp_backwards='0',host_timestamp_cadence_errors='0',hal_window_deadline_misses='0',callback_deadline_misses='0',MEASUREMENT_QUALITY='PASS',AUDIO_QUALITY='PASS',underrun_frames='0')
    reset();assert validate(p,v)[0]['CSV_INTEGRITY']=='PASS'
    assert review_run(p,v)['MEASUREMENT_QUALITY']=='PASS'
    assert review_run(p,dict(v,MEASUREMENT_QUALITY='FAIL'))['MEASUREMENT_QUALITY']=='FAIL'
    assert review_run(p,dict(v,sample_timestamp_errors='1'))['MEASUREMENT_QUALITY']=='FAIL'
    for sample in ('nan','-1','999'):
        reset();broken=[dict(row) for row in cb];broken[1]['sample_time']=sample
        write('callbacks.csv',callback_header,broken)
        assert review_run(p,v)['MEASUREMENT_QUALITY']=='FAIL',sample
    for fault in ('missing','truncated','row_short','sequence_gap','io_failure','worker_gap','replay_mismatch'):
        reset();changed=dict(v)
        if fault=='missing':(p/'workers.csv').unlink()
        if fault=='truncated':(p/'callbacks.csv').write_bytes((p/'callbacks.csv').read_bytes()[:-2])
        if fault=='row_short':write('callbacks.csv',callback_header,cb[:1])
        if fault=='sequence_gap':
            b=[dict(row) for row in cb];b[1]['sequence']=3;write('callbacks.csv',callback_header,b)
        if fault=='io_failure':changed['diagnostic_csv_save_ok']='0'
        if fault=='worker_gap':
            b=[dict(row) for row in workers];b[0]['cycle_sequence']=2;write('workers.csv',worker_header,b)
        if fault=='replay_mismatch':write('replay.csv',replay_header,[dict(zip(replay_header,[1,.4,2,1,2,3]))])
        assert validate(p,changed)[0]['CSV_INTEGRITY']=='FAIL',fault
        assert review_run(p,changed)['MEASUREMENT_QUALITY']=='FAIL',fault
    reset();write('callbacks.csv',callback_header,cb[:1])
    assert review_run(p,dict(v,MEASUREMENT_QUALITY='FAIL'))['MEASUREMENT_QUALITY']=='FAIL'
# Same pool has one free-space balance and combined allocation demand.
vol=dict(pool='apfs-one',free=1000,total=2000,path='/output')
vol2=dict(vol,path='/tmp')
assert len(grouped([vol,vol2]))==1
budget=estimate([vol,vol2],5,dict(max_temporary_bytes=100,growth_bytes_per_second=1,max_xml_bytes=10))
assert len(budget['groups'])==1 and budget['groups'][0]['free']==1000
assert budget['groups'][0]['required_growth']>=220
assert not estimate([dict(vol,free=1),dict(vol2,free=1)],5,budget['evidence'])['allowed']
print('Sticky FAIL, sample-time, CSV integrity and storage grouping injection PASS')
# Storage pressure is simulated; the real disk is never filled by tests.
from unittest.mock import patch
from phase47_trace_storage import record
class FakeRecorder:
    returncode=None
    signals=[]
    def poll(self):return self.returncode
    def send_signal(self,s):self.signals.append(int(s));self.returncode=0
    def terminate(self):self.returncode=-15
    def kill(self):self.returncode=-9
    def wait(self):return self.returncode
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);tmp=p/'temp';tmp.mkdir()
    info=dict(path=str(p),pool='one',device=1,total=10000,free=10000)
    free_values=[10000,10000,600,600]
    def fake_free(v):return dict(v,free=free_values.pop(0) if free_values else 600)
    process=FakeRecorder()
    with patch('phase47_trace_storage.volume_fast',fake_free),patch('phase47_trace_storage.subprocess.Popen',return_value=process),patch('phase47_trace_storage.time.sleep',lambda _:None):
        result=record(['fake'],p/'system.trace',tmp,tmp,5,dict(max_temporary_bytes=100,growth_bytes_per_second=1,max_xml_bytes=10),[info,dict(info,path=str(tmp))])
    assert result['stop_requested'] and result['stop_reason']=='capacity_projection' and process.signals
print('Simulated capacity pressure graceful-stop detection PASS')
# A fast FIFO read does not excuse a slow callback telemetry tail.
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory)
    row=dict(cb[0],render_requested_frames=64,wanted=64,received=64,
             io_complete_mach_ns=1000200,early_end_mach_ns=1000500,callback_end_mach_ns=3000000,
             host_mach_ns=5000000)
    write('callbacks.csv',callback_header,[row]);write('workers.csv',worker_header,workers)
    write('replay.csv',replay_header,[]);write('workers.csv.guard.csv',guards,[])
    values=dict(v,callback_records_retained='1',callback_records_total='1')
    reviewed=review_run(p,values)
    assert reviewed['MEASUREMENT_QUALITY']=='FAIL' and 'callback_budget' in reviewed['review_faults']
print('Callback telemetry-tail budget detection PASS')
# Recorder ignoring graceful/terminate requests is killed after bounded stages.
class StuckRecorder(FakeRecorder):
    def __init__(self):self.returncode=None;self.signals=[];self.terminated=False;self.killed=False
    def send_signal(self,s):self.signals.append(int(s))
    def terminate(self):self.terminated=True
    def kill(self):self.killed=True;self.returncode=-9
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);tmp=p/'temp';tmp.mkdir();process=StuckRecorder();ticks=[0]
    def clock():ticks[0]+=10;return ticks[0]
    info=dict(path=str(p),pool='one',device=1,total=10000,free=10000)
    with patch('phase47_trace_storage.volume_fast',lambda v:v),patch('phase47_trace_storage.subprocess.Popen',return_value=process),patch('phase47_trace_storage.time.sleep',lambda _:None),patch('phase47_trace_storage.time.monotonic',clock):
        result=record(['fake'],p/'system.trace',tmp,tmp,5,dict(max_temporary_bytes=100,growth_bytes_per_second=1,max_xml_bytes=10),[info,dict(info,path=str(tmp))])
    assert process.signals and process.terminated and process.killed
    assert result['STORAGE_STATUS']=='ABNORMAL_EXIT' and result['record_exit']==-9
print('Bounded SIGINT/terminate/kill failure detection PASS')
# A short recording is not permission to run long-input or repeated native
# trials before the separate short-trace calibration has actually passed.
import phase46_native
with tempfile.TemporaryDirectory() as directory:
    with patch('phase46_native.ROOT',Path(directory)),patch('phase46_native.subprocess.Popen') as launch:
        for seconds in (5,35,120):
            try:phase46_native.run(Path(directory)/'runs',trace=True,trace_seconds=seconds)
            except SystemExit:pass
            else:raise AssertionError('Native trace bypassed calibration gate')
        launch.assert_not_called()
print('Native short/long recording calibration prerequisite PASS')
