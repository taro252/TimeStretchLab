"""確定済みの実測から小さい台帳を作る。期待件数を実施数へ転記しない。"""
import argparse,json,subprocess,hashlib,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
from phase62_aggregation import exact_ids,strict_gates,file_record,need
from compact_focused import build_compact, FINAL_SOURCE
from run_remaining_gates import check_selected,check_rows

OLD_SOURCE='958f402ad625d1a9e5c38e210f6afb8c44589dae327f783bb1756051f20fedf2'
REUSED_GROUPS=['final_dynamic161','final_priority','final_regression','final_dynamic_strata','final_dynamic_remaining_formats']
UNCHANGED_BINARIES=['phase62_dynamic_pcm_tests','phase61_seek_check','phase54_core_probe','phase62_loop_tests','phase62_fix_reuse_tests']

def read(p):return json.loads(p.read_text())
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
def group(base,name,out,selected_ids=None,reuse=None):
 folder=base/name;e,s=read(folder/'EXPECTED.json'),read(folder/'SUMMARY.json');wanted=e['required_ids'];exact_ids(wanted,[r['id'] for r in s['rows']],name)
 need(s['run_complete'] is True and s['expected']==s['executed']==len(wanted),'group incomplete: '+name)
 actual_source=OLD_SOURCE if reuse is not None else FINAL_SOURCE
 need(e['source_inventory_sha256']==s['source_inventory_sha256']==actual_source,'group source mismatch: '+name)
 for binary,record in e['binaries'].items():
  if reuse is None or binary in UNCHANGED_BINARIES:file_record(record)
 if reuse is None and e.get('debug_paused_binary'):file_record(e['debug_paused_binary'])
 for record in e['references']:file_record(record)
 if selected_ids is not None:
  exact_ids(REUSED_GROUPS,selected_ids,'reused DSP groups')
  need(reuse is not None and set(selected_ids).issubset(wanted),'reuse authorization missing')
 selected=[r for r in s['rows'] if selected_ids is None or r['id'] in selected_ids]
 if selected_ids is not None:exact_ids(selected_ids,[r['id'] for r in selected],'selected reused rows')
 else:need(s['status'] in ('PASS','INCOMPLETE'),'failed group')
 compact=[]
 for row in selected:
  job=next(j for j in e['jobs'] if j['id']==row['id']);child=folder/job['directory'];ce,cs=read(child/'EXPECTED.json'),read(child/'SUMMARY.json')
  need(type(row.get('exit')) is int and row['exit']==0 and row.get('timed_out') is False,'failed/incomplete driver: '+row['id'])
  file_record(row['log'])
  if job['mode']=='selected':cert=check_selected(child,actual_source)
  else:cert=check_rows(child,job['required_program_ids'],actual_source)
  for record in ce.get('inputs',[]):file_record(record)
  if cs.get('input_recipe'):
   recipe=read(file_record(cs['input_recipe']))
   file_record(recipe['input'])
  state='INCOMPLETE' if cert.get('realtime_status')=='FAIL' else 'PASS'
  need(row['status']==state,'parent verdict mismatch: '+row['id'])
  if reuse is not None:need(state=='PASS','non-PASS reused DSP group')
  item={k:row[k] for k in ['id','status','exit','timed_out','seconds','reason']};item['expected']=identity(child/'EXPECTED.json');item['summary']=identity(child/'SUMMARY.json');item['conditions_recipe']={k:job[k] for k in ['command','original_recipe','adapted_recipe','conditions_only_from'] if k in job}
  item['actual_run_source_inventory_sha256']=actual_source
  item['evidence_use']='REUSED_DSP_CERTIFICATE' if reuse is not None else 'EXECUTED_FINAL_SOURCE'
  if job['mode']=='selected':
   wanted=[r['id'] for r in ce['cases']];actual=[r['id'] for r in cs['cases']];exact_ids(wanted,actual,row['id'])
   item.update(required_case_ids=wanted,actual_case_status=[dict(id=r['id'],status=r['status']) for r in cs['cases']],measurements=cert['measured'],explicit_not_run=cert['explicit_not_run'],source_inventory_sha256=cs['source_before'],input_recipe=cs.get('input_recipe'),binaries=cs.get('binaries'))
   dynamic=[]
   for case in cs['cases']:
    p=child/case['id']/'SUMMARY.json'
    if case['id'].startswith('dynamic_') and p.is_file():dynamic.append(dict(id=case['id'],result=read(p),summary=identity(p)))
   if dynamic:item['dynamic_case_results']=dynamic
  else:
   item.update(required_program_ids=job['required_program_ids'],actual_program_ids=cert['actual_program_ids'],measurements=cert['measurements'],measured_totals_by_unit=cert['measured_totals_by_unit'],realtime=cert['realtime'],realtime_status=cert['realtime_status'],source_inventory_sha256=ce['source']['sha256'])
   item['results']=[{k:r[k] for k in ['id','preset','status','exit','expected','executed','result','final','realtime_gate','period_frames','phase_coverage'] if k in r} for r in cs['rows']]
   if row['id']=='final_native_gates_v10':
    audits=[]
    for program in cs['rows']:
     if not program['id'].startswith(('longA_','stress_')):continue
     directory=child/program['id'];result=read(directory/'result.json');stat=read(directory/'loop_final_reuse.json')
     need(result==program['result'] and result.get('functional_pass') is True,'native result changed')
     need(stat.get('final_data_available')==1 and stat.get('workers_created')==2 and stat.get('warm_fft_plans')==0,'missing/invalid final reuse audit')
     if program['id'].startswith('longA_'):
      need(stat.get('cache_bytes')==0 and stat.get('seed_restores',0)>=program['expected']-1 and
           stat.get('warm_discarded_frames',2**64)<=(stat.get('reuse_count',0)+1)*2048,'warm prefix regression')
     audits.append(dict(id=program['id'],result=identity(directory/'result.json'),final_reuse=identity(directory/'loop_final_reuse.json'),final_reuse_content=stat,clear_result=identity(directory/'clear_result.json'),clear_result_content=read(directory/'clear_result.json')))
    need(len(audits)==8,'native final audits missing')
    device=read(child/'fault_device_restore.json');need(device.get('PASS') is True and device.get('restored') is True,'fault device not restored')
    item['final_resource_audits']=audits;item['fault_device_restore']=dict(file=identity(child/'fault_device_restore.json'),content=device)
  compact.append(item)
 status='PASS' if all(r['status']=='PASS' for r in compact) else 'INCOMPLETE'
 if selected_ids is None:need(s['status']==status,'group final status mismatch')
 target=out/('REUSED_DSP_GROUPS.json' if reuse is not None else name.upper()+'.json')
 save(target,dict(schema=2,run_complete=True,status=status,required_ids=selected_ids if selected_ids is not None else e['required_ids'],expected_program_groups=len(selected),executed_program_groups=len(compact),source_inventory_sha256=actual_source,applies_to_source_inventory_sha256=FINAL_SOURCE,evidence_use='REUSED_DSP_CERTIFICATE' if reuse is not None else 'EXECUTED_FINAL_SOURCE',reused_certificate=reuse,expected=identity(folder/'EXPECTED.json'),summary=identity(folder/'SUMMARY.json'),binary_identities={k:v for k,v in e['binaries'].items() if reuse is None or k in UNCHANGED_BINARIES},debug_binary=e.get('debug_paused_binary') if reuse is None else None,reference_identities=e['references'],rows=compact,local_overall_go=False))
 return identity(target)

