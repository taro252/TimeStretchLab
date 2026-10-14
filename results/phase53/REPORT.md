# Phase 53 — Playback Engine Hardening & Application Integration Handoff

## 位置付け

Phase 52基準 `65a875907437e410517db22d80e402d6fed93069`、作業開始HEAD `5570672`。変更はTimeStretchLabだけで、merodoaへは変更していない。凍結Experimental 3500、TimeMap/L1/L2/safe-density、位相・OLA・FIR、Phase30/36、キャッシュ・シークを変更していない。

再生ライブラリの残存3件を修正し、別リポジトリからの引き継ぎ仕様を作成した。開発版APIの利用準備を整えたもので、一般公開向けの実時間安定性保証ではない。

## 1. 修正内容

### Drainingと診断取得

`MacPlaybackEngine::callbackRecords()` が内部Ended/Failedを契機に `quiesce(false)` を呼んでいた。内部EOSはデバイス側の末尾排出完了を意味しないため、診断取得で音声出力を早期停止できた。

停止の副作用を除去した。Draining/active/in-flight中はlogic_errorで詳細履歴取得を拒否し、callback静止後にコピーする。通常の状態・診断照会もライフサイクルを変更しない。末尾HAL目標＋既存5msを待つ停止は監視・ライフサイクル側が所有する。Failed、User Stop、RouteChangedはEOSと別理由のまま。

読取り専用ポリシーの決定論的試験は1,000回反復。実機 `--verify-draining` はDraining中に8回診断取得を試み、play/prepare拒否、早期停止なし、正常Ended後の記録取得、末尾HAL期限を確認する。失敗状態での履歴取得はCLI制御側で静止を最大1秒待ち、診断APIから強制停止しない。

ネイティブ診断へ `lastPcmTargetEndNs` と `outputStoppedMachNs` を追加した。C++確保計数はRenderState構築時の基準との差分にし、前セッションの累積値を新セッションの実測件数と混同しない。

### 全セッションの品質・PCM

従来のclosed-session記録は一部カウンターしか保存せず、親判定が最終セッションのPCM照合しか見ていなかった。書込み拒否・ワーカーエラー等の伝搬も不足していた。

`PlaybackDemo` は各User Stopで完全なsummary、callback/worker/plan/operation CSVを保存する。最終セッションと終了済みセッションを `sessions.csv` で列挙し、ID・一覧の欠落や重複を検証する。過去のFIFO拒否、ワーカーエラー、同時消費、計測異常を親へ伝搬する。

| 範囲 | 記録・意味 |
| --- | --- |
| DSPが生成したPCM | `generated_frames`：出力ブロックとして準備済み。未公開の待機ブロックを含む |
| FIFO公開済みPCM | `published_frames`（旧名produced_framesと一致）。SHAの対象 `[0, published_frames)` |
| callback消費 | `consumed_frames`：FIFOから取得した実PCM。ゼロ埋めを含まない |
| SourceNodeへ渡したraw | `device_raw_frames`：消費した実PCM、入力サンプルレートでのフレーム数。SRC後の物理装置フレーム数ではない |
| 要求提示時間軸 | `presented_frames`：不足ゼロ埋めを含む要求フレーム数 |

SHAは無加工float32をサンプル順・チャンネル順に並べた接頭部。各セッション自身の開始速度・計画・安全密度履歴から独立参照を再生成し、同じ長さだけを比較する。EOSでは参照全長とも一致させる。初回セッションを最終セッションの別TimeMapや別prefix長で代用しない。

C++捕捉プロセスの終了コード0は、独立参照検証の完了ではない。summaryのPCM/CSV/SESSION_VERDICTは照合前INDETERMINATE。共通検証後のvalidation JSONで各セッションと全体を確定し、検証不能はPASSにしない。故意の供給停止は音声FAILと障害検出PASSを区別する。

### 共通最終判定と補正

`scripts/phase53_sessions.py` がCSV完全性とセッション別参照を検証し、`phase52_verdict.finalize()` が最終判定を所有する。通常検証、固定参照EOS補正、replay単位補正は同じ関数を使用する。

