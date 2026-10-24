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

## b035後のF01：初回供給jobと要求IDの同期

追加修正・今回の検証結果は [F01 REPORT](../results/phase62_f01/REPORT.md)、[制御対応表](../results/phase62_f01/CONTROL_COVERAGE.md)、[設計](PHASE62_F01_DESIGN.md)、[検証手順](PHASE62_F01_VALIDATION.md) に分離した。b035時点のD01〜D11と装置復旧後の成功記録は保持する。

KeepPosition初回で自己反復できない場合、供給jobの選択・next構築と、そのjobを保護する外部ID／Preparing／準備版を同じEngine mutex内で公開する。次要求Bを受けても必要な初回AをReplacedにせず、Aの実session/epoch/PCMを観測してCompleted、その後のBもCompletedへ進める。Aの確定済み履歴をB適用後に書き換えず、保護だけを理由にcommitやPCM開始を記録しない。

受入側はLoopSpeedReceipt、全Accepted ID履歴、Resume前ReadyForResumeと最新要求ID・入力世代・Loop・停止C・準備版、実PCMの座標、直接close後FinalLoopSpeedAuditを対応付ける。失敗版退役中の再開拒否、全owner join後のFD/InputLease・security scope解放、古い完了通知の排除を維持する。

F01の限定局所完了、一般公開、Merodoa既定採用は別判定であり、最終判定はF01 REPORTへ記録する。allowExperimentalLoops、publicLoopApproved、seek、currentCycleSpeedChanges、publicSeekApprovedの現行falseを維持する。Merodoaの初回選択・拒否/取消・再起動・曲変更・bookmark・TCC・最新要求とUI整合は実アプリの別受入試験とし、今回Merodoa本体・UI・submoduleを変更しない。

今回のF01限定局所判定は **PASS / GO**。旧比較4/4再現、修正版10 program/64 checks、変更後Engineの既存75 program/326 checks、Release/Debug各20 CTest、境界872 checks/独立handoff6 program、実出力41 program/内数の正常RT8本が完了した。共有DSPの全161速度等は実依存・binary・入力・凍結参照を照合した限定再利用で、新規実施へ付け替えていない。seek機能試験のworker期限観測は今回Candidate通常/R0各0、Baseline通常/R0各1、機能PASS/RT承認NOT_ASSESSEDで別記する。一般公開・Merodoa既定採用のNO-GOは維持する。

## 2026-10-22 A1：Paused Clearと確定速度履歴

`PHASE62_TERMINAL_CLEAR_DESIGN.md` と `../results/phase62_terminal_initial/A1_REPORT.md` を参照。Clear自身のSnapshot計数と速度要求別計数を分離し、移管済み・未終端・同一入力/Loop/準備版の要求だけを更新する。公開API・構造体フィールドは維持する。Clear前のネイティブCompleted値から、後の個別照会・履歴・close終了監査まで全フィールド不変を確認する14 checksと限定回帰は、新規Release arm64 binaryで147/147 PASS。旧13/14失敗と過去F01/D07/D08は別証拠として保持する。

Merodoa側は終端キャッシュで補正せず、同じ14 checksをbridge経由でも再確認する。終了監査contextはclose完了まで保持し、借用spanを即時所有コピーする。今回の判定は履歴修正の限定PASS。初回Exact性能A2・一般公開・Merodoa既定採用の承認には拡張しない。

## 2026-10-22 A2：初回ReturnToAの完全Exact保存状態

同prepareで互換な固定A保存点がある場合だけ、初回Loop準備へ復元する。`PHASE62_INITIAL_EXACT_REUSE.md` と `../results/phase62_terminal_initial/REPORT.md` を参照。300秒/48k stereo/PCM16、Baseline1.00、AB2秒、各n=2で、受付から最初のA RAW採用までの中央値はA30秒で3.344160→0.115776秒、A270秒で29.271878→0.120618秒。実装前固定目標を満たす。新prepare初回（A270で約30秒）、解析待ち、Clearの通常Exact再準備、キー不一致は別条件であり、高速化したとは扱わない。

追加診断は `ProgressiveDiagnostics.pipeline.loopReuse.initialCheckpointHit`。このepochの初回A保存状態復元を示し、通常seek、動的Map、ReadyForResume、可聴Completedとは別。`checkpointStartFrame + coldDiscardedFrames == outputStartFrame`、hit時の前置破棄2048未満と合わせて確認する。A0は保存位置0でもhit可能。既存analysisWaitS/mapCpuS/coldPrefixS/coldPrefixCpuS/seedOutput/checkpointPeakをそのまま使う。同じheader/libraryの組でnative bridgeを再ビルドし、公開診断へ写すなら正確に対応させる。

入力世代/finalAnalysis/resident identity、Preset、速度、A/B/固定Map全ノード・全長が一致した完全状態だけを再利用する。最大2実行owner・最大2checkpoint・FIFO16,384・短区間RAW96,000・既存予約を維持する。C≠AのPaused速度再準備では任意初回枠を先に解放する。旧FIFOの保護、全owner/入力FD/PCM leaseの寿命、join後解放、終了監査の即時所有コピーは維持する。通常手動seekのopt-inは変えない。

