# Phase 61 Fix：Fast Random Access Seek

開始点：`main@1839480e1d6cb14fcc6a7f2ce814e007457cabd2`。開始時の作業ツリーは空。実装・検証は未コミットの作業ツリーで行い、Pushは実施していない。Phase62、Merodoa、submodule、既存Golden、Phase60/61の承認記録を変更しない。

本報告とJSON内の未コミット・未ステージの記述は検証終了時点の状態を示す。利用者の後続のコミット指示は、検証結果やNO-GO判定を変更しない。

## 実装と判定

Exact Seekを維持し、先頭からのPCM合成を行わないFast Local Seekを明示的な実験APIとして追加した。原曲の確定TimeMapを使い、目的位置の0.5秒手前を基準に局所DSPを開始する。1秒・2秒も比較用に選択できる。全曲伸縮済みPCMキャッシュは作らない。

DSPは音声信号処理、FIFOは先入れ先出しの再生待ちバッファ、epochは切替ごとに識別する再生区間を指す。Readyは新しいPCMの準備完了であり、スピーカーへ提示された時刻ではない。

**製品採用はNO-GO**。短い音源648件は数値検査を通過したが、300秒インパルス列では1080件中78件が事前に定めたスペクトル誤差3dBを超えた。利用者の追加試聴は「違和感なし」だったが、この数値失敗を成功へ変更しない。既定の `allowUnvalidatedFastLocalSeek=false` はFast要求をRejectedにし、検証ホストだけが明示的にtrueを指定する。公開 `Capabilities.seek=false` は維持する。

設計とAPIは [PHASE61_FAST_SEEK_SPEC.md](../../docs/PHASE61_FAST_SEEK_SPEC.md)。変更ファイルの完全な一覧・SHA-256は `SOURCE_MANIFEST.json`、生データの保存先・サイズ・SHA-256は `ARTIFACT_MANIFEST.json` に記録する。

|変更ファイル|内容|
|---|---|
|`CMakeLists.txt`|新しい状態CTest、単独実験、実機/Sandboxの明示実行ターゲット|
|`src/dsp/RingOverlapAdd.{h,cpp}`|絶対出力位置で空のOLAを初期化|
|`src/prototype/Phase36SynthesisCore.h`|共通入力seed、FIRの絶対ブロック格子|
|`src/prototype/Phase57ProgressiveSynthesis.{h,cpp}`|確定マップから局所初期化、Exact保存点の混入拒否|
|`src/prototype/Phase58RealtimePipeline.{h,cpp}`|共有入力leaseによるFast epoch、診断、DSP側包絡|
|`src/prototype/Phase61SeekEnvelope.h`|事前確保した5msの包絡と取り消し時の復帰|
|`src/platform/macos/ProgressiveMacPlaybackEngine.{h,mm}`|研究用受付、Ready後の下降待ちと安全な切替|
|`src/playback/ProgressiveSeekContract.h`|Exact/FastLocal方式と準備長の公開|
|`src/prototype/Phase61FastSeekStudy.cpp`|独立オフライン実験ホスト|
|`tests/Phase61FastSeekTests.cpp`, `tests/Phase61FastSeekSmoke.py`|161速度の受付、状態・座標・全suffix/EOSの新試験|
|`tests/Phase61FastNativeTests.cpp`, `tests/Phase61FastSandboxApp.mm`|実機操作、境界PCM、時刻・確保・FD再利用、Sandboxの新試験|
|`scripts/phase61_fast_seek_study.py`|独立フル参照との数値比較、0.5/1/2秒と長尺測定|
|`scripts/phase61_fast_verify_native.py`|callback PCMとオフライン局所DSP＋包絡の完全一致|
|`scripts/phase61_fast_clock_experiment.py`|採用しなかった絶対座標位相補正の再現手順|
|`docs/PHASE61_FAST_SEEK_SPEC.md`, `results/phase61_fast_seek/`|今回の仕様・失敗を含む検証記録・SHA/復元情報|

## 現行状態の解析と局所初期化

- **累積合成位相**は先頭履歴に依存する。任意位置から元の累積位相を正確に復元する主張はしない。Fastでは分析位相を新しい原点にする。Exactの先頭再構築と正確な保存点は変更しない。
- **分析位相・振幅・左右の直前位相差**は局所のFFTで作成・更新できる。ピークの位相固定、過渡音リセット、左右同時処理は従来の処理を使う。
- **OLA（窓を重ねる処理）とFIR（帯域合成フィルター）**は有限の履歴である。絶対出力座標で空の領域を開始し、有限の準備区間を捨てる。FIRは2048/3584サンプルの元のブロック格子を保ち、共通周期14336で開始する。
- 3帯域を別々の入力中心から始める方式は採らず、同じ入力中心に揃える。通常の共通入力ホップは2048、0.40〜0.49倍では1024。過渡音イベントの途中から再開する際も従来の厳密な中点比較を使う。
- 原曲入力フレームのTimeMap変換、総出力長での上限処理、曲長ちょうどの扱いはExactと共通。FIR/OLA開始の都合によって要求座標を丸め直さない。

