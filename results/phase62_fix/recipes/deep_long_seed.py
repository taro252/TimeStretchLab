"""短区間キャッシュに入らない後半Aも、既存の最終実行体で独立照合する。"""
import json,sys,time,subprocess
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity,sha
F=ROOT/'build/phase62_fix/run_01/final_v9';OUT=F/'deep_long_seed';B=(F/'release').resolve();source=F/'evidence/release_longA/same_300s_48000_2_pcm16.wav';oracle=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference'
if len(sys.argv)>1:
 preset=sys.argv[1];raw=F/'deep_independent'/(preset+'.f32');cmd=[str(oracle),str(source),'2000000',preset,'/dev/null',str(270*48000),str(280*48000)]
 p=subprocess.run(cmd,capture_output=True,text=True);print(p.stderr,end='',file=sys.stderr)
 if p.returncode:raise SystemExit(p.returncode)
 m=json.loads(p.stdout);m['PASS']=m['sha256']==sha(raw) and len(m['positions'])==2;m['command']=cmd
 (OUT/(preset+'_coords.json')).write_text(json.dumps(m,indent=2)+'\n');raise SystemExit(int(not m['PASS']))
cases=[dict(id='configure',kind='exit'),dict(id='build',kind='exit'),dict(id='architecture',kind='exit')]
jobs=[('configure',['cmake','-S',ROOT,'-B',B,'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON']),('build',['cmake','--build',B,'--target','phase62_fix_reuse_tests','-j3']),('architecture',[sys.executable,'-B',ROOT/'scripts/phase62_evidence.py',B/'phase62_fix_reuse_tests',oracle])]
for preset in ('candidate','baseline'):
 cases.append(dict(id=preset+'_coords',kind='json_pass',required=[preset+'_coords.json'],result=preset+'_coords.json'));jobs.append((preset+'_coords',[sys.executable,'-B',__file__,preset]))
 cases.append(dict(id=preset+'_long_seed',kind='pcm',coordinate_case=preset+'_coords'))
 jobs.append((preset+'_long_seed',[B/'phase62_fix_reuse_tests',source,2000000,preset,270*48000,280*48000,F/'deep_independent'/(preset+'.f32'),'OA','OB']))
frozen=source_manifest(ROOT);ledger=Ledger(OUT,cases,dict(source=frozen,driver=identity(__file__),oracle=identity(oracle),architecture='arm64',configuration='Release'))
while not (F/'deep_independent/SUMMARY.json').is_file():time.sleep(5)
if source_manifest(ROOT)['sha256']!=frozen['sha256']:raise SystemExit('SOURCE CHANGED')
for name,cmd in jobs:
 spec=next(c for c in cases if c['id']==name)
 if 'coordinate_case' in spec:
  if ledger.rows[spec['coordinate_case']]['status']!='PASS':continue
  m=json.loads((OUT/(spec['coordinate_case']+'.json')).read_text());cmd=[m['positions'][0] if v=='OA' else m['positions'][1] if v=='OB' else v for v in cmd]
 ok=ledger.run(name,cmd,cwd=ROOT,inputs=[source] if source.is_file() else [],timeout=600);print(name,ledger.rows[name]['status'],flush=True)
 if name in ('configure','build','architecture') and not ok:break
if source_manifest(ROOT)['sha256']!=frozen['sha256']:
 for row in ledger.rows.values():row.update(status='INCOMPLETE',source_changed_during_run=True)
ledger.save();r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
