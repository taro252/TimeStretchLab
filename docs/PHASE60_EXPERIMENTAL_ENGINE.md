# Phase 60 実験用増分再生エンジン

`macos_progressive_playback_engine` は明示的にリンクして生成するmacOS用接続層である。ヘッダーは `platform/macos/ProgressiveMacPlaybackEngine.h`。Phase54の `MacPlaybackEngine`、その既定動作・公開API・キャッシュ・シークを変更しない。Gate 2未合格、一般公開不可というPhase59 Fix 2の判定を引き継ぐ。

## 所有と処理の分離

`ProgressiveMacPlaybackEngine` が既存の `phase58::RealtimePipeline`、AVAudioEngine、SourceNode、制御監視、準備workerを所有する。DSP・TimeMap・Phase39/50/42の計画算術を作り直さない。既存Pipelineへの追加は通常解析workerが公開する読み取り専用の位置標本だけである。位置標本は出力/入力/Map版の組で、DSP計画や音声を変更しない。

制御・照会・破棄はアプリの同じ専用直列作業キューで行う。内部準備workerが入力検証、全SHA、非公開複製、mlock、増分解析、先行PCM生成を行う。SourceNodeはFIFO消費、任意の有界な生PCM観測、最小限の時刻記録だけを行う。解析・FFT・所有権変更・mutex待機・ファイルI/O・JSON・UI通知はcallbackへ移さない。

## APIと状態

|操作|契約|
|---|---|
|`prepare(path, ProgressiveOptions)`|trueはAccepted。完了ではない。Accepted→Preparing→Ready/Failedを照会する。|
|`play()`|Readyでは昇格確認後に音声開始。Accepted/PreparingではReady後の開始を予約する。Stopped/Endedでは新規の非同期prepareと開始を予約する。trueはこの受付である。|
|`pause()` / `resume()`|Playing→Paused / Paused→Playing。DSP/FIFOを維持し、出力静止後の降格・再開前の再昇格を行う。|
|`stop()`|準備の取消と終了待ち、callback静止、音声停止、worker join、Workgroup離脱/復元、借用終了、入力解放まで待つ。|
|`setSpeed(double, expectedSession, expectedInputGeneration)`|1%刻みの40〜200%。要求IDと低水準受付結果を返す。期待世代0は現在世代を使用。|
|`getPlaybackState()` / `getStateSnapshot()`|状態、停止理由、準備通番、session、入力世代、要求/適用目標、保留/実行中/直近終端。|
|`getCurrentPlaybackPosition()`|消費済みraw出力フレームと秒数、通常解析workerの対応する入力/出力位置標本。物理提示位置ではない。|
|`getPlaybackDiagnostics()`|生成/公開/消費/論理提示、不足、作業期限、起動段階、CPU、RSS、常駐量、エラー。|
|`getNativeDiagnostics()`|装置、callback、host/sample/HAL診断、無効sample/rateScalar flags、末尾目標と出力停止。|
|`capabilities()`|契約版、速度範囲、増分Ready、資源上限、シーク未対応。|
|`seekToInputSeconds()`|false。再生位置を書き換えない。|
|`callbackRecords()`|任意の記録を静止後だけコピー。再生/Draining中は拒否する。|
|`operationHistory()` / `finalTimeMap()`|通常側の要求監査と、静止した確定Map。検証ホスト向け。|

ReadyはPipelineの安全な先行PCM蓄積が成立し、出力グラフを準備した状態である。通常はCandidate 16384 / Baseline 12288フレーム、短いEOSでは確定した残り全PCMで成立する。全曲解析の完了は要求しない。内部workerの開始だけでReadyにしない。AcceptedとPreparingの間は短く、照会で必ず両方を観測できる保証はない。

準備取消は10ms単位のReady待機を中断する。コンストラクター内の全SHA・複製・mlockそのものには中断APIがないため、Stopはその完了まで待つことがある。UIキューでStopを呼ばない。取消後に古いReadyを新しい準備へ適用しない。次の準備は前準備threadのjoin後だけ開始する。

## 速度要求

小数6桁のPhase39識別を維持し、公開側は整数パーセント×10000に対応する161値に限定する。`.405`などは例外。Phase59のPending/Submitted/Applied/Completed、Duplicate/Rejected/Replaced/Cancelledをそのまま公開する。保留1件と実行中1件を分け、保留だけをLatest-Winsで置換する。

AppliedはDSPが計画を採用したこと、Completedは消費座標と密度処理の完了であり、耳に届いた時刻ではない。適用/完了出力位置は `SpeedOperation.change.plan` にある。Ready中の要求は保留でき、再生開始まで計画送信しない。準備中・停止後の要求はID0/Stopped。停止後の初期速度を変えたい場合は新しいoptionsでprepareする。再始動は最後に受け付けた要求速度から先頭を再準備する。

