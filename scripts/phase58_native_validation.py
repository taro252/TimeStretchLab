"""Serial physical-device measurements. Failures remain rows, never filtered out."""
import argparse,hashlib,json,statistics,subprocess,time
from pathlib import Path
from phase57_study import ROOT,fixture,sha,LONG_SPEEDS

def main(a):
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'inputs').mkdir()
    native=ROOT/'build/phase58_native';legacy=ROOT/'build/phase58_legacy_startup';refbin=ROOT/'build/phase58_frozen/product_reference'
    binaries={str(p.relative_to(ROOT)):sha(p) for p in (native,legacy,refbin)}
    manifest=dict(suite=a.suite,binaries=binaries,driver_source_sha256=sha(Path(__file__)),started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),inputs=[])
    rows=[]
    def save():
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
        (out/'progress.json').write_text(json.dumps(dict(cases=len(rows),passed=sum(bool(r['PASS']) for r in rows),last=rows[-1]['name'] if rows else None),indent=2)+'\n')
    def command(cmd,log,timeout=1800):
        r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=timeout);log.write_text(r.stdout+r.stderr);return r.returncode
    def source(path):
        record=dict(path=str(path),input_sha256=sha(path));
        if record not in manifest['inputs']:manifest['inputs'].append(record);save()
    def reference(path,speed,preset,folder):
        source(path);raw=folder/'reference.f32'
        assert command([refbin,path,speed,preset,raw],folder/'reference.log')==0
        ref=json.loads((folder/'reference.log').read_text());assert sha(raw)==ref['pcm_sha256'];return raw,ref
    def native_run(name,path,speed,preset,mode='normal',window=0,cpu=0,memory=0):
        folder=out/name;folder.mkdir();raw,ref=reference(path,speed,preset,folder)
        code=command([native,path,speed,preset,raw,ref['output_frames'],ref['pcm_sha256'],folder/'native',mode,window,cpu,memory],folder/'process.log')
        paths=[folder/'native'/s/'summary.json' for s in ('cold','restart')] if mode=='restart' else [folder/'native/summary.json']
        summaries=[json.loads(p.read_text()) if p.exists() else None for p in paths]
        passed=code==0 and all(s and s['PASS'] and s['pcm_prefix_exact'] and (window>0 or mode=='route' or s['pcm_complete_exact']) for s in summaries)
        if mode=='restart' and all(summaries):passed &= summaries[0]['session']!=summaries[1]['session']
        row=dict(name=name,input=str(path),speed_micros=speed,preset=preset,mode=mode,window_s=window,exit=code,reference=ref,native=summaries,PASS=bool(passed));rows.append(row);raw.unlink();save();print(name,'PASS' if passed else 'FAIL',flush=True)
    if a.suite=='startup':
        for seconds in (30,180,300):
            path=ROOT/f'results/phase54/input/mix_{seconds}s.wav'
            for preset in ('candidate','baseline'):
                group=out/f'mix_{seconds}s_{preset}';group.mkdir();raw,ref=reference(path,500000,preset,group)
                for repeat in range(5):
                    folder=group/f'repeat_{repeat+1}';folder.mkdir()
                    acode=command([legacy,path,preset,500000,folder/'legacy'],folder/'legacy.log')
                    acases=[json.loads(p.read_text()) if p.exists() else None for p in (folder/'legacy/cold.json',folder/'legacy/warm.json')]
                    for s in acases:
                        if s:
                            with raw.open('rb') as f:prefix=f.read(s['raw_published_frames']*ref['channels']*4)
                            s['published_pcm_prefix_exact']=hashlib.sha256(prefix).hexdigest()==s['raw_sha256']
                    bcode=command([native,path,500000,preset,raw,ref['output_frames'],ref['pcm_sha256'],folder/'progressive','restart',1],folder/'progressive.log')
                    bcases=[json.loads(p.read_text()) if p.exists() else None for p in (folder/'progressive/cold/summary.json',folder/'progressive/restart/summary.json')]
                    passed=acode==0 and bcode==0 and all(s and s['startup_timing_valid'] and s['published_pcm_prefix_exact'] for s in acases) and all(s and s['PASS'] and s['startup_timing_valid'] for s in bcases)
                    rows.append(dict(name=f'mix_{seconds}s_{preset}_{repeat+1}',seconds=seconds,preset=preset,legacy_exit=acode,native_exit=bcode,legacy=acases,native=bcases,PASS=bool(passed)));save();print(rows[-1]['name'],'PASS' if passed else 'FAIL',flush=True)
                raw.unlink()
        stats=[]
        for seconds in (30,180,300):
            for preset in ('candidate','baseline'):
                group=[r for r in rows if r['seconds']==seconds and r['preset']==preset]
                record=dict(seconds=seconds,preset=preset,repeats=len(group),all_cases_pass=all(r['PASS'] for r in group))
                for method in ('legacy','native'):
                    for i,state in enumerate(('cold','restart')):
                        valid=[r[method][i] for r in group if r[method][i] and r[method][i]['startup_timing_valid']]
                        keys=('first_callback_s','process_cpu_s','peak_rss_bytes')
                        for key in keys:
                            v=[s[key] for s in valid];record[f'{method}_{state}_{key}']=dict(n=len(v),median=statistics.median(v),max=max(v),population_stddev=statistics.pstdev(v)) if v else None
                        v=[s['play_to_first_callback_s'] if method=='legacy' else s['first_callback_s']-s['play_requested_s'] for s in valid]
                        record[f'{method}_{state}_play_to_callback_s']=dict(n=len(v),median=statistics.median(v),max=max(v),population_stddev=statistics.pstdev(v)) if v else None
                stats.append(record)
        (out/'statistics.json').write_text(json.dumps(stats,indent=2)+'\n')
    elif a.suite in ('lifecycle_load','lifecycle_only'):
        path=ROOT/'results/phase31/input/mix.wav'
        for preset in ('candidate','baseline'):
            native_run(f'pause_{preset}',path,1000000,preset,'pause')
            short=out/'inputs'/f'eos_{preset}.wav';fixture(short,48000,2,3,'boundary',2)
            native_run(f'eos_restart_{preset}',short,1000000,preset,'restart')
            native_run(f'route_simulated_{preset}',path,1000000,preset,'route')
            if a.suite=='lifecycle_only':continue
            for speed in LONG_SPEEDS:
                native_run(f'cpu_memory_mix30_{speed}_{preset}',ROOT/'results/phase54/input/mix_30s.wav',speed,preset,window=3,cpu=2,memory=128)
            for kind in ('silence','sustained','train','chain'):
                p=out/'inputs'/f'{kind}_{preset}.wav';fixture(p,48000,2,3,kind,4)
                native_run(f'cpu_memory_{kind}_{preset}',p,2000000,preset,cpu=2,memory=128)
    elif a.suite=='long':
        boundary=ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav';chain=ROOT/'results/phase56/long/chain_300s.wav'
        for name,path,speed,preset in [('boundary180_candidate_040',boundary,400000,'candidate'),('boundary180_baseline_200',boundary,2000000,'baseline'),('chain300_candidate_200',chain,2000000,'candidate'),('chain300_baseline_100',chain,1000000,'baseline')]:
            native_run(name,path,speed,preset)
    for p,digest in binaries.items():assert sha(ROOT/p)==digest,'Binary changed during measurement'
    summary=dict(PASS=all(r['PASS'] for r in rows),cases=len(rows),passed=sum(r['PASS'] for r in rows),failed=sum(not r['PASS'] for r in rows),sequential=True)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary,flush=True)
    return 0 if summary['PASS'] else 2
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--suite',choices=('startup','lifecycle_load','lifecycle_only','long'),required=True);p.add_argument('--output',type=Path,required=True);raise SystemExit(main(p.parse_args()))
