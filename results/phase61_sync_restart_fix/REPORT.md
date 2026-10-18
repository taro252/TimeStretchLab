# Phase 61 Fix：診断同期と再始動順序の局所修正

開始HEAD：`main@9f1f45efc54badec950bdc95e9490b3d7dc5eae3`。開始時の未コミット差分は空。レビュー対象と同じHEADで2経路が残っていることを確認した。本書のHEAD・作業ツリー状態は検証終了時点（今回のコミット依頼前）の記録であり、その時点ではコミット、Push、履歴変更を行っていない。

## 修正と判定

**A：修正済み。B：修正済み。今回の局所修正は完了。** 明示opt-inのMerodoa開発版へ、同じ直列キュー規約と全体再ビルドを前提に引き継ぎ可能。一般公開ゲートは閉じたまま。以下は今回実行した結果であり、旧成績の流用ではない。

### A：旧pipeline退役中の診断

旧実装はstop所有者がデータmutex外で`join()`する一方、診断側が同じthreadオブジェクトの`joinable()`を呼んでいた。診断側のmutexだけでは、所有者によるthreadの変更を同期しない。この2アクセスのコード上の競合を確認した。過去のクラッシュ・DSP期限超過の実原因と同定したものではない。

start/stop/破棄を重複しない通常側所有者へ限定した。診断・最終データのエクスポートはthreadオブジェクトに触れず、原子的な`LifecycleState`をacquireで取得する。releaseはそれまでの書込みを公開し、acquireはその公開を観測した側から書込みを読めるようにする同期である。Finalizedのrelease公開は、sampler→analysis→DSPの全joinと`finalizeTransition()/cancelOperations()`の後。ここでthreadのjoinは終了待ちと資源回収を指し、Audio Workgroupへの参加とは別。未開始stop、worker生成途中の例外、正常EOS、取消、入力失敗、繰り返しstop/デストラクターでも同じ完了規則を使う。

samplerによるDSPの`native_handle()`取得は、DSP生成後からsamplerのjoin完了までの限定した借用として残す。所有者はsamplerを先にjoinし、その後にDSP threadを変更/joinする。診断からのthread状態照会は全て除去した。待機相手が必要とするデータ/操作mutexを保持してjoinしない。

実行中/退役中は原子カウンター、不変入力情報、既存のデータmutex/操作mutexで保護した値だけを読む。mailbox所有者数、profile/detail/sample vectorと欠落数は`finalDataAvailable=true`後だけ参照する。false時の従来数値欄は未取得であり、0成功として扱わない。join後専用コピーAPIはFinalized前に例外を返す。全worker終了を待って診断を返す方式にはしていない。

旧pipelineは通常所有者が生存させたまま退役診断として保持し、join/最終公開後にエンジンmutex内で累積値へ一度だけ移す。履歴16件と入力寿命累積は別。監査件数も`archivedEpochCount/archivedPreparedEpochCount`で履歴上限と独立して確認する。

### B：Stopped/Endedからの明示play

旧play分岐は、prepareと異なり`stopSeeks()`を先に待っていなかった。route監視がStoppedを公開しても、seek workerが保持する準備中/退役中の所有者が残り、予約資源の取得と衝突できるコード経路だった。これも過去の実測失敗との因果関係は確定していない。

同じ非メイン直列アプリキューから、mutexを持たずに`stopSeeks()`→`stopPreparation()`、その後mutex内で入力/状態再確認→retire→最新要求速度を初期速度へ設定→launch→明示要求のautoPlayとした。停止で旧seekの後処理と資源返却を完了してから新準備へ進む。単一所有者チェックと予約上限は維持し、resourceOwnerの強制解除、固定sleepによる猶予追加、例外の握り潰しは行っていない。装置変更だけでは再開しない。

## 変更ファイル

