"""全音声試験終了後、成功した今回の作業領域と生成WAVだけを無損失保存する。"""
import gzip
import hashlib
import json
import lzma
import shutil
from pathlib import Path
from phase57_study import ROOT,sha
from phase59_fix_archive_profiles import closed


def main():
    out=ROOT/'results/phase59_fix';data=ROOT/'build/phase59_fix_artifacts/device_final'
    lock=out/'.storage_maintenance'
    with lock.open('x') as file:file.write('完了済み成功データの無損失保存中\n')
    try:
        assert json.loads((out/'COMPLETION_QUEUE.json').read_text())['stage']=='waiting_final_trace_capacity'
        assert (out/'device_final/summary.json').exists() and (out/'eos_after/summary.json').exists()
        log=out/'DEVICE_WORKING_ARCHIVES.json';assert not log.exists();rows=[]
        def preserve(sources,destination,opener):
            assert sources and not destination.exists()
            size=sources[0].stat().st_size;digest=sha(sources[0])
            assert all(p.stat().st_size==size and sha(p)==digest and closed(p) for p in sources)
            with sources[0].open('rb') as a,opener(destination,'xb') as b:shutil.copyfileobj(a,b,1<<20)
            restored=hashlib.sha256();count=0
            with opener(destination,'rb') as file:
                for block in iter(lambda:file.read(1<<20),b''):restored.update(block);count+=len(block)
            assert restored.hexdigest()==digest and count==size
            assert all(sha(p)==digest and closed(p) for p in sources)
            row=dict(sources=[str(p) for p in sources],bytes_each=size,sha256=digest,archive=str(destination),
                     archive_bytes=destination.stat().st_size,archive_sha256=sha(destination),restored_payload_verified=True,
                     uncompressed_sources_released=False,
                     restore='拡張子.gzはgzip、.xzはXZで展開し、各sourcesへ独立したファイルとして保存してbytes_eachとSHAを照合。既存ファイルは上書きしない。')
            rows.append(row);log.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            for path in sources:path.unlink()
            row['uncompressed_sources_released']=True
            log.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
        for folder in sorted(data.glob('dynamic_*')):
            summary=folder/'summary.json'
            if not summary.exists() or not json.loads(summary.read_text())['PASS']:continue
            groups={}
            for path in sorted((folder/'working').glob('*')):
                if path.is_file() and path.suffix in ('.f32','.bin') and path.stat().st_size>=1024**2:
                    groups.setdefault(sha(path),[]).append(path)
            for digest,sources in groups.items():
                preserve(sources,folder/'working'/('verified_'+digest+'.gz'),gzip.open)
        source=data/'dynamic_long/inputs/mix_repeated_300s.wav'
        if source.exists() and json.loads((source.parent.parent/'summary.json').read_text())['PASS']:
            manifest=json.loads((source.parent.parent/'manifest.json').read_text())
            expected=next(r['sha256'] for r in manifest['inputs'] if r['path']==str(source))
            assert sha(source)==expected
            preserve([source],source.with_suffix('.wav.xz'),lzma.open)
        print('completed success archives',len(rows),'free',shutil.disk_usage(ROOT).free,flush=True)
    finally:lock.unlink()


if __name__=='__main__':main()
