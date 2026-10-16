"""Protect the full baseline, including all Phase57 evidence."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];BASE='88d5394c3d48970b14807c2d5151e4a3a4f86a2b'
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--allow',action='append',default=['CMakeLists.txt']);a=p.parse_args();assert not a.output.exists()
records=[]
for line in subprocess.check_output(['git','ls-tree','-r',BASE],cwd=ROOT,text=True).splitlines():
    metadata,name=line.split('\t',1)
    if name in a.allow:continue
    path=ROOT/name;exists=path.exists();h=hashlib.sha1()
    if path.is_symlink():
        data=os.readlink(path).encode();h.update(f'blob {len(data)}\0'.encode());h.update(data)
    elif path.is_file():
        h.update(f'blob {path.stat().st_size}\0'.encode())
        with path.open('rb') as stream:
            for b in iter(lambda:stream.read(1<<20),b''):h.update(b)
    records.append(dict(path=name,PASS=exists and h.hexdigest()==metadata.split()[2]))
result=dict(baseline=BASE,allowed=a.allow,checked=len(records),PASS=all(r['PASS'] for r in records),records=records)
a.output.write_text(json.dumps(result,indent=2)+'\n');print('Protected',sum(r['PASS'] for r in records),'/',len(records));raise SystemExit(0 if result['PASS'] else 2)
