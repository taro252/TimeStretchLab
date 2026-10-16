"""Freeze the candidate, then run the ordered logical and progressive quality gates."""
import json,shutil,subprocess,time
from pathlib import Path
from phase57_study import ROOT,sha

def main():
    out=ROOT/'results/phase59/quality_final';out.mkdir(exist_ok=False);history=[]
    def run(name,command):
        started=time.time()
        with (out/(name+'.log')).open('x') as log:p=subprocess.run(list(map(str,command)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        history.append(dict(name=name,command=list(map(str,command)),exit=p.returncode,wall_s=time.time()-started))
        (out/'driver.json').write_text(json.dumps(history,indent=2)+'\n');print(name,p.returncode,flush=True)
        if p.returncode:raise RuntimeError('Quality gate failed: '+name)
    run('release_all_build',['cmake','--build','build','-j3'])
    run('phase59_ctest',['ctest','--test-dir','build','-R','^phase59_','--output-on-failure','-j1'])
    frozen=ROOT/'build/phase59_frozen/final';frozen.mkdir(exist_ok=False)
    names=['phase59_native','phase59_check','phase59_progressive_replay','phase58_native','phase58_check','phase57_check','phase54_native']
    for name in names:shutil.copy2(ROOT/'build'/name,frozen/name)
    sources={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*') if p.is_file()}
    manifest=dict(binary_sha256={n:sha(frozen/n) for n in names},source_sha256=sources,
        build_settings={n:(ROOT/'build'/n).read_text() for n in ['CMakeFiles/phase59_native.dir/flags.make','CMakeFiles/phase59_native.dir/link.txt','CMakeCache.txt']})
    (ROOT/'results/phase59/FINAL_CANDIDATE.json').write_text(json.dumps(manifest,indent=2)+'\n')
    for suite in ('priority','all161','materials','long'):
        run(suite,['python3','-B','scripts/phase59_study.py','--suite',suite,'--binary',frozen/'phase59_check','--output',out/suite])
    for suite in ('chunks','formats'):
        run('incremental_'+suite,['python3','-B','scripts/phase59_incremental_study.py','--suite',suite,'--binary',frozen/'phase59_progressive_replay','--output',out/('incremental_'+suite)])
    assert all(sha(ROOT/p)==h for p,h in sources.items()),'Candidate source changed during quality gates'
    assert all(sha(frozen/n)==h for n,h in manifest['binary_sha256'].items())
    (out/'summary.json').write_text(json.dumps(dict(PASS=True,stages=len(history),history=history),indent=2)+'\n')
if __name__=='__main__':main()
