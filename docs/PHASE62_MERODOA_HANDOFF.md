# Phase62 Fix：Merodoa Step3への引継ぎ（一般公開NO-GO）

変更対象はTimeStretchLabだけ。Merodoa本体、submodule参照、SwiftUI、SwiftData、既定経路は変更しない。Step3で進められるのは、明示opt-inの研究用ブリッジと限定検証まで。現在周期中の動的変更は同一DSPを維持する実験実装があり、検証済み範囲と残件は `results/phase62_finish/REPORT.md` を正とする。局所全体の承認までは現行の200ms方式を既定で置き換えない。

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

`loopAvailability()` はimplemented／optIn／allowed／publicLoopApprovedを分離し、最後はfalse。`Capabilities.seek=false`も維持する。`currentCycleSpeedChanges=false` は対象経路全体の必須検証が揃っていないことを示す。同一DSPでの動的Map採用、KeepPosition初回、短周期/cacheの実装と実測の対応をREPORTで確認し、部分成功から一般能力へ広げない。

保存範囲は1フレームから、実行受付は入力100ms以上かつ確定出力周期512以上。最大callback4096で複数境界を扱う。TimeMapの確定長は平均速度による概算と異なり、準備失敗・未対応を理由付きで扱う。旧固定Loopの実測範囲は `results/phase62_fix/REPORT.md`、動的Loopと今回の追加範囲は `results/phase62_finish/REPORT.md` を参照する。

同速度は一つのDSPプログラムを再利用し、Mapやworkerを毎周作り直さない。短区間RAWは最大96000出力フレーム、全曲PCMは保持しない。Preparing/Armed/退役待ち/callback参照中を含む最大2つの実行DSP、入力lease全体で最大2つの不変保存点、FIFO16384、予約1GiBの制限を守る。

## 状態、ID、音声の進行

Pending／Preparing／Armed／Active／Cancelled／Rejected／Failed／Disabledを分ける。initialPositionCompleteは初回移動の完了、enabledは自動反復の意思、cyclesは実際に完了した境界数。初回A復帰、手動seek、Clear継続は周回に含めない。新要求の拒否で既存有効設定を取り消さない。

inputGenerationは入力世代、sessionはDSP所有者、renderEpochは論理出力区間。同じDSPを反復してもrenderEpochは進み、sessionは維持できる。自動反復をユーザーSeek台帳へ加算しない。設定のsessionは受付時の結び付きとして保持する。新入力／再prepare／Stopは設定を解除する。曲UUID、prepare UUIDも併用し、遅い返信を捨てる。

ClearはloopIDと入力世代、受付時または現在のsessionを照合する。自動周回によるepoch進行だけでClearを拒否しない。古いIDで新しい設定を解除しない。

## 操作と優先順位

- AB ONはReturnToAを1件送る。先行して通常seekを送らない。Ready／Paused／Playingを維持する。
- 全曲はKeepPosition。既存動的速度計画や初回予約の残量不足は理由付きで拒否する。暗黙にAへ戻さず、利用者がReturnToAを選べるようにする。
- 速度はrequestLoopSpeedで受付／重複／理由を得る。Preparingでは最新値へ再計画する。再利用中の有効な自己反復を残して未開始のArmed置換を取消できる。Startedの補正が参照した版は保持する。必要な次固定版がReadyで、保護範囲の後に合法な遷移区間があれば現在周期の同じDSPへ動的Mapを採用する。区間が残らない場合はproducerが公開済みFIFOを保護した固定Bを確定する。準備期限未達・内部上限・未対応・失敗は別理由で扱う。単なるB待ちを動的適用とは呼ばない。
- clearPending中は「ループ解除の継続準備待ち」と理由付き拒否し、再生停止とは表示しない。Clear完了後に最新の文脈で再送する。既存setSpeedのStopped応答は互換性を維持するが、新ブリッジは理由を返すAPIを使う。
- 手動seekは範囲内の指定位置、範囲外（Bを含む）はAへ補正する。Bを跨ぐ進入混合はspanを分ける実装があり、R=0は架空のPCMを作らず有限遷移でAへ接続する。実採用方式はExactとreasonに記録する。検証済み分割・位置・速度の範囲をREPORTで確認する。
- Pauseは原子的要求／callback応答で静止し、開始済み処理を終えてから成功する。成功後は音声・周回を進めない。Resumeまで先読みを保持する。
- Clearの受付でenabled=false。clearPendingなら、現在の有効な反復PCMを保ったまま、準備後の安全なBから通常再生への接続待ち。末尾加工が既に確定していれば次周期Bへ送る。待機中の実周回数は進む。旧boundedはBまで、新通常入力はB以後を正当に使う。Ready／Pausedでは静止Cから通常Exactを準備し、旧owner退役後に再開可能とする。Resume前に音声・C・周回を進めない。Clear準備中の明示Resumeは意思だけ保持する。
- Stop、装置変更、入力喪失、準備・供給失敗はループを解除する。明示Playでループを復元しない。Failedから自動再試行しない。

