"""Phase60の必要範囲だけをビルド・回帰。音声実機試験と同時実行しない。"""
import hashlib,json,subprocess,sys,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    data=ROOT/'build/phase60/quality';data.mkdir(exist_ok=False);out=ROOT/'results/phase60';rows=[]
    def run(name,cmd):
        if shutil.disk_usage(ROOT).free<8*1024**3:raise RuntimeError('Disk floor 8GiB')
        cmd=list(map(str,cmd));t=time.time()
        with (data/(name+'.log')).open('x') as log:p=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        row={'name':name,'command':cmd,'exit':p.returncode,'wall_s':time.time()-t,'log':str(data/(name+'.log'))};rows.append(row);(out/'QUALITY_DRIVER.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,p.returncode,flush=True)
        return p.returncode==0
    refs=json.loads((ROOT/'results/phase59_fix/FROZEN_REFERENCES.json').read_text())
    for path,entry in refs.items():
        if Path(path).name in ('product_reference','dynamic_reference','captured_reference','reference'):
            with (ROOT/path).open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==entry['sha256'],path
    targets='phase60_playback_compare phase60_contract_tests phase60_adapter_tests phase60_bridge_example phase59_tests phase59_control_tests phase58_tests phase58_fix_tests phase58_fix_mailbox_tests phase58_fix_worker_tests phase57_tests phase56_tests phase56_fixed_modes phase54_analysis_tests phase54_seek_tests phase59_fix_vocoder_tests phase59_fix_stereo_tests phase56_check phase56_reference phase57_check phase57_reference phase59_reference phase59_check phase59_progressive_replay phase59_captured_reference phase58_check phase58_product_reference phase54_core_probe'.split()
    assert run('release_build',['cmake','--build','build','--target',*targets,'-j3'])
    regex='^(phase60_|phase59_|phase58_|phase57_|phase56_|phase54_)'
    run('release_related',['ctest','--test-dir','build','-R',regex,'--output-on-failure','-j2'])
    debug=ROOT/'build/phase60/debug'
    if run('debug_configure',['cmake','-S',ROOT,'-B',debug,'-DCMAKE_BUILD_TYPE=Debug','-DCMAKE_OSX_ARCHITECTURES=arm64','-DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF']):
        if run('debug_build',['cmake','--build',debug,'--target',*targets,'-j3']):
            run('debug_related',['ctest','--test-dir',debug,'-R',regex,'--output-on-failure','-j2'])
    run('frozen_fixed',[sys.executable,'-B','tests/Phase58PcmSmoke.py','build/phase58_check','build/phase58_frozen/product_reference'])
    run('frozen_dynamic',[sys.executable,'-B','tests/Phase59PcmSmoke.py','build/phase59_frozen/dynamic_reference','build/phase59_check','build/phase59_progressive_replay','build/phase59_frozen/captured_reference'])
    run('golden_25',[sys.executable,'-B','scripts/phase57_golden.py','--output',data/'golden'])
    run('blob_guard',[sys.executable,'-B','tests/GitBlobSizeGuardTests.py','-v'])
    summary={'PASS':all(r['exit']==0 for r in rows),'rows':rows,'frozen_references_checked':True,'full_research_matrices_rerun':False,'dsp_arithmetic_changed':False}
    (out/'QUALITY.json').write_text(json.dumps(summary,indent=2)+'\n')
    return 0 if summary['PASS'] else 2
if __name__=='__main__':raise SystemExit(main())