低位の `ProgressiveSynthesisEngine::initializeFastLocal` は確定解析・確定固定マップの供給後、最初の合成前にだけ呼べる。戻り値は要求入力/出力、共通入力seed、FIR開始出力B。Bから目的位置までのPCMだけを捨てる。局所状態はExactの保存点として複製できない。

## APIとライフサイクル

```cpp
requestFastLocalSeekToInputFrame(frame, inputGeneration = 0,
                                renderEpoch = 0, prerollMillis = 500);
requestFastLocalSeekToInputSeconds(seconds, inputGeneration = 0,
                                  renderEpoch = 0, prerollMillis = 500);
```

準備区間は500/1000/2000msだけを受け付ける。研究用途ではprepare前に `ProgressiveOptions.allowUnvalidatedFastLocalSeek=true` を指定する。既存 `requestSeekToInputFrame/Seconds` はExactのまま。新しい `SeekOperation.mode` と `prerollMillis` で方式を区別する。受付ID、8状態、入力世代、render epoch、失敗理由、速度変更時の同ID再計画、Latest-Winsは既存契約を使う。NaN/Inf/負値/曲長超過は拒否し、曲長ちょうどを受け付ける。旧bool APIは公開ゲートfalseの互換動作を維持する。

Playingでは新FIFOがReadyになってから、旧DSPに5msの下降包絡を要求する。既にFIFOへ入った先行PCMと下降区間を消費した後、安全なepoch交換を行う。新PCMの先頭5msには上昇包絡を付ける。どちらもDSP作業スレッドで事前計算した曲線を掛け、フレームを挿入・削除しない。Candidate16384/Baseline12288のFIFO先行量を維持する。

**Readyと切替は別の時刻である。** 旧FIFOの先行量を維持するため、Playingの切替はReadyより遅れる。Paused/Readyは自動再生せずに移動する。取り消し時は旧DSPへ5msの復帰を要求するが、既にFIFOへ入った下降・ゼロ区間は消せないため、音量復帰が遅れる場合がある。旧DSPが既にEOSの場合は残りFIFOの消費を待ち、既存EOSの波形を変更しない。

音声コールバック本体はHEADと同一（SHA-256は `PROTECTION.json`）。DSP/I/O/メモリ確保/mutex/待機/ログを追加していない。包絡用メモリーは通常スレッドの構築時に確保する。旧epochの破棄はcallback参照終了後の通常スレッドだけで行う。入力FD lease、不変解析、単一所有者、予算上限、Workgroup参加/離脱/復元は従来経路を使う。

## 独立オフライン実験

製品経路へ接続する前に、単独の `phase61_fast_seek_study` で局所DSPを検証した。比較対象はPhase57以前の固定ソースから作った独立フルレンダーであり、局所初期化や増分DSPを経由しない。

- 独立DSPソース：`ec087019626d9ff0d9f157245729b74ddb6847d7:src/prototype/Phase36StreamingSpeedEngine.cpp`
- ソースSHA-256：`4ffec7c4db196f51e89bd4ebaf336020ae71d0969c31393a40752b4a37ed3899`
- Release参照実行体SHA-256：`de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`
- 局所実験実行体SHA-256：`8dd0f1e9f3ebb52391e5e16a2ef4b98d62848645cf3d2b307930957e8e372a0d`
- 測定時のドライバーは `build/phase61_fast_seek/quality_driver_v1.py` にSHA一致で保管。後から性能試験用の入力指定引数を追加した現行スクリプトと区別する。

条件は既存10秒音楽5種（mix/bass/drums/guitar/vocal、44.1kHzステレオ）と、低音持続音・帯域境界・左右位相差・過渡音の合成信号4種（48kHzステレオFloat32）。0.40/0.50/0.75/1.00/1.50/2.00倍、Candidate/Baseline、0.5/1/2秒準備、入力中央+17と3/4+31の2位置、各1秒の出力を比較した。合計648ケース。

要求入力座標・確定TimeMap出力座標・ブロックの連続性・有限PCMは648/648で通過。出力欠落・重複は0。PCM完全一致は464/648であり、184件には差異がある。Fastに先頭履歴とのRAW一致を要求していないことを明記する。既存Exactの完全一致基準は変更していない。

