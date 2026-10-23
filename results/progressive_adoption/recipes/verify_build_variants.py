"""Run only after audio/performance work: Debug and shared iOS compilation."""
import argparse,json,pathlib,subprocess,sys,time
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'));from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--base',type=pathlib.Path,required=True);a=p.parse_args();b=a.base;o=b/'build_variants_01';o.mkdir();source=source_manifest(R);rows=[]
def run(i,cmd,timeout=240):
 t=time.monotonic();timed=False
 with (o/(i+'.log')).open('w') as log:
  try:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=timeout).returncode
  except subprocess.TimeoutExpired:rc=None;timed=True
 if i=='repo_unchanged' and (o/(i+'.log')).read_text().strip():rc=1
 rows.append(dict(id=i,command=cmd,exit=rc,timeout=timed,wall_s=time.monotonic()-t,log=identity(o/(i+'.log'))));(o/'SUMMARY.json').write_text(json.dumps(dict(source=source['sha256'],expected=7,executed=len(rows),PASS=len(rows)==7 and all(x['exit']==0 and not x['timeout'] for x in rows),rows=rows),indent=2));print(i,rc,flush=True);return rc
py='/usr/local/bin/python3';buildcmd=[py,str(R/'results/phase62_control_ab/recipes/build_suite.py'),'--source',str(R),'--build',str(b/'debug'),'--record',str(b/'build_debug_01'),'--config','Debug','--targets','progressive_adoption_contract_tests','progressive_adoption_native_tests']
sdk=subprocess.check_output(['/usr/bin/xcrun','--sdk','iphonesimulator','--show-sdk-path'],text=True).strip();device_sdk=subprocess.check_output(['/usr/bin/xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip();probe=o/'SharedHeaders.cpp';probe.write_text('#include "playback/ProgressiveContract.h"\n#include "playback/ProgressiveSeekContract.h"\n#include "playback/ProgressiveLoopContract.h"\n#include "platform/macos/ProgressiveMacPlaybackEngine.h"\nstatic_assert(ts::playback::progressive::contractVersion==3);\nint main(){auto o=ts::playback::ProgressiveOptions::macOSProduct();return !o.featurePolicy;}\n')
cmds=[('debug_build',buildcmd,240),('debug_contract',[str(b/'debug/progressive_adoption_contract_tests')],60),('debug_native',[py,str(R/'results/progressive_adoption/recipes/run_native_suite.py'),'--build-record',str(b/'build_debug_01/BUILD.json'),'--input',str(b/'inputs/mono48_16s.wav'),'--output',str(b/'debug_native_01'),'--modes','prewarm_ready'],120),('ios_simulator_headers',['/usr/bin/xcrun','clang++','-std=c++20','-target','arm64-apple-ios17.0-simulator','-isysroot',sdk,'-I'+str(R/'src'),'-fsyntax-only',str(probe)],120),('ios_device_headers',['/usr/bin/xcrun','clang++','-std=c++20','-target','arm64-apple-ios17.0','-isysroot',device_sdk,'-I'+str(R/'src'),'-fsyntax-only',str(probe)],120),('ios_app_build',['/usr/bin/xcodebuild','-project','/Users/taro252/Docker/merodoa/Merodoa.xcodeproj','-scheme','Merodoa','-configuration','Debug','-sdk','iphonesimulator','-destination','generic/platform=iOS Simulator','-derivedDataPath',str(b/'ios_derived'),'CODE_SIGNING_ALLOWED=NO','build'],300),('repo_unchanged',['/usr/bin/git','-C','/Users/taro252/Docker/merodoa','status','--porcelain=v1'],30)]
(o/'EXPECTED.json').write_text(json.dumps(dict(source=source,driver=identity(pathlib.Path(__file__)),probe=identity(probe),expected=7,commands=cmds,scope='Debug functions, new v3 shared headers for iOS SDKs, existing app iOS build with unchanged f4 submodule; no iOS audio implementation or native v3 Swift integration'),indent=2))
for i,cmd,timeout in cmds:
 if i in ('debug_contract','debug_native') and rows[0]['exit']!=0:continue
 run(i,cmd,timeout)
assert source_manifest(R)==source
