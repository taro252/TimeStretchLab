# TimeStretchLab Phase 58：実時間増分再生の検証結果

## 判定：B（条件付き成立）

独立した固定速度の増分実時間経路を実装し、初回起動を実機で短縮できた。一方、通常負荷でもFIFO不足が再現しGate 1は未達。動的速度変更は実装・成功扱いへ進めず、製品既定経路とMerodoaは変更しない。音質・FIFO・閾値は緩めていない。

## 1. 実装した機能

解析workerとDSP workerを分離し、共有不変snapshotの最新1件、既存SPSC FIFO、AVAudioEngine/SourceNodeを接続した。世代/セッション/絶対PCM位置、背圧、真のEOS、失敗、取消、解放順を管理する。入力の全内容SHAと同時に非公開FDへ元WAVのバイト列を複製し、元パス監視を解析側へ限定した。callbackはFIFO取得・比較・事前確保した診断記録だけを行う。

CandidateはFIFO容量/先行量/生成ブロック16,384/16,384/2,048、Baselineは16,384/12,288/2,048、出力ゲイン0.5。Baselineの蓄積上限も12,288へ制限する。

## 2. 変更ファイルと既存経路

新規実装は`src/prototype/Phase58RealtimePipeline.{h,cpp}`、`Phase58Diagnostics.h`、`Phase58Check.cpp`、`Phase58Native.mm`、`Phase58LegacyStartup.cpp`、`Phase58ProductReference.cpp`。テストは`tests/Phase58Tests.cpp`と`Phase58PcmSmoke.py`。実行・再現・監査スクリプトは`scripts/phase58_*.py`。設計資料は`docs/PHASE58_*.md`。CMakeへ独立ターゲットと決定論的2テストを追加した。

既存ソースの拡張はPhase57の明示的な製品出力長指定と任意段階計測、Phase36内部の計測先ポインター設定2か所だけ。FFT/位相/OLA/FIRの算術は変更しない。Phase57の既定map終端長は保持する。PlaybackEngine/MacPlaybackEngineの公開APIと既定値は変更しない。

Release全ビルド後の従来`phase54_native`と`phase39_reference`は、開始時に保存した各バイナリとSHA-256まで一致した（`product_binary_comparison.json`）。製品リンクにPhase58/Phase57の実験ライブラリは追加していない。

### 出力長の契約差を発見

MIX10秒・0.50倍ではPhase57のmap終端参照は881,380フレームだが、実際のPhase54製品は882,000フレームだった。新経路は製品式`llround(inputFrames * timeRatio)`を合成前に明示し、最終出力882,000・SHA `b92c90d1536ef125bf3359fd27f85c52029b11ff68d2013bfc455afb17e8f0c2`と一致した。`product_length_counterexample.log`と`product_smoke/`を保存。Phase57契約の初期実機結果を製品互換成功へ流用しない。

## 3. 固定速度PCM一致

独立参照はPhase57以前のPhase36ソース（ec087019、SHA `4ffec7c4db196f51e89bd4ebaf336020ae71d0969c31393a40752b4a37ed3899`）を優先リンクした`build/phase58_frozen/product_reference`。参照バイナリSHAは`3a3b04454f754c35afa4cac121a726fa31c44a6854761a7de5f71aa057f2a957`。Float32の全生ビット・出力長・raw SHAを比較し、許容誤差を使わない。

| 試験 | 参照条件数 | 全PCMセッション | 結果 |
| --- | ---: | ---: | --- |
| pcm58_short | 336 | 1008 | PASS |
| pcm58_all_speeds | 2576 | 5152 | PASS |
| pcm58_long | 28 | 56 | PASS |

合計6,216セッション。短尺は全8形式・境界/持続/連鎖・代表7速度・両preset・3チャンク。161速度は全8形式・両preset・2チャンク。長尺は3分境界/5分連鎖・代表7速度・両preset・2チャンク。`native_gate_product_final`の62条件には別途、同じ参照の全量FIFO一致確認がある。消費側が待つ試験を実時間成功には含めない。