|数値指標|648件での最大絶対差|Fast用の暫定検査閾値|
|---|---:|---:|
|RMS音量|0.581dB|1.5dB|
|参照エネルギーで重み付けしたスペクトル誤差|0.806dB|3dB|
|左右位相差|0.163度|10度|
|左右音量比|0.0224dB|1dB|
|低音包絡の変動係数の差|0.00180|増加0.03|
|低音ピッチ|0.00414セント|5セント|
|過渡音信号の最大エネルギー位置|0ms|参考値・主観試聴と併用|
|同過渡音の最大エネルギー|0dB|参考値・主観試聴と併用|

これらは新方式のスクリーニングであり、既存Golden/実時間音質判定の代替ではない。閾値は最初の比較前に定義し、648/648が通過した。位相原点が異なる持続音ではPCM差が大きくても音量・ピッチ・揺れ・定位は別に評価する。音色や過渡音の自然さを数値だけで断定しない。

利用者が5つのA/Bクリップ（低音・定位・過渡音・音楽・帯域境界）を試聴し、**「違和感なし」**と回答した。Aは独立フルレンダー、Bは局所DSP、間に0.5秒の無音。各単独クリップの両端に5msの包絡を付けた。この結果を全速度・全長・実機の全切替音へ拡張しない。ファイルとSHAは `LISTENING_RESULT.json` に収録する。6つの試聴WAVは `LISTENING_RECIPE.json` の手順で元のSHAまで再構成できることを確認した。

先行の音質試験はビルド/回帰と並行しており、0.5秒準備でもReady p95=216.283msだった。この値を200ms達成としない。性能の本測定は他のビルド・回帰・音声実機試験と直列化して行う。

## 長尺で見つかった品質未達

48kHzモノの300秒インパルス列は、6速度×両preset×10位置×3反復×3準備長の1080件を独立参照と比較した。入力位置誤差・出力欠落・重複は全件0だが、スペクトル検査は1002/1080。失敗は78件（26条件×3反復）で、0.5秒準備36件、1秒24件、2秒18件、最大誤差3.59319dB。いずれもスペクトル閾値超過であり、閾値や信号を変更して通過させていない。44.1kHzステレオ300秒音楽の0.5秒準備360件は座標・数値検査とも通過した。

失敗入力の解析では、3515個の過渡音が1個の閉鎖イベントへ結合され、イベントのピークは解析フレーム2、終端は14058だった。従来DSPの位相リセットはピーク付近だけなので、深部へ局所初期化した累積位相差が0.5/1/2秒の事前合成では消えない。OLA/FIRの有限履歴を満たすことと、累積位相の復元は別の問題である。これは今回の分析に基づく原因の説明であり、全失敗音源への一般的な証明ではない。

既定0.5秒の失敗例（スペクトル差3.42406dB）は、主要パルス17個の位置ずれがすべて0フレームだった。追加A/Bを利用者が試聴し、**「違和感なし」**と回答した。主観評価の対象はこのクリップだけであり、音の余韻を含む数値失敗36件を取り消さない。条件・PCM SHA・ピーク対応・回答は `LONG_CHAIN_FAILURE.json` に残す。

代替仮説として、局所FFTの推定周波数と絶対入力/出力座標差を使う位相補正を、隔離した実験実行体で試した。選択した60件で失敗は8件から6件へ減ったが、最大スペクトル差は3.20581dBから5.65009dBへ悪化した。製品DSPには採用していない。`scripts/phase61_fast_clock_experiment.py` と `CLOCK_SUMMARY.json` に手順・対象・失敗を残す。

## 300秒性能試験

Release、6速度（0.40/0.50/0.75/1.00/1.50/2.00）、両preset、各3反復。固定位置は0/30/150/270/285秒、さらに乱数seed61061の5位置を使う。オフラインはPython Random、実機はホスト内のLCGなので、ランダム位置の集合は異なる。各入力セッションで未訪問の位置を用い、FastはExact保存点を使用しない。原本の読み込み・不変解析は最初に1回だけ行う。

p95は全件を含む線形補間。順位 `ceil(0.95*N)` のp95もJSONに併記する。0秒を含む全位置を集計し、深部/速度/preset別も `OFFLINE_RESULTS.json` と `NATIVE_PERFORMANCE.json` に残す。

|オフライン入力|準備長|件数|Ready p50 ms|p95 ms|最大 ms|品質数値失敗|
|---|---:|---:|---:|---:|---:|---:|
|300秒48kHz mono|0.5秒|360|44.887|71.716|80.571|36|
|同上|1秒|360|66.880|113.344|122.949|24|
|同上|2秒|360|110.186|203.240|209.490|18|
|300秒44.1kHz stereo音楽|0.5秒|360|156.107|251.198|513.281|0|