Ready/Pausedの初回ReturnToAはAへ位置合わせして静止し、明示Play前には消費/音声/周回を進めない。通常Paused速度変更は停止位置C保持であり、二つの契約を混同しない。Merodoa側ではA1のClear前凍結14checks、正当な未終端Clear移管、同prepare再要求/fresh初回/解析前後、A0/30/270、Playing進入混合、最新速度変更後の初期枠失効を限定再試験する。SpeedOperationの39fields/要求ID/終端不変/終了監査APIは変わらない。

最終品質は独立旧Exact参照で7native条件14round＋offline両Preset、70/70 checks、最終A1/F01/Paused Clear等147/147。物理出音時間・p95・全条件実時間期限・一般公開・Merodoa既定採用の承認には広げない。短全曲F01中間試験の単発期限超過もREPORTに保持する。Merodoaのコード、submodule、UIはこの作業で変更していない。

## 2026-10-22 制御負荷・Clear再ONの接続契約

ff1f677f基準の追加作業は[制御負荷・AB入口](PHASE62_CONTROL_AB_PERFORMANCE.md)、[検証手順](PHASE62_CONTROL_AB_VALIDATION.md)、[今回REPORT](../results/phase62_control_ab/REPORT.md)を参照する。旧Phase62の公開/既定採用ゲートを変更しない。Merodoa本体・依存内・gitlink・承認SHAは今回更新していない。

通常の状態/診断/Loop取得は最大3行の速度要約を使い、全履歴は明示取得時・退役/終了監査時だけコピーする。外部Accepted全IDと終端39fieldsの不変性は維持する。任意のmeasureControlCostsは通常アプリではfalseのままにし、詳細計測を定常CPUへ混ぜない。同一InputLeaseのidentity検証は通常側で共有し、既存の入力異常検出期限を緩めない。

OFFのrequestClearLoop受付後、最新のONが来たら、旧ClearのclearPending=falseを待つ必須条件はない。最新の入力・A/B・再生意思を確定し、getStateSnapshotの新しいinputGeneration/session/renderEpochでrequestLoopRange(A,B,context,ReturnToA)を通常の直列制御キューから送る。受付後はその新Loop IDでinitialPositionCompleteを追う。contextの競合拒否は最新意図がまだ同じ場合だけ取り直して再要求する。旧Accepted IDを消したり、新IDへ書き換えない。

未採用Clearは取消・停止/join後に第二枠を再利用する。Started/Doneは混合・採用・参照解放/退役を完了するまで保持し、新ReturnToAはその後に準備する。Applying/Committed/FixedBoundaryCommittedは既存どおり理由付き拒否し、B完了後の新鮮contextで再要求する。KeepPositionも新旧ownerが分かれているClear退役窓では拒否する。これらは不要なVM直列待ちとは別の安全上必要な待機である。

Pausedでは静止Cと明示Resume契約を維持する。ONは新Aへ位置を合わせる実行要求であり、事前準備だけのAPIとして早送信しない。準備中のPlay/Resume意思、再Pauseによる取消、Stop/入力/装置/closeの失効をアプリの最新意図と対応させる。終了監査は全Accepted IDを独立に回収する。開始済みで停止されたCancelledはoutputStarted/firstPCM/sessionの事実を保持するため、未出力と同義には扱わない。

`initialCheckpointHit`は同A/Bの保存点、`initialPrefixCheckpointHit`は互換な通常seekのP<=OA保存点の流用であり、速度/Preset/入力/全Map/完全DSP状態が一致した場合に限る。後者はP→Aの残合成がある。保存点のないA270のfresh初回は約28秒が残り、seekCheckpoints設定だけを高速化保証にしない。新しい先行準備APIは導入していない。

受入時は同SHAのarchiveとheaderを同時に再ビルドし、同一入力・device/buffer・観測条件でアプリ側を再計測する。単体process CPUの約12%相対減を、Merodoa全体の改善率へ転記しない。旧Clear待ちと即時ReturnToAの両接続を実PCM採用時刻・全ID終端・自然周回・供給0・callback確保0・最大2owner/2checkpointで再確認する。品質、公開承認、既定化、ピッチシフトは別ゲートを維持する。


## 2026-10-23 正式採用作業Dへの追記

上記のNO-GO/既定化禁止は当時の対象・証拠の記録として保存する。今回の正式採用指示に対する最新の方式別判断は [Progressive採用台帳](PROGRESSIVE_ADOPTION_PLAN.md) と [新実行REPORT](../results/progressive_adoption/REPORT.md) を参照する。過去の未達を成功へ書き換えない。

