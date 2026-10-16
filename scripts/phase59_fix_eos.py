"""EOS→別入力の新規Playを、周期付き/高速排出/通常優先度で区別する。"""
import argparse
import collections
import csv
import json
import shutil
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT,sha


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--tag',required=True)
    parser.add_argument('--release',type=Path,default=ROOT/'build/phase59_fix_eos_probe')
    parser.add_argument('--debug',type=Path);args=parser.parse_args()
    out=ROOT/'results/phase59_fix'/('eos_'+args.tag);out.mkdir()
    data=ROOT/'build/phase59_fix_artifacts'/('eos_'+args.tag);data.mkdir()
    binaries={'release':args.release.resolve()}
    if args.debug:binaries['debug']=args.debug.resolve()
    for label,p in list(binaries.items()):
        copy=data/(label+'_probe');shutil.copy2(p,copy);binaries[label]=copy
    sources=[ROOT/'results/phase31/input/mix.wav',ROOT/'results/phase31/input/drums.wav']
    manifest=dict(inputs=[dict(path=str(p),sha256=sha(p)) for p in sources],
        binaries={k:dict(path=str(p),sha256=sha(p)) for k,p in binaries.items()},
        driver_sha256=sha(Path(__file__)),probe_source_sha256=sha(ROOT/'tests/Phase59FixEOSProbe.cpp'),
        scope='実機callbackを持たない寿命・排出の診断。周期付きもavailable分だけ排出するため、実機供給の合格とは別。pth_run_state=1は標本時の実行可能状態で、連続したCPU実行の証明ではない。',
        modes={'paced':dict(initial=2000000,timeout=30),'unpaced':dict(initial=500000,timeout=20),'normal':dict(initial=500000,timeout=30)})
    manifest['source_sha256']={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*') if p.is_file()}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');rows=[]
    for label,binary in binaries.items():
        for mode,parameters in manifest['modes'].items():
            if shutil.disk_usage(ROOT).free<2*1024**3:raise RuntimeError('Disk floor reached')
            folder=data/(label+'_'+mode)
            command=[str(binary),*map(str,sources),str(folder),mode,str(parameters['initial']),str(parameters['timeout'])]
            start=time.time()
            with (data/(folder.name+'.log')).open('x') as log:p=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=100)
            sessions=list(csv.DictReader((folder/'summary.csv').open())) if (folder/'summary.csv').exists() else []
            analyzed=[]
            for session in sessions:
                run=session['run'];workers=list(csv.DictReader((folder/('worker_'+run+'.csv')).open()))
                samples=list(csv.DictReader((folder/('thread_samples_'+run+'.csv')).open()))
                realtime=[r for r in workers if r['realtime']=='1']
                worst=sorted(realtime,key=lambda r:float(r['wall_s'])-float(r['cpu_s']),reverse=True)[:5]
                for block in worst:
                    begin=float(block['start_s']);end=begin+float(block['wall_s'])
                    known=[s for s in samples if s['result']=='0' and float(s['before_s'])>=begin and float(s['after_s'])<=end]
                    block['non_cpu_s']=max(0,float(block['wall_s'])-float(block['cpu_s']))
                    block['sampled_run_states']=dict(collections.Counter(s['state'] for s in known))
                    block['sampled_policy_priority']=dict(collections.Counter(s['policy']+':'+s['priority'] for s in known))
                analyzed.append(dict(summary=session,realtime_blocks=len(realtime),worst_non_cpu_blocks=worst))
            row=dict(build=label,mode=mode,command=command,exit=p.returncode,wall_s=time.time()-start,sessions=analyzed,
                     functional_pass=p.returncode==0 and len(sessions)==2,
                     interval_deadline_pass=len(sessions)==2 and all(s['deadline_misses']=='0' for s in sessions),
                     realtime_cpp_new_pass=len(sessions)==2 and all(s['rt_new_measured']=='1' and s['rt_new']=='0' for s in sessions))
            row['artifacts']=[dict(path=str(f),bytes=f.stat().st_size,sha256=sha(f)) for f in folder.rglob('*') if f.is_file()]
            rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
            print(label,mode,p.returncode,'deadlines',[s['deadline_misses'] for s in sessions],flush=True)
    assert all(sha(ROOT/p)==digest for p,digest in manifest['source_sha256'].items()),'Source changed during EOS comparison'
    (out/'summary.json').write_text(json.dumps(dict(functional_pass=all(r['functional_pass'] for r in rows),
        release_paced_pass=all(r['functional_pass'] and r['interval_deadline_pass'] and r['realtime_cpp_new_pass'] for r in rows if r['build']=='release' and r['mode']=='paced'),
        modes=rows,actual_audio_callback_verified=False),indent=2)+'\n')


if __name__=='__main__':main()