## 4. 動的速度変更と5. 全161速度の範囲

固定構築・全PCM一致は0.40〜2.00倍、0.01刻みの161速度を網羅した。再生中の変更は未実装で比較0件。固定map交換は行わず、Latest-Wins、要求ID/状態、L1/L2、safe-density、Phase50保護を緩めない。同じ論理出力位置・要求順・適用境界を再現する今後の比較設計は`docs/PHASE58_SPEED_TRANSITION.md`。既存製品の動的変更回帰と新経路の対応を混同しない。

## 6. FIFO/Callback実時間試験

環境はmacOS 26.6.2（25G83）arm64、Xcode 27.0（27A266a）、Apple Clang 21.0.0、Release。MacBookAir10,1、Apple M1、8コア、メモリ16GiB。内蔵スピーカー、device 72、48kHz/2ch/512フレーム。実機出力と重いビルド・DSP試験は直列。各manifestに入力・実行バイナリSHAを保存した。

新経路の実機248セッション中、総合成功248、測定条件成立248、PCM prefix一致248、EOSまで全PCM一致106。測定版160件は起動60・形式/30秒MIX 62・ライフサイクル/負荷34・長尺4。修正後はライフサイクル8件を実施し、最終起動再測定60件・同一不足条件20件は別版の結果として追加する。window再生は全PCM一致件数へ含めない。

最初の160セッションは固定した測定版（`native_measurement_version.json`）。その後、装置通知用フラグの所有権、Ready/Cancelのmutex同期、未完了統計のnull表示を修正した。音声callback・DSP合成の算術とFIFO設定は変えていない。現在版と測定版のバイナリSHAを区別し、160件を現在版の実測件数とは呼ばない。

| 指標 | 保存した実機248セッション合計/最大 |
| --- | ---: |
| callback_deadlines（合計） | 0 |
| hal_misses（合計） | 0 |
| host_missing（合計） | 0 |
| host_backwards（合計） | 0 |
| host_cadence_errors（合計） | 0 |
| sample_errors（合計） | 0 |
| callback_formats（合計） | 0 |
| callback_records_dropped（合計） | 0 |
| callback_calls（合計） | 193,501 |
| missing_frames（合計） | 0 |
| missing_calls（合計） | 0 |
| rejected_writes（合計） | 0 |
| callback_cpp_allocations（合計） | 0 |
| pcm_mismatches（合計） | 0 |
| callback_max_ns（最大） | 808000 |
| callback_p95_ns（最大） | 25250 |
| callback_p99_ns（最大） | 48416 |
| max_consecutive_missing（最大） | 0 |
| max_dsp_wall_s（最大） | 0.143325167 |
| max_dsp_cpu_s（最大） | 0.050576750000000004 |
| max_publication_gap_s（最大） | 0.259432542 |
| peak_rss_bytes（最大） | 269647872 |

callback CSVの独立再計算：248セッション、193,501回、PASS。不足・連続不足・消費位置・最大/p95/p99・記録件数を再照合した。C++確保はTLS付きnew系で測定し、C malloc/OS内部全体を測ったものではない。

### 通常負荷の失敗は未解決

`native_product`でPCM16 Stereo 48kHz、4秒境界素材、2.00倍Candidateに不足2,048フレームが発生。同じ入力の`reproduce_fifo`は旧固定製品5/5成功、新経路9/10成功（失敗1,024フレーム）。`reproduce_stages`は19/20成功（失敗24,576フレーム）。元パス監視を分離し入力を非公開複製しても`reproduce_private_input`で19/20成功、失敗時10,240フレーム/20 callback/最大連続6,656フレーム。いずれもraw PCMは末尾まで一致していた。

非公開入力版の失敗ではDSP1ブロックの経過224.95ms、CPU27.92ms、その位相区間は経過201.70ms、CPU23.31ms。解析は最初のcallback前に完了。callback最大37,917ns、期限/HAL/時刻/形式/C++確保異常0でもFIFO不足が起きた。非CPU時間の内訳は未測定で、OS非実行や内部待ちを断定しない。最終版の再試験が成功しても未解決事象を取り消さない。

