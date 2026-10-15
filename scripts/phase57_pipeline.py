"""Run remaining checks strictly in series after the live Stage2 process."""
import json,subprocess,sys,time
from pathlib import Path
from phase55_study import ROOT
OUT=ROOT/'results/phase57'
def state(stage,status='running'):
    (OUT/'pipeline_status.json').write_text(json.dumps(dict(stage=stage,status=status,utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())),indent=2)+'\n')
def step(name,command,log):
    state(name);print(name,flush=True)
    with (OUT/log).open('x') as stream:r=subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    if r.returncode:state(name,'failed');raise SystemExit(f'{name} failed ({r.returncode}): {OUT/log}')
state('await_stage2')
while not (OUT/'stage2/summary.json').exists():
    path=OUT/'stage2.log'
    if path.exists() and 'Traceback (most recent call last)' in path.read_text():state('stage2','failed');raise SystemExit('Stage2 failed; further stages halted')
    time.sleep(10)
assert json.loads((OUT/'stage2/summary.json').read_text())['PASS']
step('configure_release',['cmake','-S','.','-B','build','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF'],'configure_release_final.log')
step('build_release',['cmake','--build','build','-j3'],'build_all_release.log')
step('unit_release',['ctest','--test-dir','build','-R','^(phase13|phase56_.*|phase57_.*)$','--output-on-failure','-j1'],'ctest_release_focused.log')
step('configure_debug',['cmake','-S','.','-B','build/phase57_debug','-DCMAKE_BUILD_TYPE=Debug','-DCMAKE_OSX_ARCHITECTURES=arm64','-DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF'],'configure_debug.log')
step('build_debug',['cmake','--build','build/phase57_debug','--target','phase57_check','phase57_tests','phase57_reference','phase56_tests','phase56_check','phase56_fixed_modes','phase56_reference','phase13_tests','-j3'],'build_debug.log')
step('frozen_debug_reference',[sys.executable,'-B','scripts/phase57_frozen_core.py','--build','build/phase57_debug','--destination','build/phase57_frozen/reference_debug'],'frozen_debug_reference.log')
step('unit_debug',['ctest','--test-dir','build/phase57_debug','-R','^(phase13|phase56_.*|phase57_.*)$','--output-on-failure','-j1'],'ctest_debug.log')
step('independent_debug_pcm',[sys.executable,'-B','scripts/phase57_study.py','--suite','smoke','--output','results/phase57/debug_smoke','--binary','build/phase57_debug/phase57_check','--reference','build/phase57_frozen/reference_debug'],'debug_smoke.log')
step('legacy_equivalence',[sys.executable,'-B','scripts/phase57_equivalence.py','--output','results/phase57/legacy_equivalence'],'legacy_equivalence.log')
step('timing_equivalence',[sys.executable,'-B','scripts/phase57_equivalence.py','--output','results/phase57/timing_equivalence','--current','build/phase57_frozen/reference_timing'],'timing_equivalence.log')
for suite in ('rejections','long','natural'):
    step(suite,[sys.executable,'-B','scripts/phase57_study.py','--suite',suite,'--output',f'results/phase57/{suite}'],f'{suite}.log')
step('ctest_deterministic',['ctest','--test-dir','build','-L','deterministic','--output-on-failure','-j1'],'ctest_deterministic.log')
step('golden',[sys.executable,'-B','scripts/phase57_golden.py','--output','results/phase57/golden'],'golden.log')
step('audit',[sys.executable,'-B','scripts/phase57_audit.py','--output','results/phase57/protected_final.json'],'protected_final.log')
for suite in ('performance','performance_chunks'):
    step(suite,[sys.executable,'-B','scripts/phase57_study.py','--suite',suite,'--output',f'results/phase57/{suite}','--reference','build/phase57_frozen/reference_timing'],f'{suite}.log')
state('complete','passed');print('All serial checks completed',flush=True)
