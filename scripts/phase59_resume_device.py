"""Resume capacity-interrupted audio groups without repeating completed cases."""
import argparse,json,subprocess,sys,time
from pathlib import Path
from phase57_study import ROOT
def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'results/phase59/device_resume')
    args=parser.parse_args()
    out=args.output;out.mkdir(exist_ok=False);rows=[]
    # The older coordinator is finishing fixed/legacy trials first. All physical
    # audio remains serial, including across the storage checkpoint.
    while not (ROOT/'results/phase59/device_final/summary.json').exists():time.sleep(2)
    for suite in ['load','lifecycle','burst','materials','long']:
        folder=ROOT/'results/phase59/device_final'/('dynamic_'+suite)
        if (folder/'summary.json').exists():continue
        command=[sys.executable,'-B','scripts/phase59_native_validation.py','--suite',suite,'--output',str(folder),
            '--binary',str(ROOT/'build/phase59_frozen/final/phase59_native'),'--resume','--minimum-free-gib','3']
        start=time.time()
        with (out/(suite+'.log')).open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        rows.append(dict(suite=suite,command=command,exit=p.returncode,wall_s=time.time()-start))
        (out/'driver.json').write_text(json.dumps(rows,indent=2)+'\n');print(suite,p.returncode,flush=True)
        if p.returncode not in [0,2]:raise RuntimeError('Audio continuation interrupted: '+suite)
    (out/'summary.json').write_text(json.dumps(dict(PASS=all(r['exit']==0 for r in rows),history=rows,original_capacity_interruptions_preserved=True),indent=2)+'\n')
if __name__=='__main__':main()