ステレオの暫定200ms目標は未達。構築p95=3.370ms、TimeMap供給0.479ms、局所初期化0.013msに対し、残りの準備合成・検証出力・その他の処理はp95=245.947ms。オフラインReadyには検証RAWの先頭部分のファイル書込みも含まれるので、この残差を純粋なDSP CPU時間とは扱わない。実機ではFIFO経由のReadyとDSP CPUを別に測る。1秒/2秒へ延ばす方式は計算量を増やし、長尺の品質問題も解消しなかった。

実機の先行測定（Ready座標の公開修正前、実行体とソースは保存済み）：

|入力・条件|件数|Ready p95 ms|切替 p95 ms|初PCM callback p95 ms|実時間診断|
|---|---:|---:|---:|---:|---:|
|mono・解析完了後|360|93.179|435.892|445.694|360/360|
|stereo音楽・解析完了後|360|251.897|624.919|635.158|353/360|
|mono・初回Ready直後|36|77.977|385.155|394.604|36/36|
|stereo音楽・初回Ready直後|36|1428.435|1773.300|1783.523|36/36|

初回Ready直後のmonoは36/36で既に解析が完了していた。stereoは36/36で未完了で、Ready最大1495.390msだった。この待ちを200ms目標達成として隠さない。初回デコード/SHA/複製/mlockの時間はシークReadyに含まれず、入力準備時間として別に保存した。

先行stereoの7件は実時間の集約検査がfalseだった。原因別カウンターを保存していなかったため、この7件の原因を後から断定しない。成功した再試験だけへ置き換えず、診断を拡充した最終版の再測定と併記する。

最終版（Ready座標の公開修正・原因別診断追加後）では、入力leaseの全SHA/一時スナップショット/mlockは各入力セッションで各1回、シークによる再実行0、Exact保存点の使用0だった。下表は受付時刻からの経過であり、初回入力準備を含まない。

|最終版の条件|件数|Ready p95 ms|切替 p95 ms|初PCM callback p95 ms|HAL提示推定 p95 ms|実時間診断|
|---|---:|---:|---:|---:|---:|---:|
|mono・解析完了後|360|98.259|445.347|455.212|468.182|350/360|
|stereo音楽・解析完了後|360|249.641|616.709|626.463|639.810|356/360|
|mono・初回Ready直後|36|75.744|384.983|394.474|407.433|36/36|
|stereo音楽・初回Ready直後|36|1634.410|1985.240|1995.410|2008.762|36/36|

確定解析再利用時のmonoはReady目標を満たしたが、stereo音楽は未達。stereoの局所初期化自体はp95=0.028ms、解析作業スレッドCPUはp95=5.111ms、DSP作業スレッドCPUはp95=234.392msだった。CPU時間は診断取得時までの累積で、Ready以後のわずかな処理も含み、壁時計の各区間を厳密に分解した値ではない。主な計算負荷は局所の合成・FIFO準備に残る。旧FIFOの先行量を維持した切替待ちもReadyとは別の遅延である。

固定位置別のReady p95（各36件、6速度×両preset×3反復）：

|入力位置|mono ms|stereo音楽 ms|
|---|---:|---:|
|0秒|38.504|107.949|
|30秒|101.988|227.893|
|150秒|92.036|283.816|
|270秒|100.063|251.814|
|285秒|95.762|243.037|

ランダム5位置のmono（180件）：Ready p95=98.681ms、最大=112.194ms。

ランダム5位置のstereo音楽（180件）：Ready p95=254.281ms、最大=279.157ms。

速度・preset別のReady p95（各30件）：

|速度|preset|mono ms|stereo音楽 ms|
|---|---|---:|---:|
|0.40|Candidate|109.880|245.831|
|0.40|Baseline|96.910|231.186|
|0.50|Candidate|60.464|150.027|
|0.50|Baseline|58.630|139.977|
|0.75|Candidate|71.689|170.244|
|0.75|Baseline|65.590|158.811|
|1.00|Candidate|74.068|172.039|
|1.00|Baseline|66.207|165.403|
|1.50|Candidate|90.391|226.874|
|1.50|Baseline|84.889|200.038|
|2.00|Candidate|96.469|285.293|
|2.00|Baseline|92.757|259.288|

