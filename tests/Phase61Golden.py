"""Read-only Golden25 check against an explicitly selected build's probe."""
import argparse,csv,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from phase53_sessions import wav_pcm,kv

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--probe',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);rows=[]
    for phase in ('phase12','phase28'):
        with (ROOT/f'results/{phase}/golden/manifest.csv').open() as f:rows.extend(r for r in csv.DictReader(f) if r['speed'] in ('0.50','0.60','0.70','0.75','0.80'))
    results=[]
    for row in rows:
        folder=a.output/(row['name']+'_'+row['speed']);folder.mkdir();golden=ROOT/row['output_path'];pcm,channels,frames=wav_pcm(golden)
        digest=hashlib.sha256(golden.read_bytes()).hexdigest();expected=hashlib.sha256(pcm).hexdigest()
        command=[str(a.probe.resolve()),str(ROOT/row['input_path']),row['speed']]
        p=subprocess.run(command,capture_output=True,text=True,timeout=240);(folder/'process.log').write_text(p.stdout+p.stderr);(folder/'summary.txt').write_text(p.stdout)
        got=kv(folder/'summary.txt');good=p.returncode==0 and digest==row['output_sha256'] and got.get('raw_pcm_sha256')==expected and got.get('produced_frames')==str(frames) and got.get('consumed_frames')==str(frames) and got.get('eos')=='1' and got.get('missing_frames')=='0' and not got.get('worker_error')
        results.append({'name':row['name'],'speed':row['speed'],'PASS':good,'command':command,'exit':p.returncode,'golden_sha256':digest,'expected_pcm_sha256':expected,'expected_frames':frames,'summary':got})
        (a.output/'progress.json').write_text(json.dumps({'completed':len(results),'passed':sum(r['PASS'] for r in results)})+'\n')
    summary={'PASS':len(results)==25 and all(r['PASS'] for r in results),'passed':sum(r['PASS'] for r in results),'total':len(results),'probe_sha256':hashlib.sha256(a.probe.read_bytes()).hexdigest(),'results':results}
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(f"Golden PCM {summary['passed']}/{len(results)}",flush=True)
    return 0 if summary['PASS'] else 2
if __name__=='__main__':raise SystemExit(main())
