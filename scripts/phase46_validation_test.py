#!/usr/bin/env python3
"""Fault-detection successes are not successful audio or trace experiments."""
import csv
import tempfile
from pathlib import Path
from phase46_trace import capture_status,analyze,coverage
from phase45_verdict import host_failures,native_verdict
from phase46_forensics import percentile

host=dict(host_timestamp_valid_callbacks='100',host_timestamp_missing_callbacks='0',
    host_timestamp_backwards='0',host_timestamp_cadence_errors='0',sample_timestamp_errors='0',
    host_timestamp_offset_outliers='0',
    hal_window_deadline_misses='0',host_continuity_tolerance_ns='100000',
    min_callback_start_minus_host_ns='-13000000',max_callback_start_minus_host_ns='-12000000')
assert not host_failures(host) # Future timestamps are normal for this rendering path.
for key in host:
    missing=dict(host);missing.pop(key);assert host_failures(missing),key
for key in ('host_timestamp_missing_callbacks','host_timestamp_backwards',
            'host_timestamp_cadence_errors','sample_timestamp_errors','hal_window_deadline_misses'):
    assert host_failures(dict(host,**{key:'1'})),key
assert percentile([1,2,3,4],.95)==4
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory);trace=p/'system.trace';trace.mkdir();(trace/'data.bin').write_bytes(b'fixture')
    toc=p/'toc.xml'
    def write_toc(code=0):
        toc.write_text(f'''<trace-toc><run><info><target><process name="phase43_play" pid="123" return-exit-status="{code}"/></target><start-date>2026-10-13T00:00:00+00:00</start-date></info><data><table schema="thread-state"/></data></run></trace-toc>''')
    write_toc()
    assert capture_status(trace,0,'Recording finished',toc,0,0,123)['TRACE_CAPTURE']=='PASS'
    assert capture_status(trace,1,'[Error] Recording failed',toc,0,0,123)['TRACE_CAPTURE']=='FAIL'
    assert capture_status(trace,0,'ok',toc,1,0,123)['TRACE_CAPTURE']=='FAIL'
    write_toc(4)
    assert capture_status(trace,54,'Recording finished',toc,0,4,123)['TRACE_CAPTURE']=='PASS'
    assert capture_status(trace,54,'ok',toc,0,0,123)['TRACE_CAPTURE']=='FAIL'
    assert capture_status(trace,0,'ok',toc,0,0,456)['TRACE_CAPTURE']=='FAIL'
    states=p/'states.xml'
    states.write_text('''<root><row><start-time id="s">0</start-time><thread id="t"><tid id="tid">7</tid><process id="p"><pid id="pid">123</pid></process></thread><thread-state id="r">Running</thread-state><duration id="d">1000000</duration><process ref="p"/></row></root>''')
    blocks=p/'workers.csv'
    blocks.write_text('thread_id,start_unix_ns,end_unix_ns\n7,1791849600000000000,1791849600001000000\n')
    a,_=analyze(toc,states,blocks,123,0)
    assert a['TRACE_ANALYSIS']=='PASS' and a['target_rows']==1,a
    a,_=analyze(toc,states,blocks,123,1)
    assert a['TRACE_ANALYSIS']=='FAIL' # Export failed even when capture succeeded.
    a,_=analyze(toc,states,blocks,456,0)
    assert a['TRACE_ANALYSIS']=='FAIL' # Wrong target process never passes.
    measured=coverage([(0,500,'Preempted'),(500,1000,'Unknown')],0,1000)
    assert measured['coverage_fraction']==1 and measured['known_fraction']==.5
print('trace capture / audio exit / XML failure and host fault detection PASS')
