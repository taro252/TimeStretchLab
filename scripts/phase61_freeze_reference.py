"""Build a full-render oracle with the pre-Phase57 DSP object first in link order."""
import argparse,hashlib,json,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='ec087019626d9ff0d9f157245729b74ddb6847d7'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--build',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    build=a.build.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    source=out/'Phase36Legacy.cpp';source.write_bytes(subprocess.check_output(['git','show',BASE+':src/prototype/Phase36StreamingSpeedEngine.cpp'],cwd=ROOT))
    link=shlex.split((build/'CMakeFiles/phase61_seek_reference.dir/link.txt').read_text())
    flags=next(line.split('=',1)[1].strip() for line in (build/'CMakeFiles/phase61_seek_reference.dir/flags.make').read_text().splitlines() if line.startswith('CXX_FLAGS ='))
    obj=out/'Phase36Legacy.o';binary=out/'phase61_frozen_reference'
    compile_cmd=[link[0],*shlex.split(flags),'-arch','arm64','-I'+str(ROOT/'src'),'-c',str(source),'-o',str(obj)]
    link.insert(1,str(obj));link[link.index('-o')+1]=str(binary)
    rows=[]
    for name,cmd in [('compile',compile_cmd),('link',link)]:
        log=out/(name+'.log')
        with log.open('x') as f:p=subprocess.run(cmd,cwd=build,stdout=f,stderr=subprocess.STDOUT)
        rows.append({'name':name,'command':cmd,'exit':p.returncode,'log':str(log)})
        if p.returncode:raise RuntimeError(str(log))
    manifest={'source_commit':BASE,'source_sha256':sha(source),'host_source_sha256':sha(ROOT/'src/prototype/Phase61SeekReference.cpp'),'driver_sha256':sha(Path(__file__)),'flags':flags,'commands':rows,'build':str(build),'binary':str(binary),'binary_sha256':sha(binary),'restore':'git show the source_commit path; run the recorded compiler and link commands in build. Never overwrite an existing frozen reference.'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(manifest),flush=True)
if __name__=='__main__':main()
