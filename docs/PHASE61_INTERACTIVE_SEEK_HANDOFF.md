# Interactive Seek：開発版の接続と所有権

基準は `main@a9fe2224193dc2e3adae23d4c98fc96db387963f`。今回の変更は既存Fast Localの500ms局所初期化と確定Adaptive TimeMapを使い、旧アプリFIFOの排出待ちを出力段の短い切替へ置き換える。Exact、Golden、過去の承認結果は維持する。実測と制限は `results/phase61_interactive_seek/REPORT.md` を参照する。

## Release操作ホスト

```sh
cmake -S . -B build/phase61_interactive_seek/release -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/phase61_interactive_seek/release --target phase61_interactive_play -j 4
build/phase61_interactive_seek/release/phase61_interactive_play input.wav 1.0 candidate
```

実音声を出す。`seek 270.123`、`speed 0.40`、`pause`、`seek 30`、`status`、`resume`、`stop`、`play`、`exact 150`、`quit` を入力できる。presetは `candidate` / `baseline`。ファイルは対応PCM WAV（44.1/48kHz、mono/stereo）。圧縮音源はアプリの通常キューで一度だけデコードし、その保護済み入力をprepareする。シークごとの再デコードは行わない。出力段固定音量は既存と同じ50%。stdin待ちの間も内部workerと音声callbackは動く。

## Merodoa開発版での明示利用

Merodoa本体とsubmoduleは今回変更しない。接続する際はTimeStretchLabをこの変更から再ビルドする。C++の構造体へ末尾フィールドを追加したため、古いバイナリと新ヘッダーを混在させない。公開bool APIの意味は維持する。

1. 専用の非メイン直列キューでengineを作成し、prepare、play、全操作、照会、stop、破棄まで同じキューに載せる。UIは値のコピーを受け取る。callbackから制御APIを呼ばない。
2. 開発版の選択項目で `ProgressiveOptions::allowUnvalidatedFastLocalSeek=true` を明示する。既定はfalse。security-scoped bookmarkのスコープはprepareから全engine退役・破棄が終わるまでアプリ側で保持する。
3. `getStateSnapshot()` で入力世代・render epoch（出力区間の世代）・sessionを取得し、下記APIに渡す。UIに遅れて届いた旧世代の操作・結果は破棄する。
4. 要求の戻り値は受付。Ready、Completed、最初のPCMの時刻は別々に監視する。音響出力時刻とはみなさない。

UIは受付IDを保持して同IDの履歴を照合する。後から拒否要求が来ても先行する有効シークは取消されないため、`latest`だけで完了待ちを管理しない。`activeId/pendingId`も参照する。補助stageは最後に観測した段階で、Cancelled/Failed/Replaced等の終端stateを優先して表示する。

```cpp
ProgressiveOptions options;
options.allowUnvalidatedFastLocalSeek = true; // 明示した開発インスタンスだけ
engine.prepare(protectedWavPath, options);
// Readyを同じ直列キューで確認してplay。Playing/Ready/Pausedで受付可能。
auto context = engine.getStateSnapshot();
auto receipt = engine.requestInteractiveSeekToInputSeconds(
    seconds, context.inputGeneration, context.renderEpoch, context.session);
// receipt.accepted / receipt.id と後続の getSeekSnapshot()/seekHistory() を分離
```

フレーム版は `requestInteractiveSeekToInputFrame(frame, generation, epoch, session)`。原曲入力フレームが基準。秒は有限・非負を検査後sampleRateで丸め、曲長ちょうどを許す。これらの新APIは3種類の識別子を必須にし、0・古いsession/世代/epochを拒否する。既存 `requestFastLocalSeekToInputFrame/Seconds` とopt-inも引き続き接続可能。既存APIの0識別子は従来どおり照合省略なので、非同期UIには新APIを推奨する。従来のpreroll引数500/1000/2000msは保持するが、Interactive標準API・今回の比較は500ms固定。

`setSpeed(speed, session, generation, epoch)` にも最新の識別子を渡す。0.40〜2.00倍の1%刻み161段階。切替開始前の速度変更は切替要求を取り下げて同じシークIDを再準備し、開始後は新epochだけへ適用する。古い指定の速度要求では切替を取り消さない。

## 能力・許可・承認の区別

