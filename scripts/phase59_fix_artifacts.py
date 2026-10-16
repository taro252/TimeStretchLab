"""全実行終了後に、今回のGit管理外成果物の現存内容と復元手順を記録する。"""
import json
from pathlib import Path
from phase57_study import ROOT, sha


def main():
    out=ROOT/'results/phase59_fix';data=ROOT/'build/phase59_fix_artifacts'
    assert json.loads((out/'COMPLETION_QUEUE.json').read_text())['stage']=='completed'
    files=[]
    for path in sorted(data.rglob('*')):
        if path.is_symlink():
            files.append(dict(path=str(path),symlink=str(path.readlink())));continue
        if not path.is_file():continue
        before=path.stat();digest=sha(path);after=path.stat()
        assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'Artifact changed during final inventory'
        files.append(dict(path=str(path),bytes=after.st_size,sha256=digest))
    archives=[p for p in out.glob('*ARCHIVE*.json')]
    archives.append(out/'validation_final/success_working_archives.json')
    index=dict(artifact_root=str(data),files=files,total_bytes=sum(r.get('bytes',0) for r in files),
               script_sha256=sha(Path(__file__)),
               archive_restore_manifests=[dict(path=str(p),sha256=sha(p)) for p in archives if p.exists()],
               generation_recipes=[dict(path=str(p),sha256=sha(p)) for p in sorted(out.rglob('manifest.json'))],
               restore='現存ファイルをpathへ復元してbytes/SHAを照合する。圧縮済み原本はarchive_restore_manifestsの復元コマンドと展開後SHAを使用。成功PCMの再利用で残らない中間サンプル列は、各caseの独立参照command/input SHA/PCM SHAを用いて再生成する。過去Phaseの固定参照はFROZEN_REFERENCES.jsonから取得する。',
               historical_assets_removed=False,git_managed_payloads=False)
    target=out/'ARTIFACT_INDEX.json'
    encoded=json.dumps(index,ensure_ascii=False,indent=2)+'\n'
    assert len(encoded.encode())<50_000_000
    target.write_text(encoded)
    print('artifact inventory',len(files),'files',index['total_bytes'],'bytes',flush=True)


if __name__=='__main__':main()
