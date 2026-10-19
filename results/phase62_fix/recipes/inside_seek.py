import json,sys,time,shlex
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';B=(F/'release').resolve();OUT=F/'inside_seek';CPP=F/'inside_seek_native.cpp';ORACLE=R/'build/phase61/oracle_release_v1/phase61_frozen_reference';sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity
cases=[dict(id=n,kind='exit') for n in ('compile','link','architecture')];jobs=[]
compile=['/usr/bin/c++','-I'+str(R/'src'),'-I'+str(R/'tests'),'-O3','-DNDEBUG','-std=c++20','-arch','arm64','-c',CPP,'-o',OUT/'host.o']
link=shlex.split((B/'CMakeFiles/phase62_native_tests.dir/link.txt').read_text());link[link.index('CMakeFiles/phase62_native_tests.dir/tests/Phase62NativeTests.cpp.o')]=str(OUT/'host.o');link[link.index('-o')+1]=str(OUT/'host')
jobs=[('compile',compile),('link',link),('architecture',[sys.executable,'-B',R/'scripts/phase62_evidence.py',OUT/'host',ORACLE])]
for rate,ch,enc in [(44100,1,1),(48000,2,1)]:
 source=F/f'evidence/release_controls/boundary_{rate}_{ch}_{enc}.wav'
 for preset in ('candidate','baseline'):
  key=f'inside_{rate}_{ch}_{preset}';reference=key+'_reference';raw=OUT/(key+'.f32')
  cases.append(dict(id=reference,kind='exit',required=[key+'.f32']));jobs.append((reference,[ORACLE,source,750000,preset,raw,17,17+rate,17+rate*2]))
  cases.append(dict(id=key,kind='native',cycles=10,period_preserving=True,clear_contract=True,result=key+'/result.json',required=[key+'/'+name for name in ('result.json','boundaries.jsonl','last_boundary.json','loop_final_reuse.json','clear_result.json','inside_seek.json','inside_reference.json','after_clear_callbacks_all_spans.jsonl')]))
  jobs.append((key,[OUT/'host',source,OUT/key,2,2,10,preset,'controls',17,raw]))
  name=key+'_clock';cases.append(dict(id=name,kind='json_pass',result=key+'/clock_recomputed.json',required=[key+'/clock_recomputed.json']));jobs.append((name,[sys.executable,'-B',R/'scripts/phase62_clock_audit.py',OUT/key/'after_clear_callbacks_all_spans.jsonl','--output',OUT/key/'clock_recomputed.json']))
while not (F/'clock_startup_extended/SUMMARY.json').is_file():time.sleep(5)
ledger=Ledger(OUT,cases,dict(source=source_manifest(R),supplemental_test_source=identity(CPP),driver=identity(__file__),purpose='interior seek I=A+(B-A)/2, actual return to original A and independent fixed .75 RAW by source output offset; safe positions only, not near-B general approval'))
for name,cmd in jobs:
 good=ledger.run(name,list(map(str,cmd)),cwd=B,timeout=600,inputs=[CPP,ORACLE]);print(name,ledger.rows[name]['status'],flush=True)
 if name in ('compile','link','architecture') and not good:break
r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
