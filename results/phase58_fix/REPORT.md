# Phase 58 Fix 実装・検証報告

判定 **A：Gate 1合格（測定範囲内）**。原因のOS観測、原因に基づく修正、最終版585音声セッション、全PCM・Golden・既存製品回帰を完了した。動的速度変更は次Phaseへ着手可能だが、未実装。製品の既定経路・公開API・Merodoaは変更していない。

## 1. 原因調査結果

通常QoSの設定と再取得には成功していたが、DSP workerの実際の通常優先度は31だった。Audio System Traceでは、再生中の位相処理で約66.34ms、DSPブロック全体で約73.55msのPreemptedを確認した。該当位相区間にmutex待ち・I/O・ページフォルト・C++ newはなかった。約199.36msのPreemptedも別に確認したが、こちらはReady前の起動遅延である。

過去のFIFO不足では、供給停止・不足callback・FIFO残量を同じ時刻軸に対応付けた。例えば10,240フレーム不足の試行には、開始FIFO 9,728の225msブロックで1,024不足、FIFO 3,072の204msブロックで6,656不足がある。過去のOS状態は未取得であり、個々の非CPU時間の理由はunknownのまま保存する。

[原因の詳細](../../docs/PHASE58_FIX_ROOT_CAUSE.md)、`historical_fifo_correlation.json`、`stall_flight100_analysis/summary.json`、`underrun_flight100_analysis_complete/summary.json`。

## 2. 修正ファイル

- `Phase58RealtimePipeline.cpp/h`：明示選択の実時間経路、入力常駐、通常側への検証分離、診断領域のページ初期化。
- `Phase58FixRealtimeWorker.cpp/h`：公開Mach時間制約と専用Audio Workgroup、区間・待機・寿命・エラー計測。
- `Phase58FixSnapshotMailbox.h`：通常側が所有する最大3スロット、実時間側の借用。
- `WavStream.cpp/h`、`Phase57ProgressiveSynthesis.cpp/h`：同じ変換算術の常駐入力と借用Snapshot。
- `Phase36StreamingSpeedEngine.h`、`Phase36SynthesisCore.h`：有界な任意診断。DSP算術は変更なし。
- `Phase58Native.mm`、`Phase58Diagnostics.h`、`Phase58Check.cpp`：ON/OFF、実機・PCM比較、未計測表示。
- CMake、追加単体テスト、再現・トレース・回帰・監査スクリプト。

## 3. 採用した修正

`--worker=workgroup --resident-input=on` を指定する独立した実験経路。Ready後、通常所有者が昇格を確認してから音声を開始する。DSPは専用Audio Workgroupへ参加し、実測priority97で供給する。区間周期は2,048/sample rate、計算予算90%、preemptible=true。Snapshot所有権操作・入力I/O・元入力検証・ブロックごとの所有関数作成を実時間区間から除いた。待機は2msのタイムアウトを指定したセマフォで、callbackから通知しない。

候補V2の詳細ログ書込みには37件・計約132µsのZero Fillが残っていた。容量確保だけでは初回ページアクセスを済ませていなかったため、V3で全診断領域を通常側で初期化した。V3のOS観測117実時間ブロックではフォルト0だった。V2の結果・ソース・実行体を保持し、V3で実機一式を再実行した。

FIFOはCandidate 16,384/16,384/2,048、Baseline 16,384/12,288/2,048、ゲイン0.5。Experimental 3500、保護条件、位相・OLA・FIRの算術順は維持。製品の公開API・既定経路・Merodoa・動的変更は変更していない。

[スケジューリング設計](../../docs/PHASE58_FIX_SCHEDULING.md)。

## 4. 変更前後の数値

同じ入力・2.00倍Candidate・出力開始81,920のDSPブロック：

| 観測 | Wall | CPU | 非CPU時間 | 実際の優先度 |
|---|---:|---:|---:|---:|
| 修正前のOS観測 | 88.127ms | 14.577ms | 73.550ms | 31 |
| 最終V3、3回 | 13.324～14.475ms | 同値近傍 | 計測分解能近傍 | 97 |

V3通常300回の全実時間ブロック最大Wallは32.040ms、最大非CPU時間1.861ms、作業区間期限超過0。詳細トレース117実時間ブロックの最大非CPU時間は約13.8µsだった。各反復の全非CPU時間をOS分類できたわけではない。公開間隔・内部待ち・CPU・RSSの全分布は集計JSONを参照する。

開始前を含む最大値も保持した。通常300回の全DSPブロック最大Wallは202.858msで、通常優先度の先行生成には長い停止が残る。ここを再生中の32.040msと混同しない。全セッションの公開間隔には起動前の待ちやPauseも含まれ、最大258.514msだった。実時間区間の作業期限超過は全585件で0だが、開始前まで含めた無条件の実行時間保証はしていない。

