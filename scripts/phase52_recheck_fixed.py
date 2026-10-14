"""Preserve initial verification failure; correct only reference EOS length."""
import csv,json,subprocess,hashlib
from pathlib import Path
from phase52_validate import ROOT,OUT,BUILD,kv,source
from phase52_verdict import classify
root=next((OUT/'native').glob('20261014_134247'));rows=[]
for folder in sorted(root.iterdir()):
 if not (folder/'validation.json').exists():continue
 old=json.loads((folder/'validation.json').read_text());speed=old['initial'];inp=source(old['source'],5);ref=folder/'reference_round_eos.wav'
 r=subprocess.run(list(map(str,[BUILD/'playback_reference',inp,ref,speed,folder/'plans.csv','L2','safe-density'])),text=True,capture_output=True,timeout=120)
 (folder/'reference_round_eos.log').write_text(r.stdout+r.stderr)
 digest=subprocess.check_output([str(BUILD/'phase45_pcm_hash'),str(ref)],text=True);values=dict(l.split('=',1) for l in digest.splitlines() if '=' in l)
 row=dict(old);row.update(classify(row,old['exit']));row['PCM_CORRECTNESS']='PASS' if r.returncode==0 and values['pcm_sha256']==row['raw_pcm_sha256'] and int(values['frames'])==int(row['output_frames']) else 'FAIL'
 row['original_verification']=old['PCM_CORRECTNESS'];row['correction_reason']='Fixed-speed reference EOS was taken from the interpolated padded TimeMap; app/frozen fixed contract is round(inputFrames/speed). No native PCM changed.'
 row['reference_sha256']=hashlib.sha256(ref.read_bytes()).hexdigest();row['VERDICT']='PASS' if row['PCM_CORRECTNESS']==row['AUDIO_QUALITY']==row['MEASUREMENT_QUALITY']=='PASS' and row['exit']==0 else 'FAIL'
 (folder/'validation_round_eos.json').write_text(json.dumps(row,indent=2));rows.append(row);print(folder.name,row['VERDICT'],flush=True)
(root/'summary_round_eos.json').write_text(json.dumps(rows,indent=2));assert len(rows)==30 and all(r['VERDICT']=='PASS' for r in rows)
