"""検証器だけの変更後、成功した既存native子runの同一性を別証明する。"""
import ast,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
BASE=ROOT/'build/phase62_e5_review_20261021_01'
def read(p):return json.loads(p.read_text())
def main():
 before=read(BASE/'BUILD_REVIEW_04.json');after=read(BASE/'BUILD_REVIEW_05.json');old=read(BASE/'review_functional_v2/EXPECTED.json')['source'];new=source_manifest(ROOT)
 assert before['status']==after['status']=='PASS' and before['source_inventory_sha256']==old['sha256'] and after['source_inventory_sha256']==new['sha256']
 a={r['path']:r['sha256'] for r in old['files']};b={r['path']:r['sha256'] for r in new['files']};delta=[p for p in sorted(a.keys()|b.keys()) if a.get(p)!=b.get(p)]
 assert delta==['scripts/phase62_review_validation.py','tests/Phase62FinishEvidenceTests.py']
 assert before['binaries']==after['binaries'];assert before['compiler']==after['compiler'] and before['fp_policy']==after['fp_policy']
 for name,sha in after['binaries'].items():assert identity(BASE/'candidate_build'/name)['sha256']==sha
 roots=[ROOT/'scripts'/name for name in ['phase62_finish_control_validation.py','phase62_finish_validation.py','phase62_api_oracle_audit.py','phase62_evidence.py']]
 roots.append(ROOT/'results/phase62_finish/recipes/run_focused_final.py');pending=roots[:];closure={}
 while pending:
  p=pending.pop();key=str(p.relative_to(ROOT))
  if key in closure:continue
  assert key not in delta;closure[key]=identity(p)
  if key in a:assert a[key]==closure[key]['sha256']
  for node in ast.walk(ast.parse(p.read_text())):
   names=[n.name for n in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) and node.module else []
   for name in names:
    q=ROOT/'scripts'/(name.split('.')[0]+'.py')
    if q.exists():pending.append(q)
 cases=[('control',BASE/'focused_final_v1/control',42),('cache',BASE/'focused_final_v1/cache',12),('playing',BASE/'focused_final_v1/playing',74),('api',BASE/'api_final_v2',16),('paused_clear',BASE/'remaining_focused_v1/paused_clear',24),('race_candidate',BASE/'remaining_focused_v1/race_candidate',8),('race_baseline',BASE/'remaining_focused_v1/race_baseline',8)]
 rows=[]
 for name,path,count in cases:
  s=read(path/'SUMMARY.json')
  if name.startswith('race_'):assert s['expected']==s['executed']==s['PASS']==count
  else:assert s['status']=='PASS' and s['run_complete'] is True and s['executed_checks']==s['expected_checks']==count
  expected=path/'EXPECTED.json'
  if name.startswith('race_'):expected=path.parent/'EXPECTED.json'
  rows.append(dict(id=name,expected=count,executed=count,status='PASS',original_summary=identity(path/'SUMMARY.json'),original_expected=identity(expected),actual_run_source=old['sha256']))
 result=dict(schema=1,status='PASS',scope='上記成功native子runのみ。旧失敗outer/API runと新review validator自身は対象外',actual_run_source=old['sha256'],applicable_final_source=new['sha256'],source_delta=[dict(path=p,before=a.get(p),after=b.get(p)) for p in delta],all_binaries_identical=True,binary_count=len(after['binaries']),build_before=identity(BASE/'BUILD_REVIEW_04.json'),build_after=identity(BASE/'BUILD_REVIEW_05.json'),python_runtime_closure=list(closure.values()),rows=rows,checks=sum(r['executed'] for r in rows),old_runs_relabelled=False,driver=identity(Path(__file__)),reason='変更2Pythonはこのnative実行経路/実行体の依存でない。全使用driver/import、製品・試験ソース、compiler/FP条件と全29実行体SHAが一致。新review validatorは最終版で別途36program再実行。')
 target=BASE/'NATIVE_EQUIVALENCE_AFTER_VALIDATOR.json';assert not target.exists();target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('PASS',result['checks'])
if __name__=='__main__':main()
