"""Rebuild independent references from the recorded pre-change Git tree."""
import argparse,io,json,shutil,subprocess,tarfile
from pathlib import Path
from phase57_study import ROOT,sha
BASE='bb22efcbd27f999e8ffe85bbe3f03e20895be3f2'
def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);source=out/'baseline';source.mkdir();build=out/'build'
    archive=subprocess.check_output(['git','archive',BASE,'CMakeLists.txt','src','tests','scripts','examples'],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if member.name.startswith('/') or '..' in Path(member.name).parts:raise ValueError('Unsafe archive path')
        tar.extractall(source)
    records=[]
    def run(command,label):
        with (out/(label+'.log')).open('x') as f:r=subprocess.run(list(map(str,command)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
        records.append(dict(command=list(map(str,command)),exit=r.returncode));assert r.returncode==0,label
    run(['cmake','-S',source,'-B',build,'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64'],'configure')
    run(['cmake','--build',build,'--target','phase39_variable','phase36_variable','phase24_variable','-j2'],'libraries')
    drivers=ROOT/'results/phase59/reference_driver_sources'
    include=out/'driver_include';(include/'prototype').mkdir(parents=True)
    for header in drivers.glob('*.h'):shutil.copy2(header,include/'prototype'/header.name)
    for stem in ['Reference','CapturedReference']:
        name='dynamic_reference' if stem=='Reference' else 'captured_reference'
        run(['/usr/bin/c++','-O3','-DNDEBUG','-std=c++20','-arch','arm64','-I'+str(source/'src'),'-I'+str(include),
            drivers/('Phase59'+stem+'.cpp'),build/'libphase39_variable.a',build/'libphase36_variable.a',
            build/'libphase24_variable.a',build/'libtimestretch_core.a','-framework','Accelerate','-o',out/name],name)
    (out/'manifest.json').write_text(json.dumps(dict(baseline=BASE,commands=records,
        driver_sources={f.name:sha(f) for f in drivers.iterdir() if f.is_file()},
        binary_sha256={name:sha(out/name) for name in ['dynamic_reference','captured_reference']},
        note='絶対パス・コンパイラー由来の識別子でバイナリSHAは元と異なる場合がある。品質の再検証には元と同じ入力・計画・生PCM比較を行う。'),indent=2,ensure_ascii=False)+'\n')
if __name__=='__main__':main()
