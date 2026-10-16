"""Complete two independent long inputs concurrently, then join all evidence."""
import concurrent.futures,json,os,signal,subprocess,sys,time
from pathlib import Path
from phase57_study import ROOT,sha

def main():
    out=ROOT/'results/phase59/regression_completion';out.mkdir(exist_ok=False);drivers=out/'driver_sources';drivers.mkdir()
    previous=ROOT/'results/phase59/regression_parallel57';fixed=ROOT/'results/phase59/regression_final'
    assert json.loads((fixed/'phase58_long/summary.json').read_text())['PASS']
    assert all(json.loads((previous/s/'summary.json').read_text())['PASS'] for s in ['stage1','stage2'])
    source=(ROOT/'scripts/phase57_study.py').read_text();binary=ROOT/'build/phase59_frozen/final/phase57_check'
    def run(suite,selection,folder):
        text=source
        if selection!='all':
            marker='    speeds=list(range';assert text.count(marker)==1
            text=text.replace(marker,"    sources=[s for s in sources if s['name']=="+repr(selection)+"]\n"+marker)
        text='import sys\nsys.path.insert(0,'+repr(str(ROOT/'scripts'))+')\n'+text
        script=drivers/(suite+'_'+selection+'.py');script.write_text(text)
        command=[sys.executable,'-B',str(script),'--suite',suite,'--output',str(folder),'--binary',str(binary)]
        start=time.time()
        with (out/(suite+'_'+selection+'.log')).open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        result=json.loads((folder/'summary.json').read_text()) if (folder/'summary.json').exists() else None
        row=dict(selection=selection,command=command,exit=p.returncode,wall_s=time.time()-start,driver_sha256=sha(script),result=result)
        assert p.returncode==0 and result and result['PASS'],row
        return row
    # The existing boundary child is independent of its paused coordinator.
    chain=run('long','chain_300s',previous/'long/chain_300s')
    boundary=previous/'long/boundary_180s/summary.json'
    while not boundary.exists():
        state=subprocess.check_output(['ps','-p','32908','-o','stat='],text=True).strip()
        if state.startswith('Z'):raise RuntimeError('Boundary child ended without a complete summary')
        time.sleep(2)
    assert json.loads(boundary.read_text())['PASS']
    boundary_row=dict(selection='boundary_180s',exit=0,result=json.loads(boundary.read_text()),
        command=json.loads((previous/'long_parallel_handoff.json').read_text())['continuing_children'][0]['command'],
        driver_sha256=sha(previous/'driver_sources/long_boundary_180s.py'))
    def aggregate(suite,rows,directory):
        directory.mkdir(exist_ok=True)
        (directory/'partitions.json').write_text(json.dumps(rows,indent=2)+'\n')
        summary=dict(PASS=all(r['result']['PASS'] and r['exit']==0 for r in rows),
            cases=sum(r['result']['cases'] for r in rows),pcm_sessions=sum(r['result']['pcm_sessions'] for r in rows),
            matched_rejections=sum(r['result']['matched_rejections'] for r in rows),partitions=len(rows),
            partition_manifest=str(directory/'partitions.json'),original_driver_sha256=sha(ROOT/'scripts/phase57_study.py'),binary_sha256=sha(binary))
        (directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(suite,summary['pcm_sessions'],'PASS',flush=True)
        return summary
    long=aggregate('long',[boundary_row,chain],previous/'long')
    history=[dict(name='phase57_'+s,exit=0,result=json.loads((previous/s/'summary.json').read_text())) for s in ['stage1','stage2']]
    history.append(dict(name='phase57_long',exit=0,result=long))
    for suite,selections,workers in [('natural',['mix','drums','vocal','bass','guitar'],4),('rejections',['all'],1)]:
        (out/suite).mkdir()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            rows=list(pool.map(lambda name:run(suite,name,out/suite/name),selections))
        summary=aggregate(suite,rows,out/suite);history.append(dict(name='phase57_'+suite,exit=0,result=summary))
    assert sum(r['result']['pcm_sessions'] for r in history)==51344
    with (out/'golden.log').open('x') as log:p=subprocess.run([sys.executable,'-B','scripts/phase57_golden.py','--output',str(out/'golden')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    assert p.returncode==0
    golden=json.loads((out/'golden/summary.json').read_text());assert len(golden)==25 and all(r['PASS'] for r in golden)
    killed=[]
    for pid,suffix in [(93149,' -B scripts/phase59_parallel57_validation.py --sequential-driver-pid 67299'),(67299,' -B scripts/phase59_regression_validation.py')]:
        command=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True).strip();assert command.endswith(suffix),command
        os.kill(pid,signal.SIGKILL);killed.append(dict(pid=pid,command=command))
    (out/'handoff.json').write_text(json.dumps(dict(stopped_coordinators=killed,children_completed=True,reason='重複する未開始段階だけを破棄し、終了済みの全検証証拠を合流。'),indent=2,ensure_ascii=False)+'\n')
    for suite in ['stage1','stage2','long','natural','rejections']:
        source_summary=(previous if suite in ['stage1','stage2','long'] else out)/suite/'summary.json'
        destination=fixed/('phase57_'+suite);destination.mkdir(exist_ok=True);assert not (destination/'summary.json').exists()
        (destination/'summary.json').write_bytes(source_summary.read_bytes())
    destination=fixed/'golden';destination.mkdir();(destination/'summary.json').write_bytes((out/'golden/summary.json').read_bytes())
    summary=dict(PASS=True,history=json.loads((fixed/'driver.json').read_text())+[dict(name='phase58_long',exit=0,checkpoint=str(fixed/'phase58_long/summary.json'))]+history+[dict(name='golden',exit=0)],
        completion_manifest=str(out/'summary.json'),handoff=str(out/'handoff.json'),performance_claim=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(fixed/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('All regression PCM and Golden PASS; audio may start',flush=True)
if __name__=='__main__':main()
