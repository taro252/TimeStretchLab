import json,sys,time
from pathlib import Path
R=Path.cwd();sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import Ledger,aggregate,identity,source_manifest
F=R/'build/phase62_fix/run_01/final_v9';OUT=F/'post_clear_clock'
while not (F/'waveform_analysis/SUMMARY.json').is_file():time.sleep(5)
cases=[];jobs=[]
for folder in sorted((F/'evidence').glob('*'))+[F/'sandbox_evidence']:
 p=folder/'EXPECTED.json'
 if not p.is_file():continue
 for c in json.loads(p.read_text())['cases']:
  if not c.get('clear_contract'):continue
  name=folder.name+'__'+c['id'];trace=folder/Path(c['result']).parent/'after_clear_callbacks_all_spans.jsonl'
  cases.append(dict(id=name,kind='json_pass',result=name+'.json',required=[name+'.json']))
  jobs.append((name,trace))
ledger=Ledger(OUT,cases,dict(source=source_manifest(R),driver=identity(__file__),axis='last 256 callbacks after Clear, including all bounded spans'))
for name,trace in jobs:
 ledger.run(name,[sys.executable,'-B',R/'scripts/phase62_clock_audit.py',trace,'--output',OUT/(name+'.json')],cwd=R,inputs=[trace],timeout=60)
r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
