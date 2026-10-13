#!/usr/bin/env python3
"""Numeric corruption must not disappear in selection or produce PASS."""
import csv,json,tempfile
from pathlib import Path
from phase48_metrics import validated_values,measure,stability_verdict,aggregate

for value,reason in [('nan','nonfinite'),('inf','nonfinite'),('-inf','nonfinite'),('-2','unexpected_negative'),(None,'missing'),('text','not_numeric'),('','missing')]:
    values,audit=validated_values([dict(dsp_wall_s=value),dict(dsp_wall_s='0.1')],'dsp_wall_s',1000)
    assert values==[100.0] and audit['invalid_count']==1 and audit['invalid_reasons'][reason]==1
    assert stability_verdict('PASS',False,False)!='PASS'
values,audit=validated_values([dict(publication_interval_s='-1'),dict(publication_interval_s='.02')],'publication_interval_s',1000)
assert values==[20] and audit['excluded_count']==1 and audit['invalid_count']==0
assert validated_values([dict(dsp_wall_s='-1')],'dsp_wall_s')[1]['invalid_count']==1
assert validated_values([dict(publication_interval_s='.02'),dict(publication_interval_s='-1')],'publication_interval_s')[1]['invalid_count']==1
stale=dict(candidate='A',METRIC_INTEGRITY='FAIL',stability_evidence_valid=True,observed_underrun=False,NATIVE_STABILITY_VERDICT='PASS',underrun_frames=0)
assert aggregate([stale])['NATIVE_QUALITY']=='INDETERMINATE'
assert aggregate([stale])['candidates']['A']['verdict_counts']['PASS']==0

with tempfile.TemporaryDirectory() as directory:
    p=Path(directory)
    row=dict(candidate='A',stress='0',fifo_capacity_frames='16384',lead_limit_frames='12288',dsp_block_frames='2048',cpu_stress_threads='0',worker_qos_requested='inherited',
             output_device_rate='48000',dsp_sample_rate='48000',output_device_buffer_frames='512',MEASUREMENT_QUALITY='PASS',PCM_CORRECTNESS='PASS',AUDIO_QUALITY='PASS',underrun_frames='0',input_path=str(p/'unused.wav'))
    (p/'csv_integrity.json').write_text(json.dumps(dict(CSV_INTEGRITY='PASS')))
    (p/'playback.log').write_text('dsp_sample_rate=48000\ndevice_presentation_latency_ms=1.375\n')
    (p/'replay.csv').write_text('generation,from,target\n')
    with (p/'callbacks.csv').open('w',newline='') as f:
        f.write('render_requested_frames,callback_start_mach_ns,callback_end_mach_ns\n512,1000000,1001000\n')
    fields=['dsp_wall_s','dsp_cpu_s','cycle_wall_s','cycle_cpu_s','publication_interval_s']
    for bad in ('nan','inf','-inf','-2',None,'bad'):
        rows=[dict.fromkeys(fields,'.01'),dict.fromkeys(fields,'.02')]
        rows[0]['publication_interval_s']='-1';rows[1]['dsp_wall_s']=bad
        with (p/'workers.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
        r=measure(row,p,{})
        assert r['CONFIG_VALIDITY']=='PASS' and r['PCM_CORRECTNESS']=='PASS'
        assert r['METRIC_INTEGRITY']=='FAIL' and r['MEASUREMENT_QUALITY']=='FAIL' and r['NATIVE_STABILITY_VERDICT']!='PASS'
        assert r['metric_value_audits']['dsp_wall_s']['invalid_count']==1
    rows[1]['dsp_wall_s']='.02'
    with (p/'workers.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    r=measure(row,p,{})
    assert r['METRIC_INTEGRITY']=='PASS' and r['NATIVE_STABILITY_VERDICT']=='PASS'
print('Finite-before-sentinel selection, audits and fail-closed metric verdict PASS')
