# Phase62：Seamless Loop Engine 検証報告

**研究版を実装。一般公開・Merodoa既定採用はNO-GO。** 初期OFF、明示opt-in、`Capabilities.seek=false`を維持する。機能、PCM一致、実時間性能、Sandbox、主観音質、公開承認を別々に判定する。500ms以上の限定条件で成立し、100ms・任意の長いA・周期内の即時速度変更などは未達である。

## 基準・変更範囲・実行環境

開始／終了HEADは指定どおり `main@88d5247fd6b67996f4d315d5cb0fb23caf8a9f0c`。開始作業ツリーは空。Merodoaも `c52fde5c06a56fe7acf74617bb90583dfdb9dcf1` と一致し、開始／終了とも変更なし。指定のStep1文書と接続コードを読み取り参照した。Merodoa本体・submodule参照・SwiftUI・SwiftData・Legacyの既定経路・既存Golden・過去の検証履歴は変更していない。コミット、Push、履歴書換え、LFS移行は行っていない。

実行日2026-10-19、macOS 26.6.2（25G83）、arm64、Xcode 27.0（27A266a）。Release／Debugは別ビルド。音質指標はCodex同梱Python／NumPy 2.3.5を使用した。実音声ホストは音声装置へアクセスできる非App Sandboxプロセスで直列実行した。主行列は入力44.1／48kHz、実出力装置48kHz・512フレームであり、装置44.1kHzの全行列を意味しない。装置レート変更試験後は48kHzへ復元した。

[機械集計](SUMMARY.json)、[ソース対応表](SOURCE_MANIFEST.json)、[実測資料のSHA一覧](ARTIFACT_MANIFEST.json)、[出所と復元方法](PROVENANCE.json)を併記する。保存先はGit管理外の `build/phase62/run_01/`。資料ごとの絶対パス・バイト数・SHA-256はmanifestに記録した。

## 採用した設計

- 原曲の入力半開区間 `[A,B)` を唯一の範囲指定とする。各周期はExact方式の固定TimeMap（原曲位置と伸縮後位置の対応表）から出力A/Bを確定する。
- Phase57の増分DSP、Phase58の保護入力FD・不変解析・有限FIFO、Phase61の二所有者の切替と退役を再利用する。別DSP方式、全曲伸縮PCMキャッシュ、161速度PCMキャッシュは作らない。原曲SHA・コピー・mlockは入力寿命内で一回。
- `createLoopSeek(A,B,speed)` はA以前の必要なExact履歴を生成し、AからB直前だけをFIFOへ公開する。Ready量は既存先行量と区間出力長の小さい方。B以後は公開せず終了する。FIFO容量・最大二DSP・1GiB予約上限は拡大しない。
- 保存範囲の妥当性は1フレームから、実行受付は500ms以上。確定出力長にも最大callback4096＋混合長を収容する条件を課す。1フレーム／100msは理由付き拒否。500msは今回成立した下限で、任意音源・全装置の保証ではない。
- 旧B直前5msと新A先頭5msを相補線形で重ねる。新ゲイン `(i+1)/N`、旧ゲイン `1−(i+1)/N`。44.1kHzは220、48kHzは240フレーム。旧B以後を使わず、A先頭も一度だけ消費する。論理Bは混合末尾である。
- 各周期のRAW消費長はそのまま、提示時間は重畳分だけ短い。隣接周期の境界間隔は原則 `旧出力長−N`。これは5ms重畳方式の仕様で、厳密に同じ拍長を保つ方式は未実装。出力ゲイン0.5は既存AVAudioEngine設定を維持する。
- 音声callbackは旧単独・混合・新単独の最大三分割、最大一境界を扱う。タイマーや200ms照会でBを実行判定しない。事前確保済み領域と原子通知を使い、DSP生成・I/O・確保／解放・mutex・join・待機・ログ・Objective-C・UI通知は追加しない。
- 自動周回は4096件のユーザーSeek台帳へ登録しない。内部job一件、64ビット累積番号、設定ごとの周回数、詳細履歴64件、退役診断16件を分離する。
- 有界周期は既存チェックポイントを保存・復元しない。固定Exact状態と動的状態の混在を避けた一方、長いAへの再合成費用と周期ごとのスレッド生成費用が残る。永続DSPや有限区間PCM再利用は完成していない。

[設計文書](../../docs/PHASE62_SEAMLESS_LOOP_DESIGN.md)と[Merodoa Step3引継ぎ](../../docs/PHASE62_MERODOA_HANDOFF.md)に状態、所有権、ブリッジ、フォールバックを記載した。