## 5. 不足再現試験

修正前・診断の音声167セッションは165成功、時刻診断FAIL2、FIFO不足0。今回この条件のFIFO不足は再現できなかった。これを原因解消の証拠にはしない。過去Phase58の不足・Phase54の実時間FAILは変更せず保持する。誤った通知待ちによる音声0件のトレース取得失敗は、音声試験へ数えない。

## 6. 修正後の反復結果

最終V3の実行体SHA：`daacdb21463fd2ebe002109758db7d6109d24a6925cae17b2476f53296213e7a`。再ビルド後も一致。

| 最終V3群 | 音声セッション | 成功 | 全PCM一致 |
|---|---:|---:|---:|
| 通常負荷・独立プロセス | 300 | 300 | 300 |
| CPU2スレッド＋128MiB | 100 | 100 | 100 |
| 計測OFF | 20 | 20 | 20 |
| 形式・素材・代表速度 | 90 | 90 | 68 |
| 負荷・ライフサイクル | 32 | 32 | 8 |
| 長尺 | 4 | 4 | 4 |
| 起動比較のFix側 | 36 | 36 | 接頭部36 |
| OSトレース | 3 | 3 | 3 |
| 合計 | 585 | 585 | 503 |

残る82件はウィンドウ・起動・模擬経路変更の接頭部比較で、全PCM一致と混同しない。OSトレース3回と起動のCold/再始動は同一プロセス内の別Pipelineを含むため、585件全体を独立プロセス試験とは呼ばない。候補V2の705セッション成功、入力常駐のみの通常方式20回成功も別の版・群として保持した。

`final_native_summary.json`、各群の`rows`・manifest・callback/worker CSVに全件保存。失敗した修正前セッションも集計から削除していない。

## 7. 長尺・高負荷試験

180秒境界Candidate 0.40/Baseline 2.00、300秒連鎖Candidate 2.00/Baseline 1.00をEOSまで再実行し、4/4成功。通常・負荷の両presetと11代表速度、無音・単発・連続アタック・持続音・連鎖・既存自然素材を含む。

全585件でFIFO不足・不足callback・書込み拒否・callback期限超過・HAL逸脱・host/sample異常・PCM不一致・測定対象のcallback/実時間worker C++ newは0。長尺ではスレッド標本の上限到達があり、全期間連続の優先度観測とはしない。callbackの記録欠落とは別である。物理装置変更・OS全体のメモリ逼迫は未検証。

## 8. PCM完全一致

実機の全PCM503件・接頭部82件は成功。全161速度を含むPhase58の6,216セッションと、Phase57の51,344セッションの回帰もすべて成功した。

| 品質回帰 | 全PCMセッション | 結果 |
|---|---:|---|
| Phase58 short / all_speeds / long | 1,008 / 5,152 / 56 | 全件一致 |
| Phase57 stage1 / stage2 / long | 4,704 / 46,368 / 48 | 全件一致 |
| Phase57 natural / rejections内の有効PCM | 210 / 14 | 全件一致 |

拒否2条件も旧参照と同じ拒否を14試行で確認した。独立した出力先のPCM試験群のみ最大3群で並列実行し、この部分の時間・CPU・RSSを単独性能の比較に使用していない。

製品長の独立参照SHA `3a3b04454f754c35afa4cac121a726fa31c44a6854761a7de5f71aa057f2a957`、元のPhase57 map終端契約の独立参照SHA `461c26d10b0fd8a781cbffcbbab49072f501e02172e2a7c2f26e3e49a0253a1e`。参照を差し替えず、サンプル数と全ビットを比較する。

## 9. Golden・CTest

Release全ターゲットビルド、Ready反復1,000/1,000、決定論的CTest88/88、Debug関連ビルド・CTest11/11、Snapshot受渡しの競合検出・メモリ/未定義動作検出、Golden25/25は成功。

基準HEAD `75ae70cecaef2739f744fc21eeecf99da179e18f` の既存34,807ファイルを許可した共有コード変更以外でGit blob照合し、全件一致。Phase53～58の保存結果・Goldenは保護された。固定参照2本のSHAも開始時と同一。`regression_v3/protected_assets.json`、`final_binaries.json`、`build_settings.json`、`regression_driver.json` に記録した。

callback CSVの独立再集計は1,549セッション・511,713 callbackで整合した。修正前の時刻FAILも含み、構造監査PASSを音声PASSへ読み替えない。`measurement_audit.json`。

## 10. 既存製品回帰

決定論的CTestでPhase54固定/cache/seek、Phase39動的変更、L1/L2/safe-densityを確認。品質回帰後、変更前と再ビルド後の既存製品実機は各4件、計8/8成功。両presetのEOSと、シーク・速度変更・Pause/Resume・Stop/Playのsmokeを含む。

