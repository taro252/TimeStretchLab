#!/usr/bin/env python3
import csv,tempfile,json
from pathlib import Path
from phase51_timing import analyze
def table(p,rows):
    with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
with tempfile.TemporaryDirectory() as folder:
    p=Path(folder);(p/'playback.log').write_text('dsp_sample_rate=48000\ndevice_presentation_latency_ms=1.375\nsource_output_presentation_latency_ms=1.375\n')
    op=dict(operation=1,target=1,scheduled_mach_ns=1000000000,observed_mach_ns=1001000000,sent_mach_ns=1010000000,accepted_mach_ns=1010000100,worker_seen_mach_ns=1011000000,ready_observed_mach_ns=1020000000,generation=1,busy_ns=9000000,busy_polls=2,state='Completed',clock_bridge_error_ns=100)
    table(p/'operations.csv',[op]);table(p/'replay.csv',[dict(generation=1,from_=.4,target=1,prepared=0,applied_output=1,completion_output=200)])
    # Reserved Python keyword is a CSV field.
    (p/'replay.csv').write_text((p/'replay.csv').read_text().replace('from_','from'))
    event=dict(pcm_before=0,received=512,callback_start_mach_ns=1020000000,io_complete_mach_ns=1020000100,timestamp_flags=2,host_mach_ns=1030000000,sequence=1)
    table(p/'callbacks.csv',[event]);r=analyze(p,p/'input.wav',first_changes=False)
    a=r['operations'][0];assert a['scheduled_to_send_ms']==10 and a['busy_wait_ms']==9 and a['hal_completion_to_ready_observed_ms']<0
    assert r['ready_may_precede_hal_presentation'] and not r['acoustic_loopback']
    table(p/'operations.csv',[op,op])
    try:analyze(p,p/'input.wav',first_changes=False)
    except ValueError:pass
    else:raise AssertionError('Duplicate operation accepted')
    table(p/'operations.csv',[op]);table(p/'callbacks.csv',[dict(event,received=0)])
    try:analyze(p,p/'input.wav',first_changes=False)
    except ValueError:pass
    else:raise AssertionError('Unpresented coordinate accepted')
print('Scheduled wait / ready vs audible / duplicate / missing frame timing PASS')
