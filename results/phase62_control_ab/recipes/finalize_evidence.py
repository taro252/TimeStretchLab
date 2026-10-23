"""最終source・成功実行体・全ゲートを結合する。過去結果を上書きしない。"""
import argparse,datetime,difflib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();base=a.base.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
def read(p):return json.loads(p.read_text())
def save(name,v):(out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
source=source_manifest(ROOT);final=read(base/'candidate_build_09/BUILD.json');assert final['status']=='PASS' and source['sha256']==final['source'];save('SOURCE.json',source)
# Every current candidate run must identify this build/source, not merely PASS.
final_identity=identity(base/'candidate_build_09/BUILD.json')
final_paths={v['path']:v for v in final['binaries'].values()}
def inspect_candidate_identities(value):
 if isinstance(value,dict):
  if value.get('path') in final_paths:assert value==final_paths[value['path']] and identity(Path(value['path']))==value
  for child in value.values():inspect_candidate_identities(child)
 elif isinstance(value,list):
  for child in value:inspect_candidate_identities(child)
for name in ['cpu_after_03','range_replacements_02','control_regressions_03','history_regressions_03','runtime_regressions_03','partial_regressions_03','ab_quality_06']:
 expected=read(base/name/'EXPECTED.json');declared=expected['source'];assert (declared['sha256'] if isinstance(declared,dict) else declared)==source['sha256']
 assert expected.get('candidate_build',expected.get('build',expected.get('build_record')))==final_identity
 inspect_candidate_identities(expected)
for name in ['dynamic_priority_03','final_gates_03']:
 expected=read(base/name/'EXPECTED.json');p=expected['provenance'];assert p.get('source_inventory_sha256',p.get('source',{}).get('sha256'))==source['sha256'];inspect_candidate_identities(expected)
gates=read(base/'final_gates_03/SUMMARY.json');assert gates['source_unchanged'] and gates['source_inventory_sha256']==source['sha256']

paths=['cpu_before_01/SUMMARY.json','cpu_after_03/SUMMARY.json','range_replacements_02/SUMMARY.json','control_regressions_03/SUMMARY.json','history_regressions_03/SUMMARY.json','runtime_regressions_03/SUMMARY.json','partial_regressions_03/SUMMARY.json','ab_quality_06/SUMMARY.json','QUALITY_REUSE_AUDIT_09.json','REFERENCE_AUDIT.json','BASELINE_RECONSTRUCTION_AUDIT.json','final_gates_03/SUMMARY.json'];runs={}
for path in paths:
 r=read(base/path);assert r['status']=='PASS' and r.get('run_complete') is True
 for expected_key,executed_key in [('expected','executed'),('expected_checks','executed_checks'),('expected_programs','executed_programs'),('expected_stage_count','executed_stage_count')]:
  if expected_key in r:assert r[expected_key]==r[executed_key]
 runs[path]=dict(record=identity(base/path),expected_record=identity((base/path).parent/'EXPECTED.json') if ((base/path).parent/'EXPECTED.json').exists() else None,expected=r.get('expected',r.get('expected_checks')),executed=r.get('executed',r.get('executed_checks')),programs=r.get('executed_programs'),stage_count=r.get('executed_stage_count'))
dynamic=read(base/'dynamic_priority_03/SUMMARY.json');assert dynamic['selected_suite_pass'] and not dynamic['source_changed'] and dynamic['final_statistics_present'] and dynamic['counts']==dict(PASS=25,FAIL=0,NOT_RUN=5,INCOMPLETE=0);runs['dynamic_priority_03/SUMMARY.json']=dict(record=identity(base/'dynamic_priority_03/SUMMARY.json'),dynamic_pcm_cases=20,counts=dynamic['counts'],selected_suite_pass=True,local_overall_go=False)
cpu=read(base/'CPU_COMPARISON_v4.json');assert cpu['status']=='PASS' and cpu['candidate']==identity(base/'cpu_after_03/SUMMARY.json') and cpu['baseline']==identity(base/'cpu_before_01/SUMMARY.json');runs['CPU_COMPARISON_v4.json']=dict(record=identity(base/'CPU_COMPARISON_v4.json'),baseline_median=cpu['baseline_median_cpu_percent'],candidate_median=cpu['candidate_median_cpu_percent'],relative_reduction=cpu['relative_reduction_percent'])
# All final executing binaries still match the successful build. Earlier CPU
# and control binaries were separately audited identical; do not relabel source.
for target,saved in final['binaries'].items():assert identity(Path(saved['path']))==saved
builds={name:dict(record=identity(base/name/'BUILD.json'),source=read(base/name/'BUILD.json')['source'],binaries=read(base/name/'BUILD.json')['binaries']) for name in ['baseline_build_01','baseline_ab_build_03','candidate_build_09']}
base_sha='ff1f677f7bcb6095b0f1d74538910f9c3e4b5d5d';patch=subprocess.check_output(['git','diff','--binary',base_sha,'--','CMakeLists.txt','src','tests'],cwd=ROOT,text=True)
for row in source['files']:
 path=row['path']
 if not (path.startswith(('src/','tests/'))):continue
 exists=subprocess.run(['git','cat-file','-e',base_sha+':'+path],cwd=ROOT,capture_output=True).returncode==0
 if not exists:patch+=''.join(difflib.unified_diff([], (ROOT/path).read_text().splitlines(True),fromfile='/dev/null',tofile='b/'+path))
(out/'CODE_DIFF.patch').write_text(patch)
inputs={p.name:identity(p) for p in sorted((base/'inputs').glob('*.wav'))};regenerated=read(base/'inputs_regenerated_01/RECIPE.json');assert len(regenerated['files'])==5
for row in regenerated['files']:assert inputs[Path(row['path']).name]['sha256']==row['sha256']
reused=read(base/'QUALITY_REUSE_AUDIT_09.json');assert reused['expected']==reused['executed']==reused['passed']==22 and reused['current']==str(base/'ab_quality_06') and reused['selection']['final_build']==9
snapshot=dict(schema=1,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),baseline_commit=base_sha,branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),source_inventory_sha256=source['sha256'],source_inventory=identity(out/'SOURCE.json'),code_diff=identity(out/'CODE_DIFF.patch'),builds=builds,inputs=inputs,initial=identity(base/'INITIAL.json'),environment=identity(base/'ENVIRONMENT.json'),acceptance_plan=identity(base/'ACCEPTANCE_PLAN.json'),runs=runs,reused_quality=dict(cold_programs=3,new_programs_in_final_ab_run=9,source='baseline cold from current-task ab_quality_02 via03; candidate cold regenerated after lifetime fix',audit=identity(base/'QUALITY_REUSE_AUDIT_09.json')),execution_records={name:dict(summary=identity(base/name/'SUMMARY.json'),expected=identity(base/name/'EXPECTED.json')) for name in ['final_execution_09','final_execution_recovery_09','final_regression_sequence_03']},prior_incomplete=[identity(base/x/'SUMMARY.json') for x in ['ab_quality_01','ab_quality_02','ab_quality_05']],retained_bug_reproduction=identity(base/'clear_repro_02/case/SUMMARY.json'),retained_lifetime_reproduction=identity(base/'repeat_range_repro_01/PROCESS.json'),retained_summary_reset_reproduction=identity(base/'summary_reset_repro_01/PROCESS.json'),classifications=dict(functional='PASS for executed scope',native_cpu='PASS',warm_return_to_A='PASS existing API direct replacement contract',fresh_cold_no_checkpoint='INCOMPLETE: ~28s A270 remains',local_overall='INCOMPLETE',general_public='NO_GO',merodoa_default='NO_GO'),not_run=['new physical loopback','new subjective listening quality approval','Merodoa actual app/TCC integration with new archive','new all161/Exact896/Golden25 full matrices; DSP arithmetic unchanged'],merodoa_changed=False,public_approved=False,commit_policy='uncommitted local diff; no staging/commit/push/history rewrite in this request',documentation_sources=[identity(ROOT/p) for p in ['docs/PHASE62_CONTROL_AB_PERFORMANCE.md','docs/PHASE62_CONTROL_AB_VALIDATION.md','docs/PHASE62_MERODOA_HANDOFF.md','docs/PHASE62_INITIAL_EXACT_REUSE.md','docs/PAUSED_SPEED_CHANGE_HANDOFF.md']],recipe_files=[identity(p) for p in sorted(Path(__file__).parent.glob('*')) if p.is_file()],recipe_source_archive=identity(base/'draft/archive/RECIPE_SOURCE_ARCHIVE.json'),large_artifact_policy='all WAV/RAW/trace/binary in ignored build; Git files <50,000,000 bytes')
save('manifest.json',snapshot);print(json.dumps(dict(source=source['sha256'],code_diff=identity(out/'CODE_DIFF.patch'),runs=len(runs),local_overall='INCOMPLETE'),indent=2))
