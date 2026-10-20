"""小さな確定台帳をGit側へまとめる。音声/性能試験終了後だけ実行する。"""
import json,sys,hashlib,subprocess,shutil,os
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest
BASE=ROOT/'build/phase62_dynamic_20261020';OUT=ROOT/'results/phase62_dynamic_loop'
def read(path):return json.loads(path.read_text())
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def rel(path):return str(path.relative_to(ROOT))
# Test program/case counts deliberately exclude configure/build/oracle preflight rows.
suites=[
 ('dynamic_all161','final_dynamic161',dict(dynamic_transitions=640),'selected'),
 ('dynamic_priority','final_priority_v5',dict(dynamic_transitions=20),'selected'),
 ('dynamic_formats_midpoint','final_dynamic_strata',dict(format_transitions=40,midpoint_transitions=6),'rows'),
 ('dynamic_remaining_formats','final_dynamic_remaining_formats',dict(format_transitions=8),'rows'),
 ('exact_golden_fixed','final_regression',dict(exact=896,golden=25,fixed_finite=322,fixed_reuse=322),'selected'),
 ('boundary100_strict','final_boundary_strict_v8',dict(boundary_cases=184),'selected'),
 ('boundary_extra_handoff','final_extra',dict(boundary_cases=368,dynamic_fixed_final_PCM_programs=6),'rows'),
 ('boundary_uncached','final_uncached_boundary',dict(boundary_cases=128),'rows'),
 ('boundary512_phases','final_min512_v9',dict(boundary_cases=192,programs=2),'rows'),
 ('native_seek_API','final_seek_api_v10',dict(API_seek_cases=44,programs=4),'rows'),
 ('native_control_PCM','final_native_matrix_v10',dict(programs=14,controls=6,probes=2,old_planner_DSP_prefix_audits=2,paused_Exact_PCM=8),'rows'),
 ('ordinary_paused','final_ordinary_paused',dict(ordinary_Exact_PCM=36,ordinary_controls=84),'rows'),
 ('current_competing_requests','final_race_native',dict(programs=2,observations=16,KeepPosition_defer_contract_only=2),'rows'),
 ('deterministic_regression','final_gates_v7',dict(Release=16,Debug=16),'rows'),
 ('native_long_stress_paused','final_native_gates_v10',dict(programs=13,Release_Paused=20,Debug_Paused=20,fault_cases=13,longA=6,stress_cycles_per_preset=4100,presets=2),'rows'),
]
if (BASE/'final_clear_pcm/SUMMARY.json').exists():suites.append(('native_clear_independent_PCM','final_clear_pcm',dict(programs=2),'rows'))
if (BASE/'final_boundary_ctest/SUMMARY.json').exists():suites.append(('final_boundary_ctest','final_boundary_ctest',dict(Release=2,Debug=2),'rows'))
entries=[];folders=[]
for label,folder,counts,kind in suites:
 path=BASE/folder;folders.append(path);summary=read(path/'SUMMARY.json');expected=path/'EXPECTED.json'
 passed=summary.get('selected_suite_pass') is True if kind=='selected' else bool(summary.get('rows')) and all(row.get('status')=='PASS' for row in summary['rows'])
 if kind=='rows':
  if 'expected_programs' in summary:passed &= summary.get('executed_programs')==len(summary['rows'])==summary['expected_programs']
  elif 'executed' in summary:passed &= summary.get('expected')==summary.get('executed')==len(summary['rows'])
  passed &= all(row.get('expected')==row.get('executed') for row in summary['rows'] if 'executed' in row and 'expected' in row)
 files=[identity(path/name) for name in ['EXPECTED.json','SUMMARY.json','LEDGER.json','COMMANDS.json','PROVENANCE.json'] if (path/name).exists()]
 source=(read(expected).get('source') or read(expected).get('provenance',{}).get('source')) if expected.exists() else None
 entries.append(dict(id=label,status='PASS' if passed else 'INCOMPLETE',expected_and_executed_when_PASS=counts,source_inventory_sha256=source.get('sha256') if source else None,artifact_directory=str(path),records=files,selected_suite_only=True,local_overall_go=False))
# Existing artifact identities are indexed without relabelling their run source.
known={}
def collect(value):
 if isinstance(value,dict):
  if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str) and len(value['sha256'])==64 and isinstance(value.get('bytes'),int):
   p=Path(value['path']);p=p if p.is_absolute() else ROOT/p
   known[str(p.resolve())]=dict(path=str(p.resolve()),bytes=value['bytes'],sha256=value['sha256'],identity_source='recorded_by_original_run')
  for v in value.values():collect(v)
 elif isinstance(value,list):
  for v in value:collect(v)
for folder in folders:
 for path in folder.rglob('*.json'):
  try:collect(read(path))
  except (ValueError,UnicodeDecodeError):pass
artifacts=[]
# Only final suite media/PCM/Maps/traces. Prior pilots/baselines remain in place,
# with separate identities below and are never counted as new success cases.
for folder in folders:
 for path in sorted(folder.rglob('*')):
  if not path.is_file() or path.suffix not in ('.wav','.f32','.bin','.jsonl'):continue
  key=str(path.resolve());row=known.get(key)
  if row is None:row=identity(path);row['identity_source']='final_index_read_after_all_audio_tests'
  elif row['bytes']!=path.stat().st_size:raise ValueError('artifact size changed: '+key)
  artifacts.append(row)
