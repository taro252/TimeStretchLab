"""e5 review Release targetをビルドし、成功binaryとソースの対応を新規記録する。"""
import argparse,json,subprocess,sys,os,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest,verify_architecture
TARGETS='phase62_paused_clear_native phase62_playing_ledger_native phase62_api_oracle_native phase62_api_boundary_reference phase62_cache_focus_tests phase62_loop_speed_ledger_native phase62_loop_speed_ledger_tests phase62_race_native phase62_dynamic_pcm_tests phase61_seek_check phase54_core_probe phase62_loop_tests phase62_fix_reuse_tests phase62_dynamic_boundary_tests phase62_dynamic_handoff_tests phase62_dynamic_controls_native phase62_dynamic_loop_probe phase62_paused_pcm_tests paused_speed_native_tests paused_speed_loop_tests phase62_dynamic_seek_native phase62_clear_pcm_native phase62_native_tests phase62_worker_transaction_tests phase62_history_invariant_tests phase62_descriptor_invariant_tests phase62_preparation_fault_native phase62_adoption_review_native phase62_partial_mix_native'.split()
def main():
 p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build=a.build.resolve();output=a.output.resolve();assert output.is_relative_to(ROOT/'build') and not output.exists();logs=output.with_suffix('');logs.mkdir(parents=True,exist_ok=False);source=source_manifest(ROOT);rows=[]
 commands=[('configure',['cmake','-S',str(ROOT),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON']),('build',['cmake','--build',str(build),'--parallel','4','--target',*TARGETS])]
 plan=dict(schema=2,source=source,commands=commands,driver=identity(Path(__file__)));(logs/'EXPECTED.json').write_text(json.dumps(plan,indent=2)+'\n')
 result=dict(status='FAIL',source_inventory_sha256=source['sha256'],source_inventory_before_build=source['sha256'],configuration='Release',architecture='arm64',rows=rows)
 try:
  for name,cmd in commands:
   log=logs/(name+'.log')
   with log.open('w') as stream:
    child=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    try:code=child.wait(timeout=1800)
    except subprocess.TimeoutExpired:
     os.killpg(child.pid,signal.SIGTERM)
     try:child.wait(timeout=15)
     except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
     raise RuntimeError(name+' timeout; old binaries are not valid')
   rows.append(dict(id=name,command=cmd,exit=code,log=identity(log)));assert code==0,name+' failed; old binaries are not valid'
  assert source_manifest(ROOT)['sha256']==source['sha256'],'source changed during build'
  architecture=verify_architecture([build/n for n in TARGETS]);assert architecture['PASS'];cache=(build/'CMakeCache.txt').read_text();compiler=next(x.split('=',1)[1] for x in cache.splitlines() if x.startswith('CMAKE_CXX_COMPILER:FILEPATH='));version=subprocess.check_output([compiler,'--version'],text=True).splitlines()[0]
  binaries={n:identity(build/n)['sha256'] for n in TARGETS};result.update(status='PASS',compiler=version,compiler_path=compiler,source_inventory_after_build=source['sha256'],architecture_checks=architecture,binaries=binaries,build_log=rows[1]['log'],configure_log=rows[0]['log'],build_exit=0,fp_policy=(build/'CMakeFiles/phase62_api_oracle_native.dir/flags.make').read_text(),draft_source_sha256={k:identity(ROOT/q)['sha256'] for k,q in [('host_source','tests/Phase62ApiOracleNative.cpp'),('adapter_source','tests/ApiOracleCommitAdapter.h'),('boundary_source','tests/ApiOracleBoundaryReference.cpp')]},host_binary_sha256=binaries['phase62_api_oracle_native'],boundary_binary_sha256=binaries['phase62_api_boundary_reference'])
 except Exception as error:result['reason']=str(error)
 output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(result['status']);return 0 if result['status']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
