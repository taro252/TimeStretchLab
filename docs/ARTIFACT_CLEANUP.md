# 成果物の容量監査と可逆保管

`scripts/artifact_cleanup.py` は、現在のローカル作業ツリーの `results/` と `build/` を監査する。GitHubには存在しないignore対象も走査する。DSP、再生処理、音質基準、PCM完全一致の条件、既存のREPORTやmanifestは変更しない。Python 3標準ライブラリを基本とし、macOS Apple Siliconで動作する。変更操作にはmacOS標準の `lsof`、優先圧縮には任意の `zstd` コマンドを利用する。

## 分類と保護

| 分類 | 意味 | 処理 |
| --- | --- | --- |
| KEEP | 永久保護、または直近の成果物 | 圧縮・削除の対象外 |
| ARCHIVE | 資料で生成出力と確認できる古い成果物 | 可逆圧縮、全内容の検証後に別操作で削除可 |
| PRUNE | CMake構成・再ビルド手順が存在する、未参照の古いオブジェクト中間物 | 直接削除不可。明示指定でアーカイブを経由 |
| REVIEW | 用途不明、参照未確定、未解決のFAIL/NO-GO証拠等 | 自動操作しない |

Git追跡済みファイル、Golden、入力原本、固定参照、baseline、oracle、REPORT、manifest、ハッシュ、生成レシピを保護する。Phase 12のUSB二次保管はローカル正本の削除理由にしない。`PHASE12_ARTIFACT_CUSTODY.md` に記録された旧比較入力も、入力ファイルとして保持する。

保護判定はファイル名による追加保護だけに依存しない。Git index、JSON/JSONL/CSVの入力・参照・出力欄、manifestの明示的なroot、REPORT、ソース・コマンド内のパスを照合する。`phase3_output` 等の出力欄に現れても、他の資料がbaselineとして使用していればKEEPを優先する。単にmanifestのファイル一覧に載っているだけで用途が不明ならREVIEWにする。過去資料の参照元はアーカイブmanifestにも保存し、既存資料を修正しない。

Phase 47の `trace_inventory.json` の `reanalysis_needed` / `deletion_authorized:false` を尊重する。REPORTにNO-GO、未解決、原因未特定等があるPhaseは、未保管の原本証拠をREVIEWにする。Phase 57〜62の独立参照・凍結バイナリ、Phase 62/62 FixのNO-GO資料は期間だけでは整理しない。別の進行中Phaseは `--active-phase phaseXX` で追加できる。

初期期間は直近7日以内をKEEP、7日を超えた確認済み生成出力をARCHIVE、30日を超えた確認済み再生成中間物をPRUNEとする。年齢はmtime（最終更新時刻）から計算し、古さ・拡張子・ignore指定だけでは削除を許可しない。`--older-than-days` と `--prune-after-days` で変更できる。期間変更でも永久保護・未解決証拠の制約は解除しない。

未知の書式から用途を推測して整理する機能や、KEEP/REVIEWを強制解除する機能は設けない。新Phaseの出力は、既存のmanifestに入力、独立参照、生成出力を区別するパスとSHA-256を記録する。REVIEWを解消する際は、生成手順と実際の用途を確認したうえで、別の小さな来歴資料を追加する。過去のFAILや既存manifestは書き換えない。

## 容量確認とドライラン

リポジトリ直下で実行する。モード未指定時も読み取り専用のレポートになる。

```sh
python3 scripts/artifact_cleanup.py --report
python3 scripts/artifact_cleanup.py --dry-run
python3 scripts/artifact_cleanup.py --dry-run --phase phase49 --details
python3 scripts/artifact_cleanup.py --report --older-than-days 14 --prune-after-days 45
```

作業ツリー全体（`.git/`除外）、results/build、Phase、拡張子、WAV/生PCM/CSV/トレース、Git状態、分類、上位50ファイル・ディレクトリ、ディスク空きを表示する。親子ディレクトリの容量は重複するため合算しない。`--details` は保護・保留も含む全対象のパス、サイズ、理由を表示する。既定の候補表示はARCHIVEとPRUNEのみ。

詳細JSONは明示指定時だけ、新規ファイルへ保存する。対象一覧には参照元、期待SHA/サイズ、ファイル数、割当量も含む。既存ファイルは上書きしない。大量になるためGit管理外に保存する。

```sh
python3 scripts/artifact_cleanup.py --report --json /private/tmp/artifact_audit_01.json
```

読み取り専用レポートでは既存の全SHAを再計算しない。圧縮・削除を実行する直前に、対象の既存manifestの期待SHA・サイズを現物と比較する。複数資料の期待値が矛盾しても停止する。参照資料を読めない、Git状態を取得できない等の監査エラーでは変更操作を停止する。

## 推定削減量と実際の空き容量

論理サイズはファイルのバイト数、割当量は `st_blocks × 512`。作業ツリー全体の割当量にはディレクトリも含み、対象分類の割当量は収録ファイルの合計とする。APFSのクローン・ハードリンク・圧縮・スナップショット等により、これらは独占使用量を示さない。

