"""回帰開始前の全ソースと実行体をGit管理外へ固定する。"""
import json
import shutil
import subprocess
from pathlib import Path
from phase57_study import ROOT,sha


def main():
    data=ROOT/'build/phase59_fix2_artifacts/final';data.mkdir()
    names=['phase59_native','phase59_check','phase59_progressive_replay','phase58_native','phase58_check','phase57_check',
           'phase54_native','phase54_core_probe','phase56_check','phase56_reference','phase58_product_reference',
           'phase59_reference','phase59_captured_reference','phase59_fix_fixed_probe','phase59_fix_startup_probe',
           'phase59_fix2_sourcenode','phase59_fix2_fixed_probe','phase59_fix2_dynamic_probe',
           'phase59_fix_eos_probe','phase59_fix_vocoder_tests','phase59_fix_vocoder_bench','phase59_fix_stereo_tests']
    for name in names:shutil.copy2(ROOT/'build'/name,data/name)
    libraries=['libphase58_realtime.a','libphase57_synthesis.a','libphase59_transition.a','libphase56_incremental.a',
               'libphase39_variable.a','libphase36_variable.a','libphase24_variable.a','libtimestretch_core.a',
               'libmacos_playback_engine.a','libplayback_engine.a']
    for name in libraries:shutil.copy2(ROOT/'build'/name,data/name)
    shutil.copytree(ROOT/'src',data/'source/src')
    shutil.copy2(ROOT/'CMakeLists.txt',data/'source/CMakeLists.txt')
    shutil.copytree(ROOT/'tests/reference/phase59_fix',data/'source/tests/reference/phase59_fix')
    for file in (ROOT/'tests').glob('Phase59Fix*.cpp'):shutil.copy2(file,data/'source/tests'/file.name)
    sources={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*') if p.is_file()}
    settings={}
    for path in [ROOT/'build/CMakeCache.txt',*[ROOT/'build/CMakeFiles'/name/(file) for name in
        ('phase59_native.dir','phase59_fix_fixed_probe.dir','phase58_realtime.dir','phase36_variable.dir') for file in ('flags.make','link.txt')]]:
        settings[str(path.relative_to(ROOT))]=path.read_text()
    manifest=dict(head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        frozen_directory=str(data),binary_sha256={name:sha(data/name) for name in names},
        library_sha256={name:sha(data/name) for name in libraries},source_sha256=sources,build_settings=settings,
        file_manifest=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in data.rglob('*') if p.is_file()],
        restore='保存済み実行体/ライブラリは記載パスでSHAを照合。ソースを再ビルドする場合は基準コミットと保存したsource、CMake設定、Xcode/SDKを使用し、独立参照PCMとの全ビット照合を再実行する。')
    with (ROOT/'results/phase59_fix2/FINAL_CANDIDATE.json').open('x') as file:file.write(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('frozen',len(names),'executables',len(libraries),'libraries',len(sources),'source files',flush=True)


if __name__=='__main__':main()
