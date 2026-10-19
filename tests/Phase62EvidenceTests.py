import json,struct,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase62_evidence import Ledger,aggregate,bit_exact_finite,inspect_case,verify_architecture

class EvidenceTests(unittest.TestCase):
    def test_signed_zero_and_nonfinite(self):
        self.assertFalse(bit_exact_finite(struct.pack('<f',0.),struct.pack('<f',-0.)))
        self.assertFalse(bit_exact_finite(struct.pack('<f',float('nan')),struct.pack('<f',float('nan'))))
        self.assertFalse(bit_exact_finite(struct.pack('<f',float('inf')),struct.pack('<f',float('inf'))))
        self.assertTrue(bit_exact_finite(struct.pack('<f',.25),struct.pack('<f',.25)))
    def test_zero_tests(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'test.xml').write_text('<testsuite tests="0"/>')
            gates,reasons=inspect_case(dict(kind='ctest',result='test.xml',required=['test.xml'],test_names=['required']),root,0)
            self.assertFalse(gates['functional'])
    def test_missing_required(self):
        with tempfile.TemporaryDirectory() as d:
            gates,reasons=inspect_case(dict(required=['missing.json']),Path(d),0)
            self.assertTrue(reasons);self.assertIsNone(gates['functional'])
    def test_failure_not_run_and_tampering(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'suite';ledger=Ledger(root,[dict(id='fail'),dict(id='not_run'),dict(id='pass',required=['result.json'],kind='json_pass',result='result.json')],{})
            ledger.run('fail',[sys.executable,'-c','raise SystemExit(3)'],cwd=root)
            ledger.run('pass',[sys.executable,'-c',"from pathlib import Path;Path('result.json').write_text('{\"PASS\":true}')"],cwd=root)
            value=aggregate(root);self.assertFalse(value['PASS']);self.assertEqual(value['counts']['FAIL'],1);self.assertEqual(value['counts']['NOT_RUN'],1)
            (root/'result.json').write_text('{"PASS":false}')
            self.assertEqual(aggregate(root)['cases'][2]['status'],'INCOMPLETE')
    def test_no_plan(self):
        with tempfile.TemporaryDirectory() as d:self.assertFalse(aggregate(d)['PASS'])
    def test_stale_result(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'suite';ledger=Ledger(root,[dict(id='stale',required=['x'])],{});(root/'x').write_text('stale')
            self.assertFalse(ledger.run('stale',[sys.executable,'-c','pass'],cwd=root));self.assertEqual(ledger.rows['stale']['status'],'INCOMPLETE')
    def test_functional_pass_is_not_realtime(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);v=dict(functional_pass=True,cycles=10)
            for name in ('raw_mix_errors','nonfinite','safety_stop_frames','missing_frames','underrun_calls','callback_deadlines','host_errors','sample_errors','hal_window_misses','callback_new','callback_heap_calls','callback_frees','final_worker_deadlines','final_workgroup_errors','final_missing_frames','final_worker_new','invalid_sample_time_calls','invalid_rate_scalar_calls'):v[name]=0
            v['final_worker_deadlines']=121;(root/'result.json').write_text(json.dumps(v))
            (root/'boundaries.jsonl').write_text('')
            g,r=inspect_case(dict(kind='native',result='result.json',cycles=10),root,0)
            self.assertFalse(r);self.assertIs(g['functional'],True);self.assertIs(g['realtime'],False)
    def test_summary_count_cannot_replace_actual_rows(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'summary.json').write_text('{"PASS":true,"passed":896}')
            (root/'rows.jsonl').write_text('')
            g,r=inspect_case(dict(kind='exact',result='summary.json',expected_count=896),root,0)
            self.assertFalse(g['raw'])
    def test_unrun_raw_case_prevents_raw_go(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'suite';ledger=Ledger(root,[dict(id='first',kind='pcm'),dict(id='unrun',kind='pcm')],{})
            ledger.run('first',[sys.executable,'-c','pass'],cwd=root)
            self.assertIsNone(aggregate(root)['gates']['raw'])
    def test_cross_architecture_is_rejected(self):
        from unittest.mock import patch
        import subprocess
        with patch('phase62_evidence.subprocess.run',return_value=subprocess.CompletedProcess([],0,'x86_64\n','')):
            self.assertFalse(verify_architecture(['host'])['PASS'])
        with patch('phase62_evidence.subprocess.run',return_value=subprocess.CompletedProcess([],0,'arm64\n','')):
            self.assertTrue(verify_architecture(['host'])['PASS'])
    def test_clear_failure_cannot_hide_behind_measured_loop_pass(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);value=dict(functional_pass=True,cycles=10)
            for key in ('raw_mix_errors','nonfinite','safety_stop_frames','missing_frames','underrun_calls','callback_deadlines','host_errors','sample_errors','hal_window_misses','callback_new','callback_heap_calls','callback_frees','final_worker_deadlines','final_workgroup_errors','final_missing_frames','final_worker_new','invalid_sample_time_calls','invalid_rate_scalar_calls'):value[key]=0
            (root/'result.json').write_text(json.dumps(value));(root/'boundaries.jsonl').write_text('')
            spec=dict(kind='native',result='result.json',cycles=10,clear_contract=True)
            gates,reasons=inspect_case(spec,root,0);self.assertTrue(reasons)
            clear=dict(PASS=True,connection_counted_as_cycle=False,failure_padding_frames=430,output_affected_frames=0,missing_frames=0,callback_deadlines=0,host_errors=0,sample_errors=0,hal_window_misses=0)
            (root/'clear_result.json').write_text(json.dumps(clear));gates,reasons=inspect_case(spec,root,0)
            self.assertFalse(reasons);self.assertIs(gates['functional'],True);self.assertIs(gates['realtime'],False)

if __name__=='__main__':unittest.main()