native LoopがenabledまたはclearPendingの間、200msの自動seek監視を同時に動かさない。フォールバックにはClear完了か明示Stopの完了が必要である。

## 出力の意味と診断

自動反復は時間的な5ms重畳を廃止し、境界前後だけへsmoothstep補正を加える。固定周期はL=OB−OA。`overlapFrames=0`、`boundaryProcessingFrames=N`。窓外はRAWビットを維持するが、任意のA/Bで音量・位相・アタックの完全保持を保証しない。出力ゲイン0.5は維持する。Clearだけは通常継続用の既存5ms混合である。

LoopBoundaryEvent.callbackFrameは論理Bのcallback座標、renderNsは処理時計、halBoundaryEstimateNsはHAL提示時刻の推定（0は未取得）。物理的音響の提示時刻とは異なる。音響ループバックなしに可聴ギャップ0と表示しない。

oldMissingFrames／newMissingFramesは旧／新DSPが混合器へ供給する出力PCMフレーム数、outputAffectedFramesは必要な入力が欠けた出力位置の和集合、failurePaddingFramesは安全停止のために0を出した出力位置。safetyStopFramesは最後の互換名。原音の無音や正常EOSを不足へ数えない。不足境界を成功周回へ加算せず、元の理由をFailedへ残す。

## 実アプリで残る確認手順

TimeStretchLabの実行済みSandbox／FD／失敗処理と、その制限は新REPORTを参照する。非Sandbox CLIや合成済みローカルWAVの成功を、Merodoaの権限検証に置き換えない。

1. 実際の署名・entitlementsで起動し、NSOpenPanelによる初回選択、scope開始、全所有者停止までの寿命、外部パス拒否を確認する。
2. 実曲のbookmarkを保存して再起動し、解決時のisStaleとscope開始失敗を処理する。移動／削除／アクセス取消／外部ボリューム取り外しを行い、理由付き停止と明示再選択を確認する。
3. 保護領域のTCC拒否と後からの許可取消を実際に行い、古い要求やPrepared版が復活しないことを確認する。
4. Preparing／Armed／Started／Pause／Clear待ちで曲変更・ウィンドウ終了・Stopを行い、FD数、所有者数、join後のscope終了を観測する。
5. 対応装置を変えて元へ戻し、SourceNode／deviceの時計を分ける。試聴と音響ループバックを行い、低音・左右位相・アタック・定位・周期を別々に承認する。
6. TimeStretchLabでの現在周期Map統合・B確定・独立参照・L1/L2の完了範囲を最新REPORTで確認し、実アプリの操作・遅延・寿命条件でも受入試験を行う。局所機能と実アプリの両ゲートが閉じるまで長周期速度応答を製品承認しない。

旧時計異常の根本原因、Debug実時間、Fast Local長尺78/1080件、stereo Ready p95 200msは、今回の固定RAW成功で解消扱いにしない。9つの判定ゲートを分け、全てを満たすまで一般公開とMerodoa既定採用はNO-GOとする。


## 2026-10 動的Loop修正の追記

今回の追加実装と新binaryによる検証は [動的Loop設計](PHASE62_DYNAMIC_LOOP_DESIGN.md)、[検証手順](PHASE62_DYNAMIC_LOOP_VALIDATION.md)、[専用REPORT](../results/phase62_dynamic_loop/REPORT.md) を参照する。この文書の旧成功件数を今回へ付け替えず、従来の未解決記録も維持する。