## APIと操作の契約

`requestLoopRange`、`requestClearLoop`、`getLoopSnapshot`、`loopAvailability`、`loopHistory`を追加した。Disabled／Pending／Preparing／Armed／Active／Cancelled／Rejected／Failed、受付ID、入力世代、受付session、現epoch、範囲、周回数、準備時間、境界の処理時刻・HAL推定時刻、拒否／失敗理由を取得できる。受付成功はPCM準備・交換完了・音質合格を意味しない。

ABのReturnToAは範囲内からもAへ復帰し、初回復帰を周回へ加算しない。Ready／Pausedでは自動再生しない。全曲KeepPositionは `[0,inputFrames)` 専用で、現在位置を維持する。既存動的速度要求のある区間、解除前の有界ABからの位置維持変更は拒否する。初回公開には4096＋混合長より多い残量と正常なPCM供給を必要とする。曲末間際に設定して間に合わない場合はFailedと安全停止になる。

速度変更は周期境界で適用する。準備中は同じ要求IDで最新値へ再計画する。Armedになった自動周期は保持し、その次の未予約周期へ最新値を反映するため、現在周期の残り＋予約済み旧速度一周期を待つことがある。長い周期内へ即時に速度を適用する要求は満たさない。Clear反映待ちの速度要求は受付不能としてStoppedを返す。これは再生状態がStoppedになった意味ではなく、完了後の再送が必要である。

範囲内の手動seekは範囲維持、範囲外（Bを含む）はA補正する。手動操作を優先し、第三DSPは追加しない。Pauseで周回を止め、Resumeで必要なWorkgroup参加を確認する。解除はloop IDと入力／受付または現sessionを照合し、自動epoch進行だけでは失わない。新設定に古い解除を適用しない。開始済み混合は完了し、通常継続への接続は周回へ加算しない。

Stop、装置変更、入力喪失、失敗で自動周回を無効化する。再Playで古いループを復活させない。B−混合長までの準備不足、FIFO不足、callback上限違反はFailedと安全停止にする。残余callbackの安全用0は `safetyStopFrames` に記録し、成功周回や正常な無音へ計上しない。

## 変更ファイル

|ファイル|役割|
|---|---|
|`src/playback/ProgressiveLoopContract.h`|範囲、文脈、受付、状態、周回、境界、公開ゲート|
|`src/platform/macos/ProgressiveMacPlaybackEngine.{h,mm}`|API、先行準備、境界分割、操作競合、失敗、退役|
|`src/prototype/Phase58RealtimePipeline.{h,cpp}`|共有入力の有界Exact生成、短区間Ready、Bでの公開停止|
|`src/prototype/Phase62LoopBoundary.h`|境界分割と短区間制限|
|`src/playback/Phase62LoopPlay.cpp`|実音声の対話CLI|
|`tests/Phase62LoopTests.cpp`|入力範囲、確定座標、独立RAW一致|
|`tests/Phase62RenderTests.mm`、`Phase62OfflineCapture.h`|実callbackの分割・不足、4100周、RAW／混合保存|
|`tests/Phase62PcmAudit.h`、`Phase62NativeTests.cpp`|PCM順序・混合監査、実音声、操作／障害、装置変更|
|`tests/Phase62DeadlineNative.cpp`|実callback期限不足、手動seek中の速度再計画、曲末間際の明示失敗|
|`scripts/phase62_verify.py`、`phase62_quality.py`|直列再現、独立参照、波形指標|
|`scripts/phase62_cli_smoke.py`、`phase62_summarize.py`、`phase62_manifest.py`|CLI操作、集計、SHAと復元資料|
|`CMakeLists.txt`、設計／引継ぎ／結果文書|ビルドと研究成果|

## 決定論的試験と既存回帰

