"""大容量証拠の全manifestは管理外に置き、GitにはSHAと復元情報を残す。"""
import json
import shutil
import subprocess
from collections import Counter
from phase59_fix2_start_state import ROOT, OUT, sha


def main():
    base=ROOT/'build/phase59_fix2_artifacts';manifest=base/'artifact_files.jsonl'
    assert json.loads((OUT/'COMPLETION_QUEUE.json').read_text())['stage']=='required_regressions_completed'
    excluded={manifest,base/'inventory_driver.log',base/'delivery_audit_driver.log',base/'report_driver.log'}
    paths=sorted(p for p in base.rglob('*') if p.is_file() and p not in excluded)
    counts=Counter();sizes=Counter();large=[];total=0
    with manifest.open('w') as file:
        for path in paths:
            size=path.stat().st_size;digest=sha(path);relative=path.relative_to(base);group=relative.parts[0]
            row=dict(path=str(path),bytes=size,sha256=digest)
            file.write(json.dumps(row,ensure_ascii=False)+'\n');total+=size;counts[group]+=1;sizes[group]+=size
            if size>=50_000_000:large.append(row)
    scripts=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in sorted((ROOT/'scripts').glob('phase59_fix2_*')) if p.is_file()]
    index=dict(artifact_root=str(base),files=len(paths),total_bytes=total,free_bytes=shutil.disk_usage(ROOT).free,
        full_manifest=dict(path=str(manifest),bytes=manifest.stat().st_size,sha256=sha(manifest),format='UTF-8 JSON Lines; one path/bytes/SHA-256 record per file'),
        groups=[dict(name=g,files=counts[g],bytes=sizes[g]) for g in sorted(counts)],
        large_git_excluded_files=large,generation_scripts=scripts,
        recipes=[
            'Release: cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64; cmake --build build -j3（別々のコマンド）',
            '最終固定: scripts/phase59_fix2_freeze.py。既存保存先へ上書きせず、新しい作業場所で実行する。',
            'PCM: phase59_fix2_validation.py --frozen <final>、Checks: phase59_fix2_checks.py --debug-build <newDebug>。各下位manifestに独立参照SHAと全コマンド。',
            '実機: phase59_fix2_device.py --frozen <final>。実行前の品質成功条件・装置条件・直列制約を維持。',
            'OS: phase59_fix2_trace.py / synced_trace.py / delayed_trace.py。各manifestに実行体SHA、正式xctrace引数、取得予算。',
            '追加比較: phase59_fix2_legacy.py / legacy_same_rate.py / deep_legacy.py / workgroup_minimal.py。別ビルドの生成ソースとリンク引数を保存。',
            '図: python3 -B scripts/phase59_fix2_timeline_data.py → Swift Chartsをtimeline.swiftからコンパイル → renderer figures.json results/phase59_fix2/figures（原本以外の新規作業場所で再生成）。'],
        restore=[
            '原本はartifact_rootの絶対パスに保持。移送した場合は全JSONLの相対位置を保ち、各bytes/SHA-256を照合して戻す。traceはbundle全体を復元する。',
            '基準HEADはSTART_STATE/FINAL_CANDIDATE参照。別ディレクトリへそのGit内容を展開し、final/sourceのsrc・CMakeLists.txt・保存testsを重ねる。保存済みXcode/SDK/arm64設定で再ビルドする。',
            '再ビルドしたバイナリの同一SHAは前提にせず、新SHAで全PCM生ビット比較と実機期限を再検証する。元の独立参照を置換しない。',
            '成功PCMの一部は作業領域を再利用済み。入力SHA・参照実行体SHA・生成レシピ・出力SHAで再生成する。失敗PCM・OS原本はそのまま保存。',
            'OSトレースは非決定的証拠で、同じ記録を再生成できない。再試験は新しい記録として扱い、保存した原本の代替にしない。'],
        historical_assets_removed=False,git_managed_payloads='報告/JSON/図/ソースのみ。50,000,000 bytes以上の新規blobなし。',
        no_commit_or_push=True)
    (OUT/'ARTIFACT_INDEX.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
    print('indexed',len(paths),'files',total,'bytes; full manifest',manifest.stat().st_size,'bytes',flush=True)


if __name__=='__main__':main()
