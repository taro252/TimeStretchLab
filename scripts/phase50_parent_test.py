#!/usr/bin/env python3
"""Fault injection validates orchestration, not native audio stability."""
import json,tempfile
from pathlib import Path
from phase49_long import REQUIRED,run_conditions

def fake(output,verdict,code,damage=None):
    output.mkdir(parents=True)
    (output/'comparison_summary.json').write_text(json.dumps(dict(all_runs=4,NATIVE_QUALITY=verdict)))
    for i in range(4):
        path=output/'runs'/str(i);path.mkdir(parents=True)
        row=dict.fromkeys(REQUIRED,'PASS');row['NATIVE_STABILITY_VERDICT']=verdict
        if verdict=='FAIL':row['AUDIO_QUALITY']='FAIL'
        if verdict=='INDETERMINATE':row['MEASUREMENT_QUALITY']='INDETERMINATE'
        (path/'comparison.json').write_text(json.dumps(row))
        for name in ('callbacks.csv','workers.csv','workers.csv.guard.csv','replay.csv','csv_integrity.json'):
            (path/name).write_text('fixture\n')
    if damage=='aggregate':(output/'comparison_summary.json').unlink()
    elif damage=='csv':(output/'runs/0/callbacks.csv').unlink()
    return code

cases=[(['PASS']*3,None,0,'COMPLETE'),(['PASS','FAIL','PASS'],None,2,'COMPLETE'),
       (['FAIL']*3,None,2,'COMPLETE'),(['INDETERMINATE']*3,None,2,'COMPLETE'),
       (['PASS']*3,'crash',3,'ERROR'),(['PASS']*3,'aggregate',3,'ERROR'),(['PASS']*3,'csv',3,'ERROR')]
with tempfile.TemporaryDirectory() as directory:
    for index,(verdicts,damage,expected,execution) in enumerate(cases):
        used=[]
        def execute(output,log):
            verdict=verdicts[len(used)];used.append(verdict)
            code=-9 if damage=='crash' else 0 if verdict=='PASS' else 2
            return fake(output,verdict,code,damage)
        r=run_conditions(Path(directory)/str(index),[('drums',5),('drums',10),('mix',5)],execute)
        assert r['exit_code']==expected and r['EXPERIMENT_EXECUTION']==execution
        assert len(used)==(3 if execution=='COMPLETE' else 1)
print('Parent failure propagation / incomplete evidence injection PASS (not audio PASS)')
