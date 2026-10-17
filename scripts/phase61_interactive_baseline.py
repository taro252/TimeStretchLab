"""Build HEAD-a9fe222's unchanged engine with the same heap-instrumented host.

Read-only git show into ignored build storage; no checkout/history mutation.
Other DSP libraries are reused only when their tracked sources match this HEAD.
"""
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='a9fe2224193dc2e3adae23d4c98fc96db387963f'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--build',type=Path,default=ROOT/'build/phase61_interactive_seek/release');a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);build=a.build.resolve()
    copied=['src/platform/macos/ProgressiveMacPlaybackEngine.h','src/platform/macos/ProgressiveMacPlaybackEngine.mm',
            'src/prototype/Phase58RealtimePipeline.h','src/prototype/Phase58RealtimePipeline.cpp','src/playback/ProgressiveSeekContract.h']
    for name in copied:
        target=out/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT))
    for name in ['Phase61InteractiveNativeTests.cpp','Phase61NativeTests.cpp','Phase61CallbackMallocProbe.h']:
        target=out/'tests'/name;target.parent.mkdir(exist_ok=True);shutil.copy2(ROOT/'tests'/name,target)
    allowed=('src/platform/macos/ProgressiveMacPlaybackEngine.','src/prototype/Phase58RealtimePipeline.','src/playback/ProgressiveSeekContract.h')
    changed=subprocess.check_output(['git','diff','--name-only',BASE,'--','src'],cwd=ROOT,text=True).splitlines()
    if any(not name.startswith(allowed) for name in changed):raise RuntimeError('An additional DSP source changed; refusing library reuse')
    arch=subprocess.check_output(['lipo','-archs',str(build/'phase61_interactive_native_tests')],text=True).strip()
    if arch not in ('arm64','x86_64'):raise RuntimeError('Single architecture required')
    flags=['/usr/bin/c++','-O3','-DNDEBUG','-std=c++20','-arch',arch,'-I'+str(out/'src'),'-I'+str(ROOT/'src')]
    commands=[]
    def run(cmd):
        with (out/'build.log').open('a') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,cwd=ROOT)
        commands.append({'command':list(map(str,cmd)),'exit':r.returncode})
        if r.returncode:raise RuntimeError('baseline build failed; see build.log')
    objects=[]
    for name in ['src/prototype/Phase58RealtimePipeline.cpp','src/platform/macos/ProgressiveMacPlaybackEngine.mm','tests/Phase61InteractiveNativeTests.cpp']:
        obj=out/(Path(name).stem+'.o');extra=['-fobjc-arc','-DTIMESTRETCH_PHASE60_SHA="'+BASE+'"'] if name.endswith('.mm') else []
        run(flags+extra+['-c',str(out/name),'-o',str(obj)]);objects.append(str(obj))
    libraries=[build/f'lib{name}.a' for name in ['phase57_synthesis','phase59_transition','phase56_incremental','phase39_variable','phase36_variable','phase24_variable','timestretch_core']]
    worker=build/'CMakeFiles/phase58_realtime.dir/src/prototype/Phase58FixRealtimeWorker.cpp.o';libraries.append(worker)
    exe=out/'phase61_interactive_native_tests'
    run(flags+objects+[str(build/'libphase61_callback_heap_probe.dylib')]+list(map(str,libraries))+['-Wl,-rpath,'+str(build),'-framework','Accelerate','-framework','AudioToolbox','-framework','AVFoundation','-framework','Foundation','-framework','CoreAudio','-o',str(exe)])
    (out/'manifest.json').write_text(json.dumps({'base':BASE,'commands':commands,'sources':[{ 'path':str(p),'sha256':sha(p)} for p in out.rglob('*') if p.is_file() and p.suffix in ('.cpp','.h','.mm')],
        'libraries':[{'path':str(p),'sha256':sha(p)} for p in libraries], 'binary_sha256':sha(exe),'driver_sha256':sha(__file__)},indent=2)+'\n')
    print(exe)
if __name__=='__main__':main()
