"""最終証拠から小さい索引を作る。未完/失敗を保持し、全必須群PASS時だけGOとする。"""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase62_aggregation import strict_gates
BASE=ROOT/'build/phase62_e5_review_20261021_01';OUT=ROOT/'results/phase62_e5_review'
FINAL='cefdb1294e89cb5280ad8f6df401eac59825212334e4110f958ca6f0d7c0199c'
def read(p):return json.loads(p.read_text())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def native_progress(folder):
 e=read(folder/'EXPECTED.json');s=read(folder/'SUMMARY.json');programs=[];required=[];rt_values=[];non_rt_observations=[]
 for job in e['jobs']:
  wanted=job['required_program_ids'];required.extend((job['id'],i) for i in wanted)
  child=folder/job['directory']/'SUMMARY.json'
  if not child.exists():continue
  rows=read(child)['rows'];ids=[x.get('id',x.get('preset')) for x in rows]
  assert len(ids)==len(set(ids)) and set(ids)<=set(wanted)
  programs.extend(dict(group=job['id'],id=i,status=row['status'],exit=row['exit'],realtime_gate=row.get('realtime_gate','NOT_ASSESSED')) for i,row in zip(ids,rows))
  for i,row in zip(ids,rows):
   values=row.get('result',row.get('final'))
   if isinstance(values,dict) and values.get('RT_deadline_approval')=='NOT_ASSESSED':
    observed={k:v for k,v in values.items() if 'deadline' in k and type(v) in [int,float] and v!=0}
    if observed:non_rt_observations.append(dict(group=job['id'],id=i,RT_deadline_approval='NOT_ASSESSED',observed=observed))
  if job['id']=='final_native_gates_v10':
   for row in rows:
    if row.get('realtime_gate') in ['PASS','FAIL']:
     values=row['result'];rt_values.append(dict(id=row['id'],realtime_gate=row['realtime_gate'],measurements={k:values[k] for k in ['cycles','period_frames','ready_ms','cold_prefix_s','warm_discarded_frames','warm_fft_plans','workers_created','missing_frames','failure_padding_frames','callback_new','callback_heap_calls','callback_frees','callback_deadlines','worker_deadlines','final_worker_deadlines','workgroup_errors','final_workgroup_errors','device_rate','device_buffer']}))
 assert len(required)==41
 rt_ids={f'longA_{a}_{p}' for a in [0,30,270] for p in ['candidate','baseline']}|{f'stress_4100_{p}' for p in ['candidate','baseline']}
 rt=[p for p in programs if p['group']=='final_native_gates_v10' and p['id'] in rt_ids]
 actual={(p['group'],p['id']) for p in programs};assert actual<=set(required)
 return dict(expected_programs=41,started_programs=len(programs),not_run_programs=len(required)-len(programs),programs=programs,normal_realtime_expected=8,normal_realtime_executed=len(rt),normal_realtime_passed=sum(r['realtime_gate']=='PASS' for r in rt),normal_realtime=rt,normal_realtime_measurements=rt_values,normal_realtime_is_subset_of_native_41=True,non_realtime_deadline_observations=non_rt_observations,complete=s['status']=='PASS' and s['run_complete'] is True and len(programs)==41 and {r['id'] for r in rt}==rt_ids and all(p['status']=='PASS' and p['exit']==0 for p in programs) and all(r['realtime_gate']=='PASS' for r in rt))