必要条件はAUDIO_QUALITY、MEASUREMENT_QUALITY、PCM_CORRECTNESS、CSV_INTEGRITY、SESSION_INTEGRITYのすべてPASS、整合する終了理由、終了コード0。CSVヘッダー・最終改行・列・通番・行数・フレーム合計・世代・有限値、capture件数、manifest、操作/lifecycleファイルを検査する。CSV不備は計測FAILにもする。

参照訂正ではPCM判定だけを再計算し、訂正理由・前後の証拠を保存する。元の音声/計測/CSV FAIL、供給不足、拒否書込み、時刻異常は保持する。再確認スクリプトは `--output` に新規の保存先を要求し、過去データを上書きしない。

捕捉に失敗したケースの番号は保存済みsummary件数ではなく試行ディレクトリで進める。summary欠損は必ずFAILにし、後続試験との名前衝突で証拠を失わない。

## 2. 障害注入

`phase53_session_integrity`：26個の保存データfixtureと参照補正試験。正常2セッション、初回PCM prefix不一致、書込み拒否、ワーカーエラー、アンダーラン、計測FAIL、CSV欠損、初回FAIL/再起動PASS、RouteChanged、通番欠落、行数不一致、最終行切断、manifest欠落、prefix範囲不一致、未完了操作、NaN、設定不一致、終了コード不整合等を確認する。

故意の不良を検出すれば回帰テスト成功であり、その音声が品質PASSになった意味ではない。補正だけでCSV/計測/音声FAILがPASSになるケースを禁止する。既存Phase52の必須値・NaN/Inf・期限・route試験も維持した。

## 3. 実機

最終ソースの保存先：`native/20261014_171604_300553/`。7試行、10セッションを独立検証した。

| 試行 | 対象 | 結果 |
| --- | --- | --- |
| EOS/Draining診断反復 | MIX 0.50、Drums 0.50、Baseline MIX 0.50 | PASS。末尾HAL＋5msを維持 |
| 双方向・pause/resume | MIX 0.40→2.00→0.40 | PASS。予定5.00〜5.25秒の一時停止 |
| stop/restart | Drums：2セッション、MIX：3セッション | 全セッションPASS。先頭から再開始、各停止prefix一致 |
| route変更 | Drums：模擬通知 | PASS。Stopped/RouteChanged、EOS=false、prefix一致 |

出力装置ID72、48kHz、512フレーム。MIXの入力44.1kHzはSRCを含む。全10セッションで不足・書込み拒否・callback期限超過・C++確保・host/sample異常0。callback最大16.459μs、最大RSS56.55MiB。正常EOSの停止は末尾HAL目標から14.134〜16.594ms後（既存5ms余裕以上）。RouteChangedは意図的停止で、このEOS余裕の判定対象外。集計は `native_final_summary.json`。

有音再生を含むが、新たなユーザー主観評価は取得していない。今回の音質アルゴリズム変更はなく、過去の試聴を包括的な製品保証へ読み替えない。物理装置変更・長尺高負荷反復・音響ループバックは今回未実施。

最初の制限内実行は「No default audio device」で不成立。ログを保持し、CoreAudioへアクセスできる実行方式で再試験した。計測不成立を音声安定性PASSに含めない。途中の実機7/7成功記録も最終ソースの記録とは別管理する。

## 4. 過去Phase52の再検証

元の64試行を読取り専用で検証した。57件PASS、7件FAIL。FAILの内訳は、終了済みセッションの必須記録不足4件、故意450ms停止2件、旧route試行の部分SHA未計測1件。旧記録から測定不能な値を推定で補完しない。

単一セッションの旧summaryにsession IDがない場合、保存済みoperations CSVに一意のIDが存在するときだけ、その証拠に基づいて照合する。これは計測値の追加やnative音声の変更ではない。複数セッションの欠損はこれで救済しない。

旧判定と元CSV/WAVは変更していない。参照EOS/単位訂正の理由を保持し、他の不良をPASSへ昇格しない。旧最終EOSガードのhost/sample不連続による計測FAILも保護対象で、今回の64件に混入させない。

## 5. ビルド・回帰・資産

Release/arm64、Apple C++20/Objective-C++、CMake、Accelerate/AVFoundation/Foundation/CoreAudio。独立consumer構成でも `add_subdirectory(... EXCLUDE_FROM_ALL)` と `macos_playback_engine` へのリンクで利用例をビルドできた。merodoaやSwiftアプリは作成していない。

