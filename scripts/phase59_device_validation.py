"""Run audio suites serially after all heavy offline validation has ended."""
import argparse,json,subprocess,time
from pathlib import Path
from phase57_study import ROOT,sha

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--wait-prerequisites',action='store_true');a=parser.parse_args()
    prerequisites=[ROOT/'results/phase59/quality_final/summary.json',ROOT/'results/phase59/regression_final/summary.json',ROOT/'results/phase59/debug_final/final_summary.json']
    while not all(p.exists() for p in prerequisites):
        for folder in ('quality_final','regression_final'):
            p=ROOT/'results/phase59'/folder/'driver.json'
            if p.exists() and any(r['exit'] for r in json.loads(p.read_text())):raise RuntimeError('Offline prerequisite failed: '+folder)
        if not a.wait_prerequisites:raise RuntimeError('Offline prerequisites incomplete')
        time.sleep(5)
    assert all(json.loads(p.read_text())['PASS'] for p in prerequisites)
    out=ROOT/'results/phase59/device_final';out.mkdir(exist_ok=False);rows=[]
    frozen=ROOT/'build/phase59_frozen/final'
    def run(name,command):
        start=time.time()
        with (out/(name+'.log')).open('x') as log:p=subprocess.run(list(map(str,command)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        rows.append(dict(name=name,command=list(map(str,command)),exit=p.returncode,wall_s=time.time()-start))
        (out/'driver.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,p.returncode,flush=True)
    for suite in ('normal','load','lifecycle','burst','materials','long'):
        run('dynamic_'+suite,['python3','-B','scripts/phase59_native_validation.py','--suite',suite,'--output',out/('dynamic_'+suite),'--binary',frozen/'phase59_native'])
    for preset in ('candidate','baseline'):
        for speed in (400000,1000000,2000000):
            for cpu in (0,2):
                name=f'fixed_{preset}_{speed}_cpu{cpu}'
                run(name,['python3','-B','scripts/phase58_fix_repeat.py','--output',out/name,'--binary',frozen/'phase58_native',
                    '--repeats','3','--speed',speed,'--preset',preset,'--cpu',cpu,'--extra=--worker=workgroup','--extra=--resident-input=on','--extra=--profile=block','--extra=--sample-thread=on'])
    run('fixed_long',['python3','-B','scripts/phase59_fixed_long_device.py'])
    run('legacy_product',['python3','-B','scripts/phase59_legacy_device.py'])
    (out/'summary.json').write_text(json.dumps(dict(PASS=all(r['exit']==0 for r in rows),stages=len(rows),history=rows),indent=2)+'\n')
if __name__=='__main__':main()
