"""Representative fixed-speed long audio regression, with independent PCM."""
import json,subprocess,time
from pathlib import Path
from phase57_study import ROOT,sha
out=ROOT/'results/phase59/device_final/fixed_long';out.mkdir();rows=[]
binary=ROOT/'build/phase59_frozen/final/phase58_native';reference=ROOT/'build/phase58_frozen/product_reference'
sources=[ROOT/'results/phase55/long/boundary_1_2_44100_180/full.wav',ROOT/'results/phase56/long/chain_300s.wav']
for source in sources:
 for preset in ('candidate','baseline'):
  folder=out/(source.parent.name+'_'+preset);folder.mkdir();raw=out/'reference.f32'
  command=[str(reference),str(source),'2000000',preset,str(raw)];p=subprocess.run(command,capture_output=True,text=True,timeout=1800)
  (folder/'reference.log').write_text(p.stdout+p.stderr);assert p.returncode==0
  info=json.loads(p.stdout);assert sha(raw)==info['pcm_sha256']
  command=[str(binary),str(source),'2000000',preset,str(raw),str(info['output_frames']),info['pcm_sha256'],str(folder/'native'),'normal','0','2','0','0','0','--worker=workgroup','--resident-input=on','--profile=block','--sample-thread=on']
  start=time.time()
  with (folder/'native.log').open('x') as log:p=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=600)
  path=folder/'native/summary.json';summary=json.loads(path.read_text()) if path.exists() else {}
  rows.append(dict(input=str(source),input_sha256=sha(source),command=command,exit=p.returncode,wall_s=time.time()-start,summary=summary,
   PASS=p.returncode==0 and bool(summary.get('PASS')) and bool(summary.get('pcm_complete_exact'))))
  (out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n');print(source,preset,p.returncode,flush=True)
(out/'summary.json').write_text(json.dumps(dict(PASS=all(r['PASS'] for r in rows),sessions=len(rows),passed=sum(r['PASS'] for r in rows)),indent=2)+'\n')
raise SystemExit(0 if all(r['PASS'] for r in rows) else 2)
