"""Build an independent old Phase36 DSP with the Phase54 length contract."""
import hashlib,json,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];build=ROOT/'build';out=build/'phase58_frozen/product_reference';assert not out.exists()
source=build/'phase58_frozen/Phase36Legacy.cpp';base='ec087019626d9ff0d9f157245729b74ddb6847d7'
raw=subprocess.check_output(['git','show',base+':src/prototype/Phase36StreamingSpeedEngine.cpp'],cwd=ROOT)
if not source.exists():source.write_bytes(raw)
assert source.read_bytes()==raw
link=shlex.split((build/'CMakeFiles/phase58_product_reference.dir/link.txt').read_text());obj=out.with_suffix('.o')
subprocess.run([link[0],'-std=c++20','-arch','arm64','-O3','-DNDEBUG','-I'+str(ROOT/'src'),'-c',str(source),'-o',str(obj)],cwd=build,check=True)
link.insert(1,str(obj));link[link.index('-o')+1]=str(out);subprocess.run(link,cwd=build,check=True)
print(json.dumps(dict(path=str(out),sha256=hashlib.sha256(out.read_bytes()).hexdigest(),legacy_source_sha256=hashlib.sha256(raw).hexdigest(),legacy_source_commit=base),indent=2))
