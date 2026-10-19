"""Phase62のソース復元資料と、Git管理外の検証資料のSHA-256を記録する。"""
import argparse
import datetime
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 50_000_000


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def record(path, root):
    return dict(path=str(path.relative_to(root)), bytes=path.stat().st_size,
                sha256=sha(path))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    out = args.output.resolve()
    if out == run or run in out.parents:
        raise ValueError('manifestの出力先は検証資料ディレクトリの外へ指定してください')
    out.mkdir(parents=True, exist_ok=True)

    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=ROOT)

    names = set(git('diff', '--name-only', '-z', 'HEAD').split(b'\0'))
    names.update(git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0'))
    sources = sorted(ROOT / name.decode() for name in names if name)
    # 集計・manifest自身との循環参照を避ける。資料は別manifestに記録する。
    sources = [p for p in sources if p.is_file() and 'results/phase62' not in str(p.relative_to(ROOT))]
    source_rows = [record(p, ROOT) for p in sources]
    if any(row['bytes'] >= LIMIT for row in source_rows):
        raise ValueError('新規Git候補が50,000,000バイト以上です')
    archive = run / 'final_sources.tar.gz'
    with archive.open('xb') as stream:
        with tarfile.open(fileobj=stream, mode='w:gz') as tar:
            for path in sources:
                tar.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    (out / 'SOURCE_MANIFEST.json').write_text(json.dumps(dict(
        base_sha=git('rev-parse', 'HEAD').decode().strip(), files=source_rows,
        archive=record(archive, ROOT)), ensure_ascii=False, indent=2) + '\n')

    rows = [record(p, run) for p in sorted(run.rglob('*')) if p.is_file()]
    manifest = out / 'ARTIFACT_MANIFEST.json'
    manifest.write_text(json.dumps(dict(root=str(run), files=len(rows),
        total_bytes=sum(r['bytes'] for r in rows), entries=rows), ensure_ascii=False, indent=2) + '\n')
    reference = ROOT / 'build/phase61/oracle_release_v1/phase61_frozen_reference'
    provenance = dict(created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        base_sha=git('rev-parse', 'HEAD').decode().strip(),
        branch=git('branch', '--show-current').decode().strip(),
        artifact_manifest=record(manifest, out), reference=record(reference, ROOT),
        source_manifest=record(out / 'SOURCE_MANIFEST.json', out),
        reference_manifest=json.loads((reference.parent / 'manifest.json').read_text()),
        source_version_notes=[
            '主実機行列・1000周・既存回帰はcore_v2_sources/manifest.jsonのソース。保存済みSHAと全件一致。',
            '最終版では入力喪失のFailed分類、Armed速度予約の保持、全曲初回の余裕と供給確認、callback診断条件を補強。',
            'DSPと混合の算術は維持。最終版のRelease/Debug再ビルドとCTest、操作・障害・全曲の追加試験を区別して保存。',
            '実行ごとのバイナリSHAは各suite/provenance.json等。全成績を最終バイナリ一個の実測とは扱わない。'],
        restore=[
            '基準SHAの新しい作業コピーへfinal_sources.tar.gzを展開しSOURCE_MANIFESTのSHAを照合する。既存作業を上書きしない。',
            'REPORTのコマンドと各commands.jsonで新規build出力先へ再生成する。既存oracle/証拠は上書きしない。',
            '既存の実測ログ・PCMを完全復元する場合はこのroot全体を別ストレージへ保存しARTIFACT_MANIFESTで照合する。',
            '実測時刻・CPU・RSSは再実行で同値にはならない。manifestは実測資料の同一性を記録する。'])
    (out / 'PROVENANCE.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(files=len(rows), total_bytes=sum(r['bytes'] for r in rows),
        manifest_sha256=sha(manifest), archive_sha256=sha(archive))))


if __name__ == '__main__':
    main()
