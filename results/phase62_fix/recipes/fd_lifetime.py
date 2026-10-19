import sys,json,time,shlex,subprocess
from pathlib import Path
R=Path.cwd();sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import Ledger,aggregate,source_manifest,identity
F=R/'build/phase62_fix/run_01/final_v9';B=(F/'release').resolve();OUT=F/'fd_lifetime';SOURCE=F/'fd_lifetime.cpp';INPUT=R/'build/phase62/run_01/native_release/boundary_48000_2_1.wav'
while not (F/'post_clear_clock/SUMMARY.json').is_file():time.sleep(5)
compile=['/usr/bin/c++','-I'+str(R/'src'),'-O3','-DNDEBUG','-std=c++20','-arch','arm64','-c',str(SOURCE),'-o',str(OUT/'host.o')]
link=shlex.split((B/'CMakeFiles/phase62_native_tests.dir/link.txt').read_text());link[link.index('CMakeFiles/phase62_native_tests.dir/tests/Phase62NativeTests.cpp.o')]=str(OUT/'host.o');link[link.index('-o')+1]=str(OUT/'host')
cases=[dict(id='compile',kind='exit'),dict(id='link',kind='exit'),dict(id='architecture',kind='exit'),dict(id='fd_lifetime',kind='json_pass',result='result.json',required=['result.json'])]
ledger=Ledger(OUT,cases,dict(source=source_manifest(R),supplemental_test_source=identity(SOURCE),driver=identity(__file__),input=identity(INPUT),note='Final production libraries; external host measures non-Sandbox pinned input/snapshot FD lifetime'))
jobs=[('compile',compile),('link',link),('architecture',[sys.executable,'-B',R/'scripts/phase62_evidence.py',OUT/'host']),('fd_lifetime',[OUT/'host',INPUT,OUT/'result.json'])]
for name,cmd in jobs:
 if not ledger.run(name,list(map(str,cmd)),cwd=B,timeout=600,inputs=[SOURCE,INPUT]):break
r=aggregate(OUT);(OUT/'SUMMARY.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(r['counts'],flush=True)
