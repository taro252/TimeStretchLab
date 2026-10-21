"""旧cache不具合を、実行前source接続を持つ新しい隔離比較版で再現する。"""
import hashlib,json,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest,verify_architecture
BASE=ROOT/'build/phase62_e5_review_20261021_01'
def read(p):return json.loads(p.read_text())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def digest(x):return hashlib.sha256(x).hexdigest()
def main():
 out=BASE/'cache_baseline_repro_identified_v2';out.mkdir(exist_ok=False);snapshot=out/'source';snapshot.mkdir();build=out/'build'
 original=source_manifest(ROOT);old=read(BASE/'BASELINE_EXPECTED.json');audit=read(ROOT/'results/phase62_e5_review/BASELINE_PROVENANCE.json');wanted={r['path']:r['sha256'] for r in old['source']['files']}
 for directory in ['src','tests','scripts']:shutil.copytree(ROOT/directory,snapshot/directory,ignore=shutil.ignore_patterns('__pycache__'))
 # EXCLUDE_FROM_ALLの例示targetもconfigure時には存在確認される。ビルド対象には含めない。
 shutil.copytree(ROOT/'examples',snapshot/'examples')
 shutil.copy2(ROOT/'CMakeLists.txt',snapshot/'CMakeLists.txt');missing=[]
 saved=BASE/'instrumented_baseline_source'
 for path,sha in wanted.items():
  destination=snapshot/path
  if destination.exists() and digest(destination.read_bytes())==sha:continue
  candidates=[saved/path,saved/Path(path).name,BASE/'baseline_recovery'/Path(path).name]
  data=next((p.read_bytes() for p in candidates if p.is_file() and digest(p.read_bytes())==sha),None)
  if data is None:
   process=subprocess.run(['git','show',old['base']+':'+path],cwd=ROOT,capture_output=True)
   if process.returncode==0 and digest(process.stdout)==sha:data=process.stdout
  if data is None:missing.append(path);continue
  destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
 assert set(missing)=={'tests/Phase62PartialMixNative.cpp','tests/Phase62PreparationFaultNative.cpp'}
 required=audit['cache04']['source_paths'];assert len(required)==104 and not set(required)&set(missing)
 assert all(identity(snapshot/p)['sha256']==wanted[p] for p in required)
 source=source_manifest(snapshot);commands=[('configure',['cmake','-S',snapshot,'-B',build,'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON']),('build',['cmake','--build',build,'--target','phase62_worker_transaction_tests','-j2'])]
 jobs=[dict(id=preset,argv=[build/'phase62_worker_transaction_tests',ROOT/'results/phase31/input/mix.wav',preset,'cache_old_new',out/preset]) for preset in ['candidate','baseline']]
 save(out/'EXPECTED.json',dict(source=source,product_source_unchanged=original['sha256'],comparison_source='保存観測版の旧cache期限判断。独立DSP oracleではない。',required_dependency_count=104,required_dependencies=[dict(path=p,sha256=wanted[p]) for p in required],configure_only_examples=[identity(p) for p in sorted((snapshot/'examples').rglob('*')) if p.is_file()],unused_old_test_sources_unrecovered=missing,build_commands=[dict(id=k,argv=list(map(str,c))) for k,c in commands],jobs=[dict(id=j['id'],argv=list(map(str,j['argv']))) for j in jobs],input=identity(ROOT/'results/phase31/input/mix.wav'),driver=identity(Path(__file__)),expected_reproductions=2,expected_child_exit=1,expected_failure_check='old_completion_isolated',old_cache04_source_binding_relabelled=False))
 for name,command in commands:
  with (out/(name+'.log')).open('w') as stream:code=subprocess.run(list(map(str,command)),stdout=stream,stderr=subprocess.STDOUT,timeout=1800).returncode
  assert code==0,name+' failed; do not use old binary'
 assert source_manifest(snapshot)==source;binary=identity(build/'phase62_worker_transaction_tests');assert verify_architecture([build/'phase62_worker_transaction_tests'])['PASS']
 save(out/'BUILD.json',dict(status='PASS',source=source['sha256'],binary=binary,compiler=subprocess.check_output(['/usr/bin/c++','--version'],text=True),flags=(build/'CMakeFiles/phase62_worker_transaction_tests.dir/flags.make').read_text(),unused_old_tests_are_not_build_dependencies=True))
 rows=[]
 for job in jobs:
  with (out/(job['id']+'.log')).open('w') as stream:code=subprocess.run(list(map(str,job['argv'])),stdout=stream,stderr=subprocess.STDOUT,timeout=180).returncode
  transaction=read(out/job['id']/'old_new_transaction.json');checks=[json.loads(x) for x in (out/job['id']/'checks.jsonl').read_text().splitlines()]
  assert code==1 and transaction['old_id']!=transaction['new_id'] and transaction['deadline_decision_id']==transaction['old_id'] and transaction['new_observed_id']==transaction['new_id'] and transaction['state']=='Rejected'
  assert any(x['id']=='old_completion_isolated' and x.get('pass') is False for x in checks)
  assert source_manifest(snapshot)==source and source_manifest(ROOT)==original and identity(build/'phase62_worker_transaction_tests')==binary
  rows.append(dict(id=job['id'],status='EXPECTED_FAILURE_REPRODUCED',child_exit=code,transaction=transaction,original_child_status=read(out/job['id']/'SUMMARY.json')['status']))
 save(out/'SUMMARY.json',dict(status='PASS',meaning='旧cache不具合の再現成功。旧製品/子試験のPASSではない。',run_complete=True,expected=2,executed=len(rows),source=source['sha256'],binary=binary,rows=rows,old_cache04_source_binding_relabelled=False));print('old cache reproduced 2/2; children remain FAIL')
if __name__=='__main__':main()
