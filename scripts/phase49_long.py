#!/usr/bin/env python3
"""Bounded three-condition A/B study; no concurrent trace/DSP workloads."""
import json,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
base=root/'results/phase49/long';base.mkdir(parents=True,exist_ok=True)
results=[]
for source,minutes in [('drums',5),('drums',10),('mix',5)]:
    name=f'{source}{minutes}_stress';out=base/name
    command=[sys.executable,str(root/'scripts/phase48_study.py'),'--output',str(out),'--source',source,'--minutes',str(minutes),'--orders','AB,BA']
    print('CONDITION_BEGIN',name,flush=True)
    with (base/f'{name}.log').open('x') as log:
        result=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=minutes*240*4+600)
    summary=out/'comparison_summary.json'
    completed=summary.exists() and json.loads(summary.read_text())['all_runs']==4
    results.append(dict(condition=name,process_exit=result.returncode,all_four_completed=completed,
        quality=json.loads(summary.read_text())['NATIVE_QUALITY'] if summary.exists() else 'UNMEASURED'))
    (base/'conditions.json').write_text(json.dumps(results,indent=2))
    print('CONDITION_END',results[-1],flush=True)
    if not completed or result.returncode not in (0,2):raise SystemExit('Incomplete experiment; subsequent conditions stopped')
print('Bounded long-run comparisons complete; all outcomes retained',flush=True)