- `src/prototype/Phase58RealtimePipeline.{h,cpp}`：所有者の完了公開、診断/コピーの安全な参照条件、通常側の明示テストhook。
- `src/prototype/Phase58Diagnostics.h`：最終値の未取得をJSONの0で隠さないための直接関連変更。最終公開フラグとnullを出力する。
- `src/platform/macos/ProgressiveMacPlaybackEngine.{h,mm}`：再始動順序、旧退役診断/累積監査件数、通常側テストhook。
- `tests/Phase61PipelineSyncTests.cpp`：join前/中/全join後・後処理前/最終公開前の4バリア、生成途中例外等。
- `tests/Phase61SyncRestartNativeTests.cpp`：同一制御キューの実音声診断、即時route再始動、22退役/16履歴、取消準備監査、Stop/EOS再始動。
- `tests/Phase61SyncRestartVerify.py`、`CMakeLists.txt`：新テスト登録と再実行手順。実音声試験は明示実行ターゲット。
- `docs/PHASE61_INTERACTIVE_SEEK_HANDOFF.md`：最終データの有効性、所有権、再始動、再ビルド要件。

## 今回の実行結果

機械集計は [SUMMARY.json](SUMMARY.json)、個々のコマンドと資料のSHAは [PROVENANCE.json](PROVENANCE.json) / [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json)。

|試験|構成・実行結果|
|---|---|
|新しい局所実機回帰|Release/Debug × 48kHz stereo/44.1kHz mono × Candidate/Baseline、48群通過|
|物理route後の即時play|内蔵出力48→44.1kHz、Release、準備中/切替開始後 × Candidate/Baseline、4群通過。元レート/バッファへ復元|
|Aの非停止診断|8群で512回ずつ、計4,096回。最長0.043083ms。4バリアで最終未公開、join後の監査取得を確認|
|履歴上限と監査|8群それぞれ22区間退役、保持16、取消した未提示準備1。入力世代不変、hash/snapshot/mlock各1|
|関連CTest|Release 26/26、Debug 26/26（Phase54/56/57/58/59/60/61、新規pipeline同期含む）|
|Exact独立全suffix|Release、8 WAV形式 × 7速度 × 2preset × 4位置 × Standard/Workgroup = 896/896 PCM一致。checkpoint利用448、常駐最大1（上限2）、Workgroup参加/離脱/復元各216、今回の期限カウンター0|
|Golden|既存25/25、WAV SHAとRAW PCM SHA、生成/消費数、EOS、FIFO不足を照合|
|JSON追加後の確認|Release/Debugの新規同期各512回とFIFO全PCM比較各12条件、全通過|
|ThreadSanitizer|Standardのみ、512回の診断と生成例外/EOS/取消/失敗/二重stop、競合報告0。JSON追加後も再実行して通過|
|既存Interactive制御|Release/Debug × 2形式、各54、計216/216機能通過。最終診断を取れた200件でFIFO/期限/時計/確保/退役エラー0。破棄16件の取得不能値はnull|
|実際の旧EOF不足補完|Release/Debug × 2形式、4/4。旧FIFO/旧受信とも0、混合240/220フレーム、PCM順序/混合/確保/期限/FIFO不足エラー0|
|Phase60 lifecycle|Release/Debug両方通過。準備取消、速度要求後の停止、入力変更、元入力の消失・復帰等|
|出力混合単体|Release/DebugのCTestで各72条件。44.1/48kHz、mono/stereo、6 chunk、3旧有効長|

局所52群の主資料はRelease 24群＋JSON変更後のDebug再確認24群＋物理route 4群。先行Debug 24群と先行Release pilot 12群は別保存し、主成績へ重複加算していない。JSON変更後のRelease native実行体は変更前とバイト一致。Debugは再ビルドした実行体で再確認した。関連CTestのRelease全26件の後に変更したJSON出力/新規同期試験は、対象のRelease/Debug同期およびFIFO比較を追加で再実行した。Debug全CTestは変更後の実行体を使用した。

最初の制限環境の実音声試行は装置バッファ取得で停止した。通常権限で再実行した先行Release局所12群も通過。先行と最終を重ねて主成績に加算せず、それぞれ保管する。

局所のA/Bは、通常workerのバリアで旧退役を残す。Stopped観測後にstopを呼ばず明示playを呼び、helperはplayがseekの整理待ちへ到達した通知を観測してからバリアを解放する。新しい資源取得がその前に始まっていないこと、整理完了→新launchの順序、別入力世代/session/epoch、最新速度0.75、旧要求が復活しないことを検査した。物理routeでは新deviceRate=44.1kHzを再取得したことも検査した。開始済切替のバリアは通常workerがStartedまたはDoneを観測した時点で、callbackを止めて作ったタイミングではない。

