# Phase62：Merodoa Step3へのAPI引継ぎ（公開NO-GO）

今回の変更はTimeStretchLabのみ。MerodoaのUI・保存・SwiftData・submodule参照は変更していない。Step3接続は別作業で、現行の200ms方式をこの変更だけで既定置換しない。

## Objective-C++ブリッジとSwiftの値モデル

専用の非メイン直列キュー（操作を順に一件ずつ実行する作業列）で作成、prepare、全操作・照会、stop、破棄を実行する。C++構造体が変わるため、全関連ライブラリとブリッジを同じソースで再ビルドする。旧ヘッダー／旧バイナリを混在させない。アプリが保護入力のsecurity scopeを、全所有者のjoinと入力lease解放まで維持する。

```cpp
ProgressiveOptions options;
options.allowExperimentalLoops = true; // 利用者が明示選択した研究版だけ
engine.prepare(protectedWavPath, options);
// Readyを確認。同じ直列キューで取得した文脈を使う。
auto s = engine.getStateSnapshot();
progressive::LoopContext context{s.inputGeneration, s.session, s.renderEpoch};
auto receipt = engine.requestLoopRange(A, B, context); // AB: 必ずAへ復帰
// receipt.accepted は受付。準備／実交換／音質合格は別。
auto loop = engine.getLoopSnapshot();
```

全曲は `requestLoopRange(0,inputFrames,context,{LoopStartPolicy::KeepPosition})`。原曲の入力フレームで指定し、秒や出力フレーム、速度から永続A/Bを作らない。PCM16/Float32、44.1/48kHz、mono/stereoの検査済みWAVを使う。圧縮音源はアプリ側で従来どおり初回だけデコードする。

Objective-C++側ではuint64_tを`NSNumber`／専用の不変DTOへコピーし、C++所有者やPCMポインタをSwiftへ渡さない。Swift `PlaybackLoopContext`、`PlaybackLoopReceipt`、`PlaybackLoopSnapshot`相当の値モデルを用意する。ブリッジの例外を、受付拒否と再生失敗を区別したエラーへ変換する。UIはMainActorへ値のコピーだけを送る。callbackからSwift/UI通知を呼ばない。

## 受付と状態

`loopAvailability()` の `implemented` は実装の存在、`optIn` はこのインスタンスの設定、`allowed` は一時点の受付可能状態、`publicLoopApproved` は一般公開承認。最後はfalse。`Capabilities.seek=false`も変更しない。

`requestLoopRange(A,B,context,options)` は非同期受付IDを返す。ID、入力世代、session、元epochを保存し、`getLoopSnapshot()` の同じIDを追跡する。`Pending / Preparing / Armed / Active / Cancelled / Rejected / Failed / Disabled`を区別する。`initialPositionComplete` が初回A復帰の完了、`enabled` が以後の自動実行の意思、`cycles` が実際に完了した周期境界数。A復帰・手動補正・Clearの通常継続は周回に含めない。Armedだけを音が出た証拠にしない。

拒否された新要求は既存の有効設定を取り消さず、receiptの理由を返す。有効設定がなければRejectedも照会に残る。最新の拒否IDだけを見て、先行する有効IDの追跡を失わない。

保存は1フレームから可能だが、実行受付は500ms以上。1フレーム／100msは理由付き拒否。500ms以上でも任意音源・任意A・全装置で期限を保証しない。準備失敗や期限違反はFailedと安全停止であり、自動再開しない。

## session・入力世代・epoch

inputGenerationは入力音源の世代、sessionはDSP再生単位の識別子、renderEpochは出力区間の世代番号である。

新設定は現在の非0のinputGeneration/session/renderEpochを必須にして古い操作を拒否する。自動周期は新DSPに伴い現在のnative sessionとrenderEpochが進む。**設定のsessionは受付時の結び付き**として保持し、自動周期だけで設定を解除しない。新入力や明示Stop／再prepareは設定を解除する。native session/epochは混合開始時に先に進み、cycles/lastBoundaryは混合完了（旧B）で確定する。snapshotのcyclesは設定IDごと、境界イベントのcycleは入力寿命内の累積番号である。

