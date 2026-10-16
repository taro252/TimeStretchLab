"""Keep every strict result, including failures; never stop at the first pass."""
import argparse,csv,json,subprocess
from pathlib import Path
from phase57_study import ROOT,sha
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'results/phase58/reproduce_fifo');parser.add_argument('--repeats',type=int,default=10);parser.add_argument('--legacy-repeats',type=int,default=5);args=parser.parse_args();assert 0<args.repeats<=30 and 0<=args.legacy_repeats<=30
out=args.output.resolve();out.mkdir(exist_ok=False)
source=ROOT/'results/phase58/native_product/inputs/boundary_1_2_48000.wav';reference=ROOT/'build/phase58_frozen/product_reference';raw=out/'reference.f32'
r=subprocess.run([str(reference),str(source),'2000000','candidate',str(raw)],capture_output=True,text=True,check=True);ref=json.loads(r.stdout);(out/'reference.json').write_text(r.stdout)
manifest=dict(input=str(source),input_sha256=sha(source),binaries={str(p.relative_to(ROOT)):sha(p) for p in (reference,ROOT/'build/phase58_native',ROOT/'build/phase58_frozen/phase54_native')})
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');rows=[]
for kind,count in (('legacy',args.legacy_repeats),('progressive',args.repeats)):
    for i in range(count):
        folder=out/f'{kind}_{i}'
        if kind=='legacy':cmd=[ROOT/'build/phase58_frozen/phase54_native',source,'candidate','2.00',folder,'eos','0']
        else:cmd=[ROOT/'build/phase58_native',source,'2000000','candidate',raw,str(ref['output_frames']),ref['pcm_sha256'],folder,'normal','0']
        r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=90);(out/f'{kind}_{i}.log').write_text(r.stdout+r.stderr)
        row=dict(kind=kind,repeat=i,exit=r.returncode,stdout=r.stdout,stderr=r.stderr)
        if kind=='progressive' and (folder/'summary.json').exists():row['summary']=json.loads((folder/'summary.json').read_text())
        elif kind=='legacy' and (folder/'summary.txt').exists():row['summary']={k:v for line in (folder/'summary.txt').read_text().splitlines() if '=' in line for k,v in [line.split('=',1)]}
        rows.append(row);(out/'rows.json').write_text(json.dumps(rows,indent=2)+'\n');print(kind,i,r.returncode,flush=True)
summary=dict(executions=len(rows),legacy_pass=sum(r['exit']==0 for r in rows if r['kind']=='legacy'),progressive_pass=sum(r['exit']==0 for r in rows if r['kind']=='progressive'))
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary,flush=True)
