"""Phase59 logical-position replay against the frozen pre-change DSP."""
import argparse,csv,hashlib,json,shutil,subprocess,time
from pathlib import Path
from phase57_study import ROOT,fixture,sha,CHUNKS

PRIORITY=[(400000,410000),(410000,400000),(490000,500000),(500000,490000),
 (990000,1000000),(1000000,1010000),(1010000,1000000),(1990000,2000000),(2000000,1990000),
 (400000,2000000),(2000000,400000),(500000,1500000),(1500000,500000),(750000,1250000),(1250000,750000)]
SEQUENCES=[list(range(400000,2000001,10000)),list(range(2000000,399999,-10000)),
 [990000,1000000,1010000,1000000,990000],[490000,500000,510000,490000],
 [400000,2000000,400000],[500000,500000,1500000,400000,410000,990000,990000,405000,2010000]]

def run(args):
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    inputs=out/'inputs';inputs.mkdir();working=out/'working';working.mkdir()
    reference=args.reference.resolve();binary=args.binary.resolve()
    sources=[];cases=[]
    if args.suite=='priority':
        for rate in (44100,48000):
            for channels in (1,2):
                for encoding in (1,3):
                    path=inputs/f'boundary_{encoding}_{channels}_{rate}.wav';fixture(path,rate,channels,encoding,'boundary',3)
                    sources.append(path)
        for source in sources:
            for initial,target in PRIORITY:
                for preset in ('candidate','baseline'):
                    cases.append((source,initial,[(16384,target)],preset,CHUNKS[len(cases)%len(CHUNKS)]))
        source=ROOT/'results/phase31/input/mix.wav';sources.append(source)
        for sequence in SEQUENCES:
            for preset in ('candidate','baseline'):
                requests=[(16384+i*(2048 if len(sequence)>10 else 12288),s) for i,s in enumerate(sequence[1:])]
                cases.append((source,sequence[0],requests,preset,'irregular'))
    elif args.suite=='all161':
        source=inputs/'sustained_3_2_48000.wav';fixture(source,48000,2,3,'sustained',3);sources.append(source)
        pairs=[(s,s+10000) for s in range(400000,2000000,10000)]
        pairs += [(b,a) for a,b in pairs.copy()]
        for initial,target in pairs:
            for preset in ('candidate','baseline'):cases.append((source,initial,[(16384,target)],preset,CHUNKS[len(cases)%len(CHUNKS)]))
    elif args.suite=='materials':
        for kind in ('silence','impulse','train','sustained','boundary','chain'):
            path=inputs/f'{kind}_3_2_48000.wav';fixture(path,48000,2,3,kind,4);sources.append(path)
        sources += [ROOT/'results/phase31/input'/f'{s}.wav' for s in ('mix','drums','vocal','bass','guitar')]
        for source in sources:
            for initial,target in [(400000,2000000),(2000000,400000),(490000,500000),(990000,1010000)]:
                for preset in ('candidate','baseline'):cases.append((source,initial,[(16384,target),(18432,initial),(18432,target)],preset,CHUNKS[len(cases)%len(CHUNKS)]))
    elif args.suite=='long':
        sources=[ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav',ROOT/'results/phase56/long/chain_300s.wav']
        for source in sources:
            for sequence in ([400000,2000000,400000],[2000000,400000,2000000],[490000,500000,510000,490000],[990000,1000000,1010000,990000]):
                for preset in ('candidate','baseline'):
                    cases.append((source,sequence[0],[(32768+i*98304,s) for i,s in enumerate(sequence[1:])],preset,'131072'))
    else:raise ValueError(args.suite)
    manifest=dict(suite=args.suite,reference=str(reference),reference_sha256=sha(reference),binary=str(binary),binary_sha256=sha(binary),
        inputs=[dict(path=str(p),sha256=sha(p)) for p in sources],planned_cases=len(cases),chunks=CHUNKS,
        comparison='同一論理要求・Frontier・適用境界。全Float32生ビット、出力数、計画・密度・全Map node',
        storage_budget=json.loads((ROOT/'results/phase59/START_STATE.json').read_text())['storage_budget_bytes'])
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    successes=0;failures=0;initials=set();targets=set();pairs=set();applied=0;status_counts={}
    with (out/'rows.jsonl').open('x') as rows:
        for index,(source,initial,requests,preset,chunk) in enumerate(cases):
            if shutil.disk_usage(ROOT).free<manifest['storage_budget']['minimum_free']:raise RuntimeError('Disk budget floor reached')
            name=f'case_{index:05d}';folder=out/name;folder.mkdir();schedule=folder/'requests.csv'
            schedule.write_text('at_output,target_micros\n'+''.join(f'{at},{s}\n' for at,s in requests))
            raw=working/'reference.f32';ref=folder/'reference';actual=folder/'actual'
            command=[str(reference),str(source),str(initial),preset,str(schedule),str(raw),str(ref)]
            start=time.monotonic();a=subprocess.run(command,capture_output=True,text=True,timeout=1800)
            (folder/'reference.log').write_text(a.stdout+a.stderr)
            row=dict(index=index,input=str(source),input_sha256=sha(source),initial_speed=initial,requests=requests,preset=preset,chunk=chunk,
                reference_exit=a.returncode,reference_command=command)
            if a.returncode==0:
                summary=json.loads(ref.with_suffix('.json').read_text());row['reference']=summary
                row['reference_pcm_bytes']=raw.stat().st_size
                if row['reference_pcm_bytes']>manifest['storage_budget']['raw_pcm_working']:raise RuntimeError('PCM budget exceeded')
                assert sha(raw)==summary['pcm_sha256']
                command=[str(binary),str(source),str(initial),preset,str(schedule),str(raw),str(ref),str(actual),chunk]
                b=subprocess.run(command,capture_output=True,text=True,timeout=1800);(folder/'actual.log').write_text(b.stdout+b.stderr)
                row.update(actual_exit=b.returncode,actual_command=command,PASS=b.returncode==0)
                if b.returncode==0:
                    row['actual']=json.loads(actual.with_suffix('.json').read_text());assert row['actual']['pcm_sha256']==summary['pcm_sha256']
                    successes+=1;initials.add(initial)
                    for _,target in requests:
                        if 400000<=target<=2000000 and target%10000==0:targets.add(target);pairs.add((initial,target))
                    with Path(str(actual)+'.operations.csv').open() as file:
                        for op in csv.DictReader(file):
                            state=op['status'];status_counts[state]=status_counts.get(state,0)+1
                            applied+=state in ('Completed','Applied')
                else:failures+=1
            else:
                row['PASS']=False;failures+=1
            row['wall_s']=time.monotonic()-start;row['disk_free_bytes']=shutil.disk_usage(ROOT).free
            row['case_artifact_bytes']=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
            rows.write(json.dumps(row,ensure_ascii=False)+'\n');rows.flush()
            # Reuse a single success reference workspace. On failure it is kept
            # intact together with the recipe, SHA, plan and first mismatch.
            if not row['PASS']:
                (out/'failure.json').write_text(json.dumps(row,indent=2,ensure_ascii=False)+'\n');raise RuntimeError(f'Case {index} failed; evidence retained: {folder}')
            if index%20==0:print(args.suite,index+1,'/',len(cases),'PASS',flush=True)
            (out/'progress.json').write_text(json.dumps(dict(completed=index+1,total=len(cases),successes=successes,failures=failures))+'\n')
    assert sha(binary)==manifest['binary_sha256'] and sha(reference)==manifest['reference_sha256']
    result=dict(PASS=failures==0,pcm_sessions=successes,failures=failures,applied_operations=applied,status_counts=status_counts,
        initial_speeds=sorted(initials),target_speeds=sorted(targets),unique_initial_target_pairs=len(pairs),all_25921_pairs_tested=len(pairs)==25921,
        retained_bytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file()),workspace_pcm_bytes=(working/'reference.f32').stat().st_size)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--suite',choices=['priority','all161','materials','long'],required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--reference',type=Path,default=ROOT/'build/phase59_frozen/dynamic_reference')
    parser.add_argument('--binary',type=Path,default=ROOT/'build/phase59_check');run(parser.parse_args())
