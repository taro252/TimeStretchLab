#!/usr/bin/env python3
"""Native driver faults are simulated, without tracing or filling a disk."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import phase46_native as native

normal=dict(STORAGE_STATUS='NORMAL_EXIT',stop_reason='time_limit',stop_requested=False,
            record_exit=0,samples=[dict(free=1000),dict(free=800)],after=[dict(free=900)])
row=dict(native.storage_fields(normal),TRACE_CAPTURE='PASS',TRACE_ANALYSIS='PASS')
assert not native.trace_batch_must_stop(row)
assert row['storage_minimum_free_bytes']==800
for change in (
    dict(STORAGE_STATUS='PARTIAL_STOP',stop_reason='capacity_projection',stop_requested=True),
    dict(STORAGE_STATUS='ABNORMAL_EXIT',record_exit=-9),
    dict(STORAGE_STATUS='START_REFUSED',reason='insufficient_record_finish_export_budget'),
    dict(STORAGE_STATUS='PARTIAL_STOP',stop_reason='record_or_finalize_timeout',stop_requested=True),
    dict(stop_reason='capacity_projection'),
):
    outcome=dict(normal,**change)
    assert native.trace_batch_must_stop(dict(native.storage_fields(outcome),TRACE_CAPTURE='PASS',TRACE_ANALYSIS='PASS'))

class FakePlayer:
    pid=12345
    def __init__(self,command,**kwargs):
        # Observed supply failure must survive a missing-evidence verdict.
        kwargs['stdout'].write('underrun_frames=512\nworker_pcm_hash_enabled=0\n')
    def poll(self):return 0
    def wait(self,**kwargs):return 0

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory)
    (root/'results/phase47').mkdir(parents=True)
    (root/'results/phase47/calibration.json').write_text(json.dumps(dict(CALIBRATION='PASS',capacity_evidence={})))
    failed_reference=SimpleNamespace(returncode=1,stdout='',stderr='injected missing replay')
    with patch.object(native,'ROOT',root),patch.object(native.subprocess,'Popen',FakePlayer),patch.object(native.subprocess,'run',return_value=failed_reference):
        result,path=native.run(root/'no_csv',trace=False)
        assert result['CSV_INTEGRITY']=='FAIL' and result['MEASUREMENT_QUALITY']=='FAIL'
        assert result['AUDIO_QUALITY']=='FAIL' and result['underrun_frames']=='512'
        faults=json.loads((path/'csv_integrity.json').read_text())['faults']
        assert all(any(name in f for f in faults) for name in ('callbacks.csv','workers.csv','workers.csv.guard.csv','replay.csv'))
        partial=dict(normal,STORAGE_STATUS='PARTIAL_STOP',stop_reason='capacity_projection',stop_requested=True)
        with patch.object(native,'record',return_value=partial),patch.object(native,'validate_run',return_value=dict(TRACE_CAPTURE='PASS',TRACE_ANALYSIS='PASS')):
            result,path=native.run(root/'capacity_stop',trace=True,attach_after=0)
        assert result['STORAGE_STATUS']=='PARTIAL_STOP' and result['storage_stop_reason']=='capacity_projection'
        assert result['storage_stop_requested'] is True and result['storage_record_exit']==0
        assert result['TRACE_SAVE_STATE']=='PARTIAL_SAVED' and native.trace_batch_must_stop(result)
        aggregate=json.loads((path/'result.json').read_text())
        assert aggregate['storage_minimum_free_bytes']==800
print('Missing CSV and decodable capacity-stop native driver injection PASS')
from phase48_metrics import aggregate
def metric(valid,missing,verdict):
    r=dict(candidate='A',stability_evidence_valid=valid,observed_underrun=bool(missing),NATIVE_STABILITY_VERDICT=verdict,underrun_frames=missing,max_continuous_missing_ms=missing/48)
    for k in ('dsp_wall_s_ms','dsp_cpu_s_ms','cycle_wall_s_ms','cycle_cpu_s_ms'):r[k]=dict(max=1,p95=.8,p99=.9)
    return r
outcome=aggregate([metric(True,512,'FAIL'),metric(True,0,'PASS'),metric(False,0,'INDETERMINATE'),metric(False,512,'FAIL')])
assert outcome['NATIVE_QUALITY']=='FAIL'
summary=outcome['candidates']['A']
assert summary['runs']==4 and summary['valid_runs']==2
assert summary['observed_underrun_rate']==.5 and summary['valid_underrun_rate']==.5
assert summary['verdict_counts']==dict(PASS=1,FAIL=2,INDETERMINATE=1)
assert summary['missing_frames_all']==1024
print('Invalid measurement excluded from stability PASS; all observed shortages retained PASS')
