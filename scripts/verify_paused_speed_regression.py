"""Keep all independent Exact regression PCM under a new evidence directory."""
import argparse,hashlib,json,platform,subprocess,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--oracle',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);rows=[];commands=[]
    build=a.build.resolve()
    (out/'provenance.json').write_text(json.dumps({'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip(),'dirty_source':True,'pipeline_sha256':sha(ROOT/'src/prototype/Phase58RealtimePipeline.cpp'),'check_sha256':sha(build/'phase61_seek_check'),'oracle_sha256':sha(a.oracle),'driver_sha256':sha(Path(__file__).resolve()),'host':platform.platform()},indent=2)+'\n')
    def run(label,cmd):
        cmd=list(map(str,cmd));r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=180);(out/(label+'.log')).write_text(r.stdout+r.stderr)
        commands.append({'label':label,'command':cmd,'exit':r.returncode});(out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
        if r.returncode:raise RuntimeError(label+': '+r.stderr)
        return json.loads(r.stdout)
    for rate,ch,preset in [(48000,2,'candidate'),(48000,2,'baseline'),(44100,1,'candidate'),(44100,1,'baseline')]:
        input=(a.fixtures/f'{rate}_{ch}.wav').resolve()
        with wave.open(str(input)) as wav:frames=wav.getnframes()
        positions=[0,frames//2+17,frames]
        for speed in [400000,500000,1000000,2000000]:
            stem=f'{rate}_{ch}_{preset}_{speed}';raw=out/(stem+'.f32')
            reference=run(stem+'_oracle',[a.oracle,input,speed,preset,raw,*positions]);assert sha(raw)==reference['sha256']
            for frame,start in zip(positions,reference['positions']):
                for mode in ['standard','workgroup']:
                    result=run(stem+f'_{frame}_{mode}',[build/'phase61_seek_check',input,speed,preset,frame,raw,start,reference['output_frames'],mode,0,0,1])
                    assert result['PASS'];rows.append({'rate':rate,'channels':ch,'preset':preset,'speed':speed,'frame':frame,'mode':mode,'result':result})
                    with (out/'rows.jsonl').open('a') as f:f.write(json.dumps(rows[-1])+'\n')
    (out/'summary.json').write_text(json.dumps({'PASS':len(rows)==96,'passed':len(rows),'checkpoint_hits':sum(r['result']['checkpoint_used'] for r in rows)},indent=2)+'\n')
    print('PASS Exact regression',len(rows),flush=True)
if __name__=='__main__':main()
