"""成功した今回の前後性能計測CSVを、全バイトの復元SHAを検証して圧縮する。"""
import gzip
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from phase57_study import ROOT,sha


def closed(path):
    r=subprocess.run(['lsof','-n','-P',str(path)],capture_output=True,text=True)
    return r.returncode==1 and not r.stdout.strip() and not r.stderr.strip()


def main():
    ledger=[];log=ROOT/'results/phase59_fix/PERFORMANCE_CSV_ARCHIVES.json';assert not log.exists()
    for name in ('phase_before_v2','phase_after'):
        data=ROOT/'build/phase59_fix_artifacts'/name
        for summary in sorted(data.glob('*/summary.json')):
            assert json.loads(summary.read_text())['PASS'],'Failed original must remain untouched'
            for source in sorted(summary.parent.glob('*.csv')):
                if source.stat().st_size<1024**2 or not closed(source):continue
                destination=source.with_suffix('.csv.gz');assert not destination.exists()
                digest=sha(source);size=source.stat().st_size
                with source.open('rb') as a,gzip.open(destination,'xb',compresslevel=4) as b:shutil.copyfileobj(a,b,1<<20)
                h=hashlib.sha256();count=0
                with gzip.open(destination,'rb') as f:
                    for block in iter(lambda:f.read(1<<20),b''):h.update(block);count+=len(block)
                assert h.hexdigest()==digest and count==size and sha(source)==digest
                row=dict(source=str(source),bytes=size,sha256=digest,archive=str(destination),archive_bytes=destination.stat().st_size,
                    archive_sha256=sha(destination),restored_payload_verified=True,uncompressed_source_released=False,
                    restore='gzipを元のsourceパスへ展開し、サイズとSHAを照合してから解析する。既存ファイルは上書きしない。')
                ledger.append(row);log.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
                if closed(source):source.unlink();row['uncompressed_source_released']=True
                log.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n')
    if not log.exists():log.write_text('[]\n')
    print('profile CSV archives',len(ledger),'logical bytes saved',sum(x['bytes']-x['archive_bytes'] for x in ledger if x['uncompressed_source_released']))


if __name__=='__main__':main()