|照会|意味|
|---|---|
|`capabilities().seek`|過去からの一般公開承認ゲート。falseを維持|
|`capabilities().seekRequests`|既存の非同期Exact要求を実装済み|
|`seekAvailability().exactImplemented / interactiveImplemented`|実装の存在|
|`interactiveOptIn`|このインスタンスの明示設定|
|`interactiveAllowed`|opt-in済みかつReady/Playing/Pausedで入力を保持|
|`publicSeekApproved`|一般公開承認。falseを維持|

許可は一時点の照会なので実際の受付結果も必ず確認する。メモリ予算、上限4096要求、入力条件、世代照合、失敗理由による拒否は別途存在する。`seekToInputSeconds` のbool互換APIは公開ゲートが閉じている間false。

## 非同期状態と時間

既存 `SeekState` の8状態（Pending/Preparing/Ready/Completed/Replaced/Cancelled/Rejected/Failed）は維持する。補助 `SeekStage` に PreparingAnalysis、PreparingFifo、SwitchReady、Transitioning、Finished を追加する。

|時刻|記録点|
|---|---|
|acceptedNs|通常キューで受付|
|preparingNs|seek workerが要求を取り出した時刻|
|analysisReadyNs|確定解析の利用可能を通常workerが観測。解析済みなら準備開始時刻|
|readyNs|新FIFOのReadyを観測|
|switchReadyNs|形式・世代・Workgroup/policyを確認し切替可能になった時刻|
|transitionBeginNs / transitionEndNs|音声callbackが先頭/最後の混合フレームを処理した時刻|
|switchedNs|PlayingのInteractiveではtransitionBeginNs。Ready/Paused/Exactは通常所有者の参照交換時刻|
|firstCallbackNs|新epochの最初のRAW PCMを含むcallback処理開始時刻|
|estimatedPresentationNs|同callbackのHAL host-time推定。音響loopbackではない|

時間はMach単調ナノ秒。transitionEndNs−beginNsはCPU処理時刻差で、混合音の持続時間ではない。持続はtransitionFrames/sampleRate（240/48000、220/44100）。Startedは短いためpollで取りこぼしても最終時刻と混合フレーム数が残る。PreparingAnalysis中の取消・置換も可能。全曲解析待ちは今回解消していない。

## 切替と退役

通常workerが別DSP/FIFOを準備し、旧再生を保つ。FIFO容量16384、Candidate先行16384、Baseline12288は維持。新FIFOのPCMへフェードを焼き込まず、callback直前のRAWと出力混合後を分ける。解析・FD・保護済み入力は共有する。`/dev/fd`の再open、全曲PCMキャッシュ、シークごとのSHA/一時ファイル/mlockは追加しない。

切替スロットはRequested→Started→Done。通常側はRequestedだけをCancelledへ原子的に取り消せる。callbackがStartedを取得したら旧/新FIFOを最大約5msだけ混ぜ、残りは新FIFOから出す。係数は新側 `(i+1)/N`、旧側 `1−(i+1)/N`、和1。最初の新フレームを小さい非ゼロ係数で使い、飛ばさない。64フレームなど短いcallbackでも混合位置を次回へ持ち越す。旧EOSは残りの有効PCMを用い、不足部分を0として新側へフェードする。期待された旧EOFはunderrunに数えない。実供給不足は従来のカウンターへ残る。

Doneの取得とcallback参照の静止確認後、通常workerが旧pipelineを降格・停止・joinして破棄する。未提示旧FIFO残量は `discardedForSeekFrames`、開始時の残量は `oldFifoAtSwitchFrames`。生産者が切替後に少量補充し得るため、この2値の差は混合フレーム数と必ずしも一致しない。SPSCのカーソルをリセットしない。既にOS/装置へ渡したPCMは取り消せない。

Latest-WinsはStartedを原子的に取得するまで。開始後に来た要求は、現在の有界切替・旧退役後に準備する。第三のDSP所有者を積まない。Pauseは未開始切替を通常側へ戻し、開始済みなら短い混合の終了後に停止し、新FIFOを停止のまま保持する。Stopは未開始を取消し、開始済みの短い切替と退役を待って安全停止する。route/入力障害はcallbackを静止させてスロットを取消し、全所有者を通常側で停止する。破棄でも同じ所有権を守る。準備・昇格・公開前に失敗した場合、旧区間はフェードされず再生を継続する。開始後の例外はPCMを巻き戻さず安全停止する。

