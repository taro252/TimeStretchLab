import os,sys,subprocess,json,hashlib
from pathlib import Path
R=Path.cwd();OUT=R/'results/phase62_fix';sys.path.insert(0,str(R/'scripts'));from phase62_evidence import identity
encoded=set(subprocess.check_output(['git','diff','--name-only','HEAD','-z'],cwd=R).split(b'\0'))|set(subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=R).split(b'\0'))
rows=[]
for data in sorted(v for v in encoded if v):
 name=os.fsdecode(data)
 if name=='results/phase62_fix/CHANGED_FILES.json':continue
 old=subprocess.run(['git','show','HEAD:'+name],cwd=R,capture_output=True);p=R/name
 rows.append(dict(path=name,old_sha256=hashlib.sha256(old.stdout).hexdigest() if old.returncode==0 else None,new=identity(p) if p.is_file() else None))
(OUT/'CHANGED_FILES.json').write_text(json.dumps(dict(base_head='d25433c88a1bae83b89168a26f1c6c9d8053a644',self_excluded='CHANGED_FILES.json',files=rows),indent=2)+'\n')
print('changed files:',len(rows))
