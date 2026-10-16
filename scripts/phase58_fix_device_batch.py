"""Run device measurements serially, after the separate final-300 cohort."""
import datetime
import json
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT

root=ROOT/'results/phase58_fix'
limit=time.monotonic()+3600
while True:
    prerequisite=json.loads((root/'final_normal300/summary.json').read_text())
    if prerequisite['executions']==prerequisite['requested']: break
    if time.monotonic()>limit: raise TimeoutError('Final independent cohort still running; no overlapping device trials started')
    time.sleep(1)
assert prerequisite['executions']==prerequisite['requested']==300
assert not (root/'device_batch.json').exists()
history=[]
def run(name,cmd):
    start=time.monotonic()
    with (root/(name+'_driver.log')).open('x') as f:
        p=subprocess.run(list(map(str,cmd)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    history.append(dict(name=name,command=list(map(str,cmd)),exit=p.returncode,elapsed_s=time.monotonic()-start,
                        end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat()))
    (root/'device_batch.json').write_text(json.dumps(history,indent=2)+'\n')
    print(name,p.returncode,flush=True)
native=ROOT/'build/phase58_fix_frozen/candidate_v2_native'
flags=['--extra=--worker=workgroup','--extra=--resident-input=on']
run('after_trace3',['python3','-B','scripts/phase58_fix_trace.py','--output',root/'after_trace3','--binary',native,'--repeats','3',*flags,'--extra=--profile=detail','--extra=--sample-thread=on'])
run('cpu_load100',['python3','-B','scripts/phase58_fix_repeat.py','--output',root/'cpu_load100','--binary',native,'--repeats','100','--cpu','2','--memory','128',*flags,'--extra=--profile=block','--extra=--sample-thread=on'])
run('profile_off20',['python3','-B','scripts/phase58_fix_repeat.py','--output',root/'profile_off20','--binary',native,'--repeats','20',*flags,'--extra=--profile=off','--extra=--sample-thread=off'])
run('resident_standard20',['python3','-B','scripts/phase58_fix_repeat.py','--output',root/'resident_standard20','--binary',native,'--repeats','20','--extra=--resident-input=on','--extra=--worker=standard','--extra=--profile=block','--extra=--sample-thread=on'])
for suite in ('grid','lifecycle_load','long','startup'):
    run('native_'+suite,['python3','-B','scripts/phase58_fix_native_validation.py','--suite',suite,'--output',root/('native_'+suite),'--binary',native])
raise SystemExit(0 if all(x['exit']==0 for x in history) else 2)
