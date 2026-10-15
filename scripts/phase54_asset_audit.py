"""Read-only audit of protected tracked research and frozen DSP sources."""
import argparse,hashlib,json,subprocess,os
from pathlib import Path
from phase53_sessions import ROOT
BASE='34b8903ef43e1bae4e518eeb124caaab9db2976f'
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
if a.output.exists():raise SystemExit('Fresh output required')
tree=subprocess.check_output(['git','ls-tree','-r',BASE],cwd=ROOT,text=True)
paths={line.split('\t',1)[1]:line.split()[2] for line in tree.splitlines()}
protected=[name for name in paths if name.startswith('results/')]
# Algorithm implementations stay byte identical; changes to wrapper/readonly telemetry are separately reviewed.
protected += [name for name in paths if name.startswith('src/') and ('PhaseVocoder' in name or 'TimeMap' in name or 'Phase42DensityGuard' in name or 'Phase10' in name or 'Phase53' in name or 'Phase30' in name)]
protected += [name for name in paths if name.startswith('src/') and ('TimeStretchEngine' in name or 'Phase34' in name or 'Phase37' in name)]
results=[]
for name in sorted(set(protected)):
 path=ROOT/name
 if not path.is_file():results.append(dict(path=name,PASS=False,reason='missing'));continue
 if path.is_symlink():
  data=os.readlink(path).encode();actual=hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
 else:
  digest=hashlib.sha1(f'blob {path.stat().st_size}\0'.encode())
  with path.open('rb') as stream:
   for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
  actual=digest.hexdigest()
 results.append(dict(path=name,expected_blob=paths[name],actual_blob=actual,PASS=actual==paths[name]))
tag=subprocess.check_output(['git','rev-parse','phase53-handoff^{}'],cwd=ROOT,text=True).strip()
result=dict(baseline=BASE,checked=len(results),PASS=all(r['PASS'] for r in results) and tag=='233c773bbc77e5824c36134915f68d6d3a0d581e',handoff_tag_commit=tag,results=results)
a.output.write_text(json.dumps(result,indent=2)+'\n')
print('protected assets',sum(r['PASS'] for r in results),'/',len(results),'tag',tag)
raise SystemExit(0 if result['PASS'] else 2)
