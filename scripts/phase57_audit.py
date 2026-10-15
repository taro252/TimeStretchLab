"""Read-only custody audit; the shared DSP extraction is the sole source exception."""
import argparse,csv,hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='ec087019626d9ff0d9f157245729b74ddb6847d7'
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();assert not a.output.exists()
tracked=[]
for line in subprocess.check_output(['git','ls-tree','-r',BASE],cwd=ROOT,text=True).splitlines():
    meta,name=line.split('\t',1)
    if name in ('CMakeLists.txt','src/prototype/Phase36StreamingSpeedEngine.cpp'):continue
    path=ROOT/name;h=hashlib.sha1()
    if path.is_symlink():data=os.readlink(path).encode();h.update(f'blob {len(data)}\0'.encode()+data)
    elif path.is_file():
        h.update(f'blob {path.stat().st_size}\0'.encode())
        with path.open('rb') as stream:
            for b in iter(lambda:stream.read(1<<20),b''):h.update(b)
    tracked.append(dict(path=name,PASS=path.exists() and h.hexdigest()==meta.split()[2]))
golden=[]
for phase in ('phase12','phase28'):
    for row in csv.DictReader((ROOT/f'results/{phase}/golden/manifest.csv').open()):
        path=ROOT/row['output_path'];actual=hashlib.sha256(path.read_bytes()).hexdigest();golden.append(dict(path=row['output_path'],expected=row['output_sha256'],actual=actual,PASS=actual==row['output_sha256']))
tag=subprocess.check_output(['git','rev-parse','phase53-handoff^{}'],cwd=ROOT,text=True).strip()
result=dict(baseline=BASE,checked=len(tracked),golden_checked=len(golden),handoff_tag=tag,PASS=all(r['PASS'] for r in tracked+golden) and tag=='233c773bbc77e5824c36134915f68d6d3a0d581e',allowed_changes=['CMakeLists.txt','src/prototype/Phase36StreamingSpeedEngine.cpp'],tracked=tracked,golden=golden)
a.output.write_text(json.dumps(result,indent=2)+'\n');print(f"Protected files {sum(r['PASS'] for r in tracked)}/{len(tracked)}, Golden {sum(r['PASS'] for r in golden)}/{len(golden)}");raise SystemExit(0 if result['PASS'] else 1)
