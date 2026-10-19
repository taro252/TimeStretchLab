import sys,json
from pathlib import Path
R=Path.cwd();RUN=R/'build/phase62_fix/run_01';OLD=RUN/'final_v8';F=RUN/'final_v9';sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import identity,source_manifest,aggregate
before=json.loads((OLD/'FROZEN_SOURCE.json').read_text());after=source_manifest(R);assert after==json.loads((F/'FROZEN_SOURCE.json').read_text())
a={r['path']:r['sha256'] for r in before['files']};b={r['path']:r['sha256'] for r in after['files']};changed=sorted(p for p in a.keys()|b.keys() if a.get(p)!=b.get(p))
assert changed==['scripts/phase62_fix_quality.py']
names=['release_ctest','debug_ctest','release_exact','release_golden','release_pcm','release_pcm161','release_native'];rows=[];bins={}
for name in names:
 folder=OLD/'evidence'/name;summary=aggregate(folder);plan=json.loads((folder/'EXPECTED.json').read_text());build=json.loads((folder/'BUILD_PROVENANCE.json').read_text())
 assert summary['PASS'] and plan['provenance']['source']['sha256']==before['sha256']
 assert build['source_before']==build['source_after']==before['sha256']
 rows.append(dict(name=name,original_source_sha256=before['sha256'],original_ledger=identity(folder/'LEDGER.json'),original_expected=identity(folder/'EXPECTED.json'),counts=summary['counts'],source_metadata_unchanged=True))
 for item in build['binaries']:
  path=item['path'];actual=identity(path);assert actual['sha256']==item['sha256'],path;bins[path]=dict(path=path,sha256=actual['sha256'],bytes=actual['bytes'])
value=dict(PASS=True,old_source_sha256=before['sha256'],new_source_sha256=after['sha256'],changed_paths=changed,compiled_product_and_test_sources_equal=True,original_result_sha_not_rewritten=True,scope='quality fixture planner only; completed CTest/Exact/Golden/bounded/reuse/native do not import or execute phase62_fix_quality.py; all recorded executable bytes match',evidence=rows,binaries=list(bins.values()),binary_records_checked=len(bins),note='Original F8 results remain attributed to F8. Their applicability is justified by this explicit source/dependency/binary audit; no results are silently relabelled F9.')
name='dependency_audit_after_main.json' if len(sys.argv)>1 else 'dependency_audit.json';(F/'evidence'/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(dict(PASS=True,binaries=len(bins),changed_paths=changed))