長い非cache Loopは既存producerの完全状態を保持してPhase59の合法な未来へ速度を適用し、採用Mapで現在Bを再確定する。次の固定A→Bは第2所有者で先に準備し、commit後は必要な境界版を保持する。短い既確定区間等の延期理由はLoopSnapshot.speedDeferReasonへ記録する。Clearは明示的な固定Exact継続であり、動的位相履歴のB以後の連続ではない。

Paused新速度は停止後の実位置CからExact再準備し、旧producerの退役完了後にStoppedSpeedState::ReadyForResumeを公開する。要求ID・inputGeneration・Loop・cycle・preparationVersion・位置を照合し、可聴Completedと区別する。Resume/Playの意思、再Pause取消、旧FIFO破棄の専用監査を使う。B直前の進入混合はBで分割し、丸めでR=0の場合も架空のPCMを追加しない。

Merodoaへ渡す側はReadyをResume前に観測し、古いcontext/準備版を再使用しない。LoopSnapshotのdynamicSpeedRequestIDとdynamicOperationID、mapVersion、dynamicCycle、dynamicOutputEndで外部要求と実計画を対応付ける。speedPreparationFailed/speedFailureRequestIDは有効な旧出力を保持した準備失敗を示す。同じ速度の再要求も失敗後は再試行できる。公開初期値、seek公開承認、currentCycleSpeedChangesの一般承認は専用REPORTの未実施ゲートが閉じるまで変更しない。Merodoa本体・UI・submoduleは今回変更しない。

## c4bdbb44以後の外部要求API

速度受付は `LoopSpeedReceipt.code` とreasonを値コピーする。Acceptedは準備完了ではない。Duplicateは既存ID、DuplicateInitialはID=0で対応する過去要求がない。上限拒否は最新の受理済み要求と停止C・再開意思を変更しない。エンジン生存期間最大4096件の `loopSpeedHistory()` / `loopSpeedOperation(id)` に全外部IDの結果を保存し、入力変更でも過去を消さない。

Pending/Preparing、停止中ReadyForResume、動的Committed、固定延期FixedBoundaryCommitted、Applied/Completed、Replaced/Cancelled/Failedを区別する。`outputStarted` はソフトウェア出力開始の事実であり、物理音響の時刻ではない。開始済み・commit済みの過去を未適用Replacedへ書き換えない。準備中のResume意思は最新要求へ保持し、再Pauseで取り消す。

受入条件は、全IDの終端、Ready前Resume禁止、現在周期適用の実PCM、独立Map/RAW/境界出力、自然周回、最大2所有者/保存点、callback禁止操作と正常供給不足0である。`loopSpeedPcmEvidence(id)` は通常キューの検証用に限り、所有者退役後の欠落を成功へ読み替えない。現行状態と過去の検証記録を分ける。下の旧追記・過去REPORTの未実装記述は当時の状態であり、現行説明はこの本文と新REPORTに従う。

停止中Clearで最新速度を使用する場合、`LoopSpeedOperation.clearContinuation` と新session/epochのReadyForResume/Completedを追う。`LoopSnapshot.pausedClearInputFrame/pausedClearDiscardedFrames` は固定Cと置換破棄の監査であり、実消費や自然周回ではない。Clearを明示seekで置換すると移管IDは理由付きCancelledとなり、その後の設定は新seek IDで追う。準備失敗は旧Cのまま停止し、旧速度へ自動復帰しない。

初回ReturnToAの採用前にClearした場合、未開始速度IDはCancelledとなり、通常音声を継続する。速度変更が必要なら、Clear後の最新文脈で通常のsetSpeedを再要求する。Startedと競合した場合は新targetを保持し、通常Exact継続を用意する。[残件の再検証手順](PHASE62_REMAINING_VALIDATION.md) を参照する。

Clear準備中にResumeを受理した場合は、旧ownerのjoin後に一度だけ開始を試み、その成功を確定してからclearPending=falseを公開する。明示ResumeなしのPaused Clearは停止を保つ。開始API成功と物理出力開始は別である。

