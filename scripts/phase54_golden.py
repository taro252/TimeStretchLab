"""App-engine raw PCM comparison; never changes the original Golden WAVs."""
import argparse,concurrent.futures,csv,hashlib,json,subprocess
from pathlib import Path
from phase53_sessions import ROOT,wav_pcm,kv
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
rows=[]
for ph in ('phase12','phase28'):
 with (ROOT/f'results/{ph}/golden/manifest.csv').open() as f:
  rows.extend(r for r in csv.DictReader(f) if r['speed'] in ('0.50','0.60','0.70','0.75','0.80'))
def run(row):
 out=a.output/(row['name']+'_'+row['speed']);out.mkdir();golden=ROOT/row['output_path'];pcm,ch,n=wav_pcm(golden)
 assert hashlib.sha256(golden.read_bytes()).hexdigest()==row['output_sha256']
 cmd=[str(ROOT/'build/phase54_core_probe'),str(ROOT/row['input_path']),row['speed']]
 r=subprocess.run(cmd,capture_output=True,text=True,timeout=240);(out/'process.log').write_text(r.stdout+r.stderr)
 (out/'summary.txt').write_text(r.stdout)
 result=dict(source=row['name'],speed=row['speed'],exit=r.returncode,golden_sha256=row['output_sha256'],expected_pcm_sha256=hashlib.sha256(pcm).hexdigest(),expected_frames=n)
 if (out/'summary.txt').exists():
  got=kv(out/'summary.txt');result['summary']=got;result['PASS']=r.returncode==0 and got['raw_pcm_sha256']==result['expected_pcm_sha256'] and int(got['produced_frames'])==n and int(got['consumed_frames'])==n and got['eos']=='1' and got['missing_frames']=='0' and not got.get('worker_error')
 else:result['PASS']=False
 return result
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,rows))
(a.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n');print(f"Golden PCM {sum(r['PASS'] for r in results)}/{len(results)}")
raise SystemExit(0 if len(results)==25 and all(r['PASS'] for r in results) else 2)
