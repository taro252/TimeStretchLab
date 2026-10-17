"""承認Phase54を別CMake graph/別プロセス用に構築。既存checkoutは変更しない。"""
import hashlib,json,subprocess,tarfile,io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SHA='039592e59cc1a525b495e38d3cedeb6c050792b1'
def main():
    out=ROOT/'build/phase60/approved_legacy';out.mkdir(parents=True,exist_ok=True)
    source=out/'source'
    if not source.exists():
        source.mkdir()
        archive=subprocess.check_output(['git','archive',SHA,'CMakeLists.txt','src','examples'],cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(source,filter='data')
    if not (source/'tests').exists():
        archive=subprocess.check_output(['git','archive',SHA,'tests'],cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(source,filter='data')
    tree=subprocess.check_output(['git','ls-tree','-rz',SHA,'--','CMakeLists.txt','src','examples','tests'],cwd=ROOT)
    for entry in tree.split(b'\0'):
        if not entry:continue
        info,name=entry.split(b'\t',1);mode,kind,oid=info.split()
        if kind!=b'blob':continue
        p=source/name.decode();data=p.read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        if actual!=oid.decode():raise RuntimeError('承認ソースSHA不一致: '+str(p))
    project=out/'project';project.mkdir(exist_ok=True)
    (project/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.21)\nproject(Phase60ApprovedLegacy LANGUAGES CXX OBJCXX)\nset(CMAKE_CXX_STANDARD 20)\nset(BUILD_TESTING OFF CACHE BOOL "" FORCE)\nadd_subdirectory("'+str(source)+'" legacy EXCLUDE_FROM_ALL)\nadd_executable(phase60_legacy_compare "'+str(ROOT/'src/playback/Phase60LegacyCompare.mm')+'")\ntarget_compile_options(phase60_legacy_compare PRIVATE -fobjc-arc -Wall -Wextra)\ntarget_link_libraries(phase60_legacy_compare PRIVATE macos_playback_engine)\n')
    commands=[['cmake','-S',str(project),'-B',str(out/'release'),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64'],['cmake','--build',str(out/'release'),'--target','phase60_legacy_compare','-j3']]
    for i,cmd in enumerate(commands):
        with (out/f'build_{i}.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    binary=out/'release/phase60_legacy_compare'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    manifest={'legacy_sha':SHA,'binary':str(binary),'binary_sha256':sha(binary),'host_sha256':sha(ROOT/'src/playback/Phase60LegacyCompare.mm'),'commands':commands,'approved_source_blobs_verified':True,'separate_process_required':True}
    # The original approved source is exported verbatim, independent of current changes.
    manifest['source_files']={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
    (ROOT/'results/phase60/LEGACY_BUILD.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(binary,flush=True)
if __name__=='__main__':main()
