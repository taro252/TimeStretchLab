"""解析済みの今回のXML出力を全バイト照合して無損失保存する。"""
import gzip
import hashlib
import json
import shutil
from pathlib import Path
from phase57_study import ROOT,sha
from phase59_fix_archive_profiles import closed
from phase58_fix_trace_analyze import complete_export


def main():
    out=ROOT/'results/phase59_fix';data=ROOT/'build/phase59_fix_artifacts'
    assert (out/'EOS_TRACE_OBSERVATIONS.json').exists()
    assert (data/'clock_audio_trace/analysis/summary.json').exists()
    log=out/'XML_ARCHIVES.json';assert not log.exists();rows=[]
    for name in ('clock_audio_trace','eos_unpaced_trace'):
        for source in sorted((data/name).rglob('*.xml')):
            if source.stat().st_size<1024**2:continue
            assert complete_export(source) and closed(source)
            destination=source.with_suffix('.xml.gz');assert not destination.exists()
            digest=sha(source);size=source.stat().st_size
            with source.open('rb') as a,gzip.open(destination,'xb',compresslevel=4) as b:
                shutil.copyfileobj(a,b,1<<20)
            restored=hashlib.sha256();count=0
            with gzip.open(destination,'rb') as file:
                for block in iter(lambda:file.read(1<<20),b''):restored.update(block);count+=len(block)
            assert restored.hexdigest()==digest and count==size and sha(source)==digest and closed(source)
            row=dict(source=str(source),bytes=size,sha256=digest,archive=str(destination),
                     archive_bytes=destination.stat().st_size,archive_sha256=sha(destination),
                     restored_payload_verified=True,uncompressed_source_released=False,
                     restore='gzipを元のsourceパスへ展開し、bytesとSHA-256を照合してから再解析する。既存ファイルは上書きしない。')
            rows.append(row);log.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            source.unlink();row['uncompressed_source_released']=True
            log.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    print('XML compressed',len(rows),'logical bytes saved',sum(r['bytes']-r['archive_bytes'] for r in rows),flush=True)


if __name__=='__main__':main()
