"""今回作成した保存済みtrace bundleだけを、全内容照合とopen FD確認後に圧縮保存する。"""
import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
import time
from pathlib import Path
from phase57_study import ROOT,sha


def require_closed(bundle):
    result=subprocess.run(['lsof','-n','-P','+D',str(bundle)],capture_output=True,text=True)
    if result.returncode not in (0,1) or result.stdout.strip() or result.stderr.strip():
        raise RuntimeError('使用中またはopen FD検査不能のため原本を保持: '+result.stdout+result.stderr)


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('manifest',type=Path);args=parser.parse_args()
    manifest_path=args.manifest.resolve();manifest=json.loads(manifest_path.read_text())
    assert manifest_path.is_relative_to(ROOT/'results/phase59_fix')
    bundle=Path(manifest['trace_bundle']).resolve()
    assert bundle.name=='focused.trace' and bundle.is_relative_to(ROOT/'build/phase59_fix_artifacts') and bundle.is_dir()
    require_closed(bundle)
    archive=bundle.with_suffix('.trace.tar.gz');assert not archive.exists()
    ledger=[]
    for p in sorted(bundle.rglob('*')):
        if p.is_symlink():ledger.append(dict(relative=str(p.relative_to(bundle)),symlink=p.readlink().as_posix()))
        elif p.is_file():ledger.append(dict(relative=str(p.relative_to(bundle)),bytes=p.stat().st_size,sha256=sha(p)))
    before=shutil.disk_usage(ROOT).free;start=time.time()
    with tarfile.open(archive,'x:gz',compresslevel=4) as tar:tar.add(bundle,arcname=bundle.name)
    with tarfile.open(archive,'r:gz') as tar:
        for entry in ledger:
            member=tar.getmember(bundle.name+'/'+entry['relative'])
            if 'symlink' in entry:
                assert member.issym() and member.linkname==entry['symlink']
            else:
                digest=hashlib.sha256();count=0
                with tar.extractfile(member) as file:
                    for block in iter(lambda:file.read(1<<20),b''):digest.update(block);count+=len(block)
                assert digest.hexdigest()==entry['sha256'] and count==entry['bytes']
    # 検査中の変更・新規openも拒否する。ktrace一時領域には一切触れない。
    for entry in ledger:
        p=bundle/entry['relative']
        if 'sha256' in entry:assert sha(p)==entry['sha256']
        else:assert p.readlink().as_posix()==entry['symlink']
    require_closed(bundle)
    record=dict(input_manifest=str(manifest_path),input_manifest_sha256=sha(manifest_path),
        bundle=str(bundle),archive=str(archive),archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,
        restored_payloads_verified=True,files=ledger,script_sha256=sha(Path(__file__)),
        free_before_bytes=before,elapsed_s=time.time()-start,uncompressed_bundle_released=False,
        restore_command=['tar','-xzf',str(archive),'-C',str(bundle.parent)],
        restore='上記コマンドで元のbundleへ復元し、filesの全SHA-256を照合。既存bundleがある場合は別の空ディレクトリへ展開して比較する。')
    log=ROOT/'results/phase59_fix'/('TRACE_ARCHIVE_'+bundle.parent.name+'.json')
    with log.open('x') as file:file.write(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    shutil.rmtree(bundle)
    record['uncompressed_bundle_released']=True;record['free_after_bytes']=shutil.disk_usage(ROOT).free
    log.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print('archived',bundle.parent.name,'bytes',record['archive_bytes'],'free',record['free_after_bytes'],flush=True)


if __name__=='__main__':main()
