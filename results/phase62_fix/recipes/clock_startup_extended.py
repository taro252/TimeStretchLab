import json,sys,time
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';OUT=F/'clock_startup_extended';B=(F/'release').resolve();sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity
cases=[];jobs=[]
for sourceRate,deviceRate in [(44100,48000),(44100,44100),(48000,48000)]:
 name=f'normal_{sourceRate}_to_{deviceRate}_100';source=F/f'evidence/release_clock/boundary_{sourceRate}_1_1.wav'
 cases.append(dict(id=name,kind='json_pass',result=name+'/summary.json',required=[name+'/summary.json',name+'/rows.jsonl',name+'_device.json']))
 jobs.append((name,[sys.executable,'-B',R/'scripts/phase62_fix_additional.py','--at-device-rate',deviceRate,'--output',OUT/(name+'_device.json'),B/'phase62_fix_clock_native',source,OUT/name,100]))
 for i in range(100):
  key=name+f'_audit_{i}';result=name+f'/{i}/clock_recomputed.json';cases.append(dict(id=key,kind='json_pass',result=result,required=[result]))
  jobs.append((key,[sys.executable,'-B',R/'scripts/phase62_clock_audit.py',OUT/name/str(i)/'callbacks_all_spans.jsonl','--output',OUT/result]))
ledger=Ledger(OUT,cases,dict(source=source_manifest(R),driver=identity(__file__),purpose='unresolved startup clock discontinuity; no loop requests; Candidate 0.4; 100 fresh starts per source/device pairing; unchanged clock thresholds'))
while not all((F/name/'SUMMARY.json').is_file() for name in ('piano_waveform','piano_listening_pack')):time.sleep(5)
assert source_manifest(R)['sha256']==json.loads((F/'FROZEN_SOURCE.json').read_text())['sha256']
for name,command in jobs:
 inputs=[Path(str(v)) for v in command if Path(str(v)).is_file() and Path(str(v)).suffix=='.wav']
 ledger.run(name,list(map(str,command)),cwd=R,timeout=300,inputs=inputs);print(name,ledger.rows[name]['status'],flush=True)
r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