|検証|結果・条件|保存先（run_01以下）|
|---|---|---|
|関連CTest|Release 28/28、Debug 28/28。Phase54/56/57/58/59/60/61と新規2件|`ctest_release/`、`ctest_debug/`|
|最終ソースの新規CTest|Release 2/2、Debug 2/2|`final_ctest_release.log`、`final_ctest_debug.log`|
|既存Exact独立suffix全行列|896/896。8入力形式×7速度×2方式×4位置×通常／Workgroup。基準・反復・位置を変更していない|`exact_release/exact/`|
|既存Golden|25/25。WAV／RAW SHA、生成／消費数、EOS、不足を照合|`golden_release/golden/`|
|有界RAWと独立参照|96/96。8入力形式×6速度×2方式、A=1023、B=rate+1025|`pcm_release/`|
|全161速度の有界RAW|322/322。48kHz Stereo Float32×161速度×2方式。実機全形式行列ではない|`pcm161_release/`|
|実callback分割|64／128／512／4096×3速度×次PCM有／無の24ケース。旧B、新A、混合、供給不足を監査|`final_render_release.log`ほか|
|長時間の状態管理|実callback関数をオフライン高速駆動し4100境界。実時間期限の試験ではない|`long4100.log`|
|境界間隔の再監査|保存された連続epoch間682組、予定長−重畳長とcallback座標差が全件一致|`SUMMARY.json`|

