"""無効timestampと未公開区間を、正常・観測済みへ補完しない回帰検査。"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase59_fix2_minimal import analyze
from phase59_fix2_legacy_trace_analyze import publication_profiles


class ForensicsTests(unittest.TestCase):
    def pair(self,flags=7,sample=512,host=10666667,logical=512,received=512):
        rows=[dict(sequence=1,flags=flags,sample_time=0,host_ticks=100000000,requested=512,
                   received=received,logical_before=0,begin_ticks=90000000),
              dict(sequence=2,flags=flags,sample_time=sample,host_ticks=100000000+host,requested=512,
                   received=512,logical_before=logical,begin_ticks=90000000+host)]
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/'summary.json').write_text(json.dumps(dict(timebase_numer=1,timebase_denom=1,pcm_mismatches=0)))
            with (folder/'callbacks.csv').open('w') as file:
                writer=csv.DictWriter(file,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
            return analyze(folder)

    def test_coherent_host_sample_jump_is_still_a_failure_event(self):
        result=self.pair(sample=1160,host=24166667)
        self.assertEqual(result['clock_jumps'][0]['extra_sample_frames'],648)
        self.assertTrue(result['clock_jumps'][0]['sample_and_host_progress_agree'])
        self.assertTrue(result['callback_signal_identical'])
        self.assertFalse(result['physical_audio_continuity_verified'])

    def test_invalid_host_not_used(self):
        result=self.pair(flags=1,sample=1160,host=-99999999)
        self.assertIsNone(result['clock_jumps'][0]['host_delta_ns'])

    def test_invalid_sample_not_used(self):
        result=self.pair(flags=2,sample=float('nan'),host=24166667)
        self.assertIsNone(result['clock_jumps'][0]['sample_delta'])

    def test_invalid_representations_do_not_invent_computable_time(self):
        result=self.pair(flags=0,sample=float('nan'),host=-99999999)
        self.assertEqual(result['clock_jumps'],[])
        self.assertFalse(result['physical_audio_continuity_verified'])

    def test_logical_position_gap_detected_independent_of_clock(self):
        result=self.pair(received=511,logical=512)
        self.assertEqual(len(result['logical_position_errors']),1)
        self.assertFalse(result['callback_signal_identical'])

    def test_zero_unpublished_and_duplicate_profiles_not_counted(self):
        valid=dict(session='1',thread_id='10',start_mach_ns='10',pcm_ready_mach_ns='15',published_mach_ns='20')
        zero=dict(valid,start_mach_ns='20')
        unknown_thread=dict(valid,thread_id='0')
        kept,unpublished,duplicates=publication_profiles([valid,zero,unknown_thread,dict(valid)])
        self.assertEqual((len(kept),len(unpublished),len(duplicates)),(1,2,1))


if __name__=='__main__':unittest.main()