停止中速度準備がFailedになった後は、失敗版の退役が続いていてもPlay/Resumeを拒否し、再開意思を新規登録しない。新速度の明示的な再要求やseekで復旧する。退役中のseekBusyを再開可能な準備待ちと誤認しない。

## e5dc9167レビュー後の採用・失敗・close監査

今回のTimeStretchLab内の修正・最終証拠は [e5レビューREPORT](../results/phase62_e5_review/REPORT.md)、[制御対応表](../results/phase62_e5_review/CONTROL_COVERAGE.md)、[設計](PHASE62_E5_REVIEW_DESIGN.md) を参照する。過去REPORTの未完件数は当時の記録として保持する。Merodoa本体・UI・submoduleは変更していない。

native Requestedの取消が確定する前に旧外部IDをReplacedへ進めない。Started/Doneが勝った版と、自己反復がないKeepPosition初回Bの必須供給版は、実使用と退役が終わるまで保持する。保護だけを理由にcommitやPCM開始を記録せず、実際のsession/epoch/firstPcmを観測して終端へ結ぶ。Clearでも採用済み旧IDと最新の継続IDを区別する。

内部4096上限は外部要求のFailed/InternalLimit、未対応はUnsupported、一般の準備失敗はPreparationFailedとして今回の確定原因を返す。過去のBusyRetryを最終失敗原因へ流用しない。cache再構成の旧要求Aは、新要求Bの受付後にBを拒否できない。失敗・取消で旧有効音声を保持しても、要求成功とは表示しない。

`ProgressiveOptions.receiveFinalLoopSpeedAudit/context` は検証用の通常側sinkである。全worker join・最終退役後、破棄前に全外部台帳を値コピーする。sinkのcontextをEngine破棄完了まで生存させ、span参照を保持しない。音声callbackへ監査やログを接続しない。製品の公開close APIを追加したとは扱わない。ブリッジ受入では全Accepted IDの終端種別と過去不変を検査する。

Pausedの受入はResume前ReadyForResumeと最新ID/入力世代/Loop/停止C/準備版の一致、失敗版退役中のPlay拒否、明示最新要求による復旧を含む。一般公開・Merodoa既定採用は引き続き別ゲートであり、4つの公開初期値（実験Loop opt-in、publicLoopApproved、seek、currentCycleSpeedChanges）をこの局所結果だけで有効化しない。


## e5レビュー修正の装置復旧前の検証状態（2026-10-21）

当時の [e5レビューREPORT](../results/phase62_e5_review/REPORT.md) は **INCOMPLETE / NO-GO**。制御36program/202checks、限定同一性で接続した既存制御184checks、Release/Debug各20CTest、選択したoffline9群はPASS。最終実機は音声callback開始待ちで同じ最初の1programが2回とも失敗し、予定41programの残り40は未実施である。正常RT8本はその内数。通常再生・標準afplay・旧成功ビルドでも開始できず、装置bufferは512へ復元した。根本原因は未確定。過去の実機成功統計を今回の無退行証拠へ転記しない。公開初期値とMerodoa既定採用は変更しない。


## 装置復旧後の局所ゲート完了（2026-10-21）

[e5レビューREPORT](../results/phase62_e5_review/REPORT.md) の今回限定の局所判定は **PASS / GO**。ユーザーの装置復旧後、同じソースcefdb129…・実行体・参照・条件でnative_recovered_01の全5群41programを新規に実行し、その内数の正常RT8本もPASSした。両Presetで実消費4100周、正常8条件の不足/padding・callback確保/解放・callback/worker期限超過0、buffer512復元を確認した。復旧前の失敗・当時の未実施数は履歴として保持する。

seek機能試験のworker期限超過1件（旧faにも同じ観測、RT承認NOT_ASSESSED）は別記録であり、全41本の期限超過0やseek切替の一般RT承認を主張しない。公開初期値4つ・publicSeekApproved=falseと、物理loopback・試聴・Merodoa/TCC実統合等の別ゲートは維持する。Merodoa本体・UI・submoduleは変更しない。