既存の厳格な実時間CTestは2/2成功し、正常試験と故障注入検出を区別して保存した。故障注入の検出成功を、注入中の再生成功とはしない。起動比較の従来経路36セッションでも測定した時刻・FIFO指標は0件だったが、その実行体にはcallback C++確保フックがなく未計測。

過去のhost約12.07ms・sample532フレームの不連続は別問題であり、今回の8件成功やFIFO修正で原因解決したとはしない。`legacy_device/`、`legacy_realtime_ctest_driver.log`、`legacy_realtime_paced/`、`native_statistics.json`。

## 11. CPU・メモリ・起動時間・未解決事項

各3回の同条件中央値。Coldは新プロセスで、OSファイルキャッシュは消去していない。

| MIX秒数/preset | 従来製品Cold | Phase58最終版Cold | Fix V3 Cold | 従来再始動 | Phase58再始動 | V3再始動 |
|---|---:|---:|---:|---:|---:|---:|
| 30/Candidate | 246.35ms | 116.63ms | 133.00ms | 62.52ms | 66.99ms | 70.54ms |
| 30/Baseline | 250.40ms | 120.87ms | 123.11ms | 72.60ms | 58.03ms | 61.18ms |
| 180/Candidate | 644.04ms | 202.87ms | 194.64ms | 61.70ms | 125.22ms | 129.95ms |
| 180/Baseline | 641.95ms | 183.35ms | 177.69ms | 53.32ms | 101.34ms | 116.11ms |
| 300/Candidate | 919.69ms | 209.83ms | 220.96ms | 61.73ms | 137.10ms | 164.28ms |
| 300/Baseline | 912.63ms | 214.15ms | 213.12ms | 54.83ms | 129.48ms | 153.99ms |

初回短縮は維持したが、再始動は完成解析キャッシュのある従来経路より遅い。入力同一性のSHA・非公開複製・常駐化と新規解析を毎回行う。入力105.84MB分の常駐メモリと同量の一時ストレージが必要で、512MiB上限は維持した。Peak RSSには検証参照211.68MBや診断領域を含むため、従来製品のRSSと単純に製品メモリ差として比較しない。個々の起動段階・CPU・RSS・標準偏差は`v3_startup/rows.json`と`statistics.json`へ保存。

300秒MIX・0.50倍Candidate・Cold、各3回中央値。CPUは準備開始から1秒再生ウィンドウの停止までで、全曲合成CPUではない。解析もこの窓内に完了しない試行がある。

| 測定 | 従来製品 | Phase58最終版 | Fix V3 |
|---|---:|---:|---:|
| プロセスCPU | 0.933s | 1.215s | 1.261s |
| 解析worker寿命CPU | 別計測形式 | 0.953s | 0.899s |
| DSP worker寿命CPU | 別計測形式 | 0.140s | 0.221s |
| DSP advanceのCPU合計 | 別計測形式 | 0.129s | 0.210s |
| プロセスPeak RSS | 59.72MiB | 253.63MiB | 367.23MiB |

追加のスレッド標本取得など計測構成の差も含み、CPU増加の全寄与率は未分離。入力常駐は約100.94MiB、事前読込み検証参照は約201.87MiBである。Peak RSSはプロセス寿命最大値であり、再始動単独の最大値や参照を除いた製品RSSとして扱わない。

過去の不足全件のOS状態、物理装置/レート変更、OS全体のメモリ逼迫、C/Objective-C全確保、物理音響遅延、製品Sandbox・全セッション合算予算・解析キャッシュ連携は未解決または未測定。動的変更は未実装。

## 12. Gate 1最終判定

**A：合格。** 観測した供給停止の主要因をOS非実行として特定し、実時間workerとその前提となるI/O・所有権・診断メモリの準備を実装した。同一ブロックのOS実行状態改善、最終300回・高負荷100回、長尺4条件、全PCM・Golden・製品回帰、全記録監査を確認した。

合格範囲はApple M1、macOS26.6.2、内蔵装置72、48kHz/512フレーム、記録した素材・負荷・固定速度条件である。反復成功を無条件の実時間保証へ拡張しない。過去不足の全OS理由はunknownを残す。機械可読の判定・未測定項目は `VERDICT.json`。

## 13. 動的速度変更へ進めるか

**次Phaseとして着手可能。** 本Phaseでは実装していない。全161段階の固定PCM一致と、再生中の全161段階変更・Latest-Wins・論理位置固定の一致は異なる。次は継続する位相・OLA・FIRへ既存Phase39契約を接続し、変更中のFIFOと全PCMを別途検証する。

Gate 2は未実装、Gate 3は部分検証、Gate 4は製品未採用。製品API・既定経路・Merodoaの統合、完成解析キャッシュ共有、入力複製・常駐リソースの寿命と予算、Sandbox、物理装置変更も別段階とする。
