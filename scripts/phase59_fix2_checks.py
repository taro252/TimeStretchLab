"""完全ビルド、CTest、Golden、競合・メモリ検査。実機音声試験とは分離する。"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from phase57_study import ROOT,sha


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--tag',default='final')
    parser.add_argument('--debug-build',type=Path,default=ROOT/'build/phase59_fix2_debug');args=parser.parse_args()
    out=ROOT/'results/phase59_fix2'/('checks_'+args.tag);out.mkdir()
    data=ROOT/'build/phase59_fix2_artifacts'/('checks_'+args.tag);data.mkdir();history=[]
    def run(name,command):
        command=list(map(str,command));start=time.time()
        with (data/(name+'.log')).open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        row=dict(name=name,command=command,exit=p.returncode,wall_s=time.time()-start,log=str(data/(name+'.log')))
        history.append(row);(out/'driver.json').write_text(json.dumps(history,indent=2)+'\n');print(name,p.returncode,flush=True)
        return p.returncode==0
    run('release_deterministic',['ctest','--test-dir','build','-L','deterministic','--output-on-failure','-j2'])
    if run('debug_configure',['cmake','-S',ROOT,'-B',args.debug_build,'-DCMAKE_BUILD_TYPE=Debug','-DCMAKE_OSX_ARCHITECTURES=arm64']):
        if run('debug_all_build',['cmake','--build',args.debug_build,'-j3']):
            run('debug_related',['ctest','--test-dir',args.debug_build,'-R','^(phase59_|phase58_|phase57_|phase56_|phase54_)','--output-on-failure','-j1'])
    run('golden',[sys.executable,'-B','scripts/phase57_golden.py','--output',data/'golden'])
    run('git_blob_guard',[sys.executable,'-B','tests/GitBlobSizeGuardTests.py','-v'])
    run('forensics',[sys.executable,'-B','tests/Phase59Fix2ForensicsTests.py','-v'])
    for sanitizer in ('thread','address,undefined'):
        for label,source in [('frontier','tests/Phase59MailboxProbe.cpp'),('borrowed','tests/Phase58FixMailboxTests.cpp')]:
            name=label+'_'+sanitizer.replace(',','_');binary=data/name
            if run(name+'_compile',['/usr/bin/c++','-arch','arm64','-std=c++20','-O1','-g','-fsanitize='+sanitizer,'-fno-omit-frame-pointer','-Isrc',source,'-o',binary]):run(name,[binary])
    binary=data/'vocoder_address_undefined'
    if run('vocoder_address_undefined_compile',['/usr/bin/c++','-arch','arm64','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-Isrc',
        'tests/Phase59FixVocoderTests.cpp','tests/reference/phase59_fix/Before59FixPhaseVocoder.cpp','src/prototype/Phase35PhaseVocoder.cpp','src/dsp/PhaseLocker.cpp','-o',binary]):
        run('vocoder_address_undefined',[binary])
    binary=data/'stereo_address_undefined'
    if run('stereo_address_undefined_compile',['/usr/bin/c++','-arch','arm64','-std=c++20','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-Isrc',
        'tests/Phase59FixStereoTests.cpp','tests/reference/phase59_fix/Before59FixPhaseVocoder.cpp',
        'tests/reference/phase59_fix/Before59FixStereoPhaseCoherence.cpp','src/prototype/Phase35PhaseVocoder.cpp',
        'src/prototype/Phase35StereoPhaseCoherence.cpp','src/dsp/PhaseLocker.cpp','-o',binary]):
        run('stereo_address_undefined',[binary])
    artifacts=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in data.rglob('*') if p.is_file()]
    (out/'artifacts.json').write_text(json.dumps(artifacts,indent=2)+'\n')
    summary=dict(PASS=all(r['exit']==0 for r in history),history=history,
        golden=json.loads((data/'golden/summary.json').read_text()) if (data/'golden/summary.json').exists() else None)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');return 0 if summary['PASS'] else 2


if __name__=='__main__':raise SystemExit(main())
