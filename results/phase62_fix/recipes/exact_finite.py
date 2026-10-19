"""Exact896の参照全量を再生成し、同一SHAと非有限値0を独立確認する。"""
import json,sys,time,subprocess
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity,sha
F=ROOT/'build/phase62_fix/run_01/final_v9';OUT=F/'exact_finite';EXACT=F/'evidence/release_exact/exact';ORACLE=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference'
if len(sys.argv)>1:
 import numpy as np
 key=sys.argv[1];r,c,e,s,preset=key.split('_');source=EXACT/f'boundary_{r}_{c}_{e}.wav';raw=OUT/(key+'.f32')
 records=[json.loads(line) for line in (EXACT/'rows.jsonl').read_text().splitlines()];rows=[row for row in records if row['name']==key];expected={row['reference_pcm_sha256'] for row in rows}
 command=[str(ORACLE),str(source),s,preset,str(raw),'0',str(max(row['input_frame'] for row in rows))]
 p=subprocess.run(command,capture_output=True,text=True);print(p.stdout+p.stderr,end='')
 if p.returncode:raise SystemExit(p.returncode)
 meta=json.loads(p.stdout);data=np.fromfile(raw,dtype='<f4');bad=int(np.count_nonzero(~np.isfinite(data)));actual=sha(raw)
 result=dict(PASS=len(records)==896 and len(rows)==8 and len(expected)==1 and actual==next(iter(expected))==meta['sha256'] and bad==0,nonfinite=bad,samples=len(data),reference_sha256=actual,expected_sha256=list(expected),command=command,oracle=identity(ORACLE),input=identity(source))
 (OUT/(key+'.json')).write_text(json.dumps(result,indent=2)+'\n');raise SystemExit(int(not result['PASS']))
cases=[dict(id='architecture',kind='exit')]
for r in (44100,48000):
 for c in (1,2):
  for e in (1,3):
   for s in (400000,500000,750000,1000000,1250000,1500000,2000000):
    for preset in ('candidate','baseline'):
     key=f'{r}_{c}_{e}_{s}_{preset}';cases.append(dict(id=key,kind='json_pass',required=[key+'.json',key+'.f32'],result=key+'.json'))
frozen=source_manifest(ROOT);ledger=Ledger(OUT,cases,dict(source=frozen,driver=identity(__file__),oracle=identity(ORACLE),architecture='arm64',purpose='参照全量のfinite検査とExact896参照SHA照合'))
while not (F/'deep_long_seed/SUMMARY.json').is_file():time.sleep(5)
if source_manifest(ROOT)['sha256']!=frozen['sha256']:raise SystemExit('SOURCE CHANGED')
for spec in cases:
 key=spec['id'];command=[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py',ORACLE] if key=='architecture' else [sys.executable,'-B',__file__,key]
 good=ledger.run(key,command,cwd=ROOT,timeout=300,inputs=[ORACLE]);print(key,ledger.rows[key]['status'],flush=True)
 if key=='architecture' and not good:break
ledger.save();r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
