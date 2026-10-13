# Phase 46 — 実機の音声不足と計測の信頼性

## 結論

**実機の音声不足は再現した。供給停止とFIFO枯渇の関係は同じ実行で確認できたが、対応するSystem Traceを取得できず、OS側の根本原因は未特定。対策の採用と正式統合は保留する。**

正式Experimental 3500、Phase 30/36のプレイヤー、キャッシュ・シーク、Phase 41/42の音質基準は変更していない。今回の変更は独立`phase43_play`、研究用ワーカーの計測、判定、検証ツールに限定した。

## 指摘5件への対応

| 項目 | 対応 | 状態 |
|---|---|---|
| host timestampの意味・評価 | 有効フラグ、符号付き差、sample time、連続性、フレーム数との整合、再開epochを記録。供給・処理時間・host検査を分離 | 実装、Drums/MIXで検証 |
| Traceの取得と解析 | AUDIO_QUALITY / TRACE_CAPTURE / TRACE_ANALYSISを分離。終了コード、エラーログ、TOC、XML、PID/TID、被覆とUnknownを検査 | 障害検出テスト成功。今回の実Traceは不合格 |
| 実機不足の常時計測・因果関係 | callback循環バッファ、同じmach時刻の公開記録、段別wall/CPU、FIFO曲線、同じ周期との照合 | 実不足を記録。OS原因は未特定 |
| 応答の意味・中央値 | HAL時刻＋バッファ内位置による推定へ変更。通常中央値とnearest-rank p95を使用、方向別に集計 | 実装・数式確認。音響実測は未実施 |
| 最終コードの全回帰 | Release/arm64、コードの指紋、基準コミット、全CTest、Golden、計測ON/OFFを記録 | 下記の回帰節に実測を記載 |

## host時刻の仕様と判定

