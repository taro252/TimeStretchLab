import sys,json,time
from pathlib import Path
R=Path.cwd();sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import Ledger,aggregate,identity,source_manifest
F=R/'build/phase62_fix/run_01/final_v9';OUT=F/'piano_quality';B=(F/'release').resolve();SOURCE=R/'results/phase2/real/stems/audition/piano_original.wav';ORACLE=R/'build/phase61/oracle_release_v1/phase61_frozen_reference'
A=1023;LONG=96017;SHORT=A+4800;speeds=(400000,500000,750000,1000000,1500000,2000000)
cases=[];jobs=[]
for speed in speeds:
 for preset in ('candidate','baseline'):
  reference=f'reference_{speed}_{preset}';raw=OUT/(reference+'.f32')
  cases.append(dict(id=reference,kind='exit',required=[reference+'.f32']));jobs.append((reference,[ORACLE,SOURCE,speed,preset,raw,A,LONG,SHORT]))
  for duration,end,index in [('long',LONG,1),('100ms',SHORT,2)]:
   if duration=='100ms' and speed not in (400000,2000000):continue
   key=f'piano_real_{duration}_{speed}_{preset}';folder=OUT/key
   cases.append(dict(id=key,kind='period_capture',result=key+'/capture.json',required=[key+'/capture.json',key+'/raw.f32',key+'/processed.f32'],reference_case=reference,position_index=index,input_rate=48000,input_a=A,input_b_exclusive=end,input_duration_seconds=(end-A)/48000,nominal_duration=duration))
   jobs.append((key,[B/'phase62_fix_render_tests',SOURCE,speed,preset,A,end,raw,'OA','OB',folder]))
   cases.append(dict(id=key+'_measure',kind='quality',result=key+'/metrics.json',required=[key+'/metrics.json',key+'/playable_gain05.wav'],capture_case=key))
   jobs.append((key+'_measure',[sys.executable,'-B',R/'scripts/phase62_fix_quality.py','--measure',folder,'--reference',raw,'--output',folder/'metrics.json']))
while not (F/'listening_pack/SUMMARY.json').is_file():time.sleep(5)
ledger=Ledger(OUT,cases,dict(source=source_manifest(R),driver=identity(__file__),oracle=identity(ORACLE),input=identity(SOURCE),input_provenance=identity(R/'results/phase2/real/stems/REPORT.md'),source_kind='existing real-music piano original audition; instrument recording method not independently verified; not piano_synthetic'))
for name,cmd in jobs:
 spec=next(c for c in cases if c['id']==name)
 if 'reference_case' in spec:
  if ledger.rows[spec['reference_case']]['status']!='PASS':continue
  m=json.loads((OUT/(spec['reference_case']+'.log')).read_text());cmd=[m['positions'][0] if x=='OA' else m['positions'][spec['position_index']] if x=='OB' else x for x in cmd]
 if 'capture_case' in spec and ledger.rows[spec['capture_case']]['status']!='PASS':continue
 ledger.run(name,list(map(str,cmd)),cwd=R,timeout=600,inputs=[SOURCE,ORACLE])
 print(name,ledger.rows[name]['status'],flush=True)
r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