初期の`native_gate_v2`はBaseline蓄積上限修正前、`native_gate_final`はPhase57 map終端長であり、中断結果とSCOPEを保持し最終製品互換件数へ合算しない。

### 高負荷・長尺・ライフサイクルの限界

CPU2 thread＋128MiB保持、30秒MIXの9固定速度を各3秒、無音/持続/連続attack/連鎖のEOS、両presetを試験した。Pause/Resume、EOS→新規Play、Stop→新規Play、安全停止の模擬を測定。長尺実機は3分境界Candidate0.40/Baseline2.00、5分連鎖Candidate2.00/Baseline1.00の4条件をEOSまで検証。全速度×全形式の長尺実時間保証ではない。OS全体のメモリ逼迫、物理装置・レート変更、速度変更中の停止/再開は未検証。

3分境界0.40倍Candidateは約450秒の実機再生で19,845,000フレーム一致。最初のcallback約164msに対し解析完了約809msで、全曲解析前の正しい実機供給を確認した。一方、5分連鎖2.00倍Candidateは解析完了約937msまでMapが増えず、最初のcallback約1,006ms、EOS前公開0フレーム。特殊素材の待機を起動高速化の成功へ含めない。

入力変化は単体試験で解析前/解析後の切詰め、削除、置換、権限変更、その後の新セッション復旧を確認する。解析待ち中の取消、FIFO背圧中の停止、同一入力の複数セッションも検証する。

## 7. 起動時間の実測

同一入力・preset・0.50倍・装置・Releaseで各5回。入力MIXは44.1kHz/Float32/Stereoの30/180/300秒。受付相当の開始から最初の有効PCM callbackまで。単位ms。各セルは中央値 / 最大 / 母標準偏差。ColdとStop→Playを分け、失敗を除去して集計しない。Phase57の約52msは290秒PCM16のオフライン先行量相当であり、直接比較しない。

| 音源 | preset | 従来Cold | 新経路Cold | 従来Stop→Play | 新経路Stop→Play |
| --- | --- | ---: | ---: | ---: | ---: |
| 30秒MIX | candidate | 217.67 / 249.15 / 12.92 | 108.06 / 110.80 / 1.35 | 60.50 / 61.84 / 0.79 | 65.46 / 67.77 / 0.96 |
| 30秒MIX | baseline | 216.85 / 222.96 / 5.75 | 108.93 / 114.89 / 2.76 | 54.56 / 55.93 / 1.39 | 58.81 / 59.12 / 1.22 |
| 180秒MIX | candidate | 614.48 / 621.67 / 5.27 | 144.20 / 186.21 / 16.79 | 61.76 / 67.76 / 2.78 | 101.78 / 105.44 / 2.84 |
| 180秒MIX | baseline | 603.63 / 608.62 / 3.15 | 141.16 / 150.96 / 4.11 | 53.48 / 61.50 / 3.32 | 90.35 / 98.06 / 3.43 |
| 300秒MIX | candidate | 906.72 / 916.66 / 6.02 | 172.57 / 193.57 / 9.04 | 62.60 / 66.76 / 2.03 | 128.18 / 130.74 / 3.42 |
| 300秒MIX | baseline | 908.06 / 973.26 / 29.80 | 188.65 / 217.12 / 13.08 | 56.28 / 64.85 / 3.59 | 123.80 / 130.94 / 4.16 |

Coldの同一条件比較は6条件とも中央値を短縮した。Stop→Playはキャッシュ条件が異なるため上表の各条件で比較する。解析キャッシュは新経路へ未統合。入力の全SHA・非公開コピーを新経路の時間から除外していない。参照PCMの事前読込みは検証器だけの作業で原点前。Mach/steady接続の不確かさも保存し、1ms以下を有効条件とした。