最終ソースでの検証結果：

- 決定論的CTest **72/72 PASS、380.56秒**。最終コード・全件実行。診断OFFでの不足検出、mono/stereo、ブロック分割、既存PCM回帰も含む。
- 独立OS期限CTest **2/2 PASS、58.93秒**。既存のFAIL/INVALID・障害注入判定を維持。
- 新規Golden再生成照合 **25/25バイト一致**。出力WAVはGit対象外、ハッシュは `golden_audit.json`。
- 保存済みGolden25本、過去保護WAV202本、追跡済み成果物5,139ファイルは監査時点で一致。旧Phase5.3 REPORTは `PHASE5_3_REPORT.md` へバイト保持し、READMEの旧参照先を修正。

検証工程中に全CTestの再実行が先行試験と重なり、固定一時ディレクトリ `phase27_repeated_sources` の削除が競合してphase27_repeatedが1件失敗した。失敗ログ `ctest_overlap_failed.log` を保持し、先行試験が終了した後に全件を単独で再実行した。DSP/PCM不一致とは扱わず、失敗をPASSへ読み替えない。

ソース変更は再生制御、ネイティブアダプター、診断・検証スクリプト、CMake、テスト、文書に限定。Phase39のワーカー変更は生成/公開範囲の計測追加で、DSP演算順・時間写像・位相・OLA・FIRへ変更はない。正式DSP、Phase30/36、Phase18/19のソースは変更していない。

## 6. 引き継ぎ

正式仕様：`docs/APP_INTEGRATION_HANDOFF.md`。submodule取得・特定SHA固定・更新運用、ターゲット依存、WAV形式/RIFF制限/所有権、API戻り値/例外/状態/制御キュー、Swift側ブリッジ契約、最小C++例、将来機能の責務を整理した。`examples/mac_playback_handoff.cpp` と外部consumerでビルドを確認した。

`playback_engine` と `macos_playback_engine`、Candidate/Baseline、Latest-Winsを維持する。アプリは要求速度・実行中目標・保留/拒否・原曲位置を分離する。制御APIをcallbackへ持ち込まない。詳細履歴取得は静止後、ライフサイクル操作は直列の作業キューへ置く。

完成コミットを `phase53-handoff` タグで固定し、merodoaはその完全SHAをsubmoduleとして記録する。TimeStretchLabを更新しただけではアプリ参照は変わらない。

## 7. 残る制限・判定

開発版のアプリ引き継ぎは可能。一般公開向けの実時間品質保証は未完了。約1.4〜1.6秒等の操作反映遅延、Busy待ち、高負荷/OS停止による不足、host/sample時刻不連続、iOS/iPadOS未検証、シーク未対応を残す。安全密度条件や過渡音保護は緩めていない。

SwiftUI、デコード、ピッチシフト、Demucs、Stemミキサー、iOSアダプター、シーク、L1/L2最適化、0.25倍研究、長時間System Traceは実装していない。アプリ側は薄いObjective-C++ブリッジと媒体管理を別途実装する。

## 8. 再現と完成版の識別

```sh
python3 -B scripts/phase53_verdict_test.py
python3 -B scripts/phase53_validate.py native
python3 -B scripts/phase53_validate.py native_review
python3 -B scripts/phase53_validate.py golden
python3 -B scripts/phase53_validate.py audit
python3 -B scripts/phase53_validate.py review
```

`review` は旧証拠の不合格を保持するため終了コード2になる。新規の再検証保存先を作り、過去結果を上書きしない。`golden` は既存の再生成ディレクトリへ上書きせず拒否する。通常/補正用スクリプトのキャプチャ工程と完全品質判定を分離している。

`build_manifest.json` に最終ソース/バイナリSHA、ビルド設定、結果、完成refを保存する。完成コミットは `git rev-parse phase53-handoff^{commit}` で取得する。READMEと引き継ぎ仕様にsubmodule固定手順を記載した。

捕捉したコンソールログ2本には出力由来の行末スペースがあるため、元バイトを保持したまま `.gitattributes` でこの2ファイルだけ行末スペースの書式判定から除外した。ソース・Markdown・CSVの検査は維持する。