最終monoの10失敗行は、同じ入力セッションでHAL時刻間隔1回・サンプル時刻不連続1回を検出した累積値によるもの。最終stereoの4失敗行はDSP作業スレッド期限超過1回の累積値によるものだった。両方でFIFO不足、書込み拒否、callback期限超過、callback/DSPのC++ new、Workgroupのpolicy/参加/復元エラーは0。これを実時間ゲート全体の成功とはしない。生のOSトレースによる発生原因の確定は未実施で、今回callback本体を変更していない事実だけから原因を断定しない。

最終の初回Ready直後stereoは36/36で原曲解析が未完了。Ready最大1827.540ms。解析完了後の集計からこの待ちを除いたことを明示する。

HAL提示推定は既存callbackの時刻記録に基づく。スピーカーからの音響到達時刻は未測定。p95だけで全ケース200ms以内と解釈しない。

## 回帰試験と実機

Release24/24（114.43秒）、Debug24/24（348.41秒）。新試験は161速度の受付、文脈拒否、絶対ホップ/FIR格子、Exact保存点混入拒否、包絡の端点、56件の決定的な全suffix/EOSを検査する。既存23件を除外・緩和していない。

|CTest名|Release秒|Debug秒|
|---|---:|---:|
|phase54_analysis_cache|0.119 PASS|1.261 PASS|
|phase54_seek_pcm|36.173 PASS|115.506 PASS|
|phase56_state_safety|0.048 PASS|0.758 PASS|
|phase56_fixed_preset_maps|0.016 PASS|0.469 PASS|
|phase56_incremental_exact|1.240 PASS|3.075 PASS|
|phase57_state_safety|0.209 PASS|1.247 PASS|
|phase57_pcm_exact|4.011 PASS|12.269 PASS|
|phase59_certified_planning|0.159 PASS|1.456 PASS|
|phase59_dynamic_pcm|18.538 PASS|54.003 PASS|
|phase61_contract|0.340 PASS|0.413 PASS|
|phase61_fast_seek_state|17.538 PASS|59.171 PASS|
|phase61_checkpoint|9.858 PASS|26.779 PASS|
|phase61_safety|0.817 PASS|1.960 PASS|
|phase61_pcm_suffix|10.468 PASS|31.982 PASS|
|phase60_contract|0.419 PASS|0.437 PASS|
|phase59_request_control|4.682 PASS|12.013 PASS|
|phase59_fix_frozen_vocoder|0.927 PASS|2.754 PASS|
|phase59_fix_frozen_stereo|2.221 PASS|6.309 PASS|
|phase58_state_safety|0.888 PASS|2.058 PASS|
|phase58_fifo_pcm|4.085 PASS|11.650 PASS|
|phase58_fix_diagnostics|0.657 PASS|1.616 PASS|
|phase58_fix_trace_analysis|0.197 PASS|0.208 PASS|
|phase58_fix_mailbox|0.375 PASS|0.567 PASS|
|phase58_fix_worker_lifecycle|0.395 PASS|0.397 PASS|

Exact Seekの独立全suffix行列はRelease896/896、Debug896/896。PCM16/Float32 × mono/stereo ×44.1/48kHz、7代表速度（0.40/0.50/0.75/1.00/1.25/1.50/2.00）、両preset、先頭/中間+17/N−1/N、Standard/実参加Workgroupを維持した。各448ケースが保存点を使用し、各構成216回の実参加を記録した。

この行列のPASSは座標・RAW PCM全suffix・EOSの判定であり、実時間期限を含む総合承認ではない。ReleaseのDSP期限超過は0だったが、DebugのWorkgroup条件では67ケースに合計71回（各最大2回）を記録した。未最適化ビルドのこの結果も保持し、Debugの期限遵守を成功として扱わない。今回、この期限値について旧版との対照測定は行っていない。

Golden25/25は全WAV SHA・RAW PCM SHA・フレーム長・EOS・不足0を確認した。既存Goldenファイル/manifestを変更していない。

最終版の機能操作はReleaseの48kHzステレオ30/30・44.1kHzモノ30/30、Debugの48kHzステレオ30/30。DebugはBaselineのPlayingとシーク後0.40倍への変更でDSP作業スレッド期限超過を各1回検出し、実時間を含む総合成績は28/30だった。Sandbox Espritの機能操作・実時間診断は30/30、無音長検査を含む総合成績は20/30。個別結果を成功へ書き換えていない。

各セルはCandidate/Baselineの総合PASS件数。括弧は総合失敗でも機能操作が成立した件数：

