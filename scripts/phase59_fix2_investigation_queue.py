"""実機試験を重ねず、診断構築と重点取得を現在の作業内で順に進める。"""
import csv
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT, sha


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    state=OUT/'INVESTIGATION_QUEUE.json';data=ROOT/'build/phase59_fix2_artifacts'
    history=json.loads(state.read_text())['history'] if args.resume else []
    state.write_text(json.dumps(dict(stage='wait_legacy_investigation',history=history),indent=2)+'\n')
    while not (OUT/'legacy_investigation/summary.json').exists():time.sleep(1)
    def run(name,command,allowed=(0,)):
        if any(r['name']==name and r['exit'] in allowed for r in history):return
        command=list(map(str,command));state.write_text(json.dumps(dict(stage=name,command=command,history=history),indent=2)+'\n')
        attempt=sum(r['name']==name for r in history)+1
        log_path=data/(name+'_queue'+('' if attempt==1 else '_attempt_'+str(attempt))+'.log')
        with log_path.open('x') as log:
            p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        history.append(dict(name=name,command=command,exit=p.returncode,log=str(log_path)))
        state.write_text(json.dumps(dict(stage=name+'_completed',history=history),indent=2)+'\n')
        print(name,p.returncode,flush=True)
        assert p.returncode in allowed,(name,p.returncode)
    py=[sys.executable,'-B']
    run('release_diagnostic_rebuild',['cmake','--build','build','-j3'])
    run('old_math_build',py+['scripts/phase59_fix2_old_product.py'])
    run('startup_cde',py+['scripts/phase59_fix2_startup.py','--repeats','5'])
    old=json.loads((OUT/'OLD_MATH_DIAGNOSTIC_BUILD.json').read_text())
    source=ROOT/'results/phase31/input/mix.wav'
    run('trace_legacy_old_math',py+['scripts/phase59_fix2_trace.py','--name','legacy_old_math','--seconds','12','--',
        old['binary'],source,'baseline','2.0',data/'legacy_old_math_trace_native','smoke','64'],allowed=(0,54))
    cde=json.loads((OUT/'startup_cde/rows.json').read_text())
    d=next(r for r in cde if r['label']=='D_dynamic_no_request')
    command=d['command'].copy();command[7]=str(data/'dynamic_no_request_trace_native')
    command=[('--capture-path='+str(data/'dynamic_no_request_trace_capture.f32')) if c.startswith('--capture-path=') else c for c in command]
    run('trace_dynamic_no_request',py+['scripts/phase59_fix2_trace.py','--name','dynamic_no_request','--seconds','8','--',*command],allowed=(0,54))
    run('trace_dynamic_no_request_analysis',py+['scripts/phase59_fix2_trace_analyze.py','--name','dynamic_no_request','--native',data/'dynamic_no_request_trace_native'])
    run('legacy_investigation_analysis',py+['scripts/phase59_fix2_legacy_analyze.py','--rows',OUT/'legacy_investigation/rows.json','--name','investigation'])
    state.write_text(json.dumps(dict(stage='completed',history=history),indent=2)+'\n')


if __name__=='__main__':main()
