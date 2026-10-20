# Phase62 Fix：Merodoa Step3への引継ぎ（一般公開NO-GO）

変更対象はTimeStretchLabだけ。Merodoa本体、submodule参照、SwiftUI、SwiftData、既定経路は変更しない。Step3で進められるのは、明示opt-inの研究用ブリッジと限定検証まで。長周期の途中速度応答が未達であり、現行の200ms方式を既定で置き換えない。

## キュー、値モデル、入力寿命

専用の非メイン直列キューで作成、prepare、操作・照会、stop、破棄を実行する。構造体が追加されたため、ブリッジと全ライブラリを同じソースで再ビルドする。C++所有者やPCMポインタをSwiftへ渡さず、入力世代、session、renderEpoch、loopID、要求IDをuint64_tの値としてコピーする。MainActorへは値のコピーだけを送る。

アプリは保護入力のsecurity scopeを全DSPの停止、join、入力lease解放まで維持する。圧縮音源のデコードは初回だけ。入力と解析は不変参照で共有する。単なるファイルパスの保存をsecurity scopeやbookmarkの代わりにしない。

```cpp
ProgressiveOptions options;
options.allowExperimentalLoops = true; // 明示的な研究モードだけ
engine.prepare(protectedWavPath, options);
// Readyを確認し、同じ直列キューで取得した文脈を使う。
auto s = engine.getStateSnapshot();
progressive::LoopContext c{s.inputGeneration, s.session, s.renderEpoch};
auto receipt = engine.requestLoopRange(A, B, c);
auto loop = engine.getLoopSnapshot();
auto speedState = engine.getStateSnapshot();
progressive::LoopContext speedContext{speedState.inputGeneration, speedState.session, speedState.renderEpoch};
auto speedReceipt = engine.requestLoopSpeed(.75, speedContext);
```

A/Bは入力フレームの半開区間。永続保存に出力座標や速度から逆算した秒を使わない。receipt.acceptedは受付だけで、準備、音声適用、音質承認は別。例外、受付拒否、再生失敗を区別する。

## 能力と対応範囲

`loopAvailability()` はimplemented／optIn／allowed／publicLoopApprovedを分離し、最後はfalse。`Capabilities.seek=false`も維持する。今回追加した `currentCycleSpeedChanges=false` を参照し、長い現在周期の途中で速度が反映されるUI期待を持たせない。

保存範囲は1フレームから、実行受付は入力100ms以上かつ確定出力周期512以上。最大callback4096で複数境界を扱う。TimeMapの確定長は平均速度による概算と異なり、準備失敗・未対応を理由付きで扱う。実測した入力形式、速度、装置、Aの範囲は `results/phase62_fix/REPORT.md` に限る。

同速度は一つのDSPプログラムを再利用し、Mapやworkerを毎周作り直さない。短区間RAWは最大96000出力フレーム、全曲PCMは保持しない。最大2つの稼働DSP、FIFO16384、予約1GiBの制限を守る。

## 状態、ID、音声の進行

Pending／Preparing／Armed／Active／Cancelled／Rejected／Failed／Disabledを分ける。initialPositionCompleteは初回移動の完了、enabledは自動反復の意思、cyclesは実際に完了した境界数。初回A復帰、手動seek、Clear継続は周回に含めない。新要求の拒否で既存有効設定を取り消さない。

inputGenerationは入力世代、sessionはDSP所有者、renderEpochは論理出力区間。同じDSPを反復してもrenderEpochは進み、sessionは維持できる。自動反復をユーザーSeek台帳へ加算しない。設定のsessionは受付時の結び付きとして保持する。新入力／再prepare／Stopは設定を解除する。曲UUID、prepare UUIDも併用し、遅い返信を捨てる。

ClearはloopIDと入力世代、受付時または現在のsessionを照合する。自動周回によるepoch進行だけでClearを拒否しない。古いIDで新しい設定を解除しない。

## 操作と優先順位

- AB ONはReturnToAを1件送る。先行して通常seekを送らない。Ready／Paused／Playingを維持する。
- 全曲はKeepPosition。既存動的速度計画や初回予約の残量不足は理由付きで拒否する。暗黙にAへ戻さず、利用者がReturnToAを選べるようにする。
- 速度はrequestLoopSpeedで受付／重複／理由を得る。Preparingでは最新値へ再計画する。再利用中の有効な自己反復を残して未開始のArmed置換を取消できる。Startedの補正が参照した版は保持する。現在周期の途中変更は未実装で、Bで固定速度プログラムへ接続する。
- clearPending中は「ループ解除の継続準備待ち」と理由付き拒否し、再生停止とは表示しない。Clear完了後に最新の文脈で再送する。既存setSpeedのStopped応答は互換性を維持するが、新ブリッジは理由を返すAPIを使う。
- 手動seekは範囲内の指定位置、範囲外（Bを含む）はAへ補正する。B直前の進入混合より短い残量の一般対応は未承認。検証済み位置に限定する。
- Pauseは原子的要求／callback応答で静止し、開始済み処理を終えてから成功する。成功後は音声・周回を進めない。Resumeまで先読みを保持する。
- Clearの受付でenabled=false。clearPendingなら、現在の有効な反復PCMを保ったまま、準備後の安全なBから通常再生への接続待ち。末尾加工が既に確定していれば次周期Bへ送る。待機中の実周回数は進む。旧boundedはBまで、新通常入力はB以後を正当に使う。Ready／Pausedでは準備だけで自動再開しない。
- Stop、装置変更、入力喪失、準備・供給失敗はループを解除する。明示Playでループを復元しない。Failedから自動再試行しない。

