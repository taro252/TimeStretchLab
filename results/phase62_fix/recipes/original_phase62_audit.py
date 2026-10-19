"""旧Phase62の保存済みSHA索引に対し全原本を読む。原本は一切変更しない。"""
import json,hashlib,time
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9'
while not (F/'figure_repair/SUMMARY.json').is_file():time.sleep(5)
p=R/'results/phase62/ARTIFACT_MANIFEST.json';manifest=json.loads(p.read_text());base=Path(manifest['root']);errors=[];checked=0;size=0
for entry in manifest['entries']:
 q=base/entry['path']
 if not q.is_file():errors.append(dict(path=entry['path'],reason='missing'));continue
 with q.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 actual=q.stat().st_size
 if actual!=entry['bytes'] or digest!=entry['sha256']:errors.append(dict(path=entry['path'],expected=entry,actual_bytes=actual,actual_sha256=digest))
 checked+=1;size+=actual
result=dict(PASS=not errors,expected=len(manifest['entries']),checked=checked,bytes=size,manifest_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),errors=errors)
(F/'ORIGINAL_PHASE62_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(result,flush=True)
raise SystemExit(int(not result['PASS']))
