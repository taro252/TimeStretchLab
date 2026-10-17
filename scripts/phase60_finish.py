"""全曲音声試験の終了を待ち、追加ライフサイクルと記録を直列に完了する。"""
import hashlib,json,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'build/phase60';OUT=ROOT/'results/phase60'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    full=OUT/'native_user_canonical/summary.json'
    while not full.exists():time.sleep(2)
    rows=[]
    def run(name,cmd,audio=False):
        print(name,'開始',flush=True);started=time.time();log=DATA/(name+'.log');attempt=1
        while log.exists():attempt+=1;log=DATA/(name+'_attempt_'+str(attempt)+'.log')
        with log.open('x') as f:p=subprocess.run(list(map(str,cmd)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
        r={'name':name,'command':list(map(str,cmd)),'exit':p.returncode,'wall_s':time.time()-started,'log':str(log),'audio':audio};rows.append(r);(OUT/'FINISH_DRIVER.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,p.returncode,flush=True);return r
    measured=DATA/'measured_bin';measured.mkdir(exist_ok=True)
    names=['phase60_playback_compare','phase60_adapter_tests','libmacos_progressive_playback_engine.a','libphase58_realtime.a','libphase57_synthesis.a','libphase59_transition.a','libphase56_incremental.a','libphase39_variable.a','libphase36_variable.a','libphase24_variable.a','libtimestretch_core.a']
    for name in names:
        if not (measured/name).exists():shutil.copy2(ROOT/'build'/name,measured/name)
    if not (measured/'phase60_legacy_compare').exists():shutil.copy2(DATA/'approved_legacy/release/phase60_legacy_compare',measured/'phase60_legacy_compare')
    libraryBefore={n:sha(measured/n) for n in names if n.endswith('.a')}
    for folder,label in [('build','release'),('build/phase60/debug','debug')]:
        configured=run('final_'+label+'_configure',['cmake','-S',ROOT,'-B',folder,'-DCMAKE_BUILD_TYPE='+('Release' if label=='release' else 'Debug'),'-DCMAKE_OSX_ARCHITECTURES=arm64'])
        if configured['exit']:return 2
        r=run('final_'+label+'_build',['cmake','--build',folder,'--target','phase60_playback_compare','phase60_lifecycle_tests','phase60_bridge_example','-j3'])
        if r['exit']:return 2
    assert all(sha(ROOT/'build'/n)==h for n,h in libraryBefore.items()),'RT library changed during JSON-only correction'
    extra=[]
    for folder,label in [('build','release'),('build/phase60/debug','debug')]:extra.append(run('extra_'+label,[ROOT/folder/'phase60_lifecycle_tests',ROOT/'results/phase31/input/mix.wav'],True))
    (OUT/'LIFECYCLE_EXTRA.json').write_text(json.dumps({'PASS':all(r['exit']==0 for r in extra),'rows':extra,'scope':'prepare→auto-play取消3回、Playing/Paused要求中Stop、曲切替、入力消失/復旧、対応位置標本'},ensure_ascii=False,indent=2)+'\n')
    capture=DATA/'final_host_smoke.f32';smoke=DATA/'final_host_smoke'
    s=run('final_host_smoke',[ROOT/'build/phase60_playback_compare',ROOT/'results/phase31/input/mix.wav','--engine=progressive','--out='+str(smoke),'--capture='+str(capture)],True)
    ref=DATA/'final_host_smoke_reference.f32';r=run('final_host_reference',[ROOT/'build/phase58_frozen/product_reference',ROOT/'results/phase31/input/mix.wav',1000000,'candidate',ref])
    exact=s['exit']==r['exit']==0 and sha(capture)==sha(ref) and capture.stat().st_size==ref.stat().st_size
    (OUT/'FINAL_HOST.json').write_text(json.dumps({'PASS':exact,'callback_pcm_sha256':sha(capture) if capture.exists() else None,'reference_sha256':sha(ref) if ref.exists() else None,'api_libraries_identical_to_full_song_measurement':True,'library_sha256':libraryBefore,'measured_host':str(measured/'phase60_playback_compare'),'measured_host_sha256':sha(measured/'phase60_playback_compare'),'final_host_sha256':sha(ROOT/'build/phase60_playback_compare'),'source_scope':'最終CLIは通常側JSON欄の意味を訂正。RTライブラリは全曲測定版と同じSHA。'},ensure_ascii=False,indent=2)+'\n')
    run('restart_driver',['python3','-B','scripts/phase60_restart_compare.py'],True)
    run('report_driver',['python3','-B','scripts/phase60_report.py'])
    run('inventory_driver',['python3','-B','scripts/phase60_inventory.py'])
    run('delivery_audit',['python3','-B','scripts/phase60_delivery_audit.py'])
    run('report_final',['python3','-B','scripts/phase60_report.py'])
    run('delivery_audit_final',['python3','-B','scripts/phase60_delivery_audit.py'])
    result={'PASS':all(r['exit']==0 for r in rows) and exact,'rows':rows}
    (OUT/'FINISH.json').write_text(json.dumps(result,indent=2)+'\n');return 0 if result['PASS'] else 2
if __name__=='__main__':raise SystemExit(main())
