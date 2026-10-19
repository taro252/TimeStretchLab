"""検証原本と同一の小さな再生成コードをGit候補へ保存する。大容量データはコピーしない。"""
import sys,json,shutil,time
from pathlib import Path
R=Path.cwd();F=R/'build/phase62_fix/run_01/final_v9';OUT=R/'results/phase62_fix/recipes';sys.path.insert(0,str(R/'scripts'));from phase62_evidence import identity,source_manifest
while not (F/'boundary_methods/SUMMARY.json').is_file():time.sleep(5)
assert source_manifest(R)==json.loads((F/'FROZEN_SOURCE.json').read_text())
OUT.mkdir(exist_ok=False);rows=[]
for p in sorted(F.iterdir()):
 if not p.is_file() or p.suffix not in ('.py','.cpp') or p.name in ('phase62_fix_quality_corrected.py','preflight_then_final.py'):continue
 dest=OUT/p.name;shutil.copy2(p,dest);old=identity(p);new=identity(dest);assert old['sha256']==new['sha256'];rows.append(dict(original=old,recipe=new))
ORACLE=R/'build/phase61/oracle_release_v1';backup=F/'frozen_oracle_backup';backup.mkdir()
shutil.copy2(ORACLE/'phase61_frozen_reference',backup/'phase61_frozen_reference')
for name in ('manifest.json','compile.log','link.log'):
 p=ORACLE/name
 if p.is_file():
  dest=OUT/('oracle_'+name);shutil.copy2(p,dest);rows.append(dict(original=identity(p),recipe=identity(dest)))
(R/'results/phase62_fix/RECIPE_MANIFEST.json').write_text(json.dumps(dict(schema=1,files=rows,oracle_backup=identity(backup/'phase61_frozen_reference'),notes='Exact copies of executed supplemental recipes. Fixed run paths describe this original evidence; use fresh output paths or a separate workspace for re-execution. Never overwrite original evidence.'),ensure_ascii=False,indent=2)+'\n')
print(dict(recipes=len(rows),oracle_backup=identity(backup/'phase61_frozen_reference')),flush=True)