def reuse_certificate(base,out):
 path=out/'REUSED_DSP_CERTIFICATE.json';certificate=read(path)
 need(certificate.get('status')=='PASS' and certificate.get('actual_run_source')==OLD_SOURCE and
      certificate.get('final_source')==FINAL_SOURCE and certificate.get('old_run_relabelled') is False and
      certificate.get('unchanged_input_references') is True,'invalid reuse certificate')
 exact_ids(REUSED_GROUPS,certificate['reused_group_ids'],'reuse group allowlist')
 exact_ids(UNCHANGED_BINARIES,[r['binary'] for r in certificate['required_unchanged_binaries']],'reuse binary allowlist')
 need(file_record(certificate['original_group_summary']).resolve()==(base/'extended_offline_v1/SUMMARY.json').resolve(),'reuse original summary mismatch')
 rebuild=read(file_record(certificate['rebuild']))
 need(rebuild.get('status')=='PASS' and rebuild.get('source_inventory_sha256')==FINAL_SOURCE and
      rebuild.get('source_inventory_before_build')==rebuild.get('source_inventory_after_build')==FINAL_SOURCE and
      rebuild.get('build_exit')==0,'reuse rebuild incomplete')
 old=read(base/'extended_offline_v1/SOURCE.json');new=source_manifest(ROOT)
 before={r['path']:r['sha256'] for r in old['files']};after={r['path']:r['sha256'] for r in new['files']}
 delta=[dict(path=p,before=before.get(p),after=after.get(p)) for p in sorted(before.keys()|after.keys()) if before.get(p)!=after.get(p)]
 need(old['sha256']==OLD_SOURCE and certificate['source_delta']==dict(before=OLD_SOURCE,after=FINAL_SOURCE,files=delta),'reuse source delta differs')
 exact_ids(['src/platform/macos/ProgressiveMacPlaybackEngine.mm','tests/Phase62PausedClearNative.cpp','tests/PausedSpeedNativeTests.cpp'],[r['path'] for r in delta],'reuse allowed source delta')
 recorded=read(base/'extended_offline_v1/EXPECTED.json')['binaries']
 for row in certificate['required_unchanged_binaries']:
  actual=identity(file_record(row['actual']))
  need(row.get('identical') is True and row['before_sha256']==row['after_sha256']==actual['sha256']==
       recorded[row['binary']]['sha256']==rebuild['binaries'][row['binary']],'reused binary changed: '+row['binary'])
 return identity(path)

