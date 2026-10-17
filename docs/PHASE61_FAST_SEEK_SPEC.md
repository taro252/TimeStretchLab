# Phase 61 Fix: Fast Local Seek

本稿はPhase61のExact Seek仕様を置き換えない。公開 `Capabilities.seek` はfalseのまま。Fast Localは実験APIを明示的に選ぶ方式であり、原曲入力フレームの座標を維持する一方、先頭からの累積位相とRAW PCMの一致を保証しない。長尺インパルス列の品質検査に未達があるため、既定の `allowUnvalidatedFastLocalSeek=false` では新Fast要求をRejectedにする。検証ホストだけが明示的にtrueを指定する。製品採用はNO-GOであり、通常のExact動作を置き換えない。

## 状態の分類

|対象|先頭履歴との関係|今回の扱い|
|---|---|---|
|Phase35PhaseVocoder|各binの累積合成位相は過去の全ホップ・リセットに依存。事前合成を延ばすだけでは完全復元できない|3帯域共通の入力中心で分析位相から開始。その後の周波数推定、ピーク位相固定、過渡音リセットは既存処理を使う|
|直前の分析位相・振幅|次フレームの周波数推定・選択的リセットに必要|局所の最初のFFTで作成し、事前区間で更新|
|Phase35StereoPhaseCoherence|直前フレームの左右位相差・有効性。合成側の位相はvocoderへ反映される|左右を同時初期化。前フレーム安定度を局所区間で作る|
|FFT/STFT作業領域・ピーク所有者|現在フレームで上書きされる|既存の窓・FFT・ピーク探索を再利用|
|RingOverlapAdd|過去の有限長の窓の加算値と重み|絶対出力座標で空のリングを開始。窓長以上を捨てた後の領域を使用|
|LiveStreamingFIR|有限タップの末尾と、4096点FFTのブロック格子|2048/3584サンプルの両格子を保ち、共通周期14336で開始。開始点以前への成分だけを捨て、準備区間で末尾を満たす|
|密度制御・入力ホップ|固定速度では速度から決まる。変更後はPhase59の履歴に依存|初期固定速度の共通格子2048、0.40〜0.49倍は1024から開始。以後の変更は既存Phase59の計画と検証を使用|
|TimeMap・閉鎖済み過渡音・アンカー|原曲全体の不変解析|Phase56/58の確定解析を再利用。入力再デコード・全SHA・一時ファイル・mlockをシークごとに繰り返さない|
|Exactの保存点|正確な位相・OLA・FIR・計画履歴の複製|Fastの状態を保存・復元しない。FastからExactへの要求は明示的にExactへ戻す|

累積位相の差異は音質不良と同義ではない。持続音の絶対位相は変化し得るため、PCM差分を音量・スペクトル・低音の揺れ・ピッチ・左右関係とは別に記録する。過渡音の自然さ、音色、クリックの聴感は主観試聴が必要であり、数値通過だけで総合音質を承認しない。

## 局所初期化

1. 確定TimeMapから `round(map(inputFrame))` を求め、製品の固定総出力フレーム数で上限処理する。入力終端ちょうどは総出力フレームを使う。
2. 指定した0.5/1/2秒を入力座標から引き、対応する出力位置を14336単位で切り下げ、FIR開始位置Bとする。
3. `map(seedInput) <= B` を満たす最大の共通入力ホップ位置を二分探索する。3帯域は同じseedInputから開始する。帯域ごとに別の中心を選ばない。
4. 各OLAの絶対開始位置は `round(map(seedInput))`。FIRはBから開始する。必要な有限区間だけ合成して目的位置以前を捨てる。読み出し・公開の絶対座標は維持する。
5. ReadyのFIFO量は従来どおりCandidate16384/Baseline12288。全曲伸縮済みPCMキャッシュは作らない。

0.5秒は入力時間であり、出力側の準備長は速度とTimeMapに依存する。FIR格子への切り下げ分やFFT先読みもある。解析が未完了なら確定解析を待つため、入力準備・解析の待ちを含む場合のReady上限は保証しない。

## API

既存 `requestSeekToInputFrame/Seconds` は引き続きExact。次の新APIだけがFast Localを選ぶ。

```cpp
requestFastLocalSeekToInputFrame(frame, expectedInputGeneration = 0,
                                expectedRenderEpoch = 0, prerollMillis = 500);
requestFastLocalSeekToInputSeconds(seconds, expectedInputGeneration = 0,
                                  expectedRenderEpoch = 0, prerollMillis = 500);
```

`prerollMillis` は500/1000/2000だけを受け付ける。秒の有限性・範囲・原曲sampleRateでの丸め、曲長ちょうど、受付ID、8状態、入力世代、render epoch、Latest-Wins、速度変更による同ID再計画はExactと共通。`SeekOperation.mode` と `prerollMillis` で方式を識別する。旧bool APIは公開ゲートfalseの互換動作を保つ。利用側は新ヘッダーとライブラリーを一緒に再ビルドする必要がある。

検証ホストはprepare前に `ProgressiveOptions.allowUnvalidatedFastLocalSeek=true` を指定する。既定値falseでは、妥当な入力位置でもFast要求は理由付きでRejectedになる。Readyでは `outputStartFrame` を公開する。`renderEpoch` と `session` は実切替時に確定するので、Readyだけを新epochの再生完了と扱わない。

下位の `RealtimePipeline::createFastLocalSeek(frame, speedMicros, prerollInputFrames = 0)` は入力leaseを共有し、新しいDSP/FIFO/計画だけを作る。0はsampleRate/2を選ぶ。診断は `fastLocalSeek`, `localSeedInput`, `localBeginOutput`, `localPrerollInputFrames`, `localInitializeS` を追加する。

## 切替・音量包絡

Playingでは新FIFOのReadyを先に確定し、旧DSPへ5msの音量下降を要求する。旧FIFOの既存先行分と下降区間が消費された後、既存のepoch交換手順で切り替える。旧区間は下降後にゼロを供給し、制御スレッドの切替を待つ。新FIFOの先頭5msは上昇包絡を持つ。両方ともDSP作業スレッド上で事前計算済み曲線を掛ける。原曲入力・出力フレームを挿入・削除しない。

Ready時刻は旧FIFOの下降を待つ前の時刻。切替・最初のcallback・HAL提示推定時刻を分離して評価する。旧FIFOの先行分だけ切替はReadyより遅れる。取り消し時は旧DSPで5msの音量復帰を行うが、FIFOに既に入った下降/ゼロ区間は消せないため、復帰は遅れることがある。既にDSPがEOSで終了している旧区間は残りFIFOを消費してから切り替える。この場合は既存EOS境界の音形を変更しない。

Paused/Readyでは消費せず位置だけ移動する。Stop、入力変更、装置変更は既存の安全停止を使う。音声コールバックの本体は変更せず、DSP/I/O/確保/mutex/待機/ログを追加しない。旧epochの破棄、Workgroup参加・復元、実験エンジン単一所有者と予算上限も既存経路を使う。

## 判定

性能の暫定目標はReleaseで初回任意位置のReady p95 <=200ms。局所初期化、準備合成、FIFO充填、旧FIFOのフェード待ち、実提示を混同しない。検証条件・未達・主観試聴の未実施・公開ゲートの判定は `results/phase61_fast_seek/REPORT.md` に記録する。Phase62、Merodoa、submodule、既存Golden、Phase60/61承認記録は変更しない。
