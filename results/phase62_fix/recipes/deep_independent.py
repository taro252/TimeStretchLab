"""同じ最終実行体・300秒入力で、独立全長RAWと後半Aの再利用を照合。"""
import json,sys,time
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity
FINAL=ROOT/'build/phase62_fix/run_01/final_v9';BUILD=(FINAL/'release').resolve();OUT=FINAL/'deep_independent';SOURCE=FINAL/'evidence/release_longA/same_300s_48000_2_pcm16.wav';ORACLE=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference'
intervals=[(s*48000,s*48000+n) for s in (0,30,270) for n in (4800,24000)]
cases=[dict(id='configure',kind='exit'),dict(id='build',kind='exit')];jobs=[('configure',['cmake','-S',ROOT,'-B',BUILD,'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON']),('build',['cmake','--build',BUILD,'--target','phase62_fix_reuse_tests','-j3'])]
for preset in ('candidate','baseline'):
 raw=OUT/(preset+'.f32');positions=[v for pair in intervals for v in pair]
 cases.append(dict(id=preset+'_reference',kind='exit',required=[preset+'.f32']));jobs.append((preset+'_reference',[ORACLE,SOURCE,2000000,preset,raw,*positions]))
 for i,(a,b) in enumerate(intervals):
  key=f'{preset}_A{a}_B{b}';cases.append(dict(id=key,kind='pcm',reference_case=preset+'_reference',position_index=i*2));jobs.append((key,[BUILD/'phase62_fix_reuse_tests',SOURCE,2000000,preset,a,b,raw,'OA','OB']))
frozen=source_manifest(ROOT);ledger=Ledger(OUT,cases,dict(source=frozen,driver=identity(__file__),oracle=identity(ORACLE),configuration='Release',build=str(BUILD),reason='実機性能測定との同時実行を避けて直列実行'))
while not (FINAL/'FINAL_AGGREGATE.json').is_file():time.sleep(5)
if source_manifest(ROOT)['sha256']!=frozen['sha256']:raise SystemExit('SOURCE CHANGED')
for name,cmd in jobs:
 spec=next(c for c in cases if c['id']==name)
 if 'reference_case' in spec:
  if ledger.rows[spec['reference_case']]['status']!='PASS':continue
  m=json.loads((OUT/(spec['reference_case']+'.log')).read_text());i=spec['position_index'];cmd=[m['positions'][i] if v=='OA' else m['positions'][i+1] if v=='OB' else v for v in cmd]
 inputs=[Path(str(v)) for v in cmd[1:] if Path(str(v)).is_file() and Path(str(v)).suffix in ('.wav','.f32')]
 ok=ledger.run(name,cmd,cwd=ROOT,timeout=600,inputs=inputs)
 print(name,ledger.rows[name]['status'],flush=True)
 if name in ('configure','build') and not ok:break
if source_manifest(ROOT)['sha256']!=frozen['sha256']:
 for row in ledger.rows.values():row.update(status='INCOMPLETE',source_changed_during_run=True)
ledger.save();result=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(result['counts'],flush=True)
