"""b035の挙動へ通常worker観測だけを加えた隔離比較版を構築する。"""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest,verify_architecture
BASE=ROOT/'build/phase62_f01_20261021_01'
REVISION='b0352c6f4c22f100f161297769b26561dc07701b'
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def main():
 out=BASE/'baseline_01';out.mkdir(exist_ok=False);snapshot=out/'source';snapshot.mkdir();build=out/'build';current=source_manifest(ROOT)
 for directory in ['src','tests','scripts','examples']:shutil.copytree(ROOT/directory,snapshot/directory,ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copy2(ROOT/'CMakeLists.txt',snapshot/'CMakeLists.txt')
 relative='src/platform/macos/ProgressiveMacPlaybackEngine.mm';original=subprocess.check_output(['git','show',REVISION+':'+relative],cwd=ROOT).decode()
 anchor='            if(!next){std::this_thread::sleep_for(std::chrono::milliseconds(2));continue;}\n'
 assert original.count(anchor)==1
 observed=original.replace(anchor,anchor+'            controlTestEvent(ProgressiveControlTestPoint::LoopJobSelected);\n')
 (snapshot/relative).write_text(observed);source=source_manifest(snapshot)
 initial=json.loads((BASE/'INITIAL.json').read_text())['source'];before={r['path']:r['sha256'] for r in initial['files']}
 changes=[r for r in source['files'] if before.get(r['path'])!=r['sha256']]
 assert {r['path'] for r in changes}=={'src/platform/macos/ProgressiveMacPlaybackEngine.h',relative,'tests/Phase62AdoptionReviewNative.cpp'}
 commands=[('configure',['cmake','-S',snapshot,'-B',build,'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON']),('build',['cmake','--build',build,'--target','phase62_adoption_review_native','-j2'])]
 save(out/'EXPECTED.json',dict(status='PLANNED',comparison_scope='b035のID公開順序＋通常worker観測hook/共通新試験。未改変binaryや独立DSP参照ではない。',base=REVISION,root_source=current,source=source,source_changes_from_b035=changes,engine_difference='旧Engine.mmにLoopJobSelected呼出し1行だけを追加。active ID公開は元の別mutex区間。',driver=identity(Path(__file__)),commands=[dict(id=k,argv=list(map(str,c))) for k,c in commands]))
 rows=[]
 for name,command in commands:
  log=out/(name+'.log')
  with log.open('w') as f:code=subprocess.run(list(map(str,command)),stdout=f,stderr=subprocess.STDOUT,timeout=1800).returncode
  rows.append(dict(id=name,exit=code,log=identity(log)))
  if code!=0:
   save(out/'BUILD.json',dict(status='FAIL',rows=rows,reason='新規ビルド失敗。旧binaryを使用しない。'));return 2
 assert source_manifest(ROOT)==current and source_manifest(snapshot)==source
 binary=identity(build/'phase62_adoption_review_native');arches=verify_architecture([Path(binary['path'])]);assert arches['PASS']
 save(out/'BUILD.json',dict(status='PASS',source=source['sha256'],root_source_unchanged=current['sha256'],rows=rows,binary=binary,architecture=arches,compiler=subprocess.check_output(['/usr/bin/c++','--version'],text=True),flags=(build/'CMakeFiles/phase62_adoption_review_native.dir/flags.make').read_text(),common_test_source=identity(snapshot/'tests/Phase62AdoptionReviewNative.cpp'),root_common_test_source=identity(ROOT/'tests/Phase62AdoptionReviewNative.cpp')))
 print('PASS isolated observed b035 baseline');return 0
if __name__=='__main__':raise SystemExit(main())