|ケース|Release 48k stereo|Release 44.1k mono|Debug 48k stereo|Sandbox Esprit|
|---|---:|---:|---:|---:|
|研究フラグ既定falseの拒否|2/2|2/2|2/2|2/2|
|Readyからシーク|2/2|2/2|2/2|2/2|
|Playingからシーク|2/2|2/2|1/2（機能2/2）|0/2（機能2/2）|
|Paused・Resume|2/2|2/2|2/2|2/2|
|準備中Pause|2/2|2/2|2/2|2/2|
|64連続・Latest-Wins|2/2|2/2|2/2|0/2（機能2/2）|
|完了後の連続シーク|2/2|2/2|2/2|0/2（機能2/2）|
|準備中の速度変更・再計画|2/2|2/2|2/2|1/2（機能2/2）|
|完了後の密度変更速度0.40|2/2|2/2|1/2（機能2/2）|0/2（機能2/2）|
|Ready後の要求置換|2/2|2/2|2/2|1/2（機能2/2）|
|準備中Stop|2/2|2/2|2/2|2/2|
|Ready後Stop|2/2|2/2|2/2|2/2|
|装置変更の模擬通知・安全停止|2/2|2/2|2/2|2/2|
|入力コピー削除・失敗と安全停止|2/2|2/2|2/2|2/2|
|曲長ちょうど・EOS|2/2|2/2|2/2|2/2|

無効秒・範囲外・古い入力世代/epochの拒否、同IDの速度再計画、旧epochへの速度操作拒否、停止/削除/装置通知時の取り消し、Paused中に消費しないことを実機で検査した。装置通知は模擬であり、物理装置の差し替えは今回未実施。

通常の境界fixtureでは、最終Release/Debugとも境界サンプルの段差0、旧epoch末尾の無音は最大469フレームだった。入力/epoch/出力座標の混入や欠落は0。連続要求で置換された古いepochの取得PCMを、新epochの全suffixと混同していない。

Fastの実機PCM照合は各構成（Release2形式・Debug1形式・Sandbox）で先頭100msの20/20、固定速度の完全なsuffix16/16。比較先はオフラインの局所DSPに同じ5ms包絡を掛けたものであり、独立フルレンダーとの音質検査の代用ではない。途中で速度を変更したケースは先頭だけを比較し、その後の全suffix完全一致を主張しない。

既存Exactの最終実機試験は20/20。独立フル参照に対して全suffix12/12、途中退役epochのprefix14/14、空の終端suffix2/2。Phase60のadapter/lifecycleもRelease/Debugの4実行がすべて成功した。準備停止、161速度受付、速度要求のLatest-Wins、Pause/Resume、EOS再開、単一所有者と予算、入力切替・消失復旧を維持している。

### Sandboxと無音長検査の扱い

署名を検証した専用アプリ `org.timestretchlab.phase61-fast-sandbox` を実際に起動した。NSOpenPanelで指定済みの `08 Esprit.m4a` と専用出力先を選択し、PID 62856 のコンテナーで実行した。入力/出力のsecurity scope開始は両方true。許可範囲外の `SANDBOX_DENIED.txt` はopen=-1、errno=1でOSに拒否された。入力M4Aを最初に1回だけ4秒（44.1kHz stereo、176400フレーム）へデコードし、各シークではその入力leaseを共有した。

Esprit冒頭では、旧epochの16935〜21168フレームが1e-8未満で、絶対無音長30msの検査が10件失敗した。独立フル参照の同じ区間にも同じ長さの無音があり、この閾値での追加無音は0だった。双方の微小なPCM差は `SANDBOX_SILENCE_CONTEXT.json` に残し、ビット一致とは扱わない。後続の退役epochでは最大332フレーム（約7.53ms）。元の20/30と閾値は保持する。この絶対長指標を、元から無音の音源で「追加された無音」と同一視できないという測定上の制限を明記する。全境界の主観試聴は未実施。

TCC/security scopeの限定条件での読み取り・実再生・範囲外拒否を確認した。期限切れブックマーク、TCC失効、FileProvider、原M4Aの再保存検知などを網羅していない。通常WAVの変更・消失検知は既存安全試験と今回のコピー削除試験で確認した。

### メモリー・callback・Workgroup

検証環境はMacBookAir10,1、16GiB、macOS26.6.2（25G83）、arm64実行体。検証後の既定出力はMacBook Airのスピーカー。全実機行でdevice ID 72、48kHz、512フレームを記録し、原曲44.1/48kHz、mono/stereoを区別した。

- mono300秒の実機ピークRSS（プロセス常駐メモリー）：107,298,816 bytes（102.33MiB）。
- stereo音楽300秒の実機ピークRSS（プロセス常駐メモリー）：168,738,816 bytes（160.92MiB）。

入力サイズ+256MiB+解析長相当の既存受付予約を維持し、原曲lease・解析を共有する。Fastの包絡領域は構築時の固定配列で、全曲PCMのシークキャッシュは作らない。RSSは受付予約や確保総量とは別の指標であり、入力上限512MiB/600秒の全域を実測したとは扱わない。

