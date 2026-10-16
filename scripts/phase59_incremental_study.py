"""Certified-prefix replay: compare actual applied plans, preserving analysis deferrals."""
import argparse,csv,json,shutil,subprocess,time
from pathlib import Path
from phase57_study import ROOT,CHUNKS,fixture,sha
from phase59_native_validation import compare_pcm

def run(args):
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'working').mkdir();(out/'inputs').mkdir()
    binary=args.binary.resolve();reference=ROOT/'build/phase59_frozen/captured_reference';cases=[];sources=[]
    patterns=[(400000,[2000000,400000]),(490000,[500000,490000]),(990000,[1000000,1010000,990000]),(500000,[1500000,400000,990000])]
    if args.suite=='chunks':
        sources=[ROOT/'results/phase31/input'/f'{name}.wav' for name in ('mix','drums')]
        for source in sources:
            for initial,targets in patterns:
                for preset in ('candidate','baseline'):
                    for chunk in CHUNKS:cases.append((source,initial,targets,preset,chunk))
    else:
        for rate in (44100,48000):
            for channels in (1,2):
                for encoding in (1,3):
                    source=out/'inputs'/f'boundary_{encoding}_{channels}_{rate}.wav';fixture(source,rate,channels,encoding,'boundary',4);sources.append(source)
                    for initial,targets in patterns[1:3]:
                        for preset in ('candidate','baseline'):cases.append((source,initial,targets,preset,CHUNKS[len(cases)%len(CHUNKS)]))
    manifest=dict(suite=args.suite,binary=str(binary),binary_sha256=sha(binary),reference=str(reference),reference_sha256=sha(reference),inputs=[dict(path=str(s),sha256=sha(s)) for s in sources],cases=len(cases),
        scope='未来解析不足は保留し、実際の適用Frontier/計画を変更前の全曲解析＋動的Phase39へ再現。元の完成解析の予定境界と違うPCMを同一と判定しない。')
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n');rows=[]
    for index,(source,initial,targets,preset,chunk) in enumerate(cases):
        if shutil.disk_usage(ROOT).free<4*1024**3:raise RuntimeError('Disk floor')
        folder=out/f'case_{index:04d}';folder.mkdir();requests=folder/'requests.csv';requests.write_text('at_output,target_micros\n'+''.join(f'{16384+i*49152},{target}\n' for i,target in enumerate(targets)))
        actual=out/'working/actual.f32';expected=out/'working/reference.f32';start=time.monotonic()
        command=[str(binary),str(source),str(initial),preset,str(requests),str(actual),str(folder/'actual'),chunk]
        p=subprocess.run(command,capture_output=True,text=True,timeout=1800);(folder/'actual.log').write_text(p.stdout+p.stderr)
        row=dict(index=index,input=str(source),initial_speed=initial,target_speeds=targets,preset=preset,chunk=chunk,command=command,actual_exit=p.returncode)
        if p.returncode==0:
            row['actual']=json.loads((folder/'actual/summary.json').read_text());command=[str(reference),str(source),str(initial),preset,str(folder/'actual'),str(expected),str(folder/'reference')]
            ref=subprocess.run(command,capture_output=True,text=True,timeout=1800);(folder/'reference.log').write_text(ref.stdout+ref.stderr);row.update(reference_exit=ref.returncode,reference_command=command)
            if ref.returncode==0:
                row['reference']=json.loads((folder/'reference.json').read_text());row['pcm']=compare_pcm(actual,expected,0,expected.stat().st_size,row['actual']['channels'],True,folder)
                row['map_exact']=(folder/'actual/dynamic_map.nodes.bin').read_bytes()==(folder/'reference.nodes.bin').read_bytes()
                row['PASS']=row['pcm']['PASS'] and row['map_exact'] and row['reference']['frontiers_exact'] and row['actual']['pcm_sha256']==row['reference']['pcm_sha256']
                row['analysis_deferral_scope']='B: actual deferred boundary replay' if row['actual']['analysis_deferrals'] else 'A: no planning deferral'
        row.setdefault('PASS',False);row['wall_s']=time.monotonic()-start;row['working_bytes']=sum(p.stat().st_size for p in (out/'working').rglob('*') if p.is_file());assert row['working_bytes']<=512*1024**2
        rows.append(row)
        with (out/'rows.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        if not row['PASS']:
            if actual.exists():shutil.copy2(actual,folder/'failure_actual.f32')
            if expected.exists():shutil.copy2(expected,folder/'failure_reference.f32')
            raise RuntimeError(f'Incremental replay mismatch: {folder}')
        if index%10==0:print(args.suite,index+1,'/',len(cases),'PASS',flush=True)
        (out/'progress.json').write_text(json.dumps(dict(completed=index+1,total=len(cases)))+'\n')
    assert sha(binary)==manifest['binary_sha256'] and sha(reference)==manifest['reference_sha256']
    result=dict(PASS=all(r['PASS'] for r in rows),pcm_sessions=len(rows),deferral_sessions=sum(bool(r['actual']['analysis_deferrals']) for r in rows),
        nonfinal_pcm_sessions=sum(r['actual']['nonfinal_pcm_frames']>0 for r in rows),nonfinal_plan_sessions=sum(r['actual']['nonfinal_plans']>0 for r in rows),
        analysis_deferrals=sum(r['actual']['analysis_deferrals'] for r in rows),nonfinal_plans=sum(r['actual']['nonfinal_plans'] for r in rows),chunks=sorted(set(r['chunk'] for r in rows)),
        retained_bytes=sum(p.stat().st_size for p in out.rglob('*') if p.is_file()))
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--suite',choices=['chunks','formats'],required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--binary',type=Path,default=ROOT/'build/phase59_progressive_replay');run(p.parse_args())