SourceNodeのtimestampは音声データをHALでレンダーする時刻を示す。SDKヘッダーは、下流にサンプルレート変換などがあるとsample timeが無効になる場合も明記している。callbackへ入った時刻そのものとは区別する。[Apple SourceNode render block](https://developer.apple.com/documentation/avfaudio/avaudiosourcenoderenderblock), [Apple render input block](https://developer.apple.com/documentation/audiotoolbox/aurenderpullinputblock)

今回の経路は`SourceNode(float32 planar、入力のサンプルレート) → mainMixer(固定gain 0.5、計測時は消音) → 内蔵出力48kHz`。Drumsは48kHzで変換なし、MIXは44.1kHzで変換あり。

判定は次の研究用基準を使う。

- **供給**：FIFO不足・書込み拒否・ワーカーエラー・要求未完了・長さ/EOS不整合をFAILとする。
- **処理時間**：`callback end − start > requestedFrames / sourceRate`を処理予算超過とする。起床遅延とは別指標。
- **host連続性**：必須hostフラグ/値がない、同じepochでhostが逆行または停止、前回フレーム時間とのずれが許容値を超える場合はFAIL。sample timeは有効な場合だけ有限性・フレーム進行を検査する。
- **HAL準備期限**：HALの最初のフレーム時刻までにデータを返すモデルとし、`end > host + tolerance`を期限逸脱として記録する。`tolerance = max(100µs, 2 source samples)`。この許容値は研究用で、Appleが保証する普遍的な閾値ではない。
- **時刻基準の取り違え**：検証した内蔵出力向けの追加検査として、startとhostの差が1秒を超える場合はoutlierとする。近い未来のhost時刻は正常として扱う。
- **停止・再開**：音声が完全に静止している間にepochを更新する。epochを跨ぐ時刻のジャンプを、連続再生中の逆行と混同しない。経路変更は従来どおり安全停止で、通常EOSとして扱わない。

これらはSourceNodeで観測できる情報に基づく検査であり、下流全体の実行時間や実際の音響提示を直接観測したものではない。AudioUnitのsample timeの連続性と、SourceNodeでSRC時に無効になる例外を区別する。[Apple AudioUnitRender](https://developer.apple.com/documentation/audiotoolbox/audiounitrender(_:_:_:_:_:_:))

短時間実機試験のDrumsではstart−hostが約−13.018〜−12.903ms、host進行誤差最大7.958µs。MIXでは約−13.377〜−13.225ms、進行誤差最大13.772µs。実際のフラグはDrums 716/716件、MIX 786/786件が7（host/sample/rate scalar有効）。今回のMIXの経路ではSRCありでもsample timeは有効だった。無効sample timeの扱いはSDK仕様と障害注入で確認し、実測と区別する。欠損、逆行、処理予算超過、HAL準備期限逸脱は0だった。未来hostを一律に異常としない設計を実測で確認した。

## 記録方式

callbackはprepare時に確保した65,536件の循環バッファへ、通番・epoch・generation・raw出力位置・start/end mach・host・フラグ・sample time・要求/取得数・FIFO残量・最後の公開時刻を記録する。CSVの書込みはエンジン停止・callback静止後に行う。上書きされた件数を明示する。

ワーカーは16,384周期の事前確保領域へ、公開mach/Unix時刻・公開数・FIFO前後・周期wall/CPU・FIFO待機/書込み・計画・mutex待ち/保持・WAV/FFT/位相/OLA/FIRのwall/CPUを記録する。記録不足件数を公開する。FIFO公開間隔は初回プレフィルを除外する。

今回の7実行はcallback記録上書き0、ワーカー記録不足0。raw PCM SHA-256はワーカー内で計算し、callback内へハッシュ処理を追加しない。比較参照の合成は実機再生後に行った。C++ newのcallback計数は0。C mallocやApple内部の割当全体を測定したとは主張しない。

## 反復実機結果

対象：Drums 3分、初期0.40、出力1/6/14/22秒で`2.00 / 0.40 / 1.00 / 2.00`へ要求。高負荷は同じ既存2本のbusyスレッド。FIFO16,384、先行12,288、DSPブロック2,048、実機callback512。

| 実行 | Trace条件 | 音声 | 計測 | Trace取得/解析 | 不足frames / calls | 最大連続不足 ms | 最大公開間隔 ms | 最低FIFO |
|---|---|---|---|---|---:|---:|---:|---:|
| 13:38:52 | なし | PASS | PASS | 未要求 | 0/0 | 0 | 186.223 | 4096 |
| 13:41:04 | なし | PASS | PASS | 未要求 | 0/0 | 0 | 184.571 | 1536 |
| 13:43:15 | なし | PASS | PASS | 未要求 | 0/0 | 0 | 206.016 | 2560 |
| 13:47:27 | 120秒記録 | PASS | PASS | FAIL/FAIL | 0/0 | 0 | 132.916 | 2560 |
| 13:50:58 | 120秒記録 | **FAIL** | PASS | **FAIL/FAIL** | **8192/16** | **106.667** | 248.740 | 0 |
| 13:54:30 | 空き容量で記録中止 | PASS | PASS | FAIL/FAIL | 0/0 | 0 | 202.807 | 2560 |
| 13:59:40 | 40秒後から35秒記録 | **FAIL** | PASS | **FAIL/FAIL** | **8704/17** | **181.333** | 442.126 | 0 |

日時は2026-10-13 JST。正しい判定を反映した一覧は`summary_reviewed.csv`。音声5件PASS・2件FAIL。全7件のraw PCMは、同じ実際のTimeMap/解析履歴の独立参照へSHA-256一致した。**raw PCMが一致しても、期限どおりに供給できない実行は音声FAIL。**

Traceなし3件では不足0/3。実際に記録を開始した3件では不足2/3。母数が小さく、OS状態の取得も失敗したため、Traceが元のPhase 45の不足原因だったとは断定しない。記録負荷・空き容量・メモリ圧迫の影響を分離する必要がある。

callback最大は全実行で0.020〜1.607ms、処理予算10.667ms未満。書込み拒否0、host検査異常0。RSSは40.17〜40.88MiB。詳細CPU、公開間隔p95/p99は`summary_reviewed.csv`。通常中央値を使った4要求の集計は約1,044〜1,045msだが、異なる方向を混ぜた値なので、初回変更の操作応答として使用しない。

## 同じ実行の不足原因の切り分け

13:50:58の実行では約56秒付近で、10回＝5,120frames（106.667ms）と、6回＝3,072frames（64ms）の2区間が不足した。callback時刻、公開mach時刻、同じ周期のCPUを関連付けた。

| output開始 | 公開間隔 wall ms | 同周期CPU ms | 公開前→後FIFO | 位相 wall/CPU ms | WAV wall/CPU ms |
|---:|---:|---:|---:|---:|---:|
| 2713600 | 43.881 | 3.919 | 10240→12288 | 2.417/2.417 | 0.105/0.105 |
| 2715648 | **248.740** | **21.427** | **512→2560** | **199.615/18.285** | 2.409/0.561 |
| 2717696 | **159.920** | **22.726** | **0→2048** | **56.036/15.703** | **101.778/5.107** |
| 2719744 | **111.058** | **27.710** | **0→2048** | 24.320/21.023 | **83.964/4.470** |
| 2721792 | 17.641 | 17.131 | 1024→3072 | 13.467/13.015 | 2.407/2.403 |

**直接確認できた原因**：長い供給間隔が連続し、最初の約249msで蓄積量が減った直後に約160/111msの供給間隔が続いてFIFOを空にした。単一の最大周期だけで因果関係を判断していない。各不足callbackの前後50件を`underrun_*_timeline.csv`へ保存した。

計画0、mutex待ちは該当周期で約0.2〜0.5µs、FIFO待機もほぼ0。位相区間とWAV区間に大きなwall/CPU差があった。ただし、これは**どの区間で時間が経過したか**の記録であり、Preempted、Runnable、Blocked、I/O、ページフォルトの直接証拠ではない。

13:59:40の短いTrace試行でも不足8,704framesを記録した。ディスク不足でドライバーが終了し、native終了コードの保存が欠けたが、**既に観測された不足はFAIL**とする。初回復旧時のINDETERMINATE表示は`quality_correction.json`で訂正した。元の生ログ/JSONを上書きせず訂正履歴を残した。

## Trace取得・解析

`phase45_focus_trace.py`は共通の新検証処理へ接続した。正常記録、エラーログ/非0記録、音声FAILだが有効Trace、XML展開FAIL、PID不一致、未知状態の被覆を障害注入テストで検査した。**検出テスト成功と実Trace成功を区別する。**

今回の実Traceは成功0件。120秒記録2件は終了処理のタイムアウト、TOC展開コード10（Document Missing Template Error）。終了コード`-1`は初回ツールの未取得sentinelであり、xctraceの実終了コードとは呼ばない。修正版はPopenの実returncodeを保存し、タイムアウト時にSIGINTで終了を試みてから必要な場合のみ停止する。

35秒記録も保存/終了処理でディスクが満杯となり、ドライバー終了120。xctrace終了コード・TOC・XML・対象PID/TID・OS状態被覆は未取得。callback/worker CSVとPCM指紋は保存されていたため復旧した。Trace解析へ別実行のOS状態を流用しない。全不足区間のSystem Trace原因分類は**未確定**。

空き容量は記録前約11GiBから、満杯まで低下した。今回生成した、開けない120秒Traceだけを不合格検査後に整理した。ファイル一覧、サイズ、先頭4KiBのハッシュを`failed_trace_inventory.json`へ保存。対応する一時ktraceはサイズ・ハッシュが失敗Trace内ファイルと一致することを確認して削除した。35秒失敗の一時ファイルは生成時刻・今回の実行との対応を確認して整理し、部分Traceパッケージは残した。既存Phase 45以前のTrace/一時ファイルは削除していない。

現在のTraceツールは記録前の6GiB空き確認を行うが、今回の急増を十分に防げると証明していない。今後は余裕のある別scratch領域、保存容量/記録時間の校正、正常停止を先に確認する。追加の実Trace試行は停止した。

## 対策A〜E

| 方式 | 実装/試験 | 判断 |
|---|---|---|
| A 標準BCD | 7実機実行、上表 | 基準を維持。不足は未解決 |
| B QoS/優先度 | 既存研究用設定を選択可能、Phase 46の反復未実施 | OS原因の有効記録がないため採用しない |
| C ブロック1024 | 独立プレイヤーの研究用パラメータを用意、反復未実施 | 採用なし |
| D WAV/計算先読み | 未実装 | WAV区間のwall増大をI/O原因と決めつけて変更しない |
| E 先行量の限定変更 | 研究用パラメータを用意、反復未実施 | 遅延と不足の改善を検証する前に採用しない |

CoreAudioの優先度は変更していない。原因情報が不十分なままQoSやバッファの比較を成功策として採用しない。

## 操作応答の定義

callback入口への単純なdevice latency加算は、HALまでの先行時間と、callback内のサンプル位置を落とす。新しい推定は次の通り。

```text
sampleOffset = (frame − callback.rawStart) / sourceSampleRate
HAL frame time = callback.timestamp.mHostTime + sampleOffset
estimated hardware presentation = HAL frame time + device.presentationLatency
response = estimated hardware presentation − user operation mach time
```

前提は、SourceNodeのHAL時刻を、HALから装置へ渡す時刻に対応するとみなすこと。直接のAudioDeviceIOProcでは、出力時刻は最初のフレームをハードウェアへ渡す時刻として定義されている。ただし今回SourceNode→HALの対応をループバックで実証したわけではない。[Apple AudioDeviceIOProc](https://developer.apple.com/documentation/coreaudio/audiodeviceioproc)

device `presentationLatency`は装置/ストリーム遅延を示す。source `outputPresentationLatency`は下流全体の最大遅延なので、deviceと重ねて加算しない。今回どちらも1.375ms。SRCや追加バッファの時間はHAL時刻との対応に含まれると仮定するが、その誤差は未校正。[Apple presentationLatency](https://developer.apple.com/documentation/avfaudio/avaudioionode/presentationlatency), [Apple outputPresentationLatency](https://developer.apple.com/documentation/avfaudio/avaudionode/outputpresentationlatency)

**これは可聴時刻のモデル推定であり、可聴時刻の実測ではない。** 最初のrawビット差分と、人間が変化を認識する位置も区別する。`direction_latency.json`、各実行の`operation_phase46.json`へ保存した。

| 方向 | 件数 | 適用ノードの推定提示遅延 中央値 ms | p95/max ms |
|---|---:|---:|---:|
| 0.40→2.00 | 7 | 1396.964 | 1397.937 |
| 2.00→0.40 | 7 | 728.569 | 728.943 |
| 0.40→1.00 | 7 | 1536.444 | 1536.671 |
| 1.00→2.00 | 7 | 650.190 | 650.626 |

各4要求の通常中央値は中央2値の平均。p95は昇順の`ceil(0.95*N)`番目（nearest-rank）。7件ではp95と最大が同じ。Trace負荷の異なる実行を含む小標本であり、性能保証とはしない。約1.4〜1.6秒の応答短縮は継続課題で、今回安全な密度切替を早める変更は行っていない。

同じ実際の履歴を持つオフライン参照と「該当要求をまだ行わない履歴」の参照を比較し、最初のraw PCMビット差分をcallbackへ対応付けた。

| 素材/方向 | 最初の差分frame | 適用ノードframe | 最初の差分の推定提示遅延 ms | ノードの推定提示遅延 ms |
|---|---:|---:|---:|---:|
| Drums 0.40→2.00 | 113664 | 114030 | 1389.208 | 1396.833 |
| Drums 2.00→0.40 | 316416 | 322050 | 610.943 | 728.319 |
| Drums 0.40→1.00 | 744460 | 744818 | 1528.567 | 1536.025 |
| Drums 1.00→2.00 | 1084366 | 1086304 | 609.932 | 650.308 |
| MIX 0.40→2.00 | 114432 | 115006 | 1613.757 | 1626.746 |

OLA/FIRや解析密度変更の依存範囲により、ノードより前に差分が現れることを確認した。公開済みPCMの不変性は既存の独立参照/回帰で保持する。差分が聴覚上識別できる大きさかは、このビット比較だけでは判断しない。

## ビルド・回帰

検証時点の基準コミット：`d0635b0a4e0557e1e9c78c4486017590cff080d0`。本検証はPhase 46の変更を未コミットの作業ツリーで実施したため、このSHA自体が最終ソースを表すとはしない。検証した最終状態を`build_manifest.json`のパス別SHA-256と全体指紋で識別する。Release、arm64、Apple C++/Accelerate/AVFoundation/CoreAudio。

最後のコード修正後、全CTestをもう一度実行し、**56/56成功、683.95秒、終了コード0**を確認した。`final_state_ctest.log`へ保存。初回の全件56/56成功（689.29秒）も`final_ctest.log`へ保持した。新規テストだけの成功とは扱わない。Phase 34低速B、Phase 37高速B、Phase 41異音解消、Phase 42 safe-density、Phase 43〜45の判定/PCM回帰を含む。

最終ソース指紋：`e961550d725ee635ac58fba382047ff169e36cfedaf1519e330ba3dc3324f839`。最後の全件実行の前後でパス別SHA-256の一致を確認した。ビルド成功、Python構文検査、`git diff --check`も成功。

Golden 25/25と保持済みストリーミング出力がmanifest SHA-256に一致（`golden_audit.csv`）。計測ON/OFFのSHAはともに`2270498ac2e9f0f8f96392f09984ed8a3aa171c985f5f4168c0e86f5183473c0`。実解析履歴とのOLA重み誤差最大`1.28004e-7`、計測ONの上位20ブロックnew計数265、OFFはunmeasured。0とは表示しない。

## 正式統合と残る課題

正式統合は**不可/保留**。音声不足0を安定して満たしておらず、同一実行のOS原因が未特定。Phase 45の64ms実行の原因を、今回の記録負荷/ディスク圧迫と自動的に同一視しない。

次の優先事項は、正常終了するTrace取得環境を用意し、不足を起こした同じ周期のOS状態を取得すること。その後にB/C等を同じ条件で反復比較する。音質基準、公開済みPCM、密度安全条件を守ったまま供給停止を防ぐ。操作応答短縮は別の評価軸として継続する。

## 再実行

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j 4
ctest --test-dir build --output-on-failure
python3 scripts/phase46_native.py --repeat 3
```

実機試験にはmacOSオーディオAPIの利用権限、ローカルの3分Drumsが必要。Trace再試行は、先に保存容量と正常停止を校正すること。失敗/未取得をPASSにしない。Source/Trace/WAV/GoldenはGit管理外のローカル資産を使用する。
