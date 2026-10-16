"""Run only after physical audio tests: build and DSP checks are strictly serial."""
import json,subprocess,time
from pathlib import Path
from phase57_study import ROOT,sha

root=ROOT/'results/phase58_fix';(root/'regression').mkdir(exist_ok=False);root=root/'regression';history=[]
def run(name,cmd):
    path=root/(name+'.log');start=time.time()
    with path.open('x') as output:
        p=subprocess.run(list(map(str,cmd)),cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
    history.append(dict(name=name,command=list(map(str,cmd)),exit=p.returncode,wall_s=time.time()-start,started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(start))))
    (root/'regression_driver.json').write_text(json.dumps(history,indent=2)+'\n');print(name,p.returncode,flush=True);return p.returncode

assert run('release_configure',['cmake','-S','.', '-B','build','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DTIMESTRETCH_ENABLE_REALTIME_TESTS=ON'])==0
assert run('release_all_build',['cmake','--build','build','-j3'])==0
run('ready_stress',['python3','scripts/phase58_ready_stress.py','--output',root/'ready_stress'])
run('deterministic_ctest',['ctest','--test-dir','build','-L','deterministic','--output-on-failure','-j1'])
assert run('debug_configure',['cmake','-S','.', '-B','build/phase58_fix_debug','-DCMAKE_BUILD_TYPE=Debug','-DCMAKE_OSX_ARCHITECTURES=arm64','-DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF'])==0
assert run('debug_related_build',['cmake','--build','build/phase58_fix_debug','--target','phase58_tests','phase58_check','phase58_product_reference','phase58_fix_tests','phase58_fix_mailbox_tests','phase58_fix_worker_tests','phase57_tests','phase57_check','phase57_reference','phase56_tests','phase56_check','phase56_reference','phase56_fixed_modes','-j3'])==0
run('debug_ctest',['ctest','--test-dir','build/phase58_fix_debug','-R','^(phase56_.*|phase57_.*|phase58_.*)$','--output-on-failure','-j1'])
for sanitizer in ('thread','address,undefined'):
    label=sanitizer.replace(',','_');binary=ROOT/'build/phase58_fix_frozen'/('mailbox_'+label)
    code=run('mailbox_'+label+'_build',['clang++','-std=c++20','-O1','-g','-fsanitize='+sanitizer,'-Isrc','tests/Phase58FixMailboxTests.cpp','-pthread','-o',binary])
    if code==0:run('mailbox_'+label+'_run',[binary])
for suite in ('short','all_speeds','long'):
    run('pcm58_'+suite,['python3','-B','scripts/phase58_fix_study.py','--suite',suite,'--output',root/('pcm58_'+suite)])
for suite in ('stage1','stage2','long','natural','rejections'):
    cmd=['python3','scripts/phase57_study.py','--suite',suite,'--output',root/('regress57_'+suite),'--reference',ROOT/'build/phase57_frozen/reference','--binary',ROOT/'build/phase57_check']
    if suite=='stage2':cmd+=['--prerequisite',root/'regress57_stage1/summary.json']
    run('regress57_'+suite,cmd)
run('golden25',['python3','scripts/phase57_golden.py','--output',root/'golden25'])
run('protected_assets',['python3','scripts/phase58_fix_audit.py','--output',root/'protected_assets.json','--allow','src/audio/WavStream.cpp','--allow','src/audio/WavStream.h','--allow','src/prototype/Phase36StreamingSpeedEngine.h','--allow','src/prototype/Phase58Check.cpp','--allow','src/prototype/Phase58Diagnostics.h','--allow','src/prototype/Phase58Native.mm','--allow','src/prototype/Phase58RealtimePipeline.h','--allow','src/prototype/Phase58RealtimePipeline.cpp','--allow','src/prototype/Phase36SynthesisCore.h','--allow','src/prototype/Phase57ProgressiveSynthesis.h','--allow','src/prototype/Phase57ProgressiveSynthesis.cpp'])
files=['build/phase58_check','build/phase58_native','build/phase58_legacy_startup','build/phase57_check','build/phase54_native','build/phase54_core_probe','build/phase39_reference','build/phase58_frozen/product_reference','build/phase57_frozen/reference']
settings={}
for build in ('build','build/phase58_fix_debug'):
    folder=ROOT/build
    settings[build]={name:(folder/name).read_text() for name in ('CMakeCache.txt','CMakeFiles/phase58_native.dir/flags.make','CMakeFiles/phase58_check.dir/flags.make','CMakeFiles/playback_demo.dir/link.txt') if (folder/name).exists()}
(root/'build_settings.json').write_text(json.dumps(settings,indent=2)+'\n')
(root/'final_binaries.json').write_text(json.dumps({p:sha(ROOT/p) for p in files},indent=2)+'\n')
raise SystemExit(0 if all(r['exit']==0 for r in history) else 2)
