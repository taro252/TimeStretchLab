"""Partition unchanged Phase57 correctness cases; join the Phase58 checkpoint."""
import argparse,concurrent.futures,json,os,signal,subprocess,sys,time
from pathlib import Path
from phase57_study import ROOT,sha

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sequential-driver-pid',type=int,required=True);a=parser.parse_args()
    out=ROOT/'results/phase59/regression_parallel57';out.mkdir(exist_ok=False);drivers=out/'driver_sources';drivers.mkdir()
    original=ROOT/'scripts/phase57_study.py';source=original.read_text();history=[]
    binary=ROOT/'build/phase59_frozen/final/phase57_check'
    formats=[(r,c,e) for r in (44100,48000) for c in (1,2) for e in (1,3)]
    assignment="formats=[(48000,2,3)] if args.suite=='smoke' else [(r,c,e) for r in (44100,48000) for c in (1,2) for e in (1,3)]"
    assert source.count(assignment)==1
    def worker(suite,selection):
        label='_'.join(map(str,selection)) if isinstance(selection,tuple) else selection
        text=source
        if isinstance(selection,tuple):text=text.replace(assignment,'formats='+repr([selection]))
        elif selection!='all':
            marker='    speeds=list(range';assert text.count(marker)==1
            text=text.replace(marker,"    sources=[s for s in sources if s['name']=="+repr(selection)+"]\n"+marker)
        # The original script imports its ROOT from phase55_study.
        text='import sys\nsys.path.insert(0,'+repr(str(ROOT/'scripts'))+')\n'+text
        driver=drivers/(suite+'_'+label+'.py');driver.write_text(text)
        folder=out/suite/label
        command=[sys.executable,'-B',str(driver),'--suite',suite,'--output',str(folder),'--binary',str(binary)]
        if suite=='stage2':command+=['--prerequisite',str(out/'stage1/summary.json')]
        start=time.time()
        with (out/suite/(label+'.log')).open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        return dict(selection=selection,command=command,driver_sha256=sha(driver),exit=p.returncode,wall_s=time.time()-start,
            result=json.loads((folder/'summary.json').read_text()) if (folder/'summary.json').exists() else None)
    for suite,selections,parallelism in [('stage1',formats,4),('stage2',formats,4),('long',['boundary_180s','chain_300s'],1),
            ('natural',['mix','drums','vocal','bass','guitar'],4),('rejections',['all'],1)]:
        (out/suite).mkdir();rows=[]
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as pool:
            futures=[pool.submit(worker,suite,selection) for selection in selections]
            for future in concurrent.futures.as_completed(futures):
                rows.append(future.result());(out/suite/'partitions.json').write_text(json.dumps(rows,indent=2)+'\n')
                print(suite,len(rows),'/',len(selections),rows[-1]['exit'],flush=True)
        result=dict(PASS=all(r['exit']==0 and r['result'] and r['result']['PASS'] for r in rows),
            cases=sum(r['result']['cases'] for r in rows if r['result']),pcm_sessions=sum(r['result']['pcm_sessions'] for r in rows if r['result']),
            matched_rejections=sum(r['result']['matched_rejections'] for r in rows if r['result']),partitions=len(rows),parallelism=parallelism,
            original_driver_sha256=sha(original),binary_sha256=sha(binary),partition_manifest=str(out/suite/'partitions.json'))
        (out/suite/'summary.json').write_text(json.dumps(result,indent=2)+'\n');assert result['PASS'],suite
        history.append(dict(name='phase57_'+suite,exit=0,result=result))
    assert sum(r['result']['pcm_sessions'] for r in history)==51344
    with (out/'golden.log').open('x') as log:p=subprocess.run([sys.executable,'-B','scripts/phase57_golden.py','--output',str(out/'golden')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    assert p.returncode==0
    (out/'summary.json').write_text(json.dumps(dict(PASS=True,history=history,original_driver_unchanged=sha(original)==history[0]['result']['original_driver_sha256']),indent=2)+'\n')
    # The old driver has already completed CTest + Phase58 short/all161. Let its
    # current long suite finish, then stop only this task's redundant follow-on.
    fixed=ROOT/'results/phase59/regression_final';checkpoint=fixed/'phase58_long/summary.json'
    while not checkpoint.exists():time.sleep(2)
    assert json.loads(checkpoint.read_text())['PASS']
    if (fixed/'summary.json').exists():return
    command=subprocess.check_output(['ps','-p',str(a.sequential_driver_pid),'-o','command='],text=True).strip()
    assert command.endswith(' -B scripts/phase59_regression_validation.py'),command
    os.kill(a.sequential_driver_pid,signal.SIGSTOP)
    stopped={a.sequential_driver_pid};descendants=[]
    for _ in range(3):
        table=subprocess.check_output(['ps','-axo','pid=,ppid=,comm='],text=True)
        rows=[line.split(None,2) for line in table.splitlines() if len(line.split(None,2))==3]
        fresh=[(int(pid),int(parent),name) for pid,parent,name in rows if int(parent) in stopped and int(pid) not in stopped]
        if not fresh:break
        for pid,parent,name in fresh:
            try:os.kill(pid,signal.SIGSTOP);stopped.add(pid);descendants.append(dict(pid=pid,parent=parent,name=name))
            except ProcessLookupError:pass
    for pid in reversed(list(stopped)):
        try:os.kill(pid,signal.SIGKILL)
        except ProcessLookupError:pass
    (out/'checkpoint_handoff.json').write_text(json.dumps(dict(checkpoint=str(checkpoint),stopped_parent=a.sequential_driver_pid,
        descendants=descendants,reason='Phase58長尺完了を保持し、既に同一条件で完了したPhase57並列検証へ引継ぎ。途中の重複試験は合格件数に含めない。'),indent=2,ensure_ascii=False)+'\n')
    for suite in ['stage1','stage2','long','natural','rejections']:
        destination=fixed/('phase57_'+suite);destination.mkdir(exist_ok=True)
        if (destination/'summary.json').exists():
            existing=json.loads((destination/'summary.json').read_text());parallel=json.loads((out/suite/'summary.json').read_text())
            assert existing['PASS'] and all(existing[k]==parallel[k] for k in ['cases','pcm_sessions','matched_rejections'])
        else:(destination/'summary.json').write_bytes((out/suite/'summary.json').read_bytes())
    destination=fixed/'golden';destination.mkdir(exist_ok=True)
    if not (destination/'summary.json').exists():(destination/'summary.json').write_bytes((out/'golden/summary.json').read_bytes())
    previous=json.loads((fixed/'driver.json').read_text())
    (fixed/'summary.json').write_text(json.dumps(dict(PASS=True,history=previous+history+[dict(name='golden',exit=0)],
        parallel_validation=str(out/'summary.json'),checkpoint_handoff=str(out/'checkpoint_handoff.json'),
        performance_claim=False),indent=2)+'\n');print('regression checkpoint complete',flush=True)
if __name__=='__main__':main()