圧縮削減量は候補ファイルの先頭・中央・末尾から最大各64KiBを読み、メモリ内のzlib圧縮率から求める**標本推定**。無音、ヘッダー偏り、実際のzstd/gzipの違いがあるため確約値ではない。同じ容量プールで圧縮物を残して原本を削除した後の論理差を想定する。別媒体へ保管すればローカル側の原本サイズに近い解放余地があるが、実際の空き増加は操作前後の測定で確認する。

圧縮だけでは原本を削除しないので、容量は一時的に増える。検証済みアーカイブを指定しない即時削除可能量は常に0。PRUNEも直接削除しない。圧縮・削除・復元時は空き容量の開始値・終了値・差を出力する。APFSや他プロセスの変動を含むため、論理削除量だけを容量回復成功とは判定しない。

## 可逆圧縮

対象の再生・検証・ビルド等を停止し、ドライランの対象と理由を確認してから実行する。`--confirm` はその確認を済ませた明示操作である。ここに示す圧縮・削除コマンドは手動運用例であり、今回の初回監査では実データには実行していない。

```sh
python3 scripts/artifact_cleanup.py --archive --phase phase49 --confirm
python3 scripts/artifact_cleanup.py --archive --phase phase49 \
  --archive-dir /Volumes/PrivateArchive/TimeStretchLab --confirm
```

既定はリポジトリの兄弟ディレクトリ `TimeStretchLab-artifact-archives/`。保存先はリポジトリ外に限定し、シンボリックリンクを含む経路を拒否する。`/tmp` 等のリンク表記は実体の `/private/tmp` を使用する。公開クラウドへアップロードする機能はない。著作権保護音源の保管先は、既存保管規則に沿ったアクセス制限のある非公開媒体を選ぶ。本ツール自体は暗号化を提供しない。

zstdがあれば `tar.zst`、なければ標準ライブラリの `tar.gz` を使う。WAV/PCMの符号化やサンプル値は一切変換しない。

```sh
python3 scripts/artifact_cleanup.py --archive --phase phase49 --compression gzip --confirm
```

`.trace` はディレクトリ内部を個別の整理対象にせず、パッケージ全体で分類・保管する。通常ファイルの内容、相対パス、空ディレクトリ、モード、mtime、macOS拡張属性を保存する。特殊ファイル、シンボリックリンク、ハードリンク共有対象は保留する。所有者・ACL等の完全なOSバックアップではなく、特殊な保管条件があるものは別途REVIEWで保持する。

必要空き容量は、元サイズ＋各ファイルのtar余裕10KiBに10%を加え、さらに64MiBを確保する保守的な上限。未圧縮tarは作らずストリーム圧縮する。空き不足ならペイロード作成前に停止する。容量プールの空きを複数パス分として加算しない。

作業中は専用の `.partial` ディレクトリを使い、全項目を展開してSHA-256を照合した後にのみ完成ディレクトリへ確定する。`.partial` 内のmanifestは通常の検証・削除には使えない。元ファイル、元資料、Git追跡状態の変更も確認する。同じ内容への再実行は既存の検証済みアーカイブを再利用する。

完成先の `archive_manifest.json` に元パス、サイズ、元SHA、アーカイブSHA、圧縮方式、圧縮前後サイズ、Phase、UTC作成時刻、検証結果、復元方法、参照元、空き容量を保存する。

PRUNE候補も保管してから整理したい場合に限り、対象Phaseを指定したうえで明示的に追加する。

```sh
python3 scripts/artifact_cleanup.py --archive --phase phaseXX \
  --include-regenerable --confirm
```

## 検証、削除、復元

`/path/to/archive_manifest.json` は実際に出力された完成manifestの絶対パスへ置き換える。

```sh
python3 scripts/artifact_cleanup.py --verify \
  --archive-manifest /path/to/archive_manifest.json
python3 scripts/artifact_cleanup.py --prune \
  --archive-manifest /path/to/archive_manifest.json --confirm
```

削除前にアーカイブSHA・サイズ・圧縮フレーム・全TAR項目・展開内容SHAを再検証し、現在の分類、Git状態、既存資料の期待値、元データのSHAとinode（ファイルの実体識別子）・mtime・ctime等を確認する。対象を開いているプロセスがあれば停止する。`lsof` が存在しない、警告を返す等の検査不能時も停止する。

削除は `build/.artifact_cleanup_transaction_<ID>/` への同一ファイルシステム内退避、再確認、削除の順に進める。退避中の失敗は元パスへ戻し、戻せなければ退避領域を保持する。削除途中の強制終了やI/O障害では残りが退避領域に残る。アーカイブ本体と過去のREPORT/manifestは削除しない。正常削除の空き容量と論理削除量はアーカイブ隣の `prune_receipt_*.json` に保存する。

元のディレクトリ構成へ復元する場合：

```sh
python3 scripts/artifact_cleanup.py --restore \
  --archive-manifest /path/to/archive_manifest.json --confirm
```

別領域へ復元試験する場合：

