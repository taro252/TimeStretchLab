import os,json,subprocess,sys,hashlib
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';OUT=R/'results/phase62_fix'
sys.path.insert(0,str(R/'scripts'));from phase62_evidence import source_manifest,identity
commands=[]
def run(cmd,cwd=R):
 p=subprocess.run(cmd,cwd=cwd,capture_output=True,text=True);commands.append(dict(command=list(map(str,cmd)),cwd=str(cwd),exit=p.returncode,stdout=p.stdout,stderr=p.stderr));return p
assert json.loads((F/'ORIGINAL_PHASE62_AUDIT.json').read_text())['PASS']
assert json.loads((F/'evidence/dependency_audit_after_sandbox.json').read_text())['PASS']
assert source_manifest(R)==json.loads((F/'FROZEN_SOURCE.json').read_text())
assert run(['git','rev-parse','HEAD']).stdout.strip()=='d25433c88a1bae83b89168a26f1c6c9d8053a644'
assert run(['git','branch','--show-current']).stdout.strip()=='main'
assert run(['git','diff','--check']).returncode==0
assert run(['python3','scripts/check_git_blob_sizes.py','staged']).returncode==0
assert not run(['git','diff','--cached','--name-only']).stdout
assert not run(['git','diff','HEAD','--','results/phase62']).stdout
M=Path('/Users/taro252/Docker/merodoa')
assert run(['git','rev-parse','HEAD'],M).stdout.strip()=='c52fde5c06a56fe7acf74617bb90583dfdb9dcf1'
assert not run(['git','status','--porcelain'],M).stdout
encoded=set(subprocess.check_output(['git','diff','--name-only','HEAD','-z'],cwd=R).split(b'\0'))|set(subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=R).split(b'\0'))
rows=[];self_path='results/phase62_fix/FINAL_CHECKS.json'
for data in sorted(v for v in encoded if v):
 name=os.fsdecode(data);path=R/name
 if name==self_path:continue
 if path.is_file():rows.append(dict(path=name,bytes=path.stat().st_size))
violations=[r for r in rows if r['bytes']>=50_000_000]
value=dict(PASS=not violations and all(row['exit']==0 for row in commands),source_unchanged=True,original_phase62_all_9678_sha_match=True,final_binary_audit_pass=True,threshold_bytes=50_000_000,staged_empty=True,candidate_scope='tracked unstaged plus untracked, including small results manifests; ignored build artifacts excluded',candidates=rows,violations=violations,self_excluded_from_rows=True,self_size_checked_after_write=True,commands=commands)
path=R/self_path;path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');assert path.stat().st_size<50_000_000
assert not violations
assert all(row['exit']==0 for row in commands)
print(dict(PASS=True,candidates=len(rows)+1,max_bytes=max([path.stat().st_size]+[r['bytes'] for r in rows]),self_bytes=path.stat().st_size))
