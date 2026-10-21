"""集計の負例。製品・DSP・音声を起動しない。"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase62_finish_validation import playing_jobs,verify_result,verify_build
from phase62_review_validation import verify as verify_review
from phase62_aggregation_manifest import entry
from phase62_gate_runner import NAMES,TARGETS
from phase62_aggregation import CONFIGURATIONS,STAGES,EvidenceError,junit,stage_log


class FinishEvidenceTests(unittest.TestCase):
 def setUp(self):
  self.temporary=tempfile.TemporaryDirectory(prefix='phase62_finish_evidence_');self.addCleanup(self.temporary.cleanup);self.folder=Path(self.temporary.name)
  self.job={'expected':2};self.stat=dict(status='PASS',expected=2,executed=2,run_complete=True)
  self.save('EXPECTED.json',{'expected_IDs':['a','b']});self.checks(['a','b'])
 def save(self,name,value):
  (self.folder/name).write_text(json.dumps(value)+'\n')
 def rows(self,name,values):
  (self.folder/name).write_text(''.join(json.dumps(x)+'\n' for x in values))
 def checks(self,ids):
  self.rows('checks.jsonl',[dict(id=i,status='PASS') for i in ids])
 def verify(self,stat=None,code=0,timed=False,suite='playing'):
  return verify_result(suite,self.job,self.folder,code,timed,self.stat if stat is None else stat)
 def test_complete_positive(self):self.assertTrue(self.verify())
 def test_missing_checks(self):
  (self.folder/'checks.jsonl').unlink();self.assertFalse(self.verify())
 def test_missing_expected(self):
  (self.folder/'EXPECTED.json').unlink();self.assertFalse(self.verify())
 def test_missing_completion_marker(self):
  self.stat.pop('run_complete');self.assertFalse(self.verify())
 def test_duplicate_check_ids(self):
  self.checks(['a','a']);self.assertFalse(self.verify())
 def test_missing_check_id(self):
  self.checks(['a']);self.assertFalse(self.verify())
 def test_foreign_check_id(self):
  self.checks(['a','foreign']);self.assertFalse(self.verify())
 def test_failed_check(self):
  self.rows('checks.jsonl',[dict(id='a',status='PASS'),dict(id='b',status='FAIL')]);self.assertFalse(self.verify())
 def test_failed_summary(self):self.assertFalse(self.verify(dict(self.stat,status='FAIL')))
 def test_timeout(self):self.assertFalse(self.verify(timed=True))
 def test_cache_completion_marker(self):self.assertFalse(self.verify(dict(self.stat,run_complete=False),suite='cache'))
 def test_bool_exit_not_measured_zero(self):self.assertFalse(self.verify(code=False))
 def test_noninteger_count(self):self.assertFalse(self.verify(dict(self.stat,expected=2.,executed=2.)))
 def test_expected_ids_must_be_list(self):
  self.save('EXPECTED.json',dict(expected_IDs='ab'));self.assertFalse(self.verify())
 def test_expected_ids_must_be_unique(self):
  self.save('EXPECTED.json',dict(expected_IDs=['a','a']));self.assertFalse(self.verify())
 def test_build_binary_identity_mismatch(self):
  binary=self.folder/'test_fixture_only';binary.write_bytes(b'not an executable')
  provenance=dict(status='PASS',source_inventory_sha256='a'*64,compiler='fixture',configuration='Release',architecture='arm64',binaries={binary.name:'0'*64})
  with self.assertRaises(ValueError):verify_build(provenance,'a'*64,[binary])
 def test_aggregator_child_count_mismatch(self):
  self.save('SUMMARY.json',self.stat);plan=dict(id='synthetic',mode='strict_gates',directory=str(self.folder),expected_counts={'Release':3,'Debug':3})
  with patch('phase62_aggregation_manifest.strict_gates',return_value=dict(status='PASS',measured_counts={'Release':2,'Debug':2})):
   self.assertEqual(entry(plan)['status'],'INCOMPLETE')
 def test_playing_plan_requires_74_and_no_close_exception(self):
  jobs=playing_jobs(Path('/build'),Path('/input.wav'),Path('/other.wav'),self.folder)
  self.assertEqual(len(jobs),12);self.assertEqual(sum(x['expected'] for x in jobs),74)
  self.assertEqual(len({x['id'] for x in jobs}),12);self.assertTrue(all('allowed_incomplete' not in x for x in jobs))
  closed=[x for x in jobs if x['mode']=='limit_close'];self.assertEqual(len(closed),2)
  for job in closed:self.assertIn('post_close_owned_sink_exact_IDs_and_terminal_kinds',job['expected_IDs'])
 def test_gate_keeps_original_18_and_adds_two(self):
  old_names=['phase59_certified_planning','phase59_request_control','phase61_contract','phase61_checkpoint','phase61_safety','phase61_output_transition','phase61_pipeline_sync','paused_speed_pipeline','phase62_loop','phase62_render','phase62_fix_safety','phase62_evidence','phase62_fix_reuse','phase62_fix_period','phase62_fix_checkpoint','phase62_dynamic_boundary','phase62_loop_speed_ledger','phase62_finish_evidence']
  old_targets=['phase59_tests','phase59_control_tests','phase61_contract_tests','phase61_checkpoint_tests','phase61_safety_tests','phase61_output_transition_tests','phase61_pipeline_sync_tests','paused_speed_pipeline_tests','phase62_loop_tests','phase62_render_tests','phase62_fix_safety_tests','phase62_fix_reuse_tests','phase62_fix_render_tests','phase62_fix_checkpoint_tests','phase62_dynamic_boundary_tests','phase62_native_tests','paused_speed_loop_tests','phase62_loop_speed_ledger_tests']
  self.assertEqual(NAMES,old_names+['phase62_history_invariant','phase62_descriptor_invariant'])
  self.assertEqual(TARGETS,old_targets+['phase62_history_invariant_tests','phase62_descriptor_invariant_tests'])
  self.assertEqual(CONFIGURATIONS,['Release','Debug']);self.assertEqual(STAGES,['configure','build','ctest'])
 def test_missing_history_ctest_is_rejected(self):self.missing_ctest('phase62_history_invariant')
 def test_missing_descriptor_ctest_is_rejected(self):self.missing_ctest('phase62_descriptor_invariant')
 def missing_ctest(self,missing):
  from xml.etree import ElementTree as ET
  names=[name for name in NAMES if name!=missing];root=ET.Element('testsuite',tests=str(len(names)),failures='0')
  for name in names:ET.SubElement(root,'testcase',name=name,status='run',time='0.01')
  path=self.folder/'junit.xml';ET.ElementTree(root).write(path)
  with self.assertRaises(EvidenceError):junit(path,NAMES)
 def test_missing_history_build_target_is_rejected(self):self.missing_target('phase62_history_invariant_tests')
 def test_missing_descriptor_build_target_is_rejected(self):self.missing_target('phase62_descriptor_invariant_tests')
 def missing_target(self,missing):
  path=self.folder/'build.log';path.write_text(''.join('Built target '+name+'\n' for name in TARGETS if name!=missing))
  with self.assertRaises(EvidenceError):stage_log(path,'build',NAMES,TARGETS)

 def close_fixture(self):
  self.job=next(x for x in playing_jobs(self.folder/'build',self.folder/'input',self.folder/'other',self.folder) if x['id']=='limit_close_candidate')
  self.stat=dict(status='PASS',expected=6,executed=6,run_complete=True,Accepted_IDs=[11,12,13])
  self.save('EXPECTED.json',dict(expected_IDs=self.job['expected_IDs']));self.checks(self.job['expected_IDs'])
  self.receipts=[dict(id=i,accepted=True,duplicate=False) for i in [11,12,13]]
  self.before=[]
  for index,request_id in enumerate([11,12,13]):
   self.before.append(dict(id=request_id,loop_id=10,input_generation=2,source_session=3,source_epoch=4,accepted_ns=100+index,speed_micros=[750000,1250000,1500000][index],state=['Completed','Replaced','Preparing'][index],terminal_ns=[900,1000,0][index],reason=['','最新要求へ置換',''][index],committed=index==0,output_started=index==0,first_PCM_observed_ns=500 if index==0 else 0,completed_ns=600 if index==0 else 0,dynamic_session=3 if index==0 else 0,dynamic_operation_id=1 if index==0 else 0))
  final=copy.deepcopy(self.before);final[2].update(state='Cancelled',terminal_ns=1200,reason='直接close')
  delivery=dict(record='audit_delivery',calls=1,sequence=77,received=True,workers_joined=True,retirement_complete=True,duplicate_delivery=False,oversized=False,copy_failed=False,invalid_marker=False,copied_count=3)
  marker=dict(record='FINAL_LOOP_SPEED_AUDIT_COMPLETE',sequence=77,expected_Accepted=3,actual=3,Completed=1,Replaced=1,Cancelled=1,all_workers_joined=True,retirement_complete=True,receipt_ID_set_exact=True,past_immutable=True,direct_close=True)
  self.sink=[delivery,*final,marker];self.write_close()
 def write_close(self):
  self.rows('receipts.jsonl',self.receipts);self.rows('pre_close_ledger.jsonl',self.before);self.rows('sink.jsonl',self.sink)
 def test_close_complete_owned_sink_positive(self):
  self.close_fixture();self.assertTrue(self.verify())
 def test_close_old_72_of_74_cannot_pass(self):
  self.close_fixture();self.checks(self.job['expected_IDs'][:-1]);self.assertFalse(self.verify(dict(self.stat,status='INCOMPLETE',executed=5),code=3))
 def test_close_old_public_query_name_cannot_replace_sink(self):
  self.close_fixture();ids=list(self.job['expected_IDs']);ids[4]='post_close_all_IDs_terminal_public_query';self.checks(ids);self.save('EXPECTED.json',dict(expected_IDs=ids));self.assertFalse(self.verify())
 def test_close_missing_sink(self):
  self.close_fixture();(self.folder/'sink.jsonl').unlink();self.assertFalse(self.verify())
 def test_close_missing_completion_marker(self):
  self.close_fixture();self.sink.pop();self.write_close();self.assertFalse(self.verify())
 def test_close_missing_accepted_id(self):
  self.close_fixture();self.sink.pop(2);self.write_close();self.assertFalse(self.verify())
 def test_close_duplicate_id(self):
  self.close_fixture();self.sink[2]['id']=11;self.write_close();self.assertFalse(self.verify())
 def test_close_foreign_id(self):
  self.close_fixture();self.sink[2]['id']=999;self.write_close();self.assertFalse(self.verify())
 def test_close_wrong_terminal_kinds(self):
  self.close_fixture()
  for operation in self.sink[1:-1]:operation['state']='Cancelled'
  self.write_close();self.assertFalse(self.verify())
 def test_close_nonterminal_id(self):
  self.close_fixture();self.sink[3]['state']='Preparing';self.write_close();self.assertFalse(self.verify())
 def test_close_copy_failed(self):
  self.close_fixture();self.sink[0]['copy_failed']=True;self.write_close();self.assertFalse(self.verify())
 def test_close_duplicate_delivery(self):
  self.close_fixture();self.sink[0].update(calls=2,duplicate_delivery=True);self.write_close();self.assertFalse(self.verify())
 def test_close_not_joined(self):
  self.close_fixture();self.sink[0]['workers_joined']=False;self.write_close();self.assertFalse(self.verify())
 def test_close_changed_completed_past(self):
  self.close_fixture();self.sink[1]['completed_ns']+=1;self.write_close();self.assertFalse(self.verify())
 def test_close_pcm_fact_missing(self):
  self.close_fixture();self.sink[1]['first_PCM_observed_ns']=self.before[0]['first_PCM_observed_ns']=0;self.write_close();self.assertFalse(self.verify())
 def test_close_summary_receipt_ids_differ(self):
  self.close_fixture();self.stat['Accepted_IDs']=[11,12,14];self.assertFalse(self.verify())
 def test_close_bool_terminal_count_rejected(self):
  self.close_fixture();self.sink[-1]['Completed']=True;self.write_close();self.assertFalse(self.verify())


REVIEW_VERIFY_CASES=(
 ('native_PASS_status',False,True,{}),('native_PASS_boolean',False,True,{'boolean_pass':True}),('partial_PASS',True,True,{}),
 ('exit_nonzero',False,False,{'code':3}),('timeout',False,False,{'timed':True}),('summary_FAIL',False,False,{'status':'FAIL'}),
 ('missing_completion_marker',False,False,{'remove_completion':True}),('false_completion_marker',False,False,{'complete':False}),
 ('wrong_expected_count',False,False,{'expected':3}),('wrong_executed_count',False,False,{'executed':1}),
 ('required_ID_missing',False,False,{'wanted':['a']}),('required_ID_duplicate',False,False,{'wanted':['a','a']}),
 ('check_ID_missing',False,False,{'actual':['a']}),('check_ID_duplicate',False,False,{'actual':['a','a']}),('check_ID_foreign',False,False,{'actual':['a','foreign']}),
 ('FAIL_check',False,False,{'failed_check':True}),('empty_checks',False,False,{'actual':[]}),
 ('SUMMARY_file_missing',False,False,{'missing':'SUMMARY.json'}),('EXPECTED_file_missing',False,False,{'missing':'EXPECTED.json'}),('checks_file_missing',False,False,{'missing':'checks.jsonl'}),
 ('SUMMARY_JSON_invalid',False,False,{'invalid':'SUMMARY.json'}),('EXPECTED_JSON_invalid',False,False,{'invalid':'EXPECTED.json'}),('checks_JSON_invalid',False,False,{'invalid':'checks.jsonl'}),
 ('partial_executed_IDs_missing',True,False,{'remove_actual':True}),
 ('partial_executed_ID_duplicate',True,False,{'expected':2,'executed':2,'job_count':2,'wanted':['a','b'],'actual':['a','a']}),
 ('partial_executed_ID_foreign',True,False,{'actual':['foreign']}),('partial_executed_ID_empty',True,False,{'actual':[]}),
 ('partial_incomplete',True,False,{'complete':False}),('partial_wrong_count',True,False,{'executed':0}),
 ('bool_exit_false',False,False,{'code':False}),('bool_counts',True,False,{'expected':True,'executed':True}),
 ('float_counts',True,False,{'expected':1.0,'executed':1.0}),('partial_executed_IDs_string',True,False,{'actual':'a'}),
 ('conflicting_FAIL_and_pass_true',False,False,{'conflicting_check':True}),('required_IDs_numeric',False,False,{'wanted':[1,2],'actual':[1,2]}),
)


class ReviewVerifierEvidenceTests(unittest.TestCase):
 """旧29/35で見つけた6件を含む、製品を起動しない永続回帰。"""
 def setUp(self):
  temporary=tempfile.TemporaryDirectory(prefix='phase62_review_evidence_');self.addCleanup(temporary.cleanup);self.folder=Path(temporary.name)
 def exercise(self,item):
  name,partial,want,mutation=item
  count=mutation.get('job_count',1 if partial else 2);wanted=mutation.get('wanted',['a'] if partial else ['a','b']);actual=mutation.get('actual',list(wanted))
  summary=dict(status=mutation.get('status','PASS'),run_complete=mutation.get('complete',True),expected=mutation.get('expected',count),executed=mutation.get('executed',count))
  # 実binary同様、実行前のEXPECTEDにも整数の期待件数を固定する。
  spec=dict(expected=count,checks=wanted)
  if mutation.get('remove_completion'):summary.pop('run_complete')
  if partial and not mutation.get('remove_actual'):summary['executed_IDs']=actual
  for filename,value in [('SUMMARY.json',summary),('EXPECTED.json',spec)]:
   (self.folder/filename).write_text(json.dumps(value)+'\n')
  rows=[dict(id=value,**({'pass':True} if mutation.get('boolean_pass') else {'status':'PASS'})) for value in actual]
  if mutation.get('failed_check'):rows[-1]['status']='FAIL'
  if mutation.get('conflicting_check'):rows[-1].update(status='FAIL',**{'pass':True})
  (self.folder/'checks.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
  if 'missing' in mutation:(self.folder/mutation['missing']).unlink()
  if 'invalid' in mutation:(self.folder/mutation['invalid']).write_text('{invalid JSON\n')
  job=dict(id=name,expected=count,binary='phase62_partial_mix_native' if partial else 'phase62_adoption_review_native')
  _,reasons=verify_review(job,self.folder,mutation.get('code',0),mutation.get('timed',False))
  self.assertEqual(not reasons,want,msg=name+': '+repr(reasons))


def review_case_test(item):
 def execute(self):self.exercise(item)
 return execute


for _case in REVIEW_VERIFY_CASES:
 setattr(ReviewVerifierEvidenceTests,'test_'+_case[0],review_case_test(_case))


if __name__=='__main__':
 loader=unittest.defaultTestLoader
 legacy=loader.loadTestsFromTestCase(FinishEvidenceTests);review=loader.loadTestsFromTestCase(ReviewVerifierEvidenceTests)
 assert legacy.countTestCases()==40 and review.countTestCases()==len(REVIEW_VERIFY_CASES)==len({x[0] for x in REVIEW_VERIFY_CASES})==35
 suite=unittest.TestSuite([legacy,review]);expected=75;result=unittest.TextTestRunner().run(suite)
 print(json.dumps(dict(suite='phase62_finish_evidence',expected=expected,executed=result.testsRun,status='PASS' if result.wasSuccessful() and result.testsRun==expected else 'FAIL',product_runs=0)))
 raise SystemExit(0 if result.wasSuccessful() and result.testsRun==expected else 1)
