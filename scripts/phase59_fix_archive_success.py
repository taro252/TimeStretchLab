"""完了済み全PCM回帰の成功作業領域だけを、復元SHA付きで無損失圧縮する。"""
import argparse
import gzip
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from phase57_study import ROOT,sha


def closed(path):
    result=subprocess.run(['lsof','-n','-P',str(path)],capture_output=True,text=True)
    return result.returncode==1 and not result.stdout.strip() and not result.stderr.strip()


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--tag',default='final');args=parser.parse_args()
    report=ROOT/'results/phase59_fix'/('validation_'+args.tag)
    summary=report/'effective_summary.json'
    if not summary.exists():summary=report/'summary.json'
    assert json.loads(summary.read_text())['PASS']
    data=ROOT/'build/phase59_fix_artifacts'/('validation_'+args.tag)
    ledger=[];log=report/'success_working_archives.json'
    assert not log.exists()
    candidates=list(data.glob('*/working/*'))
    recovery=ROOT/'build/phase59_fix_artifacts'/('validation_recovery_'+args.tag)
    if recovery.exists():
        assert json.loads((ROOT/'results/phase59_fix'/('validation_recovery_'+args.tag)/'summary.json').read_text())['PASS']
        candidates+=list(recovery.glob('*/working/*'))
    for source in sorted(candidates):
        if source.is_symlink() or not source.is_file() or source.suffix not in ('.f32','.bin') or source.stat().st_size<1024**2:continue
        if not closed(source):
            ledger.append(dict(source=str(source),uncompressed_source_released=False,reason='使用中またはopen FD検査不能のため保持'))
            log.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n');continue
        destination=source.with_suffix(source.suffix+'.gz');assert not destination.exists()
        digest=sha(source);size=source.stat().st_size
        with source.open('rb') as a,gzip.open(destination,'xb',compresslevel=4) as b:shutil.copyfileobj(a,b,1<<20)
        restored=hashlib.sha256();count=0
        with gzip.open(destination,'rb') as file:
            for block in iter(lambda:file.read(1<<20),b''):restored.update(block);count+=len(block)
        assert restored.hexdigest()==digest and count==size and sha(source)==digest
        row=dict(source=str(source),bytes=size,sha256=digest,archive=str(destination),archive_bytes=destination.stat().st_size,
                 archive_sha256=sha(destination),restored_payload_verified=True,uncompressed_source_released=False,
                 restore='gzipを展開してsourceの絶対パスへ保存し、bytesとSHA-256を照合する。既存ファイルは上書きしない。')
        ledger.append(row);log.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
        if closed(source):source.unlink();row['uncompressed_source_released']=True
        log.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
    if not log.exists():log.write_text('[]\n')
    print('success working archives',len(ledger),'logical bytes saved',sum(x['bytes']-x['archive_bytes'] for x in ledger if x.get('uncompressed_source_released')),flush=True)


if __name__=='__main__':main()
