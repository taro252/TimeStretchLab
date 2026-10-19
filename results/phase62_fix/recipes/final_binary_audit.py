"""全検証後、実行体99件の不変と、宣言済みSandbox署名1件の変化を照合する。"""
import json,sys
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import identity,source_manifest
before=json.loads((F/'evidence/dependency_audit_after_main.json').read_text());signed=json.loads((F/'sandbox_evidence/SIGNATURE.json').read_text());expected=Path(signed['host']['path']).resolve()
assert source_manifest(R)==json.loads((F/'FROZEN_SOURCE.json').read_text())
rows=[]
for item in before['binaries']:
 actual=identity(item['path']);unchanged=actual['sha256']==item['sha256'];declared=not unchanged and Path(item['path']).resolve()==expected and actual==signed['host']
 assert unchanged or declared,item['path']
 rows.append(dict(before=item,after=actual,unchanged=unchanged,declared_sandbox_signing=declared))
assert sum(r['declared_sandbox_signing'] for r in rows)==1
r=dict(PASS=True,binary_records_checked=len(rows),unchanged=sum(x['unchanged'] for x in rows),declared_signature_changes=1,source_unchanged=True,signature_record=identity(F/'sandbox_evidence/SIGNATURE.json'),note='The earlier 100/100 byte audits were before Sandbox signing. Only Release Sandbox app changed via recorded codesign; its executed signed SHA is explicit. Original completed suites did not execute this app.',binaries=rows)
(F/'evidence/dependency_audit_after_sandbox.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print({k:r[k] for k in ('PASS','binary_records_checked','unchanged','declared_signature_changes')})
