"""Phase58 Fix explicit resident/borrowed-pipeline offline PCM regression. No realtime arming."""
import argparse,json,subprocess,time
from pathlib import Path
from phase57_study import ROOT,REPRESENTATIVE,fixture,sha

def run(a):
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);(out/'inputs').mkdir()
    reference=a.reference.resolve();check=ROOT/'build/phase58_check';native=ROOT/'build/phase58_native'
    formats=[(r,c,e) for r in (44100,48000) for c in (1,2) for e in (1,3)]
    inputs=[]
    if a.suite in ('short','all_speeds','native_gate'):
        for rate,channels,encoding in formats:
            kinds=('boundary','sustained','chain') if a.suite=='short' else ('boundary',)
            for kind in kinds:
                seconds=(4 if kind=='boundary' else .5) if a.suite!='all_speeds' else .25
                p=out/'inputs'/f'{kind}_{encoding}_{channels}_{rate}.wav';fixture(p,rate,channels,encoding,kind,seconds)
                inputs.append(dict(name=p.stem,path=str(p),rate=rate,channels=channels,encoding=encoding,seconds=seconds))
        if a.suite=='native_gate':
            p=ROOT/'results/phase54/input/mix_30s.wav';assert p.exists();inputs.append(dict(name='mix_30s',path=str(p),seconds=30))
    elif a.suite=='long':
        inputs=[dict(name='boundary_180s',path=str(ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav'),seconds=180),dict(name='chain_300s',path=str(ROOT/'results/phase56/long/chain_300s.wav'),seconds=300)]
    else:raise ValueError(a.suite)
    for s in inputs:s['input_sha256']=sha(s['path'])
    binaries={str(p.relative_to(ROOT)):sha(p) for p in (reference,check,native)}
    manifest=dict(suite=a.suite,baseline='75ae70cecaef2739f744fc21eeecf99da179e18f',worker='workgroup',resident_input=True,realtime_armed=False,driver_source_sha256=sha(Path(__file__)),reference=str(reference),binaries=binaries,inputs=inputs,started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    passed=failed=rejected=pcm=0
    with (out/'rows.jsonl').open('x') as rows:
        for source in inputs:
            speeds=range(400000,2000001,10000) if a.suite=='all_speeds' else (400000,1000000,2000000) if a.suite=='native_gate' and source['name']!='mix_30s' else REPRESENTATIVE
            for speed in speeds:
                for preset in ('candidate','baseline'):
                    name=f"{source['name']}_{speed}_{preset}";folder=out/name;folder.mkdir();raw=folder/'reference.f32'
                    command=[str(reference),source['path'],str(speed),preset,str(raw)]
                    result=subprocess.run(command,capture_output=True,text=True,timeout=1800);(folder/'reference.log').write_text(result.stdout+result.stderr)
                    case=dict(input=source['name'],speed_micros=speed,preset=preset,reference_exit=result.returncode)
                    if result.returncode:
                        case.update(PASS=False,reference_error=result.stderr);failed+=1
                    else:
                        ref=json.loads(result.stdout);assert sha(raw)==ref['pcm_sha256'];case['reference']=ref
                        chunks=(32768,) if a.suite=='native_gate' else (1024,5003) if a.suite=='all_speeds' else (7168,32768,131072) if a.suite=='short' else (32768,131072)
                        checks=[]
                        for chunk in chunks:
                            p=subprocess.run([str(check),source['path'],str(speed),preset,str(raw),str(ref['output_frames']),ref['pcm_sha256'],str(chunk),'--worker=workgroup','--resident-input=on'],capture_output=True,text=True,timeout=1800)
                            (folder/f'fifo_{chunk}.log').write_text(p.stdout+p.stderr)
                            checks.append(dict(chunk=chunk,exit=p.returncode,result=json.loads(p.stdout) if p.returncode==0 else None,error=p.stderr));pcm+=p.returncode==0
                        case['checks']=checks;case['PASS']=all(c['exit']==0 and c['result']['PASS'] for c in checks)
                        if a.suite=='native_gate':
                            p=subprocess.run([str(native),source['path'],str(speed),preset,str(raw),str(ref['output_frames']),ref['pcm_sha256'],str(folder/'native'),'normal','0'],capture_output=True,text=True,timeout=600)
                            (folder/'native.log').write_text(p.stdout+p.stderr);path=folder/'native/summary.json';case['native_exit']=p.returncode;case['native']=json.loads(path.read_text()) if path.exists() else None
                            case['PASS'] &= p.returncode==0 and case['native'] is not None and case['native']['PASS'] and case['native']['pcm_complete_exact']
                        passed+=case['PASS'];failed+=not case['PASS'];raw.unlink()
                    rows.write(json.dumps(case)+'\n');rows.flush()
                    (out/'progress.json').write_text(json.dumps(dict(passed=passed,failed=failed,pcm_sessions=pcm,last=name),indent=2)+'\n')
                    print(name,'PASS' if case['PASS'] else 'FAIL',flush=True)
    for name,digest in binaries.items():assert sha(ROOT/name)==digest,'Binary changed during suite'
    summary=dict(PASS=failed==0,passed=passed,failed=failed,pcm_sessions=pcm,matched_rejections=rejected)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary,flush=True)
    return 0 if summary['PASS'] else 2
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--suite',choices=('short','all_speeds','long'),required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--reference',type=Path,default=ROOT/'build/phase58_frozen/product_reference');raise SystemExit(run(p.parse_args()))