```sh
python3 scripts/artifact_cleanup.py --restore \
  --archive-manifest /path/to/archive_manifest.json \
  --restore-dir /Volumes/PrivateArchive/restore-check-01 --confirm
```

復元は新しい作業領域へ全内容を展開して現物SHAも再計算し、検証後に対象パスへ公開する。既存のファイルやtraceパッケージには上書きしない。Git追跡対象や `.git/` への復元、不正な相対パス、親のリンク経由の復元も拒否する。既存資料を使用する検証は、元の相対パスへ復元した後で実行する。アーカイブの存在だけで古い検証スクリプトが透過的に読めるようになるわけではない。

## 失敗時の対処

- SHA不一致：原本を変更しない。元manifest、保存先、別証拠の期待値を調査する。期待値の上書きで回避しない。
- `.partial`：未完成品。元データが残っていることを確認し、新規実行する。自動的な削除・完成品への昇格は行わない。
- 退避領域：`transaction.json` のmanifestを検証し、元パスと退避先を照合する。再実行で退避データを自動削除しない。空の別領域へアーカイブを復元し、SHAを確認して復旧する。
- 復元途中：既存パスを再実行で上書きしない。残った `.artifact_restore_*.partial` を保全し、別の空領域へ復元して比較する。
- 容量不足：別の専用媒体を指定する。既存の検証証拠や条件を削減して開始しない。
- 権限・リンク・Git・参照監査エラー：原因を解消してレポートから再開する。強制実行オプションはない。
- 使用中判定：対象を使う再生・検証・ビルドを正常終了してからやり直す。整理処理同士はディレクトリFDの排他ロックで競合を防ぐ。外部の生成処理はこのロックに従わないため、運用上停止する必要がある。使用状態・属性の再検査は行うが、検査直後に新たに書き始める外部処理までロックで停止することはできない。

## 定期運用とGit方針

1. Phase終了後、REPORT、入力・参照・出力の区別、SHA、生成手順を残す。
2. 定期的に `--report` / `--dry-run` を実行し、KEEP/REVIEWと空き容量を確認する。
3. 選んだ完了Phaseのみ圧縮し、別領域へ復元試験する。
4. 復元結果を確認してから、完成manifestを指定して削除する。
5. 削除前後の空き容量差を確認し、元パスが必要な再検証時には復元する。

自動スケジュールや自動削除は登録しない。大きな詳細レポート、アーカイブ、WAV、PCM、トレースはGit管理外に置く。`docs/GIT_ARTIFACT_POLICY.md` の **50,000,000バイト以上の新規Git blob禁止**、履歴全体のpush前検査を維持する。`.gitignore` は削除許可の根拠ではない。既存履歴・フックを変更せず、Git LFS移行、`git clean -fdx`、`git gc` は行わない。

```sh
python3 -B tests/ArtifactCleanupTests.py -v
python3 scripts/check_git_blob_sizes.py staged
```

テストは隔離した一時リポジトリと小さなデータだけを使う。実データのGolden・過去証拠は使用しない。

## 範囲の絞り込みと実装上の上限

圧縮を特定のファイル・サブディレクトリに限定するには `--path` を使う。KEEP/REVIEWの解除には使えない。複数Phaseにまたがる指定は拒否する。通常のCMake中間物にはPhaseが付かないため、この明示指定を利用する。

```sh
python3 scripts/artifact_cleanup.py --archive \
  --path build/CMakeFiles/対象.dir/対象.cpp.o \
  --include-regenerable --confirm
```

参照資料は最大32MiBを構造解析する。上限を超えるmanifest・来歴資料や、壊れた参照表は監査エラーとして表示する。巨大な数値データ表にはパス欄の有無を確認して不要な構造解析を省き、ディレクトリ参照は用途ごとにまとめる。ディレクトリ単位の全参照元は詳細JSONとアーカイブmanifestの別索引に残す。アーカイブmanifestが40MiBを超える見込みなら、ペイロード作成前に `--path` で分割するよう案内する。

現物が見つからない期待SHA付き参照は詳細JSONの `missing_references` で確認できる。レポートだけでは全現物のSHA一致を保証しない。復元したファイルはinode/ctimeが変わるため、古いmanifestによる再削除を拒否する場合がある。その場合は再監査し、現在の現物を新たに保管してから操作する。

同梱ライブラリの `plot_dependencies` / `site-packages` / `node_modules`、CMakeの `CMakeFiles`、Pythonの `__pycache__` にあるGit非追跡の資料は、検証証拠の参照元として解析しない。これらも全容量と分類の対象であり、外側のPhase manifestに記録された参照は維持する。ライブラリのサンプルCSVを検証用manifestと混同することを防ぐ。削除・復元ではmanifestが実行範囲を固定するため、`--phase` / `--path` を同時指定して一部分だけ処理することはできない。

`missing_references` は、資料から求めた候補保存場所に現物を結び付けられない記録である。実際の消失、旧パス、相対パスの基点の不明、過去アーカイブへの移動を区別する調査が必要で、件数だけでデータ消失とは判定しない。
