"""Wait for device work, then run heavy exports/regressions and legacy audio serially."""
import datetime
import json
import os
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT

out=ROOT/'results/phase58_fix';history=[]
assert not (out/'post_validation.json').exists()
limit=time.monotonic()+7200
while True:
    p=out/'device_batch.json';rows=json.loads(p.read_text()) if p.exists() else []
    if len(rows)==8 and rows[-1]['name']=='native_startup':break
    if time.monotonic()>limit:raise TimeoutError('Device batch incomplete; no heavy work started')
    time.sleep(1)
def run(name,cmd,env=None):
    start=time.monotonic()
    with (out/(name+'_driver.log')).open('x') as log:
        p=subprocess.run(list(map(str,cmd)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env)
    history.append(dict(name=name,command=list(map(str,cmd)),exit=p.returncode,elapsed_s=time.monotonic()-start,
                        end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    (out/'post_validation.json').write_text(json.dumps(history,indent=2)+'\n');print(name,p.returncode,flush=True)
    return p.returncode
run('after_trace3_analysis',['python3','-B','scripts/phase58_fix_trace_analyze.py',
    '--trace',ROOT/'build/phase58_fix_frozen/after_trace3.trace','--sessions',out/'after_trace3/sessions','--output',out/'after_trace3_analysis'])
code=run('regression',['python3','-B','scripts/phase58_fix_regression.py'])
if not (out/'regression/final_binaries.json').exists():raise RuntimeError('Build/regression driver incomplete; inspect logs before device work')
run('legacy_device',['python3','-B','scripts/phase58_fix_legacy_device.py'])
environment=os.environ.copy();environment['PHASE45_TEST_OUTPUT']=str(out/'legacy_realtime_paced')
run('legacy_realtime_ctest',['ctest','--test-dir','build','-L','realtime','--output-on-failure','-j1'],environment)
run('native_statistics',['python3','-B','scripts/phase58_fix_statistics.py'])
run('measurement_audit',['python3','-B','scripts/phase58_fix_measurement_audit.py','--output',out/'measurement_audit.json'])
raise SystemExit(0 if all(r['exit']==0 for r in history) else 2)
