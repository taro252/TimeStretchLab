"""試験だけの最終変更を限定証明し、実際のrun出所を保持して統合する。"""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
BASE=ROOT/'build/phase62_e5_review_20261021_01'
def read(p):return json.loads(p.read_text())
def delta(a,b):
 a={x['path']:x['sha256'] for x in a['files']};b={x['path']:x['sha256'] for x in b['files']}
 return [dict(path=p,before=a.get(p),after=b.get(p)) for p in sorted(a.keys()|b.keys()) if a.get(p)!=b.get(p)]
def main():
 final=source_manifest(ROOT);b4=read(BASE/'BUILD_REVIEW_04.json');b6=read(BASE/'BUILD_REVIEW_06.json');b7=read(BASE/'BUILD_REVIEW_07.json')
 assert all(x['status']=='PASS' for x in [b4,b6,b7]);assert b7['source_inventory_sha256']==final['sha256']
 old=read(BASE/'review_functional_v2/EXPECTED.json')['source'];six=read(BASE/'review_functional_final_v2/EXPECTED.json')['source']
 assert b4['source_inventory_sha256']==old['sha256'] and b6['source_inventory_sha256']==six['sha256']
 changes=delta(old,final);assert [x['path'] for x in changes]==['scripts/phase62_review_validation.py','tests/Phase62FinishEvidenceTests.py','tests/Phase62PartialMixNative.cpp']
 assert [x['path'] for x in delta(six,final)]==['tests/Phase62PartialMixNative.cpp']
 for name,sha in b7['binaries'].items():
  assert identity(BASE/'candidate_build'/name)['sha256']==sha
  if name!='phase62_partial_mix_native':assert b4['binaries'][name]==b6['binaries'][name]==sha
 assert b4['compiler']==b6['compiler']==b7['compiler'] and b4['fp_policy']==b6['fp_policy']==b7['fp_policy']
 native=read(BASE/'NATIVE_EQUIVALENCE_AFTER_VALIDATOR.json')
 assert native['status']=='PASS' and native['checks']==184 and native['actual_run_source']==old['sha256']
 for item in native['python_runtime_closure']:assert identity(Path(item['path']))==item
 for row in native['rows']:
  for key in ['original_expected','original_summary']:assert identity(Path(row[key]['path']))==row[key]
 review=read(BASE/'review_functional_final_v2/SUMMARY.json');partial=read(BASE/'partial_final_v3/SUMMARY.json')
 assert review['status']==partial['status']=='PASS' and review['run_complete'] is True and partial['run_complete'] is True
 assert review['executed_programs']==review['expected_programs']==36 and review['executed_checks']==review['expected_checks']==202
 assert partial['source_inventory_sha256']==final['sha256'] and partial['executed_programs']==partial['expected_programs']==6 and partial['executed_checks']==partial['expected_checks']==6
 rows=[dict(x,actual_run_source=six['sha256']) for x in review['rows'] if not x['id'].startswith('partial_')]+[dict(x,actual_run_source=final['sha256']) for x in partial['rows']]
 assert len(rows)==36 and len({x['id'] for x in rows})==36 and {x['id'] for x in rows}==set(review['required_ids'])
 assert all(x['status']=='PASS' and x['exit']==0 and x['timeout'] is False and x['expected']==x['executed'] for x in rows)
 result=dict(schema=1,status='PASS',source_inventory_sha256=final['sha256'],source_delta_from_legacy=changes,
  binary_count=len(b7['binaries']),unchanged_binary_count=len(b7['binaries'])-1,unchanged_binaries=[x for x in b7['binaries'] if x!='phase62_partial_mix_native'],changed_binary='phase62_partial_mix_native',metadata_erratum='旧同一性証明のall_30_binaries_identicalというキー名は誤記。実際に全件照合したBUILD04/05/07の実行体は29点、最終差分で不変は28点。旧証明は保存し、本欄と実列挙を正とする。',
  scope='製品/DSPと他の試験コード・driver/importは同一。部分混合試験だけの故障確認/取り逃し記録を最終変更し、6本再実行。旧runのsource欄を付け替えない。',
  builds=[identity(BASE/('BUILD_REVIEW_'+v+'.json')) for v in ['04','06','07']],native_legacy=dict(certificate=identity(BASE/'NATIVE_EQUIVALENCE_AFTER_VALIDATOR.json'),checks=184,actual_run_source=old['sha256'],applicable_final_source=final['sha256']),
  review_functional=dict(expected_programs=36,executed_programs=36,expected_checks=202,executed_checks=sum(x['executed'] for x in rows),rows=rows,
   original_full=identity(BASE/'review_functional_final_v2/SUMMARY.json'),final_partial=identity(BASE/'partial_final_v3/SUMMARY.json')),
  driver=identity(Path(__file__)),old_runs_relabelled=False,local_overall_go=False)
 target=BASE/'FINAL_REVIEW_CERTIFICATE_v2.json';assert not target.exists();target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('PASS native184 + review202')
if __name__=='__main__':main()
