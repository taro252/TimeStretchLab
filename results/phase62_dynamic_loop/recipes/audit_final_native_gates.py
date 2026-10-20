import sys,json,collections
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity
base=ROOT/'build/phase62_dynamic_20261020';root=base/'final_native_gates';expected=json.loads((root/'EXPECTED.json').read_text());original=json.loads((root/'SUMMARY.json').read_text());rows=[];artifacts=[identity(root/'EXPECTED.json'),identity(root/'SUMMARY.json')]
assert original['executed_programs']==expected['expected_programs']==len(expected['commands'])==len(original['rows'])
for spec,row in zip(expected['commands'],original['rows']):
 assert spec['id']==row['id'];key=spec['id'];kind=spec['kind'];valid=row['exit']==0;correction=False;result=row['result'];rt=None
 if kind=='native':
  path=root/key/'result.json';reuse_path=root/key/'loop_final_reuse.json';result=json.loads(path.read_text());stat=json.loads(reuse_path.read_text());artifacts += [identity(path),identity(reuse_path)]
  valid &= result.get('functional_pass') is True and result.get('cycles',0)>=spec['expected'] and all(result.get(k)==0 for k in ['raw_mix_errors','nonfinite','missing_frames','underrun_calls','safety_stop_frames','output_affected_frames','failure_padding_frames','warm_fft_plans','final_missing_frames'])
  # Existing native host serializes its final_data_available as JSON 0/1.
  # Accept only the documented affirmative number/boolean; no string coercion.
  valid &= type(stat.get('final_data_available')) in (int,bool) and stat['final_data_available']==1 and stat.get('warm_fft_plans')==0 and stat.get('workers_created')==2
  if key.startswith('longA_'):valid &= stat.get('cache_bytes')==0 and stat.get('seed_restores',0)>=spec['expected']-1 and stat.get('warm_discarded_frames',sys.maxsize)<=(stat.get('reuse_count',0)+1)*2048
  rt=all(result.get(k)==0 for k in ['callback_deadlines','worker_deadlines','final_worker_deadlines','host_errors','sample_errors','hal_window_misses','callback_new','callback_heap_calls','callback_frees','workgroup_errors','final_workgroup_errors','worker_new','final_worker_new'])
  correction=valid and row['status']=='FAIL' and type(stat['final_data_available']) is int and stat['final_data_available']==1
 elif kind=='paused':valid &= result.get('status')=='PASS' and result.get('expected')==result.get('executed')==spec['expected']
 elif kind=='faults':valid &= len(result)==spec['expected'] and all(r.get('PASS') is True for r in result)
 else:raise ValueError('unexpected kind')
 rows.append(dict(id=key,expected=spec['expected'],status='PASS' if valid else 'FAIL',original_wrapper_status=row['status'],legacy_boolean_schema_correction=correction,realtime_gate='PASS' if rt is True else 'FAIL' if rt is False else 'NOT_ASSESSED'))
report=dict(expected_programs=expected['expected_programs'],executed_programs=len(rows),rows=rows,all_functional_pass=all(r['status']=='PASS' for r in rows),all_measured_realtime_pass=all(r['realtime_gate']=='PASS' for r in rows if r['realtime_gate']!='NOT_ASSESSED'),reason='元wrapperのis True判定は既存hostの整数1を拒否した。元FAIL/成果物を保持して、既存JSON形式に対応する型付き検算を別記録へ実施。閾値・PCM基準・期限を緩和しない。',auditor=identity(__file__),artifacts=artifacts,local_overall_go=False)
(root/'SCHEMA_AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['expected_programs','executed_programs','all_functional_pass','all_measured_realtime_pass']},ensure_ascii=False));sys.exit(0 if report['all_functional_pass'] else 1)
