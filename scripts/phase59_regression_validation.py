"""Run unchanged regression drivers into fresh Phase59 directories."""
import json,subprocess,time
from pathlib import Path
from phase57_study import ROOT,sha

def main():
    out=ROOT/'results/phase59/regression_final';out.mkdir(exist_ok=False);rows=[]
    def run(name,command):
        start=time.time()
        with (out/(name+'.log')).open('x') as log:
            p=subprocess.run(list(map(str,command)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        rows.append(dict(name=name,command=list(map(str,command)),exit=p.returncode,wall_s=time.time()-start))
        (out/'driver.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,p.returncode,flush=True)
        if p.returncode:raise RuntimeError('Regression failed: '+name)
    (out/'manifest.json').write_text(json.dumps(dict(head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        driver_sha256=sha(Path(__file__)),scope='Unchanged historical drivers; their embedded baseline fields identify their historical references, not Phase59 HEAD'),indent=2)+'\n')
    run('release_ctest',['ctest','--test-dir','build','-L','deterministic','--output-on-failure','-j2'])
    for suite in ('short','all_speeds','long'):
        run('phase58_'+suite,['python3','-B','scripts/phase58_fix_study.py','--suite',suite,'--output',out/('phase58_'+suite)])
    for suite in ('stage1','stage2','long','natural','rejections'):
        command=['python3','-B','scripts/phase57_study.py','--suite',suite,'--output',out/('phase57_'+suite),
            '--binary',ROOT/'build/phase59_frozen/final/phase57_check']
        if suite=='stage2':command+=['--prerequisite',out/'phase57_stage1/summary.json']
        run('phase57_'+suite,command)
    run('golden',['python3','-B','scripts/phase57_golden.py','--output',out/'golden'])
    (out/'summary.json').write_text(json.dumps(dict(PASS=True,stages=len(rows),history=rows),indent=2)+'\n')
if __name__=='__main__':main()