音声callback本体はHEADとバイト同一。実機で測定したcallback/DSP作業スレッドのC++ newは0、Workgroupの参加/離脱/復元回数の不一致・policy/参加/復元エラーも0。期限超過の失敗は上記のまま保持した。malloc/Objective-C/VM確保、OSページフォルト、音響的提示時刻の完全な測定は未実施。

## 再現方法と保存

ビルド例：

```sh
cmake -S . -B build/phase61_fast_seek/release -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/phase61_fast_seek/release --target phase61_fast_seek_study phase61_fast_seek_tests phase61_fast_native_tests -j4
ctest --test-dir build/phase61_fast_seek/release -R '^(phase54_|phase56_|phase57_|phase58_|phase59_|phase60_|phase61_)' --output-on-failure -j1
```

CTestの全参照・回帰ターゲットを含む正確なビルドコマンドは `COMMANDS.json`。Debugは別フォルダーへ構成する。独立参照は `scripts/phase61_freeze_reference.py --build <build> --output <new-folder>` で復元できる。

```sh
<numpy-python> -B scripts/phase61_fast_seek_study.py \
  --binary build/phase61_fast_seek/release/phase61_fast_seek_study \
  --reference build/phase61/oracle_release_v1/phase61_frozen_reference \
  --suite quality --output <new-quality-folder>
```

性能は `--suite performance --source <300s.wav>`。既存の出力ディレクトリーを上書きしない。NumPyを使った解析用Pythonと、arm64のDSP実行体を区別する。機械/OS/コンパイラーは `ENVIRONMENT.json` へ記録した。

実機は別の音声ジョブと直列で実行する：

```sh
build/phase61_fast_seek/release/phase61_fast_native_tests <4s-fixture.wav> <new-native-folder>
build/phase61_fast_seek/release/phase61_fast_native_tests <300s.wav> <new-perf-folder> --performance
build/phase61_fast_seek/release/phase61_fast_native_tests <300s.wav> <new-early-folder> --early-performance
cmake --build build/phase61_fast_seek/release --target phase61_fast_sandbox_app -j4
codesign --force --sign - --entitlements tests/Phase61Sandbox.entitlements build/phase61_fast_seek/release/phase61_fast_sandbox_app.app
codesign --verify --deep --strict build/phase61_fast_seek/release/phase61_fast_sandbox_app.app
```

Sandboxアプリは起動後、NSOpenPanelで音源と新しい出力先を選ぶ。今回の選択と実行結果は `SANDBOX_UI.json` と `NATIVE_RESULTS.json`。比較用の許可範囲外ファイルは選択フォルダーの親に `SANDBOX_DENIED.txt` として事前に置く。現行検査は無音の長い原曲で総合失敗し得るため、元の成績と独立参照による追加解析の両方を保持する。

48kHzモノ300秒入力は既存のGit管理外 `results/phase56/long/chain_300s.wav`（57,600,044 bytes、SHA-256 `13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0`）。生成レシピは `phase56_study.pulse_payload(48000,1,3,300,True)` と `phase55_study.write_wav`。44.1kHzステレオ300秒入力は `results/phase31/input/mix.wav` のfmtチャンクをそのまま保存し、dataチャンクを30回反復してRIFF/data長を更新する。正規化・再サンプリング・非可逆圧縮は行わない。後者の原本/生成物SHA・サイズは `MUSIC_RECIPE.json` に記録する。

大容量WAV/RAW PCM/ビルド/トレースは `build/phase61_fast_seek/` に保存する。Gitに大容量実体を追加せず、SHA-256・manifest・生成レシピ・保存場所・復元方法を収録する。独立RAWは参照実行体に `input micros preset output.f32 inputFrame...` を渡して再生成し、フレーム数・SHAを照合する。全曲RAWは検証用の管理外データであり、エンジンのシーク用キャッシュではない。

## 失敗と修正の記録

