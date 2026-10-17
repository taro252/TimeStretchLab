"""Exact suffix matrix. Full mode: all 8 WAV formats, 7 speeds, both presets.
The independent legacy DSP reference is supplied explicitly by the caller.
"""
import argparse, hashlib, json, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase57_study import fixture

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('check',type=Path);parser.add_argument('reference',type=Path)
    parser.add_argument('--full',action='store_true');parser.add_argument('--output',type=Path)
    args=parser.parse_args();check=args.check.resolve();reference=args.reference.resolve()
    out=args.output or Path(tempfile.mkdtemp(prefix='phase61_',dir=ROOT/'build'))
    if args.output:out.mkdir(parents=True,exist_ok=False)
    formats=[(r,c,e) for r in (44100,48000) for c in (1,2) for e in (1,3)] if args.full else [(48000,2,3)]
    speeds=[400000,500000,750000,1000000,1250000,1500000,2000000] if args.full else [400000,1000000,2000000]
    rows=[];inputs=[];passed=failed=0
    manifest={'check':str(check),'check_sha256':sha(check),'reference':str(reference),'reference_sha256':sha(reference),'driver_sha256':sha(Path(__file__)),'formats':formats,'speeds':speeds,'presets':['candidate','baseline'],'rows_path':str(out/'rows.jsonl'),'inputs':inputs}
    for rate,channels,encoding in formats:
        source=out/f'boundary_{rate}_{channels}_{encoding}.wav';fixture(source,rate,channels,encoding,'boundary',1.5)
        inputs.append({'path':str(source.resolve()),'sha256':sha(source)})
        n=round(rate*1.5);positions=[0,n//2+17,n-1,n] if args.full else [0,n//2+17,n]
        for speed in speeds:
            for preset in ('candidate','baseline'):
                name=f'{rate}_{channels}_{encoding}_{speed}_{preset}';folder=out/name;folder.mkdir();raw=folder/'reference.f32'
                cmd=[str(reference),str(source.resolve()),str(speed),preset,str(raw.resolve()),*map(str,positions)]
                ref=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
                (folder/'reference.log').write_text(ref.stdout+ref.stderr)
                if ref.returncode:raise RuntimeError(ref.stderr)
                expected=json.loads(ref.stdout);assert sha(raw)==expected['sha256']
                group_good=True
                for frame,start in zip(positions,expected['positions']):
                    for mode in ('standard','workgroup'):
                        cmd=[str(check),str(source.resolve()),str(speed),preset,str(frame),str(raw.resolve()),str(start),str(expected['output_frames']),mode,'0','0','1']
                        p=subprocess.run(cmd,capture_output=True,text=True,timeout=150)
                        log=folder/f'{frame}_{mode}.log';log.write_text(p.stdout+p.stderr)
                        row={'name':name,'input_frame':frame,'output_start':start,'mode':mode,'exit':p.returncode,'log':str(log),'result':json.loads(p.stdout) if p.returncode==0 else None,'reference_pcm_sha256':expected['sha256']}
                        rows.append(row);good=p.returncode==0 and row['result']['PASS'];passed+=good;failed+=not good;group_good&=good
                        with (out/'rows.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
                        (out/'progress.json').write_text(json.dumps({'passed':passed,'failed':failed,'last':name,'frame':frame,'mode':mode})+'\n')
                        if not good:print('FAIL',name,frame,mode,p.stdout+p.stderr,flush=True)
                if group_good:raw.unlink() # disposable newly generated success PCM; manifest preserves full SHA/recipe
                print(name,'PASS' if group_good else 'FAIL',flush=True)
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    expected_count=len(formats)*len(speeds)*2*(4 if args.full else 3)*2
    hits=sum(bool(r['result'] and r['result']['checkpoint_used']) for r in rows)
    resident=max((r['result']['checkpoint_states'] for r in rows if r['result']),default=0)
    summary={'PASS':failed==0 and passed==expected_count and hits>0 and resident<=2,'passed':passed,'failed':failed,'expected':expected_count,'checkpoint_hits':hits,'max_checkpoint_states':resident,'full':args.full,'output':str(out),'manifest_sha256':sha(out/'manifest.json')}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
    return 0 if summary['PASS'] else 2
if __name__=='__main__':raise SystemExit(main())
