"""新しいソース台帳と実行体を対応付ける有限のビルド。失敗時は実行体を登録しない。"""
import argparse,json,os,pathlib,subprocess,sys
R=pathlib.Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'scripts'))
from phase62_evidence import source_manifest,identity
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True)
p.add_argument('--build',type=pathlib.Path,required=True);p.add_argument('--configuration',default='Release',choices=['Release','Debug'])
p.add_argument('--targets',nargs='+',required=True);a=p.parse_args();o=a.output.resolve();o.mkdir(parents=True,exist_ok=False)
before=source_manifest(R)
def save(n,v):(o/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
record=dict(status='INCOMPLETE',source=before['sha256'],source_manifest=before,source_root=str(R),configuration=a.configuration,architecture='arm64',rows=[],binaries={})
save('EXPECTED.json',dict(source=before,targets=a.targets,driver=identity(__file__)))
env=dict(os.environ,PATH='/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin')
commands=[['cmake','-S',str(R),'-B',str(a.build.resolve()),'-DCMAKE_BUILD_TYPE='+a.configuration,'-DCMAKE_OSX_ARCHITECTURES=arm64','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DBUILD_TESTING=ON'],['cmake','--build',str(a.build.resolve()),'--target',*a.targets,'-j2']]
for name,cmd in zip(['configure','build'],commands):
 with (o/(name+'.log')).open('w') as f:rc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,env=env).returncode
 record['rows'].append(dict(command=cmd,exit=rc,log=identity(o/(name+'.log'))));save('BUILD.json',record)
 if rc:record['status']='FAIL';save('BUILD.json',record);raise SystemExit(rc)
assert source_manifest(R)['sha256']==before['sha256'],'source changed during build'
record['binaries']={target:identity(a.build/target) for target in a.targets}
record['compile_commands']=identity(a.build/'compile_commands.json')
record['status']='PASS';save('BUILD.json',record);print(json.dumps(dict(status='PASS',source=record['source'],targets=len(a.targets))))