Play→callbackの統計は`startup_after_ready_fix/statistics.json`、Readyや解析・各公開境界・資源の統計は`startup_after_ready_fix/stage_resource_statistics.json`。従来の段階情報は所要時間であり、最初の閉鎖eventの絶対時刻は未計測。新経路の各段階はsummaryへ保存する。callback到達は物理的な可聴開始ではない。ループバック未実施。Coldは新規プロセス・解析キャッシュmissを意味し、OSファイルキャッシュは消去しない。参照生成後に各回A→Bで測定し、装置・OS履歴への順序効果を独立評価していない。

## 8. CPU・メモリ

Cold準備と約1秒の実機再生を含むプロセスCPU時間とプロセス生存中Peak RSSの中央値。検証用の記録出力などの費用も含む。新経路の検証器は全参照PCM・記録領域を追加するため製品DSP単独のメモリ差ではない。

| 音源/preset | 従来CPU秒 | 新経路CPU秒 | 従来RSS MiB | 新経路RSS MiB | 参照PCM MiB | 入力複製MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 30秒/candidate | 0.255 | 0.366 | 58.3 | 69.5 | 20.2 | 10.1 |
| 30秒/baseline | 0.251 | 0.359 | 58.3 | 69.4 | 20.2 | 10.1 |
| 180秒/candidate | 0.624 | 0.918 | 58.4 | 172.1 | 121.1 | 60.6 |
| 180秒/baseline | 0.618 | 0.911 | 58.5 | 172.0 | 121.1 | 60.6 |
| 300秒/candidate | 0.918 | 1.223 | 59.7 | 253.6 | 201.9 | 100.9 |
| 300秒/baseline | 0.919 | 1.221 | 59.8 | 253.6 | 201.9 | 100.9 |

入力複製は一時ストレージとOSページキャッシュを消費する。上限512MiBで、曲長に比例する。伸縮済み全PCMディスクキャッシュは追加していない。解析CPU/監視込みthread CPU、DSP advance CPU/thread全CPU、待機・snapshot所有量は各summaryに保存する。従来側のpublished worker cycle CPUは公開ブロックの部分和であり、thread全量と比較しない。未計測の従来callback確保はnull。

初期起動試験の5分MIXでは17セッションが解析完了前に停止した。raw summaryの`analysis_cpu_s`/snapshot統計は`analysis_done=false`時の初期値0であり、0 CPU/0 byteの実測ではない。`final_summary.json`ではnullへ正規化し、段階統計も解析完了した実行だけを母数にする（各nを保存）。原記録と初期集計を保持する。process/thread CPUは停止までの実測区間費用であり、未処理の残りを含む全曲総量ではない。

## 9. ビルド・Golden・既存回帰

Release全ターゲット・別領域のarm64 Debug全ターゲットをビルドした。決定論的CTest 84/84、関連Debug CTest 8/8、Golden 25/25。Phase56増分解析、Phase54 cache/seek、既存動的計画・境界・densityのテストを含む。

| Phase57回帰 | 全PCMセッション | 一致拒否条件数 | 結果 |
| --- | ---: | ---: | --- |
| stage1 | 4,704 | 0 | PASS |
| stage2 | 46,368 | 0 | PASS |
| long | 48 | 0 | PASS |
| natural | 210 | 0 | PASS |
| rejections | 14 | 2 | PASS |

Phase57合計51,344全PCM回帰。元のmap終端契約の固定参照（SHA `461c26d10b0fd8a781cbffcbbab49072f501e02172e2a7c2f26e3e49a0253a1e`）を使い、製品長参照へ置き換えていない。

従来製品の実機smoke（シーク・速度変更・Pause/Resume・Stop/Play）は1/2。既存実時間CTestは2/2、不合格0。過去Phase54のphase44 FAIL（最大起床遅れ42.1952ms）はそのまま保存し、同一条件・閾値の今回ログを`legacy_realtime_ctest.log`へ保存。故障注入検出のテスト成功を通常再生成功とはしない。

元HEAD `88d5394c3d48970b14807c2d5151e4a3a4f86a2b`、main、開始時clean。既存資産15,695件のGit blob照合はPASS。例外はCMake、Phase36内部ヘッダー、Phase57合成cpp/hのみ。Phase53〜57結果・Golden・旧参照を上書きしていない。固定参照ハッシュ再確認はPASS。最終バイナリ・ビルド設定・製品link内容は`final_binaries.json`と`build_settings.json`。

