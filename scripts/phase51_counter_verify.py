#!/usr/bin/env python3
import csv,hashlib,json,subprocess
from pathlib import Path
from phase45_store import parse_log
ROOT=Path(__file__).resolve().parents[1]
rows=[]
for history in ('C','C_L1'):
 path=ROOT/'results/phase51/counterfactual'/history
 for plan in csv.DictReader((path/'summary.csv').open()):
  label=plan['candidate'];files=[path/(label+suffix+'.wav') for suffix in ('','_1024','_2048')]
  assert plan['safe']=='1'
  hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in files];assert len(set(hashes))==1
  r=subprocess.run([str(ROOT/'build/phase45_pcm_hash'),str(files[0]),str(path/'prepared_prefix.wav')],capture_output=True,text=True,check=True)
  v=parse_log(r.stdout);assert v['first_changed_pcm_frame']=='none' and v['nonfinite']=='0'
  rows.append(dict(history=history,**plan,PCM_CORRECTNESS='PASS',prefix_unchanged=True,sha256=hashes[0]))
Path('results/phase51/counterfactual/verified.json').write_text(json.dumps(rows,indent=2))
print('Eight same-frontier branches / prefix /1024/2048 PCM PASS')