def delta(out):
 source=source_manifest(ROOT);old=read(ROOT/'build/phase62_finish_20261021/INITIAL.json')['source'];before={x['path']:x['sha256'] for x in old['files']};after={x['path']:x['sha256'] for x in source['files']};rows=[dict(path=p,before_sha256=before.get(p),after_sha256=after.get(p)) for p in sorted(before.keys()|after.keys()) if before.get(p)!=after.get(p)]
 save(out/'FINAL_SOURCE_DELTA.json',dict(review_base='c4bdbb44d92a367369e8ecf3c51fd50cb3abed4c',initial_source_inventory_sha256=old['sha256'],final_source_inventory_sha256=source['sha256'],files=rows,uncommitted=True));save(out/'SOURCE_MANIFEST.json',source)
 return identity(out/'FINAL_SOURCE_DELTA.json')

def metadata_delta(out):
 paths=set(subprocess.check_output(['git','diff','--name-only'],cwd=ROOT,text=True).splitlines())
 paths.update(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines())
 selected=[p for p in sorted(paths) if (p.startswith('docs/') and p.endswith('.md')) or
           (p.startswith('results/') and '/recipes/' in p and Path(p).suffix in ('.py','.md')) or
           p in ('results/phase62_finish/REPORT.md','results/phase62_finish/CONTROL_COVERAGE.md')]
 rows=[]
 for path in selected:
  old=subprocess.run(['git','show','HEAD:'+path],cwd=ROOT,capture_output=True)
  rows.append(dict(path=path,before_sha256=hashlib.sha256(old.stdout).hexdigest() if old.returncode==0 else None,
                   after=identity(ROOT/path)))
 target=out/'FINAL_METADATA_ONLY_DELTA.json'
 save(target,dict(schema=1,review_base='c4bdbb44d92a367369e8ecf3c51fd50cb3abed4c',source_inventory_sha256=FINAL_SOURCE,
                  scope='docsと変更された検証recipe、REPORT/CONTROL_COVERAGE。生成JSONはMANIFESTの各hashで対応。相互自己hashを含めない。',
                  files=rows,sha256=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),uncommitted=True))
 return identity(target)

