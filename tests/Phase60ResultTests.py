import sys,unittest,tempfile,struct
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase60_native import summarize
from phase60_prepare_wav import rewrap
class ResultTests(unittest.TestCase):
    def test_empty_is_unmeasured(self):
        r=summarize([],4,2)
        self.assertFalse(r['measurement_completed']);self.assertFalse(r['supply_and_callback_pass']);self.assertFalse(r['pcm_pass']);self.assertFalse(r['progressive_worker_deadlines_pass'])
    def test_missing_execution_is_not_pass(self):
        row={'name':'one','exit':0,'summary':{'engine':'progressive','sessions':[{'worker_deadline_misses':0}],'supply_and_callback_pass':True},'pcm':{'PASS':True}}
        self.assertFalse(summarize([row],2,1)['supply_and_callback_pass'])
    def test_missing_pcm_is_not_pass(self):
        row={'name':'one','exit':0,'summary':{'engine':'progressive','sessions':[{'worker_deadline_misses':0}],'supply_and_callback_pass':True}}
        self.assertFalse(summarize([row],1,1)['pcm_pass'])
    def test_ended_does_not_mask_missing(self):
        row={'name':'one','exit':2,'summary':{'engine':'progressive','sessions':[{'worker_deadline_misses':1,'state':'Ended'}],'supply_and_callback_pass':False},'pcm':{'PASS':True}}
        r=summarize([row],1,1);self.assertTrue(r['measurement_completed']);self.assertFalse(r['supply_and_callback_pass']);self.assertFalse(r['progressive_worker_deadlines_pass']);self.assertEqual(r['failures'],['one'])
    def test_rewrap_preserves_pcm_bits(self):
        payload=struct.pack('<IIII',0x80000000,0x3eaaaaab,0x00000001,0xbf800000)
        fmt=struct.pack('<HHIIHHHHI',0xfffe,2,44100,352800,8,32,22,32,3)+bytes.fromhex('0300000000001000800000aa00389b71')
        body=b'WAVEfmt '+struct.pack('<I',len(fmt))+fmt+b'data'+struct.pack('<I',len(payload))+payload
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'ext.wav';dst=Path(d)/'canonical.wav';src.write_bytes(b'RIFF'+struct.pack('<I',len(body))+body)
            r=rewrap(src,dst);self.assertTrue(r['pcm_payload_unchanged']);self.assertEqual(dst.read_bytes()[44:],payload);self.assertEqual(struct.unpack_from('<H',dst.read_bytes(),20)[0],3)
            with self.assertRaises(FileExistsError):rewrap(src,dst)
if __name__=='__main__':unittest.main()
