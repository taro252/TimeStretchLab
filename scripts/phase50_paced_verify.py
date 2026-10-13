#!/usr/bin/env python3
"""Independent PCM verification of saved consumer-timing trials, without rewriting logs."""
import json,subprocess
from pathlib import Path
from phase45_store import parse_log
from phase45_verdict import classify
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase50/paced'
def verify_trial(path,row):
    path=Path(path);v=row['values']
    ref=subprocess.run([str(ROOT/'build/phase39_reference'),str(ROOT/'results/phase49/input/drums30.wav'),
                        str(path/'reference.wav'),'.4',str(path/'metrics.csv.replay.csv'),'C','safe-density'],capture_output=True,text=True,timeout=120)
    (path/'reference.log').write_text(ref.stdout+ref.stderr)
    digest=subprocess.run([str(ROOT/'build/phase45_pcm_hash'),str(path/'reference.wav')],capture_output=True,text=True) if ref.returncode==0 else None
    if digest:(path/'reference_hash.log').write_text(digest.stdout+digest.stderr)
    raw=parse_log(digest.stdout) if digest else {}
    match=(ref.returncode==0 and raw.get('pcm_sha256')==v.get('pcm_sha256') and raw.get('frames')==v.get('output_frames') and raw.get('nonfinite')=='0')
    outcome=classify(v,match,row['process_exit'])
    if row['INJECTION_VALIDITY']!='PASS':outcome['OVERALL_REALTIME']='FAIL'
    return dict(callback=row['callback'],process_exit=row['process_exit'],INJECTION_VALIDITY=row['INJECTION_VALIDITY'],**outcome,
        missing_frames=v.get('missing_frames'),expired_slots=v.get('expired_callback_slots'),max_wake_seconds=v.get('max_wake_seconds'),max_callback_seconds=v.get('max_callback_seconds'))

def main():
    rows=json.loads((OUT/'summary.json').read_text())
    verified=[verify_trial(OUT/str(row['callback']),row) for row in rows]
    (OUT/'verified_quality.json').write_text(json.dumps(verified,indent=2))
    print(json.dumps(verified,indent=2))
    return 2 if any(r['OVERALL_REALTIME']!='PASS' for r in verified) else 0
if __name__=='__main__':raise SystemExit(main())