def main():
 p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();base=a.base.resolve();out=a.output.resolve();assert not (out/'MANIFEST.json').exists();source=source_manifest(ROOT)
 need(source['sha256']==FINAL_SOURCE,'final source differs from fixed plan')
 certificate=strict_gates(base/'deterministic_final_v7')
 need(certificate['status']=='PASS' and certificate['source_inventory_sha256']==FINAL_SOURCE,'deterministic source mismatch')
 save(out/'DETERMINISTIC_CERTIFICATE.json',certificate)
 reuse=reuse_certificate(base,out)
 groups=[group(base,'extended_offline_v1',out,REUSED_GROUPS,reuse),
         group(base,'renderer_final_v2',out),group(base,'extended_native_v3',out)]
 focused=build_compact(base);save(out/'COMPACT_FOCUSED.json',focused)
 need(focused['source_inventory_sha256']==source['sha256'],'focused source mismatch')
 source_delta=delta(out);metadata=metadata_delta(out)
 refs=read(out/'REFERENCE_VERIFIED.json');assert all(identity(Path(x['path']))==x for x in refs['binaries'])
 remaining=[dict(id=id,status=status,reason=reason) for id,status,reason in [
 ('close_ID_terminal','INCOMPLETE','破棄後の公開照会不可、2件'),('Applying_return_cancel','NOT_RUN','実DSPのApplying→Requestedと取消の統合注入なし'),('DSP_Requested_cancel','INCOMPLETE','offer前ゲートと実planner状態は別'),('native_Started_partial_ID','INCOMPLETE','Started/Doneを分離し部分混合中の操作を確定できていない'),('Workgroup_join_failure','NOT_RUN','昇格前throwは実参加APIの失敗ではない'),('Loop_internal_operation_limit','INCOMPLETE','下位4096受付とLoop統合拒否は別'),('history512_failure','NOT_RUN','単一owner履歴上限の強制注入なし'),('descriptor64_stale_cycle','NOT_RUN','正常周回と異常追越しは別'),('checkpoint_reservation_failure','NOT_RUN','正常peak2だけでは失敗時保存の証拠にならない'),('dynamic_memory_reservation_failure','NOT_RUN','初期prepare予算拒否と別'),('next_preparation_failure_deadline','INCOMPLETE','供給保持遅延と準備失敗/期限切れの終端は別')]]
 build=read(out/'BUILD_PROVENANCE.json')
 need(build.get('status')=='PASS' and build.get('source_inventory_sha256')==FINAL_SOURCE,'final build provenance differs')
 need(source_manifest(ROOT)['sha256']==FINAL_SOURCE,'source changed while assembling')
 manifest=dict(schema=2,status='INCOMPLETE',review_base='c4bdbb44d92a367369e8ecf3c51fd50cb3abed4c',head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),source_inventory_sha256=source['sha256'],source_manifest=identity(out/'SOURCE_MANIFEST.json'),source_delta=source_delta,metadata_delta=metadata,uncommitted=True,staged=False,commit=False,push=False,build=identity(out/'BUILD_PROVENANCE.json'),environment=identity(out/'ENVIRONMENT.json'),references=identity(out/'REFERENCE_VERIFIED.json'),focused=identity(out/'COMPACT_FOCUSED.json'),deterministic=identity(out/'DETERMINISTIC_CERTIFICATE.json'),aggregation=[identity(out/'aggregation/FINAL_36.json'),identity(out/'aggregation/FINAL_10.json'),identity(out/'aggregation/COMPACT_LEGACY_SUMMARY.json')],groups=groups,reused_DSP_certificate=reuse,development=identity(out/'DEVELOPMENT_RESULTS.json'),remaining_required=remaining,coverage=identity(out/'CONTROL_COVERAGE.md'),local_overall_go=False,public_go=False,Merodoa_default_adoption=False,capabilities=dict(allowExperimentalLoops_default=False,publicLoopApproved=False,seek=False,currentCycleSpeedChanges=False),evidence_root=str(base),large_evidence_in_git=False,old_results_relabelled=False,reused_scope='独立参照・SHA検証済み入力/RAW・旧条件定義。製品実測はsource958の指定5群だけをREUSED_DSP_CERTIFICATEで別枠再利用し、今回実行数へ付替えない。旧renderer/nativeは採用しない',separate_public_gates=['FastLocal長尺','stereo Ready目標','開始時計','Debug実時間期限','主観音質','物理loopback','Merodoa実TCC/実アプリ統合','一般公開承認'])
 save(out/'MANIFEST.json',manifest);print(json.dumps(dict(status='INCOMPLETE',source=source['sha256'],local_overall_go=False,remaining=len(remaining)),ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
