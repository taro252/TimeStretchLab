# Phase 53 Post-Handoff Fixes

基準：`233c773bbc77e5824c36134915f68d6d3a0d581e`。本作業は検証処理の修正に限定する。`phase53-handoff` は基準コミットに固定し、動かさない。

## 1. 原本CSVと補正後CSVの検証

`phase53_sessions.validate_plans()` で原本を先に厳密検証し、補正後にも同じ検査を行う。ヘッダーの列・順序・重複、各行の列数、整数項目、有限値・負値、最終改行、保存件数、計画世代と操作履歴、対象速度・適用/完了座標を照合する。

計画には拒否された要求の世代が含まれないため、計画世代を単純な連番にはしない。操作履歴の要求世代と照合し、完了した操作の計画欠落をFAILにする。現行記録では停止時の `plan_rows` を必須とする。旧記録では完了した操作から照合し、キャンセル時の計画件数を証明できない場合はFAILにする。欠損した件数を推定で補わない。

証拠の `plan_csv.original` と `plan_csv.corrected` に判定・理由・行数・SHA-256を分離保存する。`plan_csv.conversion` に両ハッシュ、変換理由、対象列 `density_input`、倍率1024、許可判定を記録する。補正後がPASSでも、原本FAILはCSV全体のFAILとして残る。

`phase52_recheck_controls.py` は補正前の完全性を保存し、正常な原本に対してだけ共通の変換関数を呼ぶ。許可する差分は `density_input` のMidフレーム単位から入力サンプル単位への変換だけ。他の列、行順、世代、件数、理由なしの変換、違う倍率は拒否する。原本を上書きせず、補正先が既存なら拒否する。

通常検証・補正後検証・参照再生ができなかった経路も、既存の `phase52_verdict.finalize()` で最終判定する。元の音声・計測・CSV FAILは全体とセッション別に保持する。不正なCSVから参照DSPを再生しない。

## 2. 終了済みセッションの操作状態

正常EOSは `Ended/EOS/eos=1`、User StopとRouteChangedは `Stopped/eos=0` を確認する。既存の音声判定も独立して適用する。

終端状態は `Completed / Replaced / Duplicate / Rejected / Cancelled / Configured` に限定する。`Pending / Submitted / Applied`、未知・空の状態が終了時の記録に残ればFAIL。停止・経路変更によるCancelled、最新要求へのReplaced、安全なRejectedは正常終端として検証可能にする。

操作IDは完了順に記録されるので、行順をID順に強制しない。欠落・重複を検査する。sessionの範囲、session内の要求世代の順序・欠落・重複、送信時刻、Completedの完了時刻・座標、同じ世代の計画との一致を検査する。以前のセッションの履歴を含む最終CSVも扱う。再生ライフサイクルには変更しない。

## 3. 障害注入と保存済み実機記録

新規 `phase53_post_handoff_integrity` は20テストメソッドと各パラメータ試験。指定された原本/補正後の8条件、ヘッダー・列数、変換倍率・他列変更、補正先の上書き禁止、補正CLIでの最終改行欠損、旧記録の計画欠損、EOS・Stop・RouteChanged、Latest-Winsの置換、拒否・キャンセル、未完了/未知状態、ID/session/generation不一致を検証した。全件成功。不正証拠の検出成功は音声品質PASSを意味しない。

保存済みPhase 53実機結果を読み取り専用で再検証した。

| バッチ | 試行 | セッション | 再検証 |
| --- | ---: | ---: | --- |
| `20261014_165756_567871` | 7 | 10 | 全PASS |
| `20261014_171604_300553` | 7 | 10 | 全PASS |

保存済みの独立参照WAVとFIFO公開PCMのSHA-256、停止時の接頭部、EOSの全長を照合した。新しい実機再生や音質評価は行っていない。最初の `20261014_165255` は音声装置へのアクセス不成立で、検証可能な実機記録がない。既存の失敗記録を保持し、成功14件に含めない。

`completion_revalidation/saved_native_review.json` に全試行の新旧判定、各CSVの証拠、元ファイルの再検証前後ハッシュを保存した。元のPhase 53ディレクトリのファイル集合・バイトは一致し、原本レポート・CSV・WAV・検証JSONは上書きしていない。初回とソース確定時の再検証結果も `revalidation/`、`revalidation_final/` に別保存した。

## 4. 回帰と差分監査

最終ソース・Release/arm64ビルドでの結果：

- 決定論的CTest **73/73 PASS、344.56秒**。新規20メソッド、既存の26個のセッションfixture、DSP/PCM/TimeMap/状態管理の全件を含む。
- 独立の実時間CTest **2/2 PASS、58.38秒**。通常条件と故意の不足・遅刻の検出を含む。既存の音声FAIL/INVALID判定は変更していない。今回の成功を長尺高負荷の一般的な安定性保証とは扱わない。
- 最終CTest後にも、保存済み実機14試行・20セッションと保護資産を再照合し、すべて一致。結果は `completion_revalidation/`。

`ctest_deterministic.log`、`ctest_realtime.log`、`fault_injection_final.log` に全結果を保存する。実時間試験は決定論的試験終了後に単独実行し、最後に通常の実時間テスト登録OFFへ戻した。ソース修正は全件実行より前に確定し、その後の変更はレポート・検証証拠の保存だけ。

Golden 25本、保護対象WAV 202本、基準コミットの追跡済み成果物5,524ファイルをハッシュ照合し、すべて一致。C++の既存ソース・ヘッダー・テスト222ファイルも基準と一致。ソース差分は検証スクリプト、新規障害注入・再検証スクリプト、CTest登録1件に限定する。DSP、TimeMap、L1/L2、safe-density、再生API、Phase30/36、キャッシュ・シークは変更しない。

実時間CTestのコード・合否基準・登録条件は変更しない。決定論的試験とは分けて実行し、失敗やINVALIDを読み替えない。

## 5. 再現と次段階

```sh
python3 -B scripts/phase53_post_handoff_test.py
python3 -B scripts/phase53_post_handoff_review.py --output results/phase53_post_handoff/review_NEW
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j 3
ctest --test-dir build -L deterministic --output-on-failure -j 3
```

再検証の出力先は新規ディレクトリを指定する。既存結果への出力は拒否する。Golden・参照WAVが不足する環境では再検証成功を主張せず、元の引き継ぎ資料に従って復元する。

引き継ぎタグは233c773を維持し、本修正を新しい完成コミットとして保存する。実機の長尺高負荷安定性、操作反映遅延、iOS未検証など従来の制限を解消したとは主張しない。

この検証修正による追加のDSP研究や統合待機条件は設けない。次の機能開発はPhase 54のシークとし、既存引き継ぎ仕様の停止・音声バッファ寿命・公開済みPCM保護を前提に進める。今回の修正に新しいシーク機能は含めない。
