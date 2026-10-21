"""集計の負例。製品・DSP・音声を起動しない。"""
import json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase62_finish_validation import verify_result,verify_build
from phase62_aggregation_manifest import entry
from phase62_evidence import identity

def require(x):
 if not x:raise AssertionError('不完全な証拠を受理')
with tempfile.TemporaryDirectory(prefix='phase62_finish_evidence_') as d:
 f=Path(d);save=lambda n,v:(f/n).write_text(json.dumps(v)+'\n')
 job={'expected':2};stat=dict(status='PASS',expected=2,executed=2,run_complete=True)
 save('EXPECTED.json',{'expected_IDs':['a','b']});save('SUMMARY.json',stat)
 def checks(ids): (f/'checks.jsonl').write_text(''.join(json.dumps(dict(id=i,status='PASS'))+'\n' for i in ids))
 def verify(s=stat,code=0,timed=False,suite='playing'):return verify_result(suite,job,f,code,timed,s)
 checks(['a','b']);require(verify())
 (f/'checks.jsonl').unlink();require(not verify())
 checks(['a','b']);require(not verify({k:v for k,v in stat.items() if k!='run_complete'}))
 checks(['a','a']);require(not verify())
 checks(['a']);require(not verify())
 checks(['a','b']);require(not verify(dict(stat,status='FAIL')))
 require(not verify(timed=True))
 require(not verify(dict(stat,run_complete=False),suite='cache'))
 binary=f/'test_fixture_only';binary.write_bytes(b'not an executable')
 provenance=dict(status='PASS',source_inventory_sha256='a'*64,compiler='fixture',configuration='Release',architecture='arm64',binaries={binary.name:'0'*64})
 try:verify_build(provenance,'a'*64,[binary]);accepted=True
 except ValueError:accepted=False
 require(not accepted)
 plan=dict(id='synthetic',mode='strict_gates',directory=str(f),expected_counts={'Release':3,'Debug':3})
 with patch('phase62_aggregation_manifest.strict_gates',return_value=dict(status='PASS',measured_counts={'Release':2,'Debug':2})):
  require(entry(plan)['status']=='INCOMPLETE')
print(json.dumps(dict(suite='phase62_finish_evidence',expected=10,executed=10,status='PASS',product_runs=0)))
