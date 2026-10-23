"""ソース不変と成功buildに実行体を対応付ける。失敗時の旧binaryは使用しない。"""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'scripts'))
from phase62_evidence import identity,source_manifest
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,default=ROOT);p.add_argument('--build',type=Path,required=True);p.add_argument('--record',type=Path,required=True);p.add_argument('--config',default='Release');p.add_argument('--targets',nargs='+',required=True);a=p.parse_args();out=a.record.resolve();out.mkdir(parents=True,exist_ok=False);src=a.source.resolve();b=a.build.resolve();source=source_manifest(src)
def save(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
commands=[['cmake','-S',str(src),'-B',str(b),'-DCMAKE_BUILD_TYPE='+a.config,'-DCMAKE_OSX_ARCHITECTURES=arm64','-DBUILD_TESTING=ON'],['cmake','--build',str(b),'--target',*a.targets,'-j2']];save('EXPECTED.json',dict(source=source,commands=commands,configuration=a.config,compiler=subprocess.check_output(['clang++','--version'],text=True),targets=a.targets));rows=[]
for i,c in enumerate(commands):
 log=out/('configure.log' if i==0 else 'build.log')
 with log.open('w') as f:code=subprocess.run(c,stdout=f,stderr=subprocess.STDOUT).returncode
 rows.append(dict(command=c,exit=code,log=identity(log)))
 if code:break
ok=len(rows)==2 and all(r['exit']==0 for r in rows) and source_manifest(src)==source
save('BUILD.json',dict(status='PASS' if ok else 'FAIL',source=source['sha256'],source_root=str(src),source_manifest=source,configuration=a.config,architecture='arm64',rows=rows,binaries={t:identity(b/t) for t in a.targets} if ok else {}));print('build',ok,flush=True);raise SystemExit(0 if ok else 2)
