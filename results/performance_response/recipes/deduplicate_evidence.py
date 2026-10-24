"""今回作成した完了済みrunの同一RAWを共有する。全パス/内容/SHAを保持し、監査を残す。"""
import argparse,json,os,pathlib,sys
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import identity
B=R/'build/performance_response_20261023_01'
p=argparse.ArgumentParser();p.add_argument('--roots',nargs='+',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
assert a.output.resolve().is_relative_to(B) and not a.output.exists()
files=[]
for root in a.roots:
 root=root.resolve();assert root.is_relative_to(B) and root.is_dir()
 # A completed row in an incomplete attempt may still be retained. The caller
 # must select an idle run; hashes/paths are checked before and after each link.
 files.extend(root.rglob('*.f32'))
record=dict(recipe=identity(__file__),scope='new performance_response evidence only; identical immutable RAW; all paths and SHA retained',files=[],replaced=0,logical_duplicate_bytes_shared=0)
def save():a.output.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
save();seen={}
for path in sorted(files):
 old=identity(path);key=(old['bytes'],old['sha256']);source=seen.get(key)
 if source is None:seen[key]=path;continue
 assert identity(source)['sha256']==old['sha256']
 if os.stat(source).st_ino==os.stat(path).st_ino:continue
 temporary=path.with_name(path.name+'.dedup_tmp');assert not temporary.exists()
 os.link(source,temporary);assert identity(temporary)['sha256']==old['sha256'];os.replace(temporary,path)
 assert identity(path)==old
 record['files'].append(dict(file=old,shared_with=identity(source)));record['replaced']+=1;record['logical_duplicate_bytes_shared']+=old['bytes'];save()
record['complete']=True;save();print(json.dumps({k:record[k] for k in ['complete','replaced','logical_duplicate_bytes_shared']}))