## 10. リスク、11. 製品統合、12. 次Phase

主な未達は通常負荷での供給停止、動的161段階変更と同一論理条件でのPCM比較、Latest-Wins、物理装置/レート変更、速度変更中のライフサイクル、キャッシュ共有、OS全体の資源圧迫。FIFO不足はraw PCM一致だけでは検出できず、最終版の成功例だけで安定性保証へ拡張できない。

Gate 1未達、Gate 2未実装、Gate 3部分検証、Gate 4採用不可。公開API/既定製品経路/Merodoaは維持する。非同期準備API、状態・世代・通知・キャッシュ寿命の設計案と移行条件は`docs/PHASE58_PRODUCT_HANDOFF.md`。

Phase58 Fixでは保存済み入力の2.00倍CandidateをAudio System Traceで調べ、非実行と内部待ちを切り分ける。通常pthreadのQoS指定だけでは足りていない。リアルタイムworker/Audio Workgroup、事前確保、有界同期、I/O分離を検証し、先行量や品質を緩めずGate 1を再評価する。その後に継続DSPへPhase39動的契約を接続し、要求の論理位置を固定した参照比較器・161速度網羅・実機負荷試験を進める。物理装置試験と公開API統合はその後とする。

## 再現用コマンド例

各`--output`には存在しない新規パスを指定する。ネイティブ再生と重い試験を同時実行しない。

```sh
python3 scripts/phase58_study.py --suite all_speeds --output results/phase58/recheck_161
python3 scripts/phase58_reproduce.py --output results/phase58/recheck_underrun --repeats 20 --legacy-repeats 5
python3 scripts/phase58_native_validation.py --suite long --output results/phase58/recheck_native_long
```

不足再現driverの終了コードだけで合格判定しない。各`rows.json`/`summary.json`とnative summaryのPASS・PCM・FIFO・時刻を参照する。保存済み結果は再実行先にしない。


従来Candidate実機のFAIL内訳：raw PCM/FIFO/処理期限はPASSだったが、callback 2でhost進行誤差12,069,728ns（約12.07ms）、sample進行誤差532フレームを検出した。`legacy_native_candidate_clock_analysis.json`に既存Phase46基準による再計算を保存。BaselineはPASS。今回の既存実時間CTest 2/2成功だけで、この実機FAILを取り消さない。

## Ready通知の修正と最終版の追加確認

修正前の速度行列では、準備は約17〜39msで完了しているのに約60秒待つケースを23件検出した。元のPCM比較PASSは通知期限の成功を意味しない。`ready_wait_counterexamples.json`、`pcm58_all_speeds_before_ready_fix`、当時のバイナリとソースを保持する。Ready/Cancelledの更新を条件変数の待機と同じmutexで保護し、predicate確認と待機開始の間の通知取りこぼしを防いだ。callbackのmutexや品質・FIFO設定は変更しない。

修正後の短尺EOS反復：1000セッション、PCM/通知 PASS、最大通知遅れ2.745ms。1秒の検出基準は60秒通知落ちを検出する機能試験であり、音声callbackの期限やPCM許容誤差ではない。

測定版160セッションの後、通知用フラグの所有権とReady/Cancel同期、未完了統計のnull表示を修正した。`notification_lifecycle_final`の8セッションはこの版で再確認した。最初の160件を現在のバイナリの計測へ読み替えない。

最終版の起動比較をさらに30組・新経路60セッションで再実行した。上の起動/CPU表はこの最終版の値を使用し、初期測定を`startup_final`へ保持する。同じ通常負荷不足条件を20回追加で再実行し、成功/失敗を`reproduce_after_ready_fix`へ全件保存した。

最終版同条件再実行：20/20成功。準備通知の修正だけでは、再生中の位相処理区間で生じた非CPU時間の原因を解消した証明にはならない。Gate 1と動的実装の保留は維持する。