save(OUT/'ARTIFACTS.json',dict(storage='ignored build directory; never stage media/PCM/traces',artifact_count=len(artifacts),total_bytes=sum(row['bytes'] for row in artifacts),restore='各suiteのEXPECTED/COMMANDSと保存recipeで新規出力先へ再生成。参照/input SHAを先に照合し、既存証拠を上書きしない。',artifacts=artifacts))
# Current binary inventory plus immutable raw-matrix executables when unchanged.
binaries=[]
for configuration in ['release','debug']:
 for name in ['phase62_dynamic_pcm_tests','phase62_dynamic_boundary_tests','phase62_dynamic_handoff_tests','phase62_dynamic_controls_native','phase62_dynamic_loop_probe','phase62_paused_pcm_tests','phase62_dynamic_seek_native','phase62_clear_pcm_native','phase62_race_native','phase62_native_tests','phase62_fix_safety_tests','paused_speed_loop_tests','phase61_seek_check','phase54_core_probe','phase62_loop_tests','phase62_fix_reuse_tests']:
  p=BASE/configuration/name
  if p.is_file():binaries.append(dict(configuration=configuration,**identity(p),architecture=subprocess.check_output(['lipo','-archs',str(p)],text=True).strip()))
source=source_manifest(ROOT);save(OUT/'SOURCE_MANIFEST.json',source)
reference_specs=[('dynamic',ROOT/'build/phase59_frozen/captured_reference','bb22efcbd27f999e8ffe85bbe3f03e20895be3f2',ROOT/'results/phase59/CAPTURED_REFERENCE.json'),('fixed',ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference','ec087019626d9ff0d9f157245729b74ddb6847d7',ROOT/'results/phase62_fix/recipes/oracle_manifest.json')]
references=[dict(kind=k,source_commit=commit,binary=identity(binary),manifest=identity(manifest)) for k,binary,commit,manifest in reference_specs]
input_paths=[ROOT/'results/phase31/input/mix.wav',ROOT/'build/phase62/run_01/step1_release/mix_repeat_36s.wav',ROOT/'build/phase62_fix/run_01/final_v9/evidence/release_longA/same_300s_48000_2_pcm16.wav']
inputs=[identity(p) for p in input_paths]
records=[]
for name in ['BASELINE_BOUNDARY_V6_EXPECTED.json','BASELINE_BOUNDARY_V6_RESULT.json','BASELINE_BOUNDARY_V6_SOURCE.json','baseline_native_probe_device.log','baseline_boundary_v6.log','FINAL_SOURCE_ARCHIVE.json','FINAL_SOURCE_V5.json','FINAL_SOURCE_V6.json','FINAL_SOURCE_V7.json','FINAL_SOURCE_V9.json','FINAL_SOURCE_V10.json','V6_TEST_ONLY_DELTA.json','V7_CONTROL_DELTA.json','FINAL_SOURCE_V11.json','FINAL_SOURCE_V12.json','FINAL_METADATA_ONLY_DELTA.json','FINAL_METADATA_ONLY.patch','EXECUTABLES_USED.json','BASELINE_RACE_SOURCE.json','baseline_race_run_v1/EXPECTED.json','baseline_race_run_v1/SUMMARY.json','r0_fixture_v10/SUMMARY.json','final_native_gates/SCHEMA_AUDIT.json','final_native_gates/SUMMARY.json','configure_final_v12_release.log','configure_final_v12_debug.log','build_final_all_release.log','build_final_all_debug.log']:
 p=BASE/name
 if p.exists():records.append(identity(p))
manifest=dict(schema=1,status='INCOMPLETE',local_overall_go=False,public_go=False,base_commit='7c05319d8142ef53a70c95be4f214f293bb2428a',head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip(),final_source_inventory_sha256=source['sha256'],source_inventory=identity(OUT/'SOURCE_MANIFEST.json'),changeset='CHANGESET.json',artifact_index=identity(OUT/'ARTIFACTS.json'),environment=identity(OUT/'ENVIRONMENT.json'),suites=entries,binaries=binaries,references=references,inputs=inputs,provenance_and_preserved_results=records,missing_required=[dict(status='INCOMPLETE',item='KeepPosition初回の通常ownerに対する現在周期動的変更'),dict(status='INCOMPLETE',item='全要求の受付〜置換/取消/完了を失わない外部要求台帳'),dict(status='NOT_RUN',item='全境界状態の連打・上限・準備失敗/遅延・古い通知を重ねた網羅')],separate_public_gates=['FastLocal長尺既存失敗','stereo Ready目標','開始時計の既存問題','Debug期限の既存問題','主観音質/物理loopback','Merodoa実TCC/実アプリ統合','一般公開承認'],git_actions='no stage/commit/push/PR/history rewrite; no Merodoa/UI/submodule changes')
manifest['missing_required'].append(dict(status='NOT_RUN',item='非0のA・複数warm周期後の独立動的planner/Map/全列PCM。長尺固定速度warmの6件とは別'))
manifest['git_capacity_audit']=dict(existing_history=identity(OUT/'EXISTING_HISTORY_BLOBS.json'),working_tree_validation='FINAL_WORKTREE_CHECKS.json',threshold_bytes=50000000,commit_push='not performed; existing history violations are preserved, not newly added blobs')
if not any(e['id']=='native_clear_independent_PCM' and e['status']=='PASS' for e in entries):manifest['missing_required'].append(dict(status='NOT_RUN',item='実採用Exact Clear最終PCMの独立DSP比較'))
save(OUT/'MANIFEST.json',manifest)
print(json.dumps(dict(source=source['sha256'],suites=len(entries),artifacts=len(artifacts),bytes=sum(r['bytes'] for r in artifacts),local_overall_go=False)))