def group(name,count,allow_partial=False):
 folder=BASE/name;e=read(folder/'EXPECTED.json');s=read(folder/'SUMMARY.json')
 if allow_partial and s['status']!='PASS':
  assert s['source_inventory_sha256']==e['source_inventory_sha256']==FINAL
  assert s['expected']==count and s['executed']==len(s['rows']) and s['executed']<=count
  assert len({r['id'] for r in s['rows']})==len(s['rows']) and {r['id'] for r in s['rows']}<=set(e['required_ids'])
  return dict(status='INCOMPLETE',expected_groups=count,executed_groups=s['executed'],source_inventory_sha256=FINAL,expected=identity(folder/'EXPECTED.json'),summary=identity(folder/'SUMMARY.json'),binary_identities=e['binaries'],debug_binary=e.get('debug_paused_binary'),references=e['references'],rows=s['rows'],not_run_groups=[x for x in e['required_ids'] if x not in {r['id'] for r in s['rows']}],reason='; '.join(x['id']+': '+x.get('reason',x['status']) for x in s['rows'] if x['status']!='PASS'))
 assert s['status']=='PASS' and s['run_complete'] is True and s['expected']==s['executed']==count and s['source_inventory_sha256']==FINAL
 assert len(s['rows'])==count and len({x['id'] for x in s['rows']})==count
 assert len(e['required_ids'])==count and set(e['required_ids'])=={x['id'] for x in s['rows']}
 assert e['source_inventory_sha256']==FINAL
 rows=[]
 for r in s['rows']:
  assert r['status']=='PASS' and r['exit']==0 and r['timed_out'] is False
  c=r['certificate'];assert c['status']=='PASS'
  item=dict(id=r['id'],status='PASS',seconds=r['seconds'],log=r['log'])
  for key in ['actual_case_ids','measured','explicit_not_run','expected_programs','executed_programs','actual_program_ids','measurements','measured_totals_by_unit','realtime','realtime_status']:
   if key in c:item[key]=c[key]
  if 'realtime_status' in c:assert c['realtime_status'] in ['PASS','NOT_ASSESSED']
  rows.append(item)
 return dict(status='PASS',expected_groups=count,executed_groups=count,source_inventory_sha256=FINAL,expected=identity(folder/'EXPECTED.json'),summary=identity(folder/'SUMMARY.json'),binary_identities=e['binaries'],debug_binary=e.get('debug_paused_binary'),references=e['references'],rows=rows)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--native-run',default='native_final_v2');parser.add_argument('--refresh-archive',type=Path);parser.add_argument('--device-recovery-report',type=Path);args=parser.parse_args()
 if (OUT/'MANIFEST.json').exists():
  assert args.refresh_archive,'既存索引の更新前には全byteの退避を指定する'
  archive=read(args.refresh_archive);wanted={r['path']:r for r in archive['files']};old_path='results/phase62_e5_review/MANIFEST.json'
  old_bytes=(OUT/'MANIFEST.json').read_bytes();assert hashlib.sha256(old_bytes).hexdigest()==wanted[old_path]['sha256']
  for relative,row in wanted.items():
   data=(Path(archive['archive_root'])/relative).read_bytes();assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
 source=source_manifest(ROOT);assert source['sha256']==FINAL
 pipeline=read(BASE/'final_pipeline/SUMMARY.json');assert pipeline['run_complete'] is True and pipeline['expected']==pipeline['executed']==5
 assert {x['id'] for x in pipeline['rows']}=={'partial','equivalence','strict','offline','native'} and len(pipeline['rows'])==5
 assert all(x['status']=='PASS' and type(x['exit']) is int and x['exit']==0 and x['timed_out'] is False for x in pipeline['rows'] if x['id']!='native')
 review=read(BASE/'FINAL_REVIEW_CERTIFICATE_v2.json');assert review['status']=='PASS' and review['source_inventory_sha256']==FINAL and review['review_functional']['executed_checks']==202 and review['native_legacy']['checks']==184
 assert review['binary_count']==29 and review['unchanged_binary_count']==28
 cache_folder=BASE/'cache_baseline_repro_identified_v2';cache_expected=read(cache_folder/'EXPECTED.json');cache_summary=read(cache_folder/'SUMMARY.json');cache_build=read(cache_folder/'BUILD.json')
 assert cache_summary['status']=='PASS' and cache_summary['run_complete'] is True and cache_summary['expected']==cache_summary['executed']==2
 assert cache_summary['source']==cache_expected['source']['sha256']==cache_build['source'] and cache_expected['required_dependency_count']==104
 assert {x['id'] for x in cache_summary['rows']}=={'candidate','baseline'} and all(x['child_exit']==1 and x['original_child_status']=='FAIL' for x in cache_summary['rows'])
 assert identity(Path(cache_build['binary']['path']))==cache_build['binary']==cache_summary['binary']
 cache_record=dict(status='PASS',meaning='旧不具合の2/2再現成功。修正版の品質PASSや独立DSP oracleではない。',source_inventory_sha256=cache_summary['source'],binary=cache_summary['binary'],required_dependencies=104,old_cache04_source_binding_relabelled=False,expected=identity(cache_folder/'EXPECTED.json'),build=identity(cache_folder/'BUILD.json'),summary=identity(cache_folder/'SUMMARY.json'),rows=cache_summary['rows'],failed_configure=identity(BASE/'cache_baseline_repro_identified/configure.log'),failed_executed_recipe=identity(BASE/'executed_recipes/run_cache_baseline_repro_identified_v1.py'))
 save(OUT/'CACHE_BASELINE_REPRO.json',cache_record)
 refs=read(OUT/'REFERENCE_VERIFIED.json');assert refs['status']=='PASS' and refs['run_complete'] is True and refs['expected']==refs['executed']==refs['passed']==10
 deterministic=strict_gates(BASE/'strict_final');assert deterministic['status']=='PASS' and deterministic['source_inventory_sha256']==FINAL
 save(OUT/'DETERMINISTIC_CERTIFICATE.json',deterministic)
 native_folder=BASE/args.native_run;progress=native_progress(native_folder)
 recovery_identity=None
 if args.refresh_archive:
  old_expected=read(BASE/'native_final_v2/EXPECTED.json');new_expected=read(native_folder/'EXPECTED.json')
  for key in ['source_inventory_sha256','binaries','debug_paused_binary','references']:assert old_expected[key]==new_expected[key]
  for old_job,new_job in zip(old_expected['jobs'],new_expected['jobs']):
   for key in ['id','required_program_ids','conditions_only_from','original_recipe']:assert old_job[key]==new_job[key]
  old_inputs=read(BASE/'native_final_v2/final_native_matrix_v10/EXPECTED.json')['inputs'];new_inputs=read(native_folder/'final_native_matrix_v10/EXPECTED.json')['inputs']
  assert [(r['bytes'],r['sha256']) for r in old_inputs]==[(r['bytes'],r['sha256']) for r in new_inputs]
  recovery_identity=dict(status='PASS',scope='実行条件・来歴の一致だけ。音声/RTの結果はGROUP_RESULTSを参照。',source_inventory_sha256=FINAL,release_binaries=len(new_expected['binaries']),debug_binaries=1,expected_programs=41,prior_expected=identity(BASE/'native_final_v2/EXPECTED.json'),recovery_expected=identity(native_folder/'EXPECTED.json'),same_frozen_references=True,same_required_ids_and_original_conditions=True,same_first_matrix_input_bytes_and_sha=True,prior_failures_unchanged=True,archive=identity(args.refresh_archive))
  save(OUT/'RECOVERY_PROVENANCE.json',recovery_identity)
 groups=[group('offline_final',9),group(args.native_run,5,True)];local_pass=all(x['status']=='PASS' for x in groups) and progress['complete']
 guard_path=BASE/'RECOVERY_DEVICE_GUARD_01.json';guard=read(guard_path) if guard_path.exists() else None
 if args.refresh_archive:assert guard is not None,'復旧runの装置復元結果が未確定'
 if guard is not None:local_pass=local_pass and guard['PASS'] is True and guard['restored'] is True
 if local_pass:assert guard is not None and progress['normal_realtime_executed']==progress['normal_realtime_passed']==8
 save(OUT/'GROUP_RESULTS.json',dict(status='PASS' if local_pass else 'INCOMPLETE',groups=groups,native_progress=progress,device_guard=identity(guard_path) if guard else None,scope='各単位を独立集計。checks/cycles/observationsを合算しない。'))
 save(OUT/'REVIEW_CERTIFICATE.json',review)
 build=read(BASE/'BUILD_REVIEW_07.json');assert build['status']=='PASS' and build['source_inventory_sha256']==FINAL
 assert all(identity(BASE/'candidate_build'/n)['sha256']==h for n,h in build['binaries'].items());save(OUT/'BUILD_PROVENANCE.json',build)
 initial=read(BASE/'INITIAL.json');save(OUT/'SOURCE_MANIFEST.json',source)
 a={x['path']:x['sha256'] for x in initial['source']['files']};b={x['path']:x['sha256'] for x in source['files']}
 delta=[dict(path=p,before=a.get(p),after=b.get(p)) for p in sorted(a.keys()|b.keys()) if a.get(p)!=b.get(p)]
 patch=subprocess.check_output(['git','diff','--binary','HEAD','--','CMakeLists.txt','src','tests','scripts'],cwd=ROOT)
 save(OUT/'SOURCE_DELTA.json',dict(review_base=initial['head'],initial_source=initial['source']['sha256'],final_source=FINAL,uncommitted=True,files=delta,tracked_source_diff_sha256=hashlib.sha256(patch).hexdigest(),tracked_source_diff_bytes=len(patch),untracked_source_included_in_inventory=True))
 recovery_report=read(args.device_recovery_report) if args.device_recovery_report else None
 if recovery_report is not None:assert recovery_report['source']=='user_message' and isinstance(recovery_report['message'],str) and recovery_report['message']
 output_restored=any(p['group']=='final_native_matrix_v10' and p['id']=='controls_candidate' and p['status']=='PASS' for p in progress['programs'])
 device_rate={r['measurements']['device_rate'] for r in progress['normal_realtime_measurements']};device_buffers={r['measurements']['device_buffer'] for r in progress['normal_realtime_measurements']}
 if local_pass:assert device_rate=={48000} and device_buffers=={512} and guard['original']==512
 environment=dict(recorded_commands=initial['environment'],machine_model=subprocess.check_output(['sysctl','-n','hw.model'],text=True).strip(),cpu=subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip(),memory_bytes=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True)),configuration='Release/Debug',architecture='実行体arm64、shellのunameはx86_64（Rosetta）',python_runtime=identity(Path(sys.executable)),normal_device=dict(id=guard['device'] if guard else 72,sample_rate=next(iter(device_rate)) if len(device_rate)==1 else None,buffer_frames=guard['original'] if guard else 512,channels=2,output_start_status='PASS' if output_restored else 'BLOCKED',normal_realtime_measurements=progress['normal_realtime_executed'],normal_realtime_passed=progress['normal_realtime_passed']),partial_device=dict(id=72,buffer_frames_tested=[64,128],restored_to_frames=512),recovery_device_guard=identity(guard_path) if guard else None,physical_loopback='NOT_RUN',listening='NOT_RUN')
 save(OUT/'ENVIRONMENT.json',environment)
 native_folder=BASE/args.native_run;native_expected=read(native_folder/'EXPECTED.json');native_summary=read(native_folder/'SUMMARY.json')
 expected_programs=sum(len(x['required_program_ids']) for x in native_expected['jobs']);assert expected_programs==41
 blocker=dict(status='RESOLVED' if output_restored else 'BLOCKED',attempted_run_status='PASS' if local_pass else 'INCOMPLETE',native_expected_programs=41,native_distinct_programs_started=progress['started_programs'],native_not_run_programs=progress['not_run_programs'],normal_realtime_expected=8,normal_realtime_is_subset_of_native_41=True,normal_realtime_executed=progress['normal_realtime_executed'],normal_realtime_passed=progress['normal_realtime_passed'],root_cause='UNDETERMINED',user_reported_device_recovery=recovery_report is not None,user_device_recovery_report=identity(args.device_recovery_report) if recovery_report else None,historical_same_failure_in_old_success_binary=True,historical_standard_afplay_timeout=True,buffer_restored_to=guard['original'] if guard and guard['restored'] else None,daemon_or_other_app_forced_restart_by_agent=False,historical_first_failed_program='controls_candidate',historical_first_program_expected_checks=3,historical_first_program_executed_checks=0,historical_reason='復旧前nativeは2回とも最初の同じprogramでfirst callback timeout。通常再生もcallback0/消費0/公開FIFO16384。標準afplay・旧成功ビルドも開始不可。OS/装置原因は推測であり未確定。',historical_evidence=[identity(BASE/n) for n in ['native_final/SUMMARY.json','native_final_v2/SUMMARY.json','native_final_v2/final_native_matrix_v10/EXPECTED.json','native_final_v2/final_native_matrix_v10/SUMMARY.json','FIRST_CALLBACK_ENV_02.json','DEVICE_BUFFER_RECOVERY_01.json','AFPLAY_AFTER_BUFFER_RECOVERY_01.json','OLD_NATIVE_ENV_EXPECTED.json','OLD_NATIVE_ENV_RESULT.json','FIRST_CALLBACK_DIAG_EXPECTED.json','first_callback_diag_loop_01.jsonl','first_callback_normal_02.log']],recovery_evidence=[identity(native_folder/'EXPECTED.json'),identity(native_folder/'SUMMARY.json')]+([identity(guard_path)] if guard else []),historical_runs_relabelled=False)
 save(OUT/'NATIVE_BLOCKER.json',blocker)
 deadline_observation=None
 if progress['non_realtime_deadline_observations']:
  previous=ROOT/'build/phase62_finish_20261021/extended_native_v3/final_seek_api_v10';current=native_folder/'final_seek_api_v10';old_plan=read(previous/'EXPECTED.json');old_build=read(ROOT/'results/phase62_finish/BUILD_PROVENANCE.json')
  assert old_plan['source']['sha256']==old_build['source_inventory_sha256']
  assert old_plan['binary']['sha256']==old_build['binaries']['phase62_dynamic_seek_native'] and identity(Path(old_plan['binary']['path']))==old_plan['binary']
  old_result=previous/'candidate_normal/SUMMARY.json';new_result=current/'candidate_normal/SUMMARY.json'
  deadline_observation=dict(status='OBSERVED_NOT_RT_APPROVED',observations=progress['non_realtime_deadline_observations'],previous_source=old_plan['source']['sha256'],current_source=FINAL,previous_expected=identity(previous/'EXPECTED.json'),previous_build=identity(ROOT/'results/phase62_finish/BUILD_PROVENANCE.json'),previous_binary=old_plan['binary'],previous_summary=identity(old_result),current_summary=identity(new_result),summaries_byte_identical=old_result.read_bytes()==new_result.read_bytes(),meaning='seek機能試験でworker期限超過1件。旧fa保存runにも存在。原因・局面の同一や一般無退行は未証明。正常RT8本と別に記録し、seekの一般RT承認へ用いない。')
  save(OUT/'FUNCTIONAL_DEADLINE_OBSERVATION.json',deadline_observation)
 development=[
  dict(id='instrumented_baseline',status='EXPECTED_FAIL',evidence=[identity(BASE/'BASELINE_EXPECTED.json'),identity(BASE/'BASELINE_EXECUTION.json'),identity(BASE/'baseline_cache_candidate_04/old_new_transaction.json')],reason='e5へ観測・注入のみを加えた保存ソース。純粋なe5 binaryとは呼ばない。Started旧ID、初回必須供給ID、InternalLimit理由、旧cache A→新Bを再現。'),
  dict(id='fault_test_v1',status='FAIL',evidence=identity(BASE/'review_functional_v1/SUMMARY.json'),reason='reservation2件はowner構築前拒否に存在しない退役workerを待った試験不備。保存し修正後再実行。'),
  dict(id='API_wrong_python',status='FAIL',evidence=identity(BASE/'focused_final_v1/api/SUMMARY.json'),reason='NumPyなしPython3.14で16件FAIL、独立DSP比較0件。Python3.12再実行16/16PASSだけを採用。失敗親はINCOMPLETEのまま。'),
  dict(id='partial_window_missed',status='FAIL',evidence=identity(BASE/'review_functional_final/SUMMARY.json'),reason='200/202。replace両Presetが窓未捕捉。即poll・有限retry、Stop前故障確認、取り逃し理由保存を追加し最終6/6PASS。'),
  dict(id='validator_negative_before',status='FAIL',evidence=identity(BASE/'verify_evidence_1k250crp/SUMMARY.json'),reason='旧verifyは35件中29PASS/6FAIL。bool/float/必須ID型/矛盾結果を修正し、既存40+追加35=75件を最終Release/Debug CTestで確認。'),
  dict(id='binary_count_label',status='METADATA_CORRECTED',evidence=identity(BASE/'NATIVE_EQUIVALENCE_AFTER_VALIDATOR.json'),reason='all_30_binaries_identicalのキー名だけ30と誤記。実比較列挙は29点。REVIEW_CERTIFICATEに29/28を明記、旧記録と実行済recipeのコピーを保持。'),
  dict(id='native_output_start_before_recovery',status='FAIL',evidence=[identity(BASE/n) for n in ['native_final/SUMMARY.json','native_final_v2/SUMMARY.json','FIRST_CALLBACK_ENV_02.json','DEVICE_BUFFER_RECOVERY_01.json','AFPLAY_AFTER_BUFFER_RECOVERY_01.json','OLD_NATIVE_ENV_RESULT.json']],reason='復旧前2runは各最初のcontrol 0/3、callback timeout。通常再生diagも製品callback0/消費0、標準afplayもtimeout。bufferは512へ復元、旧成功ビルドも同じ開始失敗。当時未実施の40programと正常RT8を後から成功へ変更しない。'),
  dict(id='native_after_user_device_recovery',status='PASS' if local_pass else 'INCOMPLETE',evidence=[identity(native_folder/'EXPECTED.json'),identity(native_folder/'SUMMARY.json')]+([identity(guard_path)] if guard else []),reason='復旧後の新しいrun。全41programと、その内数の正常RT8、装置復元の実結果から判定する。ソース/実行体/参照/driverを保持し、旧失敗は別履歴。'),
  dict(id='identified_old_cache_repro',status='EXPECTED_FAIL_REPRODUCED',evidence=identity(OUT/'CACHE_BASELINE_REPRO.json'),reason='初回configure失敗は実行0、v2で依存104件とsource/binary/inputを固定し両Presetで旧不具合を再現。子は各exit1/FAIL。'),
 ]
 save(OUT/'DEVELOPMENT_RESULTS.json',development)
 assert source_manifest(ROOT)['sha256']==FINAL
 remaining=[] if local_pass else [dict(id='native_regression_5_groups',status='INCOMPLETE',reason=f"予定41本、起動{progress['started_programs']}本、未実施{progress['not_run_programs']}本。各FAIL/期限/装置復元結果をGROUP_RESULTSとNATIVE_BLOCKERで確認する。"),dict(id='normal_realtime_8',status='INCOMPLETE',subset_of='native_regression_5_groups',reason=f"41本の内数8本、実施{progress['normal_realtime_executed']}本、正常RT PASS {progress['normal_realtime_passed']}本。条件・期限は変更しない。")]
 manifest=dict(schema=1,status='PASS' if local_pass else 'INCOMPLETE',local_overall_go=local_pass,scope='TimeStretchLab Phase62 e5レビューA/B/C・D01–D11と影響する局所回帰。D07/D08は限定された不変条件による閉鎖。',review_base=initial['head'],head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),branch=subprocess.check_output(['git','branch','--show-current'],text=True).strip(),source_inventory_sha256=FINAL,uncommitted=True,staged=False,commit=False,push=False,
  source=identity(OUT/'SOURCE_MANIFEST.json'),delta=identity(OUT/'SOURCE_DELTA.json'),build=identity(OUT/'BUILD_PROVENANCE.json'),environment=identity(OUT/'ENVIRONMENT.json'),references=identity(OUT/'REFERENCE_VERIFIED.json'),baseline_history=identity(OUT/'BASELINE_PROVENANCE.json'),cache_baseline_reproduction=identity(OUT/'CACHE_BASELINE_REPRO.json'),native_blocker=identity(OUT/'NATIVE_BLOCKER.json'),review=identity(OUT/'REVIEW_CERTIFICATE.json'),deterministic=identity(OUT/'DETERMINISTIC_CERTIFICATE.json'),groups=identity(OUT/'GROUP_RESULTS.json'),development=identity(OUT/'DEVELOPMENT_RESULTS.json'),coverage=identity(OUT/'CONTROL_COVERAGE.md'),pipeline_expected=identity(BASE/'final_pipeline/EXPECTED.json'),pipeline_summary=identity(BASE/'final_pipeline/SUMMARY.json'),remaining_required=remaining,
  functional_deadline_observation=identity(OUT/'FUNCTIONAL_DEADLINE_OBSERVATION.json') if deadline_observation else None,recovery_provenance=identity(OUT/'RECOVERY_PROVENANCE.json') if recovery_identity else None,user_device_recovery_report=identity(args.device_recovery_report) if recovery_report else None,recovery_history=identity(args.refresh_archive) if args.refresh_archive else None,recovery_device_guard=identity(guard_path) if guard else None,native_run=args.native_run,separate_public_gates=['FastLocal長尺既存失敗','stereo Ready目標','開始時計','Debug実時間期限','seek切替の一般RT承認（機能試験の期限観測を含む）','主観音質','物理loopback','Merodoa実TCC/実アプリ統合','一般公開承認'],public_go=False,Merodoa_default_adoption=False,capabilities=dict(allowExperimentalLoops_default=False,publicLoopApproved=False,seek=False,currentCycleSpeedChanges=False),evidence_root=str(BASE),large_evidence_in_git=False,old_runs_relabelled=False,source_equivalence_scope='成功native184、review他30programは実行体・依存一致を別証明。実行時source SHAは保持。その他は最終sourceの新run。')
 assert not subprocess.check_output(['git','diff','--cached','--name-only'],text=True).strip(),'unexpected staged files'
 save(OUT/'MANIFEST.json',manifest);print(manifest['status'],'local GO=',local_pass,'public/Merodoa NO-GO')
if __name__=='__main__':main()
