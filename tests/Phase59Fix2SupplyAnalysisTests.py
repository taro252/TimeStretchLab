"""供給停止の解釈で、寿命外のMach標本と生成完了の逆推論を防ぐ。"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase59_fix2_deep_analyze import analyze


class SupplyEvidenceTests(unittest.TestCase):
    def fixture(self,folder,feed_start=200):
        status=dict(timebase_numer=1,timebase_denom=1,event_export_ok=1,sample_export_ok=1,event_dropped=0,sample_dropped=0)
        (folder/'supply_status.json').write_text(json.dumps(status))
        fields='before_ticks,after_ticks,thread,owner,kind,logical,frames,read,write,cpu_ns'.split(',')
        events=[(100,1),(feed_start,20),(feed_start+40,22),(700,23),(750,50),(800,51),(900,21),(1000,2)]
        with (folder/'supply_events.csv').open('w') as file:
            writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
            for tick,kind in events:writer.writerow(dict(zip(fields,[tick,tick+1,7,11,kind,0,16,0,16 if tick>=800 else 0,0])))
        fields='before_ticks,after_ticks,thread,owner,result,state,policy,priority,base,user_ns,system_ns'.split(',')
        with (folder/'supply_samples.csv').open('w') as file:
            writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
            for tick,result in [(450,0),(460,5),(1010,0)]:writer.writerow(dict(zip(fields,[tick,tick+1,7,11,result,3,1,31,31,0,0])))
        (folder/'worker_0.csv').write_text('session,thread_id\n1,7\n')
        (folder/'callbacks_0.csv').write_text('session,start_ns,wanted,received\n1,500,16,12\n')

    def test_only_successful_lifetime_samples_are_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);self.fixture(folder);summary,data=analyze(folder)
        self.assertEqual(summary['valid_lifetime_samples'],1)
        self.assertEqual(summary['invalid_or_outside_lifetime_samples'],2)
        self.assertEqual(summary['sampled_states'],{3:1})

    def test_pcm_arrived_before_shortage_during_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);self.fixture(folder);summary,data=analyze(folder)
        self.assertTrue(data['shortages'][0]['pcm_positive_evidence_before_shortage'])
        self.assertIn(22,[r['kind'] for r in data['shortages'][0]['active_scopes_at_shortage']])
        self.assertEqual(summary['missing_frames'],4)

    def test_later_marker_does_not_establish_earlier_compute_state(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);self.fixture(folder,600);summary,data=analyze(folder)
        self.assertFalse(data['shortages'][0]['pcm_positive_evidence_before_shortage'])
        self.assertEqual(summary['shortages_with_positive_generated_pcm_evidence'],0)


if __name__=='__main__':unittest.main()