callbackで行う追加処理は、事前確保FIFO読取り、最大2入力のゲイン乗算/加算、原子通知だけ。FFT、解析、I/O、確保/解放、mutex、待機、ログ、Objective-C呼出しはない。係数・scratchは要求公開前に通常側で初期化する。検証observerにも同じ制約がかかる。

## 監査と利用上の制限

`observeEpochPcm` は混合前の各epochのRAW。`observeOutputPcm` は混合後と `ProgressiveOutputSpan`（新旧epoch、各入力座標/受信数、混合位置、callback連続座標）を受け取る。混合区間を単一epochのsuffixとしてハッシュしない。`callbackFrame` は有効な出力callbackの累積フレーム数で、Pause中の壁時計時間を含まない。実際の装置clockは既存のhost/sampleTime監視で別に検査する。入力/出力座標はシークで飛ぶ別軸。

入力寿命累積のFIFO/時刻/期限カウンターを保持する。`workerDeadlineMisses/workerNewCalls/workgroupErrors` は退役履歴の16件制限とは独立した累積値。切替中・退役中の旧所有者も計数する。操作前後差分を併記し、過去1回を後続の全操作で新発生と判定しない。

取消・失敗した準備workerもjoin後に監査へ残す。`closedEpochs().preparedOnly=true` は新PCMを提示していない準備区間で、epoch未割当なら0。routeで混合途中に停止した場合も、部分混合数・最後に処理した時刻・受信したPCMを記録する。途中取消のtransitionEndNsは最後の部分処理時刻であり、5msの正常完了を意味しない。

### 診断の最終公開と明示再始動（局所修正）

Phase58 pipelineの`start/stop/破棄`は、重複しない通常側の所有者が担当する。所有権を通常スレッド間で引き渡すことはできるが、同時にstart/stopを呼ばない。診断側は生存期間を保持したうえで並行取得でき、`std::thread`自体の状態を読まない。

`pipeline.lifecycle` はUnstarted/Starting/Running/Stopping/Finalized。`finalDataAvailable=true`は、sampler→analysis→DSPのjoin、`finalizeTransition()/cancelOperations()`、最後の書込みを終えた所有者のrelease公開を、診断側がacquireで観測した場合だけ。解析EOSや`dspDone`とは別である。実行中・退役中のカウンターは原子変数、不変な入力情報、既存のデータmutexを使う。mailbox所有者数、profile/detail/sampleのvector件数・欠落数は`finalDataAvailable=false`の間は**未取得**であり、既存数値フィールドの0を実測0と解釈しない。JSON等へ渡す場合はnullとして扱う。`workerRecords/detailEvents/threadSamples/dynamicTimeMap`のコピーはFinalized後に限り、早い呼出しは例外になる。

エンジンの`retiringPipeline`診断は、旧区間の所有者をjoin中も保持したスナップショットで、同じ最終公開規則に従う。`archivedEpochCount/archivedPreparedEpochCount`は入力寿命の退役数/未提示準備区間数で、`closedEpochs()`の16件上限と独立する。旧区間の生存中加算から退役後の累積加算へは、エンジンmutex内で一度だけ移す。

Stopped/Endedからの明示`play()`は、専用の非メイン直列キューで、エンジンmutexを持たずに`stopSeeks()`→`stopPreparation()`を待ち、その後mutex内で入力と状態を再確認し、retire→最新要求速度の引継ぎ→launch→autoPlayを設定する。route変更だけでは再開しない。新しい形式取得・入力検査・単一所有者の予算検査は維持する。

`pipelineLifecycleTestHooks/controlTestHooks`は期限付きの局所回帰用で、通常アプリでは空のままにする。音声callbackからは呼ばない。追加フィールドを含めヘッダーと実行体を一緒に再ビルドする。修正と今回の実行結果・未検証範囲は [局所修正REPORT](../results/phase61_sync_restart_fix/REPORT.md) を参照する。

旧長尺スペクトル検査78/1080件失敗、主観試聴6クリップで違和感なし、旧Sandbox総合20/30、旧Release時刻/期限エラーはそのまま残す。今回の開発利用は、これらを成功へ書き換えたものではない。新クロスフェードの主観試聴、全装置、全TCC経路、音響出力時刻、OS内部確保の網羅は別途必要。解析済みReady 200msは目標であり、未達値を達成と呼ばない。詳しい今回の測定範囲は新REPORTを参照する。
