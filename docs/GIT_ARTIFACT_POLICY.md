# Gitへ保存する検証成果物の容量

Phase 59 Fix以降、**50,000,000バイト以上の新規blobをコミット・Pushしない**。blobはGitが保持するファイル内容であり、ディスク上の圧縮サイズではなく、復元した内容のバイト数で判定する。

## 検査とフック

```sh
git config --local core.hooksPath .githooks
python3 scripts/check_git_blob_sizes.py staged
python3 scripts/check_git_blob_sizes.py history --base origin/main --tip HEAD
```

pre-commitはステージ済みの変更ファイルのblobを検査する。作業ファイルだけを小さくしても、indexに大容量の内容が残っていれば拒否する。pre-pushはGitが渡す送信refと、送信先が現在広告するrefから、新規に到達可能となる全履歴を検査する。中間コミットで追加後に削除したblobも対象となる。最終ツリーだけの確認では代替できない。

pre-pushでは送信先へ読み取り専用の `git ls-remote` を行う。取得できない場合は検査不能として中止する。ローカルにないremoteオブジェクトを除外根拠には使わないため、必要ならfetchして再検査する。上の手動history検査はローカルのorigin/mainが最新である場合の補助検査であり、実際のpre-push検査も実施する。

フックはこの作業環境で有効化済み。新しいcloneでは設定を行う。既存の別フックがある環境では、その内容を確認せず上書きしない。

境界値49,999,999/50,000,000、indexと作業ファイルの差、履歴途中の大容量blob、remote既存履歴、新規branch、検査エラーを、隔離した一時リポジトリで検証する。

```sh
python3 -B tests/GitBlobSizeGuardTests.py -v
```

## Git管理外へ保存する内容

新しいWAV、PCM、マップの生バイナリ、XML、トレース、固定実行体、圧縮アーカイブは原則 `build/phaseXX_artifacts/` などへ保存する。詳細CSVや行データが大きくなる場合も、同じ場所へ保存する。小さな集計・manifest・生成レシピはresultsへ保存する。

各成果物には以下を記録する。

- 内容のSHA-256とバイト数。
- 保存場所の絶対パス。
- 入力・実行体のSHA、Git基準、実行コマンド、品質設定。
- 再生成レシピ、または無損失圧縮からの復元方法と復元SHA。
- 成功・失敗・未実施の区別。必要なFAIL原本は保持する。

`.gitignore`は追跡済みファイルを除外しない。Phase 59以前の50MB以上のblobは `results/phase59_fix/START_STATE.json` に記録した。既存履歴と原本は保持し、以後の新規blobと区別する。履歴の書換え、証拠削除、Git LFSへの移行は無断で行わない。

品質基準、PCM完全一致、速度行列、反復数、実機条件は容量のために削減しない。保存先を確保できない場合は、未実施条件を記録して試験開始を止める。
