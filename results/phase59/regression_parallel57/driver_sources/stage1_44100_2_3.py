import sys
sys.path.insert(0,'/Users/taro252/Docker/TimeStretchLab/scripts')
"""Sequential staged exact-PCM experiments. Never changes existing assets."""
import argparse,array,hashlib,json,math,statistics,struct,subprocess,sys,tempfile,time
from pathlib import Path
from phase55_study import ROOT,write_wav
CHUNKS=['1024','7168','8192','32768','131072','5003','irregular']
REPRESENTATIVE=[400000,500000,750000,1000000,1250000,1500000,2000000]
LONG_SPEEDS=[400000,410000,500000,990000,1000000,1010000,1500000,1990000,2000000]
KINDS=['silence','impulse','train','sustained','boundary','chain']

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def fixture(path,rate,channels,encoding,kind,seconds):
    count=round(rate*seconds);data=array.array('h' if encoding==1 else 'f')
    onset=min(8193,max(2501,count//3));pulses=set()
    if kind=='impulse':pulses={min(count-2,max(3001,count//2))}
    elif kind in ('train','chain'):pulses=set(range(onset,count-1,4096 if kind=='chain' else max(4096,rate//8)))
    elif kind=='boundary':
        pulses={n for boundary in (7168,8192,32768,131072) for n in (boundary-1,boundary+1) if 0<=n<count}
        pulses|={max(1,count//2),count-2}
    for i in range(count):
        base=.08*math.sin(2*math.pi*437.3*i/rate) if kind in ('sustained','boundary') else 0.
        if i in pulses:base+=.72
        for c in range(channels):
            value=base if c==0 else base*.73+(.013*math.sin(i*.023) if kind in ('sustained','boundary') else 0)
            data.append(round(value*32767) if encoding==1 else value)
    if sys.byteorder!='little':data.byteswap()
    write_wav(path,rate,channels,encoding,data.tobytes())

def call(command):
    return subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=1800)

def run(args):
    if args.suite=='stage2':
        prerequisite=json.loads(args.prerequisite.read_text());assert prerequisite['PASS']
    performance=args.suite.startswith('performance')
    out=args.output;out.mkdir(parents=True,exist_ok=False);(out/'inputs').mkdir()
    reference=args.reference.resolve();binary=args.binary.resolve();binary_sha=sha(binary);reference_sha=sha(reference)
    sources=[]
    if args.suite in ('smoke','stage1','stage2'):
        formats=[(44100, 2, 3)]
        for rate,channels,encoding in formats:
            kinds=['boundary','chain'] if args.suite=='smoke' else KINDS
            for kind in kinds:
                seconds=(4 if kind=='boundary' else .5) if args.suite=='stage1' else (.5 if args.suite=='smoke' else .25)
                path=out/'inputs'/f'{kind}_{encoding}_{channels}_{rate}.wav';fixture(path,rate,channels,encoding,kind,seconds)
                sources.append(dict(name=path.stem,path=str(path.resolve()),rate=rate,channels=channels,encoding=encoding,kind='synthetic '+kind,seconds=seconds))
    elif args.suite=='rejections':
        path=out/'inputs'/'early_impulse.wav';data=array.array('f',[0])*32768;data[3001]=.75
        if sys.byteorder!='little':data.byteswap()
        write_wav(path,48000,1,3,data.tobytes());sources=[dict(name='early_impulse',path=str(path.resolve()),rate=48000,channels=1,encoding=3,kind='synthetic frozen Phase37 rejection',seconds=32768/48000)]
    elif args.suite=='long':
        sources=[dict(name='boundary_180s',path=str(ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav'),rate=44100,channels=2,encoding=1,kind='synthetic boundary pattern repeated 180s',seconds=180),
                 dict(name='chain_300s',path=str(ROOT/'results/phase56/long/chain_300s.wav'),rate=48000,channels=1,encoding=3,kind='synthetic event chain 300s',seconds=300)]
    elif args.suite=='natural':
        for kind in ('mix','drums','vocal','bass','guitar'):
            path=ROOT/'results/phase31/input'/f'{kind}.wav';sources.append(dict(name=kind,path=str(path),kind='existing natural excerpt 10s',seconds=10))
    elif args.suite=='performance_chunks':
        sources=[dict(name='mix_10s',path=str(ROOT/'results/phase31/input/mix.wav'),kind='existing natural excerpt stereo 44.1kHz 10s',seconds=10)]
    elif args.suite=='performance':
        sources=[dict(name='mix_290s',path=str(ROOT/'results/phase55/input/mix_290_pcm16.wav'),kind='repeated natural excerpt PCM16 stereo 44.1kHz 290s',seconds=290),
                 dict(name='chain_300s',path=str(ROOT/'results/phase56/long/chain_300s.wav'),kind='synthetic event chain float mono 48kHz 300s',seconds=300)]
    else:raise RuntimeError('Unknown suite')
    speeds=list(range(400000,2000001,10000)) if args.suite=='stage2' else LONG_SPEEDS if args.suite=='long' else [500000,2000000] if args.suite=='rejections' else [500000] if performance else [400000,1000000,2000000] if args.suite=='smoke' else REPRESENTATIVE
    chunks=['1024','5003','irregular'] if args.suite=='stage2' else ['131072'] if args.suite=='long' else CHUNKS if args.suite not in ('smoke','performance','natural') else ['1024','5003','irregular'] if args.suite=='smoke' else ['32768','131072'] if performance else ['7168','131072','5003']
    if args.suite=='performance_chunks':chunks=CHUNKS
    for s in sources:s['input_sha256']=sha(s['path'])
    manifest=dict(driver_source_sha256=sha(Path(__file__)),baseline='ec087019626d9ff0d9f157245729b74ddb6847d7',suite=args.suite,reference=str(reference),reference_binary_sha256=reference_sha,incremental_binary=str(binary),incremental_binary_sha256=binary_sha,speeds=speeds,chunks=chunks,inputs=sources,started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    cases=0;sessions=0;rejections=0
    with tempfile.TemporaryDirectory(prefix='phase57_reference_',dir=ROOT/'build') as temporary,(out/'rows.jsonl').open('w') as rows:
        raw=Path(temporary)/'reference.f32'
        for source in sources:
            for speed in speeds:
                for preset in ('candidate','baseline'):
                    a=call([reference,source['path'],speed,preset,raw]);cases+=1
                    case=dict(input=source['name'],speed_micros=speed,preset=preset,reference_exit=a.returncode)
                    selected=chunks.copy()
                    if args.suite=='long' and source['name']=='boundary_180s' and speed in (500000,1000000,2000000):selected+=['32768','5003']
                    if a.returncode:
                        expected=[m for m in ('No monotonic high-speed event interval','Unsafe high-speed Mid synthesis hop','Unsafe variable synthesis hop','Phase 24 requires nonempty audio') if m in a.stderr]
                        if not expected:raise RuntimeError('Unexpected frozen reference failure: '+a.stderr)
                        rejected=[]
                        for rejected_chunk in selected:
                            b=call([binary,source['path'],speed,preset,'-',0,'-',rejected_chunk,'reject'])
                            rejected.append(dict(chunk=rejected_chunk,exit=b.returncode,error=b.stderr,matched=b.returncode!=0 and expected[0] in b.stderr))
                        case.update(reference_error=a.stderr,rejections=rejected,matched_rejection=all(r['matched'] for r in rejected))
                        rows.write(json.dumps(case)+'\n');rows.flush()
                        if not case['matched_rejection']:raise RuntimeError('Rejection differs: '+str(case))
                        rejections+=1
                        continue
                    ref=json.loads(a.stdout);case['reference']=ref
                    if raw.stat().st_size!=ref['output_frames']*ref['channels']*4 or sha(raw)!=ref['pcm_sha256']:raise RuntimeError('Frozen raw data/hash differs')
                    if performance:
                        validation_trace=out/f"{source['name']}_{speed}_{preset}_validation"
                        validation=call([binary,source['path'],speed,preset,raw,ref['output_frames'],ref['pcm_sha256'],','.join(selected),'exact',validation_trace])
                        if validation.returncode:
                            case.update(validation_exit=validation.returncode,validation_error=validation.stderr);rows.write(json.dumps(case)+'\n');rows.flush();raise RuntimeError('Performance input full-bit validation failed: '+str(case))
                        case['validation_measurements']=[json.loads(line) for line in validation.stdout.splitlines()]
                        assert len(case['validation_measurements'])==len(selected) and all(m['PASS'] and not m['bench'] and m['pcm_sha256']==ref['pcm_sha256'] for m in case['validation_measurements'])
                    repeat_count=5 if performance else 1
                    for repeat in range(repeat_count):
                        if performance:
                            p=call([reference,source['path'],speed,preset,'-']);assert p.returncode==0,p.stderr
                            full=json.loads(p.stdout);assert full['pcm_sha256']==ref['pcm_sha256'];case.setdefault('full_runs',[]).append(full)
                        trace=out/f"{source['name']}_{speed}_{preset}_{repeat}" if performance else '-'
                        measurements=[]
                        for run_chunks in ([[c] for c in selected] if performance else [selected]):
                            b=call([binary,source['path'],speed,preset,raw,ref['output_frames'],ref['pcm_sha256'],','.join(run_chunks),'bench' if performance else 'exact',trace])
                            if b.returncode:
                                case.update(incremental_exit=b.returncode,incremental_stdout=b.stdout,incremental_error=b.stderr);rows.write(json.dumps(case)+'\n');rows.flush();raise RuntimeError('PCM mismatch/failure: '+str(case))
                            measurements.extend(json.loads(line) for line in b.stdout.splitlines())
                        assert len(measurements)==len(selected)
                        for m in measurements:assert m['PASS'] and m['output_frames']==ref['output_frames'] and m['pcm_sha256']==ref['pcm_sha256'];m['repeat']=repeat
                        case.setdefault('measurements',[]).extend(measurements);sessions+=len(measurements)
                    case['PASS']=True;rows.write(json.dumps(case)+'\n');rows.flush();raw.unlink()
                if args.suite=='stage2' and speed%100000==0:print(source['name'],speed,'PASS',flush=True)
            print(source['name'],'complete',cases,'reference cases',sessions,'PCM sessions',rejections,'matched rejections',flush=True)
            (out/'progress.json').write_text(json.dumps(dict(cases=cases,sessions=sessions,rejections=rejections,last_input=source['name']),indent=2)+'\n')
    assert sha(binary)==binary_sha and sha(reference)==reference_sha,'Executable changed during suite'
    result=dict(PASS=True,cases=cases,pcm_sessions=sessions,matched_rejections=rejections,completed_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--suite',choices=['smoke','stage1','stage2','long','natural','performance','performance_chunks','rejections'],required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--reference',type=Path,default=ROOT/'build/phase57_frozen/reference');p.add_argument('--binary',type=Path,default=ROOT/'build/phase57_check');p.add_argument('--prerequisite',type=Path,default=ROOT/'results/phase57/stage1_final/summary.json');run(p.parse_args())
