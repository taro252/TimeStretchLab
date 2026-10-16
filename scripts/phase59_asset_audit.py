"""Protect the pre-change tracked tree and independent reference hashes."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from phase57_study import ROOT,sha
BASE='bb22efcbd27f999e8ffe85bbe3f03e20895be3f2'
ALLOWED={'CMakeLists.txt',*[f'src/prototype/{n}' for n in ['Phase36SynthesisCore.h','Phase39TimeMap.cpp','Phase39TimeMap.h',
    'Phase57ProgressiveSynthesis.cpp','Phase57ProgressiveSynthesis.h','Phase58Diagnostics.h',
    'Phase58FixSnapshotMailbox.h','Phase58Native.mm','Phase58RealtimePipeline.cpp','Phase58RealtimePipeline.h']]}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'results/phase59/protected_assets.json');args=parser.parse_args()
    changed=subprocess.check_output(['git','diff','--name-only',BASE],cwd=ROOT,text=True).splitlines()
    unexpected=[p for p in changed if p not in ALLOWED]
    sources=json.loads((ROOT/'results/phase59/START_STATE.json').read_text())
    references={str(Path('build/phase59_frozen')/p):h for p,h in sources['binary_sha256'].items()}
    references.update({'build/phase58_frozen/product_reference':'3a3b04454f754c35afa4cac121a726fa31c44a6854761a7de5f71aa057f2a957',
        'build/phase57_frozen/reference':'461c26d10b0fd8a781cbffcbbab49072f501e02172e2a7c2f26e3e49a0253a1e'})
    for manifest,name in [('FROZEN_REFERENCE.json','dynamic_reference'),('CAPTURED_REFERENCE.json','captured_reference')]:
        info=json.loads((ROOT/'results/phase59'/manifest).read_text())
        references[str(Path('build/phase59_frozen')/name)]=info.get('binary_sha256',info.get('dynamic_reference_sha256'))
    checked={p:dict(expected=h,actual=sha(ROOT/p)) for p,h in references.items()}
    tree=subprocess.check_output(['git','ls-tree','-r',BASE],cwd=ROOT,text=True)
    result=dict(baseline=BASE,tracked_files=len(tree.splitlines()),baseline_tree_sha256=hashlib.sha256(tree.encode()).hexdigest(),
        changed_tracked=changed,unexpected_changes=unexpected,reference_hashes=checked,
        PASS=not unexpected and all(v['expected']==v['actual'] for v in checked.values()))
    output=args.output
    if output.exists():raise RuntimeError('Choose a fresh audit name; preserve earlier evidence')
    output.write_text(json.dumps(result,indent=2)+'\n');print(result['PASS'],result['tracked_files'],unexpected)
if __name__=='__main__':main()