## 実時間出力と寿命

入力の44.1/48kHzで非インターリーブFloat32 SourceNodeを接続し、既存同様にmainMixer→outputの変換を使う。出力ゲインはmainMixerの0.5。入力フレーム数を装置48kHzフレームへ換算して計数しない。

Audio Workgroup、Mach実時間policy、resident input、dynamic transitions、解析/Map最大3スロットを必須選択する。Ready後、`setRealtimeRendering(true)` の成功と実測policyを確認して音声を開始する。短い曲でDSP全体が既に完了している場合は供給workerの再昇格を要求しない。通常threadへの黙った切替はない。常駐失敗、昇格/参加失敗はFailedとなる。

Pauseではcallback消費を止め、既に渡した末尾のソフトウェア提示目標を待ち、AVAudioEngineをpauseしてworkerを降格する。Resumeは新しい時刻epochで再昇格する。自然EOSではFIFO排出をDrainingとし、最後のPCM目標、報告された提示遅延の大きい方、5ms余裕を待って出力を止め、join後にEndedとする。物理的な出力連続性の証明ではない。

Stop/失敗/装置変更では、callback無効化→AVAudioEngine停止→実行中callback静止→worker停止/join→Workgroup離脱/復元→Snapshot/Map借用終了→DSP/入力解放の順。通知blockは当該セッションのRenderStateしか参照しない。装置ID・レート・チャンネル・バッファ変更はRouteChangedで安全停止し、自動再開しない。模擬route試験と実際の装置差替えは別である。

## 資源上限

|資源|実験上限/方針|
|---|---|
|入力WAV|512MiB以下、28,800,000入力フレーム以下、44.1/48kHz、PCM16/Float32、mono/stereo。|
|非公開複製/常駐|入力バイト数ずつ。準備前に一時領域の入力サイズ+256MiB以上の空きを確認。mlock失敗は拒否。|
|メモリ予約|入力bytes + 256MiB + ceil(inputFrames/1024)×4096。既定かつ上限1GiB。厳密なRSS/allocator上限ではなく保守的な入場予算。|
|同時所有|このプロセスで入力/DSPを所有する実験セッションは1つ。準備中・Pausedも含めて別インスタンスを拒否。自然EOS/Stopで入力と予約を解放。|
|DSP/解析/Map|既存の作業領域、解析Snapshot最大3、動的Map最大3、固定Map cache最大5、解析Snapshot容量64MiB。|
|FIFO|容量16384、生成2048、先行量Candidate16384/Baseline12288。|
|要求監査|適用計画512、操作4096。LimitReachedを返す。|
|callback記録|既定0、明示時最大262144。昇格前にページへアクセス。超過はdropとして保持。|

一時複製の除去やPhase54解析cache共用は行わない。Stop→Playも全SHA・複製・解析をやり直す。実験予算にアプリのデコード済みPCMキャッシュ、他のLegacyインスタンス、SwiftUI等のメモリは含めない。アプリ全体の合算予算はMerodoa側で別管理する。`pcmBudget`をDSP/FIFOエラーへ付け替えない。

EOS/Stop後も診断記録・操作履歴・確定Mapを当該インスタンスに保持する。保持量は1インスタンスごとに有界だが、破棄済みでない多数インスタンスの合算上限をライブラリだけで保証しない。アプリは旧エンジンを破棄してから次を生成する。診断のresidentInputBytes/temporarySourceBytesは当該セッションで所有した量で、終了後も保持する測定値である。終了後の現在の常駐量はRSSと区別する。

## 診断と品質

`presentedFrames` は有音/不足ゼロ埋めを含むraw要求時間軸、`consumedFrames` はFIFOから実際に得たPCM。EOS後の余剰無音は供給不足へ加算しない。missingFrames>0は必ず供給FAILとし、Endedと相殺しない。callback期限、worker期限、時計診断は別計数する。

API単体で独立PCM比較を実施しないため、`pcmCorrect` は未測定(null)。不足/期限/worker失敗の観測があればoverallAudioQuality=false、成功をまだ証明していない場合はnull。C++ new、OS faultも未測定をnullとして返す。RSSは現在値とプロセス生涯peak、CPUは要求受付後のプロセス値と終了後確定するDSP worker値であり、他thread負荷を含む範囲を区別する。

既知の初回時刻不連続、Client Overload、旧FIFO不足、OS欠測、独立loopback未実施は[Phase59 Fix 2](../results/phase59_fix2/REPORT.md)のまま。API追加を原因解決や一般公開保証へ読み替えない。