能力契約はv3。ヘッダーと全archiveを同じ候補から再ビルドし、`prepare(..., ContractV3Tag)`のリンク記号でも混在を防ぐ。`ProgressiveOptions::macOSProduct()`はExact方式だけをApprovedOnlyで有効にする。Interactive/FastLocal、nativeLoop、現在周期速度の正式承認は未達を残す。旧包括`Capabilities.seek`/`publicSeekApproved`はfalseで、Exact単独の承認を隠さないよう`seekAvailability().exact`と`.interactive`を分けて読む。現在のMerodoaのInteractive要求をExactへ差し替えてはいない。

Loop研究経路を使用する場合は、明示の方式別Research設定を渡す。同じ実効設定から24MiB追加予約、有限観測、受付、診断を導出する。[v3 API・理由コード・復旧](PROGRESSIVE_ADOPTION_API_V3.md) に従い、日本語理由文の文字列一致で制御しない。採用済み境界・退役待ち・範囲拒否・入力障害・上限到達を区別する。

A/B確定後の準備だけには`requestLoopPreparation(A,B,context)`を使う。これは位置を変えず、最大1件の準備を行い、全join後に不変A保存点をReadyとして返す。ONは従来`requestLoopRange`で明示する。準備前のON/Playは先行準備を取消して操作を優先する。Ready前に旧PCMを消費せず、Pausedから自動再開しない。warm短縮をcold高速化としない。

専用の非メイン直列制御キュー、engine/prepare UUID、inputGeneration/session/epoch/loopID/requestID、FD/security scope/PCM leaseの全join後解放は維持する。4096上限はStop→prepareでは回復しない。全Acceptedの終端を所有コピーとして回収し、close後、新UUIDのengineを作り、入力・静止C・速度・Loop・再開意思を明示復元する。ID1の再利用を旧engineと混同しない。

Merodoa本体、依存gitlink、承認SHAはこの作業では変更しない。実アプリF、TCC、試聴、物理loopback、RTと性能の未達は[受入表](PROGRESSIVE_ADOPTION_F_ACCEPTANCE.md)で個別に閉じる。

通常速度全終端の回収には`receiveFinalEpochAudit`も設定する。全join/参照解放後・256件切詰め前に所有コピーし、destructorの最終`epochAuditConfigured/Calls/Rejected`を照合する。新300Accepted cohortのRelease/Debug各56 checks PASSを既存Loop H<=1から独立に記録した。詳細と未達は上記最終REPORTを参照。

## 2026-10-23 性能・応答候補の追加契約

今回の候補は契約v4／`ContractV4Tag`。同じソースから全header/archiveを同時に
再ビルドする。`ContractV3Tag`名はソース互換の別名だけで、旧v3のリンク記号は
提供しない。上のv3実行結果は当時の結果として保持する。

同一identityの準備途中に明示ReturnToAを受けた場合は、先行jobの完了済み仕事を
保持し、残りを待って完全A状態を引き継ぐ。`LoopSnapshot.preparationRequestID`と
非終端準備行の`transferredToLoopID`を別IDとして対応付け、終端行を書き換えない。
準備Ready・Loop採用・最初のPCM・旧owner退役を分ける。Pauseは静止を優先し、
移管済み準備は継続する。明示Resumeの意思は準備と必要な退役が終わるまで保持する。
未移管の任意先行準備は従来どおり操作優先で取り消す。

通常Exactの一部は必要な解析確定後に開始できる。全曲解析完了とは別の事実であり、
FastLocal・Loop保存点・末尾Nのfinal待ちまで解消したという意味ではない。
共有解析はInputLeaseごと一つで、旧owner停止後も新ownerへ供給し、最後の利用者の
join後にFD／常駐PCMを解放する。最大2owner／2checkpointと予約は維持する。

内部stage hashは最終候補08でnative通常時も既定ONへ戻した。
保存05の既定OFFは全体CPU悪化を実測したため取り下げ、入力identity SHAと最終PCM検査は維持する。
必要な診断は`recordStageDigests`または詳細profileで明示する。未測定値をhash=0の
実測として扱わない。採用判断・実行コマンド・失敗は
[性能・応答REPORT](../results/performance_response/REPORT.md)へ分ける。
本体・gitlink・承認SHA・既定engineはこの作業で変更しない。統合時はcommitした
40桁候補SHAを固定し、同じ提供素材・Release・UI条件で受け入れる。

## 性能候補08の評価確定（2026-10-24）

性能候補は未commitのsource08 `b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94`。
checkpointの安全拒否/状態保持/明示Exact再準備3caseは現行実行体でPASS。
CPUは固定n6のmono1倍で全pair増加し、一式として性能採用しない。隔離09/probe10も棄却。
Closed済みPhase62の機能証拠は維持するが、08の全面native回帰・性能採用へ拡張しない。
契約v4は候補で、今回Merodoaへ固定する承認済みcommit SHAは作っていない。
本体/gitlink/承認SHA/既定engineを変更せず、[確定REPORT](../results/performance_response/REPORT.md)
のNOT_RUN・品質/応答FAIL・実アプリFを引き継ぐ。
