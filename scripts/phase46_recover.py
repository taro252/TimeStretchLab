"""Recover evidence from the ENOSPC-aborted driver; unknown native exit is not a pass."""
import json,subprocess
from pathlib import Path
from phase45_store import parse_log,save_result
from phase45_verdict import native_verdict
from phase46_forensics import investigate
root=Path(__file__).resolve().parents[1]
output=root/'results/phase46/native'
path=output/'runs/20261013T135940.647340+0900_drums_3m_A_trace1_12a852ce'
if (path/'result.json').exists():raise SystemExit('Immutable result already exists')
values=parse_log((path/'playback.log').read_text())
validation=dict(TRACE_CAPTURE='FAIL',TRACE_ANALYSIS='FAIL',record_exit=None,driver_exit=120,
    reason='Driver aborted with disk full before recorder exit/TOC/export could be persisted',
    trace_exists=True,trace_bytes=sum(f.stat().st_size for f in (path/'system.trace').rglob('*') if f.is_file()),
    temporary_file_removed='/private/var/folders/ft/xsqp1bg15lvcr2m90ynsllmr0000gn/T/instrumentsX8qy9p.ktrace',
    temporary_bytes_removed=3842878440,native_exit=None)
(path/'trace_validation.json').write_text(json.dumps(validation,indent=2))
row=dict(run_id=path.name,run_time='2026-10-13T13:59:40.647340+09:00',source='drums',input_minutes=3,
    candidate='A',stress=1,trace_requested=1,profile=1,attach_after_seconds=40,trace_seconds=35,
    exit_code='unmeasured',recovered=1)
row.update(values);row.update(native_verdict(values,120));row.update(validation)
row.update(investigate(path,values))
source=root/'results/phase40/long_input/drums_repeat_180.wav'
reference=path/'reference.wav'
result=subprocess.run([str(root/'build/phase39_reference'),str(source),str(reference),'0.4',str(path/'replay.csv'),'C','safe-density'],capture_output=True,text=True,timeout=1800)
(path/'reference.log').write_text(result.stdout+result.stderr)
if result.returncode==0:
    digest=subprocess.run([str(root/'build/phase45_pcm_hash'),str(reference)],capture_output=True,text=True)
    (path/'reference_hash.log').write_text(digest.stdout+digest.stderr)
    checked=parse_log(digest.stdout)
    row['PCM_CORRECTNESS']='PASS' if checked.get('pcm_sha256')==values.get('worker_pcm_sha256') and checked.get('frames')==values.get('output_length') and checked.get('nonfinite')=='0' else 'FAIL'
else:row['PCM_CORRECTNESS']='FAIL'
row['AUDIO_QUALITY']='FAIL' if int(values.get('underrun_frames','0'))>0 else 'INDETERMINATE'
# A missing process exit never hides an already observed supply failure.
save_result(output,path,row)
print(path.name,row['AUDIO_QUALITY'],row['MEASUREMENT_QUALITY'],row['TRACE_CAPTURE'],row['PCM_CORRECTNESS'])
