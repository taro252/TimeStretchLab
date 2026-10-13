#!/usr/bin/env python3
"""Requested consumer quanta, distinct from the fixed512 native device."""
import csv,json,os,subprocess
from pathlib import Path
from phase45_store import parse_log
from phase50_paced_verify import verify_trial
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase50/paced'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'summary.json').exists():raise SystemExit('Fresh output required')
    rows=[]
    for n in (64,128,256,512,1024):
        path=OUT/str(n);path.mkdir()
        env=os.environ.copy();env.update(PHASE44_TRACE_EVENTS='1',PHASE49_STALL_MS='300',PHASE49_STALL_OUTPUT='216000',PHASE49_STALL_FIFO='16384')
        cmd=[ROOT/'build/phase40_paced_sim',ROOT/'results/phase49/input/drums30.wav',.4,2,1,'C',n,16384,16384,2048,70,path/'metrics.csv','safe-density']
        result=subprocess.run(list(map(str,cmd)),env=env,capture_output=True,text=True,timeout=120)
        (path/'run.log').write_text(result.stdout+result.stderr);v=parse_log(result.stdout)
        injection_valid=(v.get('controlled_stall_triggered')=='1' and v.get('controlled_stall_fifo_before')=='16384' and float(v.get('controlled_stall_wall_s',0))>=.3)
        valid=v.get('SIMULATION_VALIDITY')=='VALID' and injection_valid
        supply=('FAIL' if int(v.get('missing_frames',-1))>0 else 'PASS' if valid and result.returncode==0 else 'INDETERMINATE')
        row=dict(callback=n,INJECTION_VALIDITY='PASS' if injection_valid else 'FAIL',process_exit=result.returncode,SIMULATION_VALIDITY=v.get('SIMULATION_VALIDITY','MISSING'),
            CALLBACK_TIMING=v.get('CALLBACK_TIMING','MISSING'),SUPPLY_INTEGRITY=supply,
            OVERALL_REALTIME='PASS' if result.returncode==0 and valid else 'FAIL' if supply=='FAIL' else 'INDETERMINATE',values=v)
        row.update(verify_trial(path,row))
        row['verdict_stage']='FINAL_WITH_INDEPENDENT_PCM_REPLAY'
        rows.append(row);(OUT/'summary.json').write_text(json.dumps(rows,indent=2))
        print(n,row['OVERALL_REALTIME'],v.get('missing_frames'),row['SIMULATION_VALIDITY'],flush=True)
    return 2 if any(r['OVERALL_REALTIME']!='PASS' for r in rows) else 0
if __name__=='__main__':raise SystemExit(main())
