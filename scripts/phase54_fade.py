"""Short fixed-gain boundary clips, separate from the raw DSP comparison."""
import argparse,array,csv,hashlib,io,json,math,subprocess
from pathlib import Path
from phase53_sessions import ROOT,wav_pcm
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False);rows=[]
for source,position in [('drums',3.77),('mix',4.0)]:
 out=a.output/(source+'_040');input=ROOT/f'results/phase54/input/{source}_30s.wav'
 r=subprocess.run([str(ROOT/'build/phase54_fade_study'),str(input),'0.4',str(position),str(out)],capture_output=True,text=True,timeout=120)
 (a.output/(source+'.log')).write_text(r.stdout+r.stderr)
 if r.returncode:raise SystemExit(r.returncode)
 (a.output/(source+'_metrics.csv')).write_text(r.stdout)
 for values in csv.DictReader(io.StringIO(r.stdout)):
  wav=out/f"fade_{values['fade_frames']}.wav";pcm,ch,n=wav_pcm(wav);data=array.array('f');data.frombytes(pcm)
  finite=all(math.isfinite(v) for v in data);peak=max(map(abs,data))
  rows.append(dict(source=source,input=str(input.relative_to(ROOT)),input_sha256=hashlib.sha256(input.read_bytes()).hexdigest(),speed=.4,fixed_gain=.5,path=str(wav.resolve().relative_to(ROOT)),sha256=hashlib.sha256(wav.read_bytes()).hexdigest(),frames=n,channels=ch,finite=finite,peak=peak,metrics=values,PASS=finite and peak<1))
(a.output/'manifest.json').write_text(json.dumps(rows,indent=2)+'\n');print('fade clips',sum(r['PASS'] for r in rows),'/',len(rows))
raise SystemExit(0 if all(r['PASS'] for r in rows) else 2)
