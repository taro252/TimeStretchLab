# Phase 59 Fix 検証

判定 **B、Gate 2未合格**。初回時計、旧製品の供給停止、OS未観測域の原因証明は残る。品質の完全一致と実時間の供給・時計は別に判定する。

## 独立参照とPCM

最終固定実行体は `results/phase59_fix/FINAL_CANDIDATE.json` の19実行体・10ライブラリ・209ソースSHAで識別する。変更前の独立参照は既存のfrozenバイナリを使い、許容誤差を導入しない。

| 検査 | PCM条件数 | 結果 |
|---|---:|---|
| 動的 | 1140 | 完全一致 |
| Phase58固定 | 6216 | 完全一致 |
| Phase57固定 | 51344 | 完全一致 |

全161速度の隣接640条件は動的1140件に含む。Phase57は形式ごとの分割だけを行い、速度・素材・チャンクを削減していない。Phase56は状態安全性、161速度固定Map、増分一致をCTestで再検査した。全25921速度組や実機全161値の各適用を網羅したという意味ではない。

最初の動的長尺は1件一致後に空き4GiB基準で中断した。`validation_final/summary.json`に初回中断を残し、長尺16件と続く増分144件を同じ参照・条件で別保存先へ実行した。全行列の集計は`validation_final/effective_summary.json`。初回の成功1件を最終1140件に重複加算しない。

## 最終音声試験

| 動的群 | 合格/セッション | 全PCM / 接頭部PCM |
|---|---:|---:|
| dynamic_normal | 29/30 | 30 / 0 |
| dynamic_load | 90/90 | 90 / 0 |
| dynamic_lifecycle | 30/30 | 18 / 12 |
| dynamic_burst | 6/6 | 6 / 0 |
| dynamic_materials | 30/30 | 30 / 0 |
| dynamic_long | 4/4 | 4 / 0 |

固定短尺36件、固定長尺8件（180秒の両preset×3反復、300秒の両preset）、同一プロセスのEOS再生成40件を別に実行した。各群のCPU/Wall中央値・p95・p99・最大、全ゼロ項目の値は `MEASUREMENTS.json` を参照する。新経路の実機合格と旧製品の結果を合算して解決扱いにしない。

旧製品最終比較は11/12。修正前調査では保存済み旧バイナリのBaseline smokeに8208フレーム不足を再現した。過去Candidateの1319フレーム不足も保持した。最終比較が成功しても根本原因は解明済みとしない。

今回の最終比較でも旧Baseline smokeのsession4/epoch1、callback179に234フレーム不足を再現した。PCMと時刻診断は合格だが供給失敗である。個別値とraw callbackは`FINAL_LEGACY_FAILURES.json`。

正式な最終新経路の不合格セッションは1件。`FINAL_NATIVE_FAILURES.json`に項目別値、callbackの時刻差・不足、取得できた実期限区間を保存する。最初の動的normalではsample0→1160（要求512、余分648フレーム）を再現し、PCM一致・不足0でも時計FAILとした。

## EOS・メモリ・OS

最終実機のEOSは同一入力を用いた新engine/sessionの40反復。別入力への切替と旧session要求の拒否は、2入力の機能・周期付き診断でも検査した。FIFOにある分だけ引く模擬排出は、物理callbackの不足0の代用にはしない。

高速排出のOS優先度低下とPreemptedを確認した。Debug・高速排出の失敗は実時間性能の失敗として別記し、通常優先度の機能合格で相殺しない。VMの初回書込み対策は行ったが、Unknownや取得窓の外をfault 0として埋めない。

最終focused traceの実時間区間とOS状態の直接照合は`FINAL_TRACE_OBSERVATIONS.json`（取得・解析不能なら未検証）。全90秒に対して6秒窓であること、Unknownと窓外を分けて記録する。

追加の最終trace付き再生のNative判定は不合格。正式274音声セッションとは別記する。最終6秒窓の全状態既知は94/155区間、窓内Unknownは61、窓外・部分区間は1777。既知区間のVM観測は{'Decompress Memory': 3}。全区間のfault 0とはしない。指定した元の最大Wall位置付近の7区間は、窓内0区間で未取得。attachの開始遅延により取得位置は後ろへずれた。

追加試行の時計FAILは起動時ではなく、約85.821秒のcallback8016→8017の518フレームの余分な進みだった。直前のIOProcが遅れ、OSはClient Overloadを1件記録した。Native独自のHAL windowカウンター0とは区別する。Client threadの約11.2ms Blockedとdtsecurityによる起床を観測したが、待機の全因果や計測器の関与は未証明。元の初回時計異常と同原因だとはしない。根拠はPOST_TRACE_CLOCK_VM.json。

## CTest・Golden・検査器

Release93/93、Debug関連18/18、Golden25/25。固定前コードとの位相更新3840、Stereo1920フレーム比較、ASAN/UBSAN、値・借用メールボックスのTSAN/ASAN/UBSAN、Git容量ガードの隔離5検査を実行した。根拠は `checks_final/summary.json`。

## 保存・再現

全PCM・大きい行データ・CSV・XML・トレース・実行体は `build/phase59_fix_artifacts/` に保存した。各manifestに入力/実行体SHA、コマンド、保存場所を記録する。成功作業PCMの圧縮は `validation_final/success_working_archives.json`、トレース復元は `TRACE_ARCHIVE_*.json` を参照する。いずれも復元SHAを検証する。FAIL原本と過去Phaseの証拠は保持する。

未測定項目は `MEASUREMENTS.json` のnullで明示する。初回2回の除外、期限延長、FIFO拡大、品質・条件数の削減は行っていない。