native LoopがenabledまたはclearPendingの間、200msの自動seek監視を同時に動かさない。フォールバックにはClear完了か明示Stopの完了が必要である。

## 出力の意味と診断

自動反復は時間的な5ms重畳を廃止し、境界前後だけへsmoothstep補正を加える。固定周期はL=OB−OA。`overlapFrames=0`、`boundaryProcessingFrames=N`。窓外はRAWビットを維持するが、任意のA/Bで音量・位相・アタックの完全保持を保証しない。出力ゲイン0.5は維持する。Clearだけは通常継続用の既存5ms混合である。

LoopBoundaryEvent.callbackFrameは論理Bのcallback座標、renderNsは処理時計、halBoundaryEstimateNsはHAL提示時刻の推定（0は未取得）。物理的音響の提示時刻とは異なる。音響ループバックなしに可聴ギャップ0と表示しない。

oldMissingFrames／newMissingFramesは入力単位、outputAffectedFramesは必要な入力が欠けた出力位置の和集合、failurePaddingFramesは安全停止のために0を出した出力位置。safetyStopFramesは最後の互換名。原音の無音や正常EOSを不足へ数えない。不足境界を成功周回へ加算せず、元の理由をFailedへ残す。

## 実アプリで残る確認手順

TimeStretchLabの実行済みSandbox／FD／失敗処理と、その制限は新REPORTを参照する。非Sandbox CLIや合成済みローカルWAVの成功を、Merodoaの権限検証に置き換えない。

1. 実際の署名・entitlementsで起動し、NSOpenPanelによる初回選択、scope開始、全所有者停止までの寿命、外部パス拒否を確認する。
2. 実曲のbookmarkを保存して再起動し、解決時のisStaleとscope開始失敗を処理する。移動／削除／アクセス取消／外部ボリューム取り外しを行い、理由付き停止と明示再選択を確認する。
3. 保護領域のTCC拒否と後からの許可取消を実際に行い、古い要求やPrepared版が復活しないことを確認する。
4. Preparing／Armed／Started／Pause／Clear待ちで曲変更・ウィンドウ終了・Stopを行い、FD数、所有者数、join後のscope終了を観測する。
5. 対応装置を変えて元へ戻し、SourceNode／deviceの時計を分ける。試聴と音響ループバックを行い、低音・左右位相・アタック・定位・周期を別々に承認する。
6. 現在周期の動的Map統合、B確定、Phase59同一適用履歴の独立参照とL1/L2を実装・測定する。それまでは長周期速度応答を製品対応としない。

旧時計異常の根本原因、Debug実時間、Fast Local長尺78/1080件、stereo Ready p95 200msは、今回の固定RAW成功で解消扱いにしない。9つの判定ゲートを分け、全てを満たすまで一般公開とMerodoa既定採用はNO-GOとする。


## 2026-10 動的Loop修正の追記

今回の追加実装と新binaryによる検証は [動的Loop設計](PHASE62_DYNAMIC_LOOP_DESIGN.md)、[検証手順](PHASE62_DYNAMIC_LOOP_VALIDATION.md)、[専用REPORT](../results/phase62_dynamic_loop/REPORT.md) を参照する。この文書の旧成功件数を今回へ付け替えず、従来の未解決記録も維持する。

長い非cache Loopは既存producerの完全状態を保持してPhase59の合法な未来へ速度を適用し、採用Mapで現在Bを再確定する。次の固定A→Bは第2所有者で先に準備し、commit後は必要な境界版を保持する。短い既確定区間等の延期理由はLoopSnapshot.speedDeferReasonへ記録する。Clearは明示的な固定Exact継続であり、動的位相履歴のB以後の連続ではない。

Paused新速度は停止後の実位置CからExact再準備し、旧producerの退役完了後にStoppedSpeedState::ReadyForResumeを公開する。要求ID・inputGeneration・Loop・cycle・preparationVersion・位置を照合し、可聴Completedと区別する。Resume/Playの意思、再Pause取消、旧FIFO破棄の専用監査を使う。B直前の進入混合はBで分割し、丸めでR=0の場合も架空のPCMを追加しない。

Merodoaへ渡す側はReadyをResume前に観測し、古いcontext/準備版を再使用しない。LoopSnapshotのdynamicSpeedRequestIDとdynamicOperationID、mapVersion、dynamicCycle、dynamicOutputEndで外部要求と実計画を対応付ける。speedPreparationFailed/speedFailureRequestIDは有効な旧出力を保持した準備失敗を示す。同じ速度の再要求も失敗後は再試行できる。公開初期値、seek公開承認、currentCycleSpeedChangesの一般承認は専用REPORTの未実施ゲートが閉じるまで変更しない。Merodoa本体・UI・submoduleは今回変更しない。
