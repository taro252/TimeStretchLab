"""Serial device trials for the explicit Phase58 Fix worker; retain every failure."""
import argparse
import datetime
import hashlib
import json
import statistics
import subprocess
import time
from pathlib import Path
from phase57_study import ROOT, fixture, sha

SPEEDS = (400000,410000,500000,750000,990000,1000000,1010000,1250000,1500000,1990000,2000000)
FLAGS = ('--worker=workgroup','--resident-input=on','--profile=block','--sample-thread=on')

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def main(a):
    out=a.output.resolve(); out.mkdir(parents=True,exist_ok=False); (out/'inputs').mkdir()
    native=a.binary.resolve(); original=ROOT/'build/phase58_fix_frozen/phase58_native'
    legacy=ROOT/'build/phase58_fix_frozen/legacy_startup'; refbin=ROOT/'build/phase58_frozen/product_reference'
    used=(native,refbin,original,legacy) if a.suite=='startup' else (native,refbin)
    binaries={str(p):sha(p) for p in used}
    manifest=dict(suite=a.suite,binaries=binaries,driver_sha256=sha(Path(__file__)),start_utc=utc(),
                  inputs=[],expected_device=72,expected_rate=48000,expected_buffer=512,
                  speeds_micros=SPEEDS,flags=FLAGS,independent_process_per_case=True,
                  head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  cold_definition='fresh process; OS filesystem cache is not flushed',
                  rss_scope='process lifetime peak, including preloaded verification reference',
                  memory_pressure_scope='bounded process allocation; not system-wide pressure')
    rows=[]
    def save():
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n')
        s=dict(PASS=all(r['PASS'] for r in rows),cases=len(rows),passed=sum(r['PASS'] for r in rows),
               failed=sum(not r['PASS'] for r in rows),sequential=True,last=rows[-1]['name'] if rows else None)
        (out/'progress.json').write_text(json.dumps(s,indent=2)+'\n'); return s
    def command(cmd,log,timeout=1800):
        record=dict(command=list(map(str,cmd)),start_utc=utc()); start=time.monotonic()
        try:
            r=subprocess.run(record['command'],capture_output=True,text=True,timeout=timeout)
            log.write_text(r.stdout+r.stderr); record['exit']=r.returncode
        except subprocess.TimeoutExpired as e:
            log.write_text(str(e.stdout)+str(e.stderr)); record.update(exit=None,timeout=True)
        record.update(end_utc=utc(),elapsed_s=time.monotonic()-start)
        log.with_suffix('.command.json').write_text(json.dumps(record,indent=2)+'\n')
        return record['exit']
    def reference(path,speed,preset,folder):
        record=dict(path=str(path),input_sha256=sha(path),input_bytes=path.stat().st_size)
        if record not in manifest['inputs']: manifest['inputs'].append(record); save()
        raw=folder/'reference.f32'
        code=command([refbin,path,speed,preset,raw],folder/'reference.log')
        if code: raise RuntimeError('Independent reference failed: '+str(folder))
        ref=json.loads((folder/'reference.log').read_text()); assert sha(raw)==ref['pcm_sha256']
        return raw,ref
    def valid(s,fix=True):
        return bool(s and s['device_id']==72 and s['device_rate']==48000 and s['device_buffer_frames']==512
                    and (not fix or s.get('workgroup_enabled') and s.get('input_samples_prevalidated')))
    def native_run(name,path,speed,preset,mode='normal',window=0,cpu=0,memory=0):
        folder=out/name; folder.mkdir(); raw,ref=reference(path,speed,preset,folder)
        code=command([native,path,speed,preset,raw,ref['output_frames'],ref['pcm_sha256'],folder/'native',
                      mode,window,cpu,memory,0,0,*FLAGS],folder/'process.log')
        paths=[folder/'native'/s/'summary.json' for s in ('cold','restart')] if mode=='restart' else [folder/'native/summary.json']
        summaries=[json.loads(p.read_text()) if p.exists() else None for p in paths]
        conditions=all(valid(s) for s in summaries)
        passed=code==0 and conditions and all(s and s['PASS'] and s['pcm_prefix_exact'] and
                     (window>0 or mode=='route' or s['pcm_complete_exact']) for s in summaries)
        if mode=='restart' and all(summaries): passed &= summaries[0]['session']!=summaries[1]['session']
        row=dict(name=name,input=str(path),speed_micros=speed,preset=preset,mode=mode,window_s=window,
                 cpu_load_threads=cpu,memory_load_mib=memory,exit=code,reference=ref,native=summaries,
                 conditions_valid=conditions,PASS=bool(passed))
        rows.append(row); raw.unlink(); save(); print(name,'PASS' if passed else 'FAIL',flush=True)
    if a.suite=='grid':
        for rate in (44100,48000):
            for channels in (1,2):
                for encoding in (1,3):
                    p=out/'inputs'/f'boundary_{encoding}_{channels}_{rate}.wav'; fixture(p,rate,channels,encoding,'boundary',4)
                    for speed in (400000,1000000,2000000):
                        for preset in ('candidate','baseline'): native_run(f'{p.stem}_{speed}_{preset}',p,speed,preset)
        for kind in ('silence','impulse','train','sustained','chain'):
            p=out/'inputs'/f'{kind}.wav'; fixture(p,48000,2,3,kind,4)
            for preset in ('candidate','baseline'): native_run(f'{kind}_{preset}',p,2000000,preset)
        for kind in ('mix','drums','vocal','bass','guitar'):
            for preset in ('candidate','baseline'):
                native_run(f'natural_{kind}_{preset}',ROOT/f'results/phase31/input/{kind}.wav',2000000,preset)
        for speed in SPEEDS:
            for preset in ('candidate','baseline'):
                native_run(f'mix30_{speed}_{preset}',ROOT/'results/phase54/input/mix_30s.wav',speed,preset,window=3)
    elif a.suite=='lifecycle_load':
        path=ROOT/'results/phase31/input/mix.wav'
        for preset in ('candidate','baseline'):
            native_run(f'pause_{preset}',path,1000000,preset,'pause')
            short=out/'inputs'/f'eos_{preset}.wav'; fixture(short,48000,2,3,'boundary',2)
            native_run(f'eos_restart_{preset}',short,1000000,preset,'restart')
            native_run(f'route_simulated_{preset}',path,1000000,preset,'route')
            for speed in SPEEDS:
                native_run(f'cpu_memory_mix30_{speed}_{preset}',ROOT/'results/phase54/input/mix_30s.wav',speed,preset,window=3,cpu=2,memory=128)
            native_run(f'memory512_{preset}',path,2000000,preset,memory=512)
    elif a.suite=='long':
        boundary=ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav'; chain=ROOT/'results/phase56/long/chain_300s.wav'
        for name,path,speed,preset in [('boundary180_candidate_040',boundary,400000,'candidate'),
                ('boundary180_baseline_200',boundary,2000000,'baseline'),
                ('chain300_candidate_200',chain,2000000,'candidate'),('chain300_baseline_100',chain,1000000,'baseline')]:
            native_run(name,path,speed,preset)
    elif a.suite=='startup':
        for seconds in (30,180,300):
            path=ROOT/f'results/phase54/input/mix_{seconds}s.wav'
            for preset in ('candidate','baseline'):
                group=out/f'mix_{seconds}s_{preset}'; group.mkdir(); raw,ref=reference(path,500000,preset,group)
                for repeat in range(a.repeats):
                    folder=group/f'repeat_{repeat:02}'; folder.mkdir(); summaries={}; exits={}
                    exits['legacy']=command([legacy,path,preset,500000,folder/'legacy'],folder/'legacy.log')
                    summaries['legacy']=[json.loads(p.read_text()) if p.exists() else None for p in (folder/'legacy/cold.json',folder/'legacy/warm.json')]
                    for s in summaries['legacy']:
                        if s:
                            with raw.open('rb') as f: prefix=f.read(s['raw_published_frames']*ref['channels']*4)
                            s['published_pcm_prefix_exact']=hashlib.sha256(prefix).hexdigest()==s['raw_sha256']
                    for method,binary,flags in (('original',original,()),('fix',native,FLAGS)):
                        exits[method]=command([binary,path,500000,preset,raw,ref['output_frames'],ref['pcm_sha256'],
                            folder/method,'restart',1,0,0,0,0,*flags],folder/(method+'.log'))
                        summaries[method]=[json.loads(p.read_text()) if p.exists() else None for p in
                            (folder/method/'cold/summary.json',folder/method/'restart/summary.json')]
                    passed=all(e==0 for e in exits.values()) and all(s and valid(s,False) and s['startup_timing_valid'] and s['published_pcm_prefix_exact'] for s in summaries['legacy'])
                    passed &= all(s and valid(s,method=='fix') and s['PASS'] and s['startup_timing_valid'] for method in ('original','fix') for s in summaries[method])
                    rows.append(dict(name=f'mix_{seconds}s_{preset}_{repeat:02}',seconds=seconds,preset=preset,exits=exits,**summaries,PASS=bool(passed)))
                    save(); print(rows[-1]['name'],'PASS' if passed else 'FAIL',flush=True)
                raw.unlink()
        stats=[]
        for seconds in (30,180,300):
            for preset in ('candidate','baseline'):
                group=[r for r in rows if r['seconds']==seconds and r['preset']==preset]
                record=dict(seconds=seconds,preset=preset,repeats=len(group),all_cases_pass=all(r['PASS'] for r in group))
                for method in ('legacy','original','fix'):
                    for i,state in enumerate(('cold','restart')):
                        for key in ('first_callback_s','process_cpu_s','peak_rss_bytes'):
                            values=[r[method][i][key] for r in group if r[method][i]]
                            record[f'{method}_{state}_{key}']=dict(n=len(values),median=statistics.median(values),max=max(values),population_stddev=statistics.pstdev(values)) if values else None
                        values=[s['play_to_first_callback_s'] if method=='legacy' else s['first_callback_s']-s['play_requested_s'] for r in group if (s:=r[method][i])]
                        record[f'{method}_{state}_play_to_callback_s']=dict(n=len(values),median=statistics.median(values),max=max(values),population_stddev=statistics.pstdev(values)) if values else None
                stats.append(record)
        (out/'statistics.json').write_text(json.dumps(stats,indent=2)+'\n')
    manifest['end_utc']=utc(); manifest['binaries_unchanged']=all(sha(p)==h for p,h in binaries.items())
    s=save(); s['PASS'] &= manifest['binaries_unchanged']; (out/'summary.json').write_text(json.dumps(s,indent=2)+'\n')
    print(s,flush=True); return 0 if s['PASS'] else 2

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--suite',choices=('grid','lifecycle_load','long','startup'),required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--binary',type=Path,default=ROOT/'build/phase58_fix_frozen/candidate_v2_native')
    p.add_argument('--repeats',type=int,default=3); raise SystemExit(main(p.parse_args()))