TSan実行は純粋な通常側pipeline処理へ分離し、実音声/Workgroup併用の証明とはしない。`-fsanitize=thread`がphase58ライブラリ全体へ適用され、実行体のTSan runtimeリンクも確認した。ASan/UBSanの成功を競合不存在の根拠には使っていない。sanitizer/バリア付き試験の時間をReleaseシーク性能へ混ぜない。

### 切替待ち時間の今回の再測定

Release、各300秒、mono=48kHz/1ch、stereo=44.1kHz/2ch。0.40/0.50/1.00/2.00倍 × Candidate/Baseline × 30/150/270/285秒と未訪問`83*rate+12345`フレーム × 3反復、各120操作。全て初回訪問、確定解析後、装置48kHz/512フレーム、FIFO/先行量/500msは従来どおり。ホストを同時起動せず順次測定した。各操作の時刻差を先に求め、ソートした分布の線形補間でp95を計算した。別々のp95同士を引き算していない。

|入力|受付→Ready p95|受付→新PCM p95|Ready→新PCM p95 / 最大|SwitchReady→混合開始 p95|
|---|---:|---:|---:|---:|
|mono|78.689ms|84.962ms|9.842ms / 10.807ms|9.707ms|
|stereo|220.311ms|224.454ms|10.115ms / 10.661ms|9.965ms|

約0.4秒の旧FIFO排出待ちへの後退は観測しなかった。240操作すべてでFIFO/callback・DSP期限/host・sample・HAL時計/コールバックC++ new・Cヒープ呼出し/解放の操作差分0、入力寿命の最大値も0。混合は240/220フレーム、旧FIFOは残したまま有界切替している。音響提示時刻は測っていない。

**stereo Ready p95は今回も200ms未達**（22/120が200ms超過）。monoにも最大203.486msの外れ値1件がある。この局所修正がDSP準備を高速化したとの因果関係は主張しない。初回解析待ちは今回この比較で測り直しておらず、解消していない。

## 再現・保存

今回のビルド・全ログはGit管理外の`build/phase61_sync_restart_fix/run_01/`へ保存する。再実行時は新しいrun番号/出力名を使い、既存結果を上書きしない。

```sh
python3 -B tests/Phase61SyncRestartVerify.py --suite targets
cmake -S . -B build/phase61_sync_restart_fix/NEW_RUN/release -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
# 上で表示された全targetをRelease/Debugそれぞれビルドする。
# native実行は実出力装置へアクセス可能な通常の非Sandboxプロセスで順次行う。
python3 -B tests/Phase61SyncRestartVerify.py --suite local --release BUILD_RELEASE --debug BUILD_DEBUG --output NEW_LOCAL_RESULTS
python3 -B tests/Phase61SyncRestartVerify.py --suite native --release BUILD_RELEASE --debug BUILD_DEBUG --output NEW_NATIVE_RESULTS
python3 -B tests/Phase61SyncRestartVerify.py --suite regression --release BUILD_RELEASE --debug BUILD_DEBUG --output NEW_REGRESSION_RESULTS
python3 -B tests/Phase61SyncRestartVerify.py --suite performance --release BUILD_RELEASE --debug BUILD_DEBUG --output NEW_PERFORMANCE_RESULTS
# ThreadSanitizerは別ビルド（通常経路のみ）。
cmake -S . -B NEW_TSAN_BUILD -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=ON -DCMAKE_CXX_FLAGS='-fsanitize=thread -fno-omit-frame-pointer' -DCMAKE_EXE_LINKER_FLAGS=-fsanitize=thread
cmake --build NEW_TSAN_BUILD --target phase61_pipeline_sync_tests -j 4
TSAN_OPTIONS=halt_on_error=1 NEW_TSAN_BUILD/phase61_pipeline_sync_tests results/phase31/input/mix.wav --standard-only
```

