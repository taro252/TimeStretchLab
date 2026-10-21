"""未コミットのコード・文書・小証拠を識別する。ステージ/コミットは行わない。"""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import source_manifest
OUT=ROOT/'results/phase62_e5_review/ARTIFACTS.json'
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--refresh-archive',type=Path);args=parser.parse_args()
 if OUT.exists():
  assert args.refresh_archive,'既存索引の更新前には全byteの退避を指定する'
  archive=json.loads(args.refresh_archive.read_text());old={r['path']:r for r in archive['files']}[str(OUT.relative_to(ROOT))]
  data=OUT.read_bytes();assert len(data)==old['bytes'] and hashlib.sha256(data).hexdigest()==old['sha256']
  saved=Path(archive['archive_root'])/OUT.relative_to(ROOT);assert saved.read_bytes()==data
 assert not git('diff','--cached','--name-only').strip()
 subprocess.run(['git','diff','--check'],cwd=ROOT,check=True)
 manifest=json.loads((OUT.parent/'MANIFEST.json').read_text());source=source_manifest(ROOT)
 assert source['sha256']==manifest['source_inventory_sha256']
 assert git('rev-parse','HEAD').decode().strip()==manifest['head']
 rows=[]
 paths=git('ls-files','--modified','--others','--exclude-standard','-z').split(b'\0')
 for raw in sorted(set(paths)):
  if not raw:continue
  relative=raw.decode();path=ROOT/relative
  if path==OUT:continue
  data=path.read_bytes();assert len(data)<50_000_000,relative
  rows.append(dict(path=relative,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
 encoded=json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
 tracked=git('diff','--binary','HEAD','--')
 result=dict(schema=1,status=manifest['status'],local_overall_go=manifest['local_overall_go'],head=manifest['head'],branch=manifest['branch'],uncommitted=True,staged=False,source_inventory_sha256=source['sha256'],inventory_sha256=hashlib.sha256(encoded).hexdigest(),inventory_encoding='UTF-8 JSON sort_keys=True separators=(comma,colon)',tracked_diff_sha256=hashlib.sha256(tracked).hexdigest(),tracked_diff_bytes=len(tracked),file_count=len(rows),files=rows,self_excluded=True,large_ignored_evidence='build/phase62_e5_review_20261021_01',checks=dict(diff_check='PASS',new_file_size_limit_bytes=50_000_000,new_file_sizes='PASS',staged_empty=True),mandatory_gate_status=manifest['status'],remaining=manifest['remaining_required'],recovery_history=str(args.refresh_archive) if args.refresh_archive else None)
 OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print('artifact index',len(rows),'files;',manifest['status'],'; no stage/commit')
if __name__=='__main__':main()
