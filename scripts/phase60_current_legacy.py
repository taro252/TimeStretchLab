"""Phase60と同じcheckoutのLegacy経路でも、指定音源の自然EOSを確認する。"""
import hashlib,json,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'results/phase60';DATA=ROOT/'build/phase60'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    while not (OUT/'FINISH.json').exists():time.sleep(2)
    checked=OUT/'FINISH_REVIEWED.json' if (OUT/'FINISH_REVIEWED.json').exists() else OUT/'FINISH.json'
    assert json.loads(checked.read_text())['PASS'],'Inspect finish failure before more playback'
    source=Path(json.loads((OUT/'INPUT.json').read_text())['wav']);binary=ROOT/'build/phase60_playback_compare';folder=DATA/'current_legacy_user'
    cmd=[str(binary),str(source),'--engine=legacy-current','--preset=candidate','--speed=1.00','--verify-pcm','--out='+str(folder)]
    started=time.time();print('current_legacy_user 開始',flush=True)
    with (DATA/'current_legacy_user.log').open('x') as log:r=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
    summary=json.loads((folder/'summary.json').read_text()) if (folder/'summary.json').exists() else None
    oracle=json.loads((DATA/'native_user_canonical/user_2_progressive_reference.json').read_text())
    exact=bool(summary and len(summary['sessions'])==1 and summary['sessions'][0]['published_pcm_sha256']==oracle['pcm_sha256'] and summary['sessions'][0]['published_frames']==oracle['output_frames'])
    result={'name':'current_legacy_user','command':cmd,'exit':r.returncode,'wall_s':time.time()-started,'binary_sha256':sha(binary),'summary':summary,'pcm':{'PASS':exact,'scope':'現行Legacy公開raw全PCM','reference_sha256':oracle['pcm_sha256'],'reference_binary':'build/phase58_frozen/product_reference'},'comparison_scope':'Phase60と同じcheckoutの既存Legacy製品経路。承認039592eと区別する。'}
    (OUT/'CURRENT_LEGACY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('current_legacy_user',r.returncode,'PCM',exact,flush=True)
    for script,log in [('phase60_report.py','report_current.log'),('phase60_inventory.py','inventory_driver.log'),('phase60_delivery_audit.py','delivery_audit_final.log')]:
        with (DATA/log).open('w') as f:subprocess.run(['python3','-B','scripts/'+script],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    return 0 if r.returncode in (0,2) and exact else 2
if __name__=='__main__':raise SystemExit(main())
