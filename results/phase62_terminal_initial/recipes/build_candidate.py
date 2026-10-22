"""成功binaryと不変source inventoryの対応を保存する。旧binaryは使用しない。"""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--configuration',default='Release');a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);b=a.build.resolve();source=source_manifest(ROOT)
targets=['phase62_initial_entry_native','phase62_initial_checkpoint_tests','phase62_initial_loop_native','phase62_history_clear_native','phase62_loop_speed_ledger_tests','phase62_paused_clear_native','phase62_playing_ledger_native','phase62_adoption_review_native','phase62_fix_reuse_tests']
cmds=[['cmake','-S',str(ROOT),'-B',str(b),'-DCMAKE_BUILD_TYPE='+a.configuration,'-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON'],['cmake','--build',str(b),'--target',*targets,'-j2']]
def save(name,v):(out/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
save('EXPECTED.json',dict(source=source,commands=cmds,configuration=a.configuration,targets=targets));rows=[]
for i,c in enumerate(cmds):
 log=out/('configure.log' if i==0 else 'build.log')
 with log.open('w') as f:code=subprocess.run(c,stdout=f,stderr=subprocess.STDOUT).returncode
 rows.append(dict(command=c,exit=code,log=identity(log)))
 if code:break
ok=len(rows)==2 and all(r['exit']==0 for r in rows) and source_manifest(ROOT)==source
save('BUILD.json',dict(status='PASS' if ok else 'FAIL',source=source['sha256'],source_manifest=source,configuration=a.configuration,architecture='arm64',compiler=subprocess.check_output(['clang++','--version'],text=True),rows=rows,binaries={x:identity(b/x) for x in targets} if ok else {}));print('build',ok,flush=True);raise SystemExit(0 if ok else 2)