1. 最初のビルド要求はCMake生成完了前に実行され、Makefile未生成で失敗した。`build.log` と `configure.log` を保持し、構成完了後に `build_v2.log` で再実行した。
2. 最初の局所試験は `FIR ring capacity exceeded` で失敗した（`quick.err`）。開始ブロックが準備区間より前へ出す成分を捨てる処理と、共通seedからOLAを順次消費する処理を修正した。`quick_v2.*` と以後の648比較を保持する。
3. 新しい終端状態試験は、N−1の期待出力を製品総出力長で上限処理しておらず、`Suffix/EOS count` で失敗した。先行Releaseは23/24。期待値を既存APIと同じ上限処理に修正し、再試験した。初回ログは `release_ctest.log`、修正確認は `state_fix_test.log`。
4. 新しい実機ターゲットをCMake再生成前にビルド要求して失敗した。`fast_native_build.log` を保持し、再構成後の `fast_native_build_v2.log` 以降で検証した。
5. 隔離した絶対座標位相補正の最初のコンパイルは `<numbers>` 不足で失敗した。元の失敗ログを `clock_variant/` に保持し、`clock_variant_v2/` で再ビルドした。コンパイルを修正しても品質は未達で、製品へ採用していない。
6. 短尺648件の成功後に長尺の78失敗とステレオ音楽の性能未達が判明した。研究用フラグを既定falseにし、品質閾値は維持した。初期の成功結果を長尺の承認へ流用していない。
7. レビューでFastのReady状態に出力開始フレームを公開していない点を発見し、Ready遷移前に公開するよう修正した。Ready中の座標を検査する実機試験を追加した。先行性能測定版のソース・実行体SHAは `PERFORMANCE_VERSION.json`、最終版のソースSHAは `SOURCE_MANIFEST.json` で区別する。DSPと性能測定時の局所合成方式は同じである。

失敗結果は削除・成功への置換をせず、最終結果と区別する。

## 制限とMerodoaへの引継ぎ

- 公開seekはfalse。Phase60/61の既存NO-GO承認記録を書き換えない。全曲・全速度・全装置・全TCC経路の承認を意味しない。
- Fastは先頭累積位相を復元しない。ExactとRAW完全一致したい用途は既存Exact APIを使う。
- 改善候補は、全帯域の位相リセットが成立したことを証明できる位置からの局所再開、または累積位相を保存する疎な索引である。前者には過渡音の長い結合イベントや持続音の扱い、後者には161速度・位相固定・左右履歴・動的速度変更とメモリー上限の両立が未解決として残る。今回、これらの方式を実装・承認したとは扱わない。
- Ready目標は入力lease・確定解析を再利用できる条件の測定。入力直後で解析が未完了の要求は解析完了を待つ。初回デコード/SHA/複製/mlockを除外した条件を明記する。
- Playingの実切替には旧FIFOのフェード待ちが加わる。取り消し時の既存FIFOに残る音量下降、旧区間EOS直前の短い下降、既に終わった旧DSPのEOS境界は追加の聴感評価対象である。今回の成功例だけで全境界の無クリックを断言しない。
- C++ newの計測をmalloc/Objective-C/VM確保やOSページフォルトの完全な計測と混同しない。HALの時刻は音響的な到達測定ではない。
- TCC失効、期限切れブックマーク、FileProvider、物理装置の差し替えを今回の限定試験で網羅したとは扱わない。
- Merodoaは変更していない。今回のFastを製品側で有効にしない。将来渡す場合は対応するヘッダー/ライブラリーを同時に再ビルドし、Fast/Exactを明示的に選択し、ID・入力世代・epoch・受付と実完了・Readyと提示を区別する。入力security scopeを全epochとFD leaseの終了まで保持する。研究フラグ・公開Capabilitiesの製品承認は別途必要である。

## 最終ゲート

|対象|判定|
|---|---|
|先頭から全PCMを合成しない局所シーク|研究用実装あり。確定解析・FD leaseを再利用|
|入力座標・出力連続性|オフライン2088件で誤差/欠落/重複0|
|新しい音質の数値検査|2010/2088。長尺mono78件未達。主観試聴は6クリップで「違和感なし」|
|ReleaseのReady p95 <=200ms|mono98.259msは通過、stereo249.641msは未達。解析待ちを含む条件は別表|
|実時間ゲート|長尺monoで時刻不連続、長尺stereoとDebug機能試験でDSP期限超過を検出。ExactのDebug比較にも71回。不合格|
|Sandbox|選択scope・実再生・範囲外拒否を確認。機能/実時間30/30、絶対無音長を含む総合20/30を保持|
|Exact・既存回帰・Golden|Release/Debug CTest各24/24、独立Exact suffix各896/896、Golden25/25、Exact実機20/20|
|保護・容量|既存Golden/Phase60/61承認/FD修正を保護。callback本体同一。全新規候補50,000,000 bytes未満|
|製品採用|**NO-GO**。`Capabilities.seek=false`、研究フラグ既定false|

主観試聴だけで数値未達を取り消さず、未測定の音響提示・VM/TCC経路なども承認しない。研究用の局所初期化・測定ホストと失敗例を残し、既存Exactを維持する。Merodoa・submodule・既存承認記録は未変更。Phase62には進んでいない。検証終了時点ではステージ・コミット・Pushは実施していない。