`requestClearLoop(loopID,context)` は対象IDと入力世代、受付sessionまたは現在sessionを照合し、epochの進行だけでは拒否しない。新しく作られた設定へ古いIDのClearは適用しない。Swift側では元prepare UUID／曲UUID／操作トークンも保持し、別曲・新prepareの遅い返信を捨てる。

## 操作の接続

- **AB ON**：別の通常seekを先に送らず、ReturnToAの設定を一件だけ送る。元のReady/Paused/Playingを維持する。A移動の希望表示と確定位置を分離する。
- **1曲**：KeepPositionを指定し、現在位置から曲末を経てA=0へ接続する。既存区間に動的速度要求がある場合は拒否するため、理由を表示して利用者がA復帰を選べるようにする。暗黙に先頭へ移動しない。有界ABから位置維持の1曲へ切り替える場合は、Clear完了を先に確認するか、明示してReturnToAを選ぶ。
- **速度**：`setSpeed(speed,currentSession,currentGeneration,currentEpoch)` はループ中、次の未予約周期への固定速度要求を受け付ける。準備中は同IDで最新値へ再計画するが、Armed周期は保持し、その次に適用する。最大で現在周期の残り＋予約済みの旧速度一周期を待つ。snapshotの`speedRequestID / requestedSpeed / appliedSpeed`で受付と適用を分ける。これは既存Phase59操作履歴の新しい周期内プランではない。長周期の途中へ即時適用するUI期待は満たさない。clearPending中は受付不能（Stopped）として拒否するため、Clear完了後に最新文脈で再送する。
- **手動seek**：既存の入力フレームAPIを使う。範囲内は維持、範囲外はネイティブでもA補正する。古い文脈なら理由付き拒否を処理する。自動準備より優先するが、B直前の厳しい期限ではFailedとなり得る。
- **Pause/Resume**：成功したPauseは設定と先読みを保持。Resumeまで周期を進めない。Pause拒否時はStep1同様、停止の意思を優先し、UIモードと未送信自動操作を解除する。
- **OFF/Clear**：receipt受理で`enabled=false`になる。`clearPending`中は現在周期Bから通常再生への接続待ち。既に開始した混合を取り消さない。Paused/ReadyならPlay/Resumeまで音声を再開しない。準備期限違反はFailedとして表示する。
- **Stop/曲変更/終了/装置変更**：モードと未送信操作を先に無効化し、stopする。明示Play後も保存範囲からONや自動再生を復元しない。

## 従来方式から切り替える条件

現時点の製品採用はNO-GO。Step3の開発版はユーザーの明示opt-inと限定試験だけにする。公開承認には、各音源のアタック・持続音・左右位相、長いAの期限、全速度、Sandbox/TCC/FD寿命、装置変更、実音響ループバック、反復負荷を別々に確認する必要がある。

Loop未対応／opt-inなし／受付拒否なら、理由を表示してStep1の既存実行へフォールバックできる。ただしネイティブLoopがすでにenabled/clearPendingなら、Clearまたは明示Stopの完了を確認するまで200msの自動seek監視を同時に動かさない。Failedは自動再開せず、利用者の明示操作を待つ。能力照会と受付結果の両方を照合する。

callback処理時刻とHAL host-time推定、物理的な音響提示は別。`LoopBoundaryEvent.callbackFrame` は混合末尾にある論理Bのエンジン出力座標で、`renderNs`は処理時計。`halBoundaryEstimateNs`は有効なcallback host-timeにcallback内の境界フレーム差を加えた推定で、0は未取得。音響提示時刻ではない。5ms重畳により周期の提示時間はRAW区間より短い。音響loopbackなしに「可聴ギャップ0」と表示しない。結果と未達は `results/phase62/REPORT.md` を参照する。
