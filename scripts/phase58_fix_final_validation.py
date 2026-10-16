"""Final V3: verify measured diagnostic-fault fix, then serialize device and quality tests."""
import datetime
import gzip
import json
import os
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT,sha

out=ROOT/'results/phase58_fix'; history=[]
assert not (out/'final_validation.json').exists()
native=ROOT/'build/phase58_fix_frozen/candidate_v3_native'; binary_sha=sha(native)
def run(name,cmd,env=None):
    start=time.monotonic()
    with (out/(name+'_driver.log')).open('x') as log:
        p=subprocess.run(list(map(str,cmd)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env)
    history.append(dict(name=name,command=list(map(str,cmd)),exit=p.returncode,elapsed_s=time.monotonic()-start,
                        binary_sha256=binary_sha,end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    (out/'final_validation.json').write_text(json.dumps(history,indent=2)+'\n'); print(name,p.returncode,flush=True)
    assert sha(native)==binary_sha,'Frozen binary changed'
    return p.returncode
trace=json.loads((out/'v3_trace3/summary.json').read_text())
assert trace['trace_exit']==0 and trace['sessions']==3 and trace['failed']==0
assert run('v3_trace3_analysis',['python3','-B','scripts/phase58_fix_trace_analyze.py',
    '--trace',ROOT/'build/phase58_fix_frozen/v3_trace3.trace','--sessions',out/'v3_trace3/sessions','--output',out/'v3_trace3_analysis'])==0
evidence=[]
for folder in sorted((out/'v3_trace3_analysis').glob('session_*')):
    p=next(folder.glob('blocks.json*'))
    blocks=json.loads(gzip.open(p,'rt').read() if p.suffix=='.gz' else p.read_text())
    blocks=[b for b in blocks if b['realtime']]
    evidence.append(dict(session=folder.name,realtime_blocks=len(blocks),faults=sum(len(b['os']['faults']) for b in blocks),
                         unobserved_s=sum(b['os']['unobserved_s'] for b in blocks)))
fixed=bool(evidence) and all(r['realtime_blocks'] and r['faults']==0 and r['unobserved_s']<1e-6 for r in evidence)
(out/'v3_diagnostic_fault_verification.json').write_text(json.dumps(dict(PASS=bool(fixed),records=evidence,
    scope='Observed realtime math blocks; no claim that all process pages are pinned'),indent=2)+'\n')
assert fixed,'Inspect remaining OS faults before final cohorts'
flags=['--extra=--worker=workgroup','--extra=--resident-input=on']
for name,repeats,extra in [('v3_normal300',300,['--extra=--profile=block','--extra=--sample-thread=on']),
    ('v3_cpu100',100,['--cpu','2','--memory','128','--extra=--profile=block','--extra=--sample-thread=on']),
    ('v3_profile_off20',20,['--extra=--profile=off','--extra=--sample-thread=off'])]:
    run(name,['python3','-B','scripts/phase58_fix_repeat.py','--output',out/name,'--binary',native,'--repeats',repeats,*flags,*extra])
for suite in ('grid','lifecycle_load','long','startup'):
    run('v3_'+suite,['python3','-B','scripts/phase58_fix_native_validation.py','--suite',suite,
                    '--output',out/('v3_'+suite),'--binary',native])
run('v3_regression',['python3','-B','scripts/phase58_fix_regression.py','--output',out/'regression_v3'])
assert (out/'regression_v3/final_binaries.json').exists(),'Regression driver incomplete'
run('legacy_device',['python3','-B','scripts/phase58_fix_legacy_device.py'])
environment=os.environ.copy();environment['PHASE45_TEST_OUTPUT']=str(out/'legacy_realtime_paced')
run('legacy_realtime_ctest',['ctest','--test-dir','build','-L','realtime','--output-on-failure','-j1'],environment)
run('native_statistics',['python3','-B','scripts/phase58_fix_statistics.py'])
run('measurement_audit',['python3','-B','scripts/phase58_fix_measurement_audit.py','--output',out/'measurement_audit.json'])
raise SystemExit(0 if all(r['exit']==0 for r in history) else 2)
