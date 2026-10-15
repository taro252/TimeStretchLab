"""Link the saved pre-extraction DSP object ahead of current archives.
Only unchanged Phase35/core members are pulled from those archives. The saved
legacy object resolves Phase36 synthesis, without the new shared-header object.
"""
import argparse,hashlib,json,shlex,subprocess
from pathlib import Path
from phase55_study import ROOT
p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);a=p.parse_args()
b=a.build.resolve();out=a.destination.resolve();assert not out.exists();legacy=ROOT/'build/phase57_frozen/source/Phase36Legacy.cpp'
expected=subprocess.check_output(['git','show','ec087019626d9ff0d9f157245729b74ddb6847d7:src/prototype/Phase36StreamingSpeedEngine.cpp'],cwd=ROOT)
# A fresh checkout can restore the exact baseline source from Git. Never replace
# a saved source or a reference executable that already exists.
if not legacy.exists():
    legacy.parent.mkdir(parents=True,exist_ok=True)
    with legacy.open('xb') as stream:stream.write(expected)
assert legacy.read_bytes()==expected
out.parent.mkdir(parents=True,exist_ok=True)
link=shlex.split((b/'CMakeFiles/phase57_reference.dir/link.txt').read_text());flags=['-std=c++20','-arch','arm64','-I'+str(ROOT/'src')]
flags+=['-g'] if 'debug' in str(b) else ['-O3','-DNDEBUG']
obj=out.with_suffix('.o');subprocess.run([link[0],*flags,'-c',str(legacy),'-o',str(obj)],check=True,cwd=b)
link.insert(1,str(obj));link[link.index('-o')+1]=str(out);subprocess.run(link,cwd=b,check=True)
print(json.dumps(dict(binary=str(out),sha256=hashlib.sha256(out.read_bytes()).hexdigest(),legacy_source_sha256=hashlib.sha256(expected).hexdigest(),build=str(b)),indent=2))