CTestには既存Phase59の161速度・動的PCM、Phase60の契約／ライフサイクル、Phase61のシーク・クロスフェード・診断同期を含む。既存Exact／Goldenの判定値は変更していない。独立参照はPhase57以前の `ec087019626d9ff0d9f157245729b74ddb6847d7` のDSPオブジェクトを先にリンクした固定実行体で、SHA-256は `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。出所・コンパイル／リンク手順はPROVENANCEに収録した。

## 実機・操作・障害試験

Release主行列は **53条件・530周**。500msの48条件は入力44.1kHz Mono PCM16、44.1kHz Stereo Float32、48kHz Mono Float32、48kHz Stereo PCM16の4代表形式×Candidate／Baseline×0.40／0.50／0.75／1.00／1.50／2.00倍速、各10周。加えて自然音源の1秒・2秒・約10秒、3秒素材の全曲、曲末Bの1秒区間を各10周実行した。約10秒の実範囲は `[17,441000)` である。結果JSONの`range_seconds`は要求引数で、whole時の実際の全曲長は`last_boundary.json`のA/Bで確認する。

主行列のRAW／混合／順序誤り、非有限値、FIFO不足、underrun（音声供給不足）、安全停止フレーム、DSP期限超過、callback期限超過、Workgroupエラー、callback内C++ new／Cヒープ確保／解放はいずれも0。試験した出力で旧区間のB以後の再生は0フレームで、新Aの消費順序も一致した。

ただし `boundary_44100_1_1_candidate_0.4` で **host時刻診断1件・sample時刻診断1件** がある。同一条件の単独再試験10周では両方0だったが、初回の原因を確定していない。初回を消去・置換せず、実時間の全面合格にはしない。HAL提示窓逸脱とcallback実行時間超過は当該試験も0。再試験は `trace_repeat/` にcallback CSVと境界を保存した。

|追加試験|Release|Debug|資料|
|---|---|---|---|
|Pause／速度変更／Bへの手動seek→A補正、解除、Stop／再Play|4条件各10周|4条件各10周|`controls_release/`、`controls_debug/`|
|研究ゲート、ReadyでA復帰・範囲変更・拒否・旧解除、準備失敗、route停止、Paused入力パス喪失|11チェック|11チェック|`last_faults_release/`、`last_faults_debug/`、以前の両形式追加試験も保持|
|既存Interactive controls64／診断同期／Phase60 lifecycle|各終了0|各終了0|`controls_*/commands.json`|
|手動seek準備中の速度変更|同じseek ID=1で1回再計画、0.75倍、A=12000|同条件通過|`last_manual-speed_*/`|
|公開済みArmed周期中の速度変更、Paused範囲変更、解除、Stop／再Playの実CLI|通過|通過|`last_cli_*/`|
|B直前まで準備を保留する期限不足|期待どおりFailed、0周、安全用0は141フレーム|同じ|`last_deadline_*/`|
|曲末間際の全曲設定|期待どおりFailed、0周|同じ|`last_near-end_*/`|
|最終ソースの全曲10周|PCM不足0、時刻／callback／DSP期限超過0|PCM不足0、時刻／callback超過0、**DSP期限超過121件**|`final_supply_whole_*/`|

期限不足試験は準備側を止めて実callbackを境界へ到達させ、安全停止・準備所有者の退役・明示再Playでループが戻らないことを確認した。成功周回に加算していない。入力パス喪失は入力の監視機構であり、期限切れsecurity bookmark／強制FD closeの網羅試験ではない。Workgroup昇格前・公開前の失敗注入は、実装置でのすべてのWorkgroupエラーを再現したものではない。メモリ不足、TSan、VM faultの全面計測も未実施。

実装置のプロパティを48kHz→44.1kHzへ変え、RouteChangedで停止・ループ解除・元48kHzへの復元を確認した（`physical_loop/result.json`）。これは物理装置の設定変更で、ケーブル抜き差し・別装置への物理交換は未実施である。

## CPU・メモリ・遅延

|測定|実測値|解釈|
|---|---|---|
|主行列53条件の初回ループReady|中央値38.077ms、p95 115.799ms、最大302.809ms|入力prepare後のループ受付→初回Ready。短い素材・A≦2秒の限定値|
|同CPU|中央値17.91%、p95 37.44%、最大77.02%|プロセスCPU秒÷測定実時間、1コア=100%|
|同終了RSS／ピークRSS最大|50,659,328／50,839,552バイト|主行列の値。後続試験全体の最大値ではない|
|1000周：48kHz Stereo PCM16、Candidate、500ms、2倍|242.725秒、CPU79.3266秒＝32.68%|毎周期のDSP／スレッド作成費用を含む|
|1000周RSS|開始41,058,304→終了30,687,232、ピーク46,006,272バイト|単調な増加は観測せず。100周ごとの標本を保存|
|1000周退役・診断|詳細16件保持、最終退役1002件、供給／DSP／callback／Workgroup誤り0|詳細履歴と累積数を分離|
|最終全曲Release|ピーク71,430,144バイト、初回Ready145.271ms|追加試験。旧試行の74,125,312バイトも保存|
|最終全曲Debug|ピーク61,526,016バイト、初回Ready315.409ms、最終DSP期限超過121件|機能通過のみ。Debug実時間性能は不合格|

p95は53条件の値を昇順にした線形補間。独立した多数反復の応答分布や、無負荷のベンチマーク保証ではない。準備中の`lastReadyNs`が前回のままなら当該試行は未取得（null）であり、負数や0ms成功へ変換しない。既存Fast Seekの300秒素材／stereo準備p95 200msの問題と同じ条件ではないため、今回のReady値で改善済みとは扱わない。RSSは実際にメモリへ常駐した使用量で、1GiB予約量とは異なる。

## PCM・音質指標

独立RAWと同じ音声callbackの混合前／混合後キャプチャを **120/120完全一致** で確認した。既存Mix／Bass／Drums／Guitar／Vocal／Sineと、55Hz低音持続音・左右90度位相差音・インパルス列・倍音減衰の人工ピアノの10音源×6速度×2方式。自然音源は44.1kHz、人工音源は48kHz。非ゼロクロスを含む入力範囲 `[1023,2×rate+17)` を使った。人工ピアノは実録ピアノの代替合格ではない。

各フォルダーに `old_raw.f32`、`new_raw.f32`、`mixed.f32`、固定ゲイン0.5の試聴可能な `mixed_gain05.wav` を保存した（`quality_release_final/`）。RAWは凍結した独立DSP、混合は独立libmの `fmaf(old,1-w,float32(new*w))` とビット一致させた。許容誤差は緩和していない。

- 混合窓のRMS（実効音量）を対応する旧末尾／新先頭の平均実効値と比較すると **−5.548〜+1.084dB**。相補線形でも位相干渉による音量低下があり、無音量変化は未達。
- 最大出力ピークはゲイン0.5後で **0.706310以下**。これは保存した120条件の値で、任意素材のピーク保証ではない。
- 隣接フレーム差の最大はゲイン前1.089197。アタックや音源自身の変化も含み、クリックの合否閾値にはしていない。
- 参照にない数値0フレームは0。供給不足と区別した。自然EOSや原音由来の0は別に数える。最終全曲試験の`zero_source_or_output_frames=417`も供給不足0と区別し、可聴無音なしとは解釈しない。
- 左右実効値、主成分の左右位相差、周波数、ピーク、0連続長、入力／RAW／混合SHAを `rows.json` に保存した。5ms FFTの分解能は約200Hzで、55Hzの音程・位相品質の承認には使えない。全RAW一致と局所FFTの限界は別事項である。

主観試聴・音響ループバック・実録ピアノの全面評価は未実施。アタック、低音、定位、位相、周期短縮が練習用途に自然かは未承認である。数値一致から全音源のシームレス性を断定しない。

## Step1との比較

44.1kHz Stereo・36秒、A=0の対応条件のうち、(2秒,0.40／1.00／2.00倍)、(10秒,2.00倍)、(30秒,2.00倍)の **5条件・20周** をネイティブで実施した。素材は既存Mixを反復して作った36秒WAVで、Step1の元音源との同一性は未確認。全9速度範囲条件、Legacy／Progressive全18条件72周の再現ではない。

この20周では旧B以後のPCMは0フレーム、混合・供給・期限・時刻誤りは0だった（`step1_release/`）。Step1の最大約395msは200msポーリングで得た原曲位置標本、今回は音声callbackの確定出力境界で、測定軸が異なる。アプリ表示遅延の改善量や可聴ギャップ0を算出しない。`render_ns`は処理時計、`hal_boundary_estimate_ns`はcallback host-time＋内部フレーム差の推定で、物理的音響提示時刻ではない。

## 失敗した試行と修正履歴

途中資料は削除せず、主成績へ重複加算しない。

1. `pilot_release.log`：制限環境では出力装置を取得できず音声開始前に終了。音声装置へアクセスできるプロセスで再実行した。App Sandboxの合格証拠にはしない。
2. `build_tests_release.log`：新規render試験の名前空間不足でコンパイル失敗。修正・再ビルド後の試験を採用した。通常PythonのNumPy import失敗も保持し、同梱Pythonへ切り替えた。
3. `quality_release/`：108キャプチャ完了、自然音源1倍速の12条件が失敗。高速駆動ハーネスが部分混合の旧FIFO待機を省いていた。旧供給も待つよう修正した。混合参照の非融合演算は最大約5.96e−8の差があり、arm64コンパイラーの融合積和を独立libmで再現した。元の108資料の再照合も108/108一致（`quality_first_reference_recheck.json`）。修正後120件を新しい保存先へ全再実行した。
4. `build_capture_wait_fix.log`、`build_capture_diagnostic.log`：ハーネスの符号なし型不一致でビルド失敗し、後続シェルが旧実行体を動かした試行がある。`capture_1x_corrected`／`capture_1x_diagnostic`は採用しない。型修正と`set -e`、再ビルドを確認した `capture_1x_fixed_verified` と最終120件を採用した。旧ハーネスも `quality_first_sources/` に保持した。
5. `build_contracts_debug.log`：新規target追加後のDebug再configure不足でビルド不能。明示configureから修復し、`final_contract_repair_commands.json`以下を別記録した。
6. `cli_final/`：実装の旧速度方針ではArmed PCMを取り消し、実CLIの遅い速度要求で58フレームの安全停止を起こした。成功ではない。Armed自動周期を保持する方針へ修正し、Release／Debugの状態駆動CLIと手動seek再計画を再実行した。適用が一周期遅れる制約をAPIへ明記した。
7. `armed_policy_summary.json`のDebug CLI：固定待ち時間でPreparing中にLoopを送り、正しく受付拒否されたのにテストが受付成功を期待した。状態を確認して送るドライバーへ修正した。元ドライバーは `cli_fixed_delay_driver.py` に保存した。
8. 初回主行列の時刻逸脱とDebug全曲のDSP期限超過は、再試験成功や機能成功で解消済みにしていない。元データを残し未解決とする。

主行列・1000周・既存回帰のエンジンは `core_v2_sources/manifest.json` の保存済みSHAと6ファイル全件一致する。後続版では入力喪失のFailed分類、Armed速度予約、全曲初回の残量／供給検査、callback診断条件を補強した。DSPと混合の算術は維持し、最終版の再ビルド・新規CTest・操作／障害・全曲試験を別記録した。全成績を最終バイナリ一個で実行したとは扱わない。コミット準備時には試験コードの末尾空白1バイトのみ除去し、実測時の `final_sources.tar.gz` は保持した。コミット対象ソースは `commit_sources.tar.gz` とSOURCE_MANIFEST、実行時バイナリSHAは各suiteのprovenance等で追跡する。

## 再現手順・保存と復元

リポジトリルートから、新しい出力先で実行する。以下の`NEW`は未使用名に置き換える。既存資料を上書きしない。音声試験は通常の音声装置アクセスが必要で、重い試験を並行実行しない。

```sh
cmake -S . -B build/phase62/NEW/release -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/phase62/NEW/release --target $(python3 -B scripts/phase62_verify.py --suite targets) -j 3
cmake -S . -B build/phase62/NEW/debug -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON
cmake --build build/phase62/NEW/debug --target $(python3 -B scripts/phase62_verify.py --suite targets) -j 3
python3 -B scripts/phase62_verify.py --suite ctest --build build/phase62/NEW/release --output build/phase62/NEW/ctest_release
python3 -B scripts/phase62_verify.py --suite ctest --build build/phase62/NEW/debug --output build/phase62/NEW/ctest_debug
```

`--suite`を `exact`、`golden`、`pcm`、`pcm161`、`native`、`controls`、`long`、`step1` に替え、それぞれ別の`--output`へ実行する。controlsはDebugも別実行する。実際のコマンド、終了値、経過時間は各`commands.json`。入力生成は `phase57_study.fixture`、Step1は既存Mixの36秒反復、人工音源は `phase62_quality.py` の固定式である。

独立oracleは既存 `build/phase61/oracle_release_v1/` を読み取り使用する。無い場合は `python3 -B scripts/phase61_freeze_reference.py --build build/phase62/NEW/release --output build/phase62/NEW/oracle` で別の保存先へ作り、参照パスを新しい固定実行体へ合わせる。記録済みoracleを上書きしない。

```sh
/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -B scripts/phase62_quality.py --build build/phase62/NEW/release --output build/phase62/NEW/quality
build/phase62/NEW/release/phase62_render_tests results/phase31/input/mix.wav --long
build/phase62/NEW/release/phase62_deadline_native input.wav build/phase62/NEW/deadline
build/phase62/NEW/release/phase62_deadline_native input.wav build/phase62/NEW/manual_speed --manual-speed
build/phase62/NEW/release/phase62_deadline_native input.wav build/phase62/NEW/near_end --near-end
python3 -B scripts/phase62_cli_smoke.py --host build/phase62/NEW/release/phase62_loop_play --input input.wav --output build/phase62/NEW/cli
```

deadline系の`input.wav`は主行列生成の3秒48kHz Stereo PCM16を使用する。Debugも同じ条件で別出力へ実行する。装置設定変更は `phase62_native_tests input.wav 新規出力先 --physical-loop`。固定oracleの再ビルドは環境差でバイナリSHAが変わり得るため、ソースSHA・コンパイル条件・PCM一致を併せて確認する。

実音声CLIは `phase62_loop_play input.wav 1.0 candidate` で起動する。`loop A B`、`whole`、`speed 0.75`、`pause`、`resume`、`clear`、`stop`、`play`、`status`、`quit`。A/Bは入力フレームで、初期Playing／Readyを確認して操作する。ホストを明示起動した場合だけ実験機能を有効にする。

基準SHAの新しい作業コピーへソースアーカイブを展開しSOURCE_MANIFESTで確認することで、未コミット実装を復元できる。元の実測資料は `build/phase62/run_01` 全体を保存し、ARTIFACT_MANIFESTで照合する。レシピでPCMを再生成できても、実測時刻・CPU・RSSは同値にならない。`phase62_manifest.py` がソース・資料のSHA、バイト数、生成元を記録する。ログやバイナリを含む容量の大きな証拠はGitへ追加しない。

最終確認で `git diff --check` と `python3 scripts/check_git_blob_sizes.py staged` は合格。Git候補の各ファイルが50,000,000バイト未満であることも確認する。ステージング／コミット／Pushは実施していない。フック設定は既存 `.githooks` を維持した。

## 未達条件と公開判定

|ゲート|判定|
|---|---|
|API・境界・安全退役の研究実装|限定条件で成立|
|旧B超過0／RAW・混合完全一致|上記試験範囲で成立|
|500ms未満|未対応。100ms／1フレームは実行拒否|
|速度変更|周期境界方式。周期内即時適用は未対応|
|実時間性能|全面合格せず。Releaseの時刻逸脱、DebugのDSP期限超過が未解決|
|音質・音量・拍長|全音源の承認なし。約5ms周期短縮、音量低下を観測|
|網羅性|全161速度の実機全形式・全区間、長いA、実録ピアノ、全Step1条件は未実施|
|実音響・装置|音響ループバック、主観試聴、物理的ケーブル交換は未実施|
|Sandbox／TCC／FD／メモリ|今回のアプリ権限・期限切れbookmark・FD強制失効・不足の網羅は未実施|
|公開／Merodoa既定採用|**NO-GO**|

既存Fast Localの長尺音質 **78/1080件失敗**、既存DSP期限問題、stereo Ready p95 200ms未達は未解決として保持する。Step3では直列Objective-C++ブリッジとSwift値モデル、受付／適用／失敗の表示、モードOFF／Stop後の自動再開禁止、ネイティブ解除完了まで従来ポーリングを併走させない契約を守る。公開前に、長いAと短周期の再利用設計、速度応答、音量・拍長、実時間と実音響、Sandboxを個別に解決・再検証する。