テストhookは通常アプリでは空である。callbackにhook/待機は追加していない。helperスレッドはバリアの解放/テスト情報の確認だけを行い、公開APIは全て同じ非メイン直列キューから呼ぶ。各バリアに10〜15秒、各試験に外部終了期限を設ける。

今回の実行コマンドは`run_01/{build_commands,build_native_final,build_json_final,verification_commands}.json`と各suiteの`commands.json`、追加JSON確認は`json_final_checks/commands.json`、最終Debug確認は`local_debug_after_json/commands.json`。すべて保存資料のmanifestに含めた。Golden/Exactの全行・各ログ・入力recipeもGit管理外へ保持する。

保存資料は**8,249ファイル、437,719,913バイト**。WAV/PCM/実行体/ビルド/圧縮ソースはGit管理外。ソースと結果再集計レシピは`source_snapshot_with_recipe.tar.gz`（63,750バイト、SHA-256 `22b2e3c0d4aa918438f071e5e2a67bdea201d3e928562aef8afa9a8623d6e101`）にも保存した。基準HEADの**別の新しいチェックアウト**へ復元して再ビルドする。現在の利用者の作業へ強制展開しない。入力のSHA/生成レシピ、独立凍結参照の保存場所/実行体SHAはPROVENANCEを参照する。既存の検証証拠は削除していない。

## 保護する既存動作と未実施項目

Fast Localの500ms、DSP算術、確定TimeMap、Exact条件、相補混合約5ms、FIFO 16384、先行16384/12288、最大2 DSP所有者、FD/保護入力/解析lease、Workgroup、Latest-Wins、識別子検査、明示opt-inは変更しない。`Capabilities.seek=false`を維持する。

既知のstereo Ready 200ms未達、初回全曲解析待ち、旧音質スクリーニング78/1080件失敗、過去のExact DSP期限超過はこの2件の修正と別。過去の結果/承認を改変せず、今回で解消したと主張しない。全装置/TCC/App Sandboxの再認証、新しい主観音質評価・位相研究・音響loopbackは対象外。Merodoa本体、submodule、既存Golden、Phase62は変更しない。

検証装置はMacBook Airのスピーカー、macOS 26.6.2/arm64。物理route試験後の出力48kHzと、各試験後の512フレーム復元を照会で確認した。今回の性能ホストのプロセスRSS高水位はmono 99,352,576 / stereo 161,841,152バイト。単一実験所有者、1GiB予約上限、最大2 DSPを変更していない。物理RAM/modelのsysctl取得は制限環境で失敗しており、今回の測定値として補完しない。

装置利用不能そのものの故障注入、全競合の形式的証明、長時間運転、実音響提示時刻、Merodoaプロセス内での統合は未実施。元入力失効による理由付き失敗は局所試験と既存lifecycleで確認した。通常側TSanの成功を、AVAudioEngine/HAL内部を含む全系の競合不存在や一般公開承認へ読み替えない。

## 引き継ぎと最終差分

今回の2点は修正・局所ゲート通過としてMerodoa開発版へ引き継げる。TimeStretchLabのソース/ヘッダー/ライブラリを一緒に再ビルドし、専用の非メイン直列キュー、明示opt-inを維持する。停止後に同じengineでplayする際も保護WAVと必要なsecurity scopeを保持または再取得し、受付と非同期Ready/Playing/Failedを分けて扱う。`finalDataAvailable=false`の最終値をUI/JSONで実測0にしない。Merodoa側のSandbox/TCC・実装接続確認は別途必要。

検証終了時点のHEADは開始時と同じ`9f1f45efc54badec950bdc95e9490b3d7dc5eae3`、ブランチmain。ソース/試験/手順10ファイルのSHA集合の識別値は`c6650e40998e638197e258e11531339d151137662c412cae4f77eb254d85818b`。その時点の未コミット差分は上記10ファイルと新規`results/phase61_sync_restart_fix/`。各ファイルのサイズ/SHA、基準HEAD、作業ツリー状態をPROVENANCEへ記録した。旧Phase60/61/Interactiveの結果・承認・Goldenに差分はない。検証終了時点ではコミット、ステージ、Push、履歴書換えを行っていない。
