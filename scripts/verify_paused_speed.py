"""Release native PCM verification. Evidence is new, ignored build/ data only."""
import argparse,hashlib,json,math,platform,struct,subprocess,time,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def fixture(path,rate,channels):
    # Time-identifiable chirps, nonperiodic impulses and a changing envelope.
    with wave.open(str(path),'wb') as wav:
        wav.setparams((channels,2,rate,rate*3,'NONE','not compressed'))
        data=bytearray()
        for i in range(rate*3):
            t=i/rate;block=i//(rate//17)
            for c in range(channels):
                value=.17*math.sin(2*math.pi*(173*t+89*t*t+c*.07))*(.3+.7*((block*13)%19)/19)
                value+=.23*math.exp(-(i%(rate//11))/(rate*.001))*math.sin(2*math.pi*(610+block*7)*t+c*.31)
                if i%(rate//7+23)<3:value+=.35*((block%3)-1)
                data.extend(struct.pack('<h',round(max(-.95,min(.95,value))*32767)))
        wav.writeframes(data)
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--oracle',type=Path,required=True);p.add_argument('--full',action='store_true');p.add_argument('--references-from',type=Path);a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);build=a.build.resolve();commands=[]
    def run(label,cmd,timeout=600):
        cmd=list(map(str,cmd));start=time.time()
        with (out/(label+'.log')).open('x') as log:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        commands.append({'label':label,'command':cmd,'exit':r.returncode,'wall_s':time.time()-start})
        (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if r.returncode:raise RuntimeError(f'{label}: exit {r.returncode}; {out/(label+".log")}')
    source={str(f.relative_to(ROOT)):sha(f) for f in [ROOT/'CMakeLists.txt',*sorted((ROOT/'src/platform/macos').glob('ProgressiveMacPlaybackEngine.*')),ROOT/'src/prototype/Phase58RealtimePipeline.cpp',ROOT/'src/prototype/Phase58RealtimePipeline.h',ROOT/'tests/PausedSpeedNativeTests.cpp',Path(__file__).resolve()]}
    (out/'provenance.json').write_text(json.dumps({'start_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'dirty_source':True,'source_sha256':source,'host':platform.platform(),'machine':platform.machine(),'oracle':str(a.oracle.resolve()),'oracle_sha256':sha(a.oracle),'build_type':'Release','native_binary_sha256':sha(build/'paused_speed_native_tests')},indent=2)+'\n')
    combinations=[(48000,2,'candidate'),(44100,1,'baseline'),(44100,1,'candidate'),(48000,2,'baseline')]
    for rate,ch,preset in combinations:
        stem=f'{rate}_{ch}_{preset}';wav=out/f'{rate}_{ch}.wav'
        if not wav.exists():fixture(wav,rate,ch)
        refs=out/(stem+'_refs');refs.mkdir()
        if a.references_from:
            previous_provenance=json.loads((a.references_from/'provenance.json').read_text())
            assert previous_provenance['oracle_sha256']==sha(a.oracle)
            if (a.references_from/wav.name).exists():assert sha(wav)==sha(a.references_from/wav.name)
        speeds=range(400000,2000001,10000) if a.full else [750000,1250000,400000,2000000,490000,500000,990000,1000000,1010000]
        for speed in speeds:
            destination=refs/f'{speed}_{preset}.f32'
            previous=a.references_from/(stem+'_refs')/destination.name if a.references_from else None
            # Reuse only completed independent-oracle outputs, with a recorded
            # successful command. No PCM is removed or overwritten.
            rows=json.loads((a.references_from/'commands.json').read_text()) if a.references_from else []
            label=f'{stem}_oracle_{speed}'
            if previous and previous.exists() and any(r['label']==label and r['exit']==0 for r in rows):
                destination.symlink_to(previous.resolve());commands.append({'label':label,'reused_reference':str(previous.resolve()),'sha256':sha(previous),'exit':0})
            else:run(label,[a.oracle,wav,speed,preset,destination,rate])
        run(stem+'_pcm',[build/'paused_speed_native_tests',wav,refs,preset,'matrix' if a.full else 'representative'])
        run(stem+'_controls',[build/'paused_speed_native_tests',wav,refs,preset,'controls'])
        short=out/f'{rate}_{ch}_short.wav'
        if not short.exists():
            with wave.open(str(wav),'rb') as source, wave.open(str(short),'wb') as dest:
                dest.setparams(source.getparams());dest.writeframes(source.readframes(2049))
        short_refs=out/(stem+'_short_refs');short_refs.mkdir()
        run(stem+'_short_oracle',[a.oracle,short,1250000,preset,short_refs/f'1250000_{preset}.f32',0])
        run(stem+'_short',[build/'paused_speed_native_tests',short,short_refs,preset,'short'])
    artifacts=[{'path':str(f.relative_to(out)),'bytes':f.stat().st_size,'sha256':sha(f)} for f in sorted(out.rglob('*')) if f.is_file()]
    (out/'artifact_manifest.json').write_text(json.dumps(artifacts,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps({'PASS':True,'pcm_cases':len(list(speeds))*4,'controls':19*4,'commands':len(commands)},indent=2)+'\n')
    print(out,flush=True)
if __name__=='__main__':main()
