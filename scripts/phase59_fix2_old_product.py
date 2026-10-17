"""旧演算と現行診断を組み合わせた対照実行体を別ディレクトリで構築する。"""
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


def main():
    data=ROOT/'build/phase59_fix2_artifacts/old_math_diagnostic_v2';data.mkdir()
    source=data/'source';source.mkdir();build=data/'build'
    shutil.copy2(ROOT/'CMakeLists.txt',source/'CMakeLists.txt')
    shutil.copytree(ROOT/'src',source/'src');shutil.copytree(ROOT/'tests',source/'tests')
    shutil.copytree(ROOT/'examples',source/'examples')
    baseline='bb22efcbd'
    changed=[]
    names=['src/dsp/PhaseLocker.cpp','src/prototype/Phase35PhaseVocoder.cpp','src/prototype/Phase35PhaseVocoder.h',
           'src/prototype/Phase35StereoPhaseCoherence.cpp','src/prototype/Phase35StereoPhaseCoherence.h']
    for name in names:
        path=source/name
        before=sha(path)
        raw=subprocess.check_output(['git','show',baseline+':'+name],cwd=ROOT)
        path.write_bytes(raw)
        changed.append(dict(path=name,current_sha256=before,old_sha256=sha(path)))
    # The old stereo class has no diagnostic neighborhood counter. Remove only
    # its readout, retaining every arithmetic statement and owner/state order.
    path=source/'src/prototype/Phase36SynthesisCore.h'
    text=path.read_text();needle='if(profile_)profile_->phaseFrames[resolutionIndex_].neighborhoodEvaluations+=coherence_.lastNeighborhoodEvaluations();'
    assert text.count(needle)==1
    path.write_text(text.replace(needle,''))
    commands=[['cmake','-S',str(source),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64'],
              ['cmake','--build',str(build),'--target','phase54_native','-j3']]
    for i,command in enumerate(commands):
        with (data/f'build_{i}.log').open('x') as log:subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    generated=ROOT/'build/phase59_fix2_artifacts/legacy_diagnostic_build/legacy_probe.cpp'
    local=data/'legacy_probe.cpp';shutil.copy2(generated,local)
    link=shlex.split((build/'CMakeFiles/phase54_native.dir/link.txt').read_text())
    at=next(i for i,p in enumerate(link) if p.endswith('.o'))
    link[at:at+1]=['-std=c++20','-I'+str(source/'src'),str(local)]
    binary=data/'legacy_old_probe';link[link.index('-o')+1]=str(binary)
    with (data/'probe_build.log').open('x') as log:subprocess.run(link,cwd=build,stdout=log,stderr=subprocess.STDOUT,check=True)
    manifest=dict(baseline_commit=subprocess.check_output(['git','rev-parse',baseline],cwd=ROOT,text=True).strip(),
                  source_directory=str(source),build_directory=str(build),old_math_files=changed,
                  non_math_adjustment=dict(path='src/prototype/Phase36SynthesisCore.h',removed=needle),
                  frozen_old_binary_unmodified=True,commands=commands+[link],
                  binary=str(binary),binary_sha256=sha(binary),generated_probe_sha256=sha(local),
                  source_sha256={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()},
                  scope='旧実行体そのものではない。旧DSP演算と現行の有界な診断を持つ制御対照。元の旧実行体の失敗とは区別する。')
    with (OUT/'OLD_MATH_DIAGNOSTIC_BUILD.json').open('x') as f:json.dump(manifest,f,ensure_ascii=False,indent=2);f.write('\n')
    print(binary,flush=True)


if __name__=='__main__':main()
