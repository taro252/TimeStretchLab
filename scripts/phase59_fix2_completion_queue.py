"""原因調査の判断後に最終実行体を固定し、必須回帰を省略せず実行する。"""
import concurrent.futures
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT


def main():
    data=ROOT/'build/phase59_fix2_artifacts';state=OUT/'COMPLETION_QUEUE.json'
    history=[];lock=threading.Lock()
    state.write_text(json.dumps(dict(stage='wait_forensics_decision_and_minimal_long',history=history),indent=2)+'\n')
    while not (OUT/'REPAIR_DECISION.json').exists() or not (OUT/'minimal_long/summary.json').exists():time.sleep(1)
    def run(name,command,allowed=(0,)):
        command=list(map(str,command));started=time.time()
        with lock:state.write_text(json.dumps(dict(stage=name,command=command,history=history),indent=2)+'\n')
        log_path=data/(name+'_completion.log')
        with log_path.open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        row=dict(name=name,command=command,exit=p.returncode,wall_s=time.time()-started,log=str(log_path))
        with lock:
            history.append(row);state.write_text(json.dumps(dict(stage=name+'_completed',history=history),indent=2)+'\n')
        print(name,p.returncode,flush=True)
        if p.returncode not in allowed:raise RuntimeError('Stage failed: '+name)
        return row
    py=[sys.executable,'-B'];frozen=data/'final';debug=ROOT/'build/phase59_fix2_debug'
    run('release_final_build',['cmake','--build','build','-j3'])
    run('freeze_final',py+['scripts/phase59_fix2_freeze.py'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(run,'quality_final',py+['scripts/phase59_fix2_validation.py','--frozen',frozen]),
               pool.submit(run,'checks_final',py+['scripts/phase59_fix2_checks.py','--debug-build',debug])]
        failures=[]
        for task in tasks:
            try:task.result()
            except Exception as error:failures.append(str(error))
    if failures:
        state.write_text(json.dumps(dict(stage='quality_or_checks_failed',history=history,failures=failures),indent=2)+'\n')
        raise RuntimeError('; '.join(failures))
    # Nativeには他の品質解析・ビルドを重ねない。品質不一致なら開始しない。
    run('device_final',py+['scripts/phase59_fix2_device.py','--frozen',frozen],allowed=(0,2))
    run('eos_final',py+['scripts/phase59_fix2_eos.py','--tag','final','--release',frozen/'phase59_fix_eos_probe',
                      '--debug',debug/'phase59_fix_eos_probe'],allowed=(0,2))
    state.write_text(json.dumps(dict(stage='required_regressions_completed',history=history,
                                    measurement_failures_retained=any(r['exit']==2 for r in history)),indent=2)+'\n')


if __name__=='__main__':main()
