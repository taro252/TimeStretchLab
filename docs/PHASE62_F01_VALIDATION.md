# Phase 62 F01 検証手順と受入条件

対象はKeepPosition初回供給jobの選択と外部要求ID公開の競合である。[設計](PHASE62_F01_DESIGN.md)と併せて読む。今回の開始点は`main@b0352c6f4c22f100f161297769b26561dc07701b`、作業開始時の未コミット差分は空だった。開始ソース一覧は`cefdb1294e89cb5280ad8f6df401eac59825212334e4110f958ca6f0d7c0199c`、今回のコード・試験を固定した一覧は`272b9a4da27ff86993993e03ade356a4b64705cce717228366ca40254bd490d1`である。文書・結果を一覧へ含めたと誤解せず、`source_manifest()`が定めるCMake・src・tests・scriptsの範囲と各ファイルSHAを参照する。

今回の原本は`build/phase62_f01_20261021_01/`へ保存する。`INITIAL.json`にはHEAD、branch、status、指示ファイルと旧証拠のSHA、環境を記録した。`VALIDATION_PLAN.json`は実行前に決めた期待件数であり、結果そのものではない。最終の実施結果・限定再利用・局所完了は`results/phase62_f01/`のREPORTとmanifestへ集約する。過去のe5レビューの成功・失敗・装置復旧記録は保持する。

## 比較版を区別する

旧挙動比較版は、未改変のb035実行体でも独立DSP参照でもない。`recipes/build_baseline.py`は新しい隔離snapshotへ共通のF01試験と通常worker用hook宣言をコピーし、Engine.mmをb035から取得して`LoopJobSelected`呼出し1行だけを加える。active IDの公開はb035の別mutex区間のままである。利用者の作業ツリーや旧runは戻さない。

比較版のソース一覧は`1c7d096f775baad3b25e1c3b33e29e0150e15b4680aeda6ac02b259b3cb27e0f`、実行体SHAは`e92762bbce17aa485b34a76bb14ccf49e21b641a1c5f79a9a7a3110f7fea23d0`。修正版の実行体SHAは`919e7db68bb690cc4753fefa1801d5cc79233801e75a2435359324505603f030`。両方とも`phase62_adoption_review_native`で、共通試験ソースのSHAは`292f2860c5861c840e3a3c698f9e0dad124044a19bc0a977f7669a6a8200da86`である。`baseline_01/EXPECTED.json`、`baseline_01/BUILD.json`、`BUILD_CANDIDATE_01.json`が、これらの値とconfigure/build終了コード・compiler・flagsを結び付ける。

ビルド環境はmacOS 26.6.2、Apple clang 21.0.0、CMake 4.3.3。Releaseはarm64、`-O3 -DNDEBUG -std=c++20 -arch arm64`を使う。shellの`uname -m`だけで実行体のarchitectureを決めず、保存した実行体のarchitecture検査を使う。ビルド失敗後に旧実行体を代用しない。

## 同じ介入順序を実Engineで固定する

1. 通常Playingから全曲KeepPosition Loopを要求する。`LoopJobDispatch`で選択前の通常workerを待機させ、通常APIからA=75%を受理する。
2. dispatchを解除し、job選択・next構築後の最初のmutex解放直後、`next->start()`前の`LoopJobSelected`で同じworkerを待機させる。このhookはEngine mutex外であり、callbackへ待機を入れない。
3. 通常APIからB=200%を受理する。入力世代、normal session/epoch、loopID、選択時刻・準備件数・外部準備版、公開/消費位置、AのB受付前後とBの行を値として取得する。commit、outputStarted、first PCMを未発生のまま確認する。
4. gateを解除してから小さい観測ファイルを保存し、初回Bの実RAWとboundaryを観測する。その後のB Completedまで待ち、Aの確定済み履歴が変わらないことを検査する。

hookは有限であり、状態フィールドを直接書き換えない。callbackには確保・解放・mutex・join・I/O・planner・FFT・待機を加えない。gate中の通常APIをhook自身から呼ばず、Engine mutex内hookから別threadのEngine API完了を待つ構造も使わない。窓未捕捉、gate期限、装置開始不能、A/Bの準備期限超過はFAILであり、旧不具合の再現成功へ数えない。

通常ownerの自己反復が使えない二つの原因を層別する。240ms入力はdspDoneと未消費FIFO、1秒入力は実際のnormal checkpoint permitを1回拒否してLimitReachedを使う。入力は既存生成物をSHAで固定し、短入力を別の素材へ黙って置き換えない。

|fixture|入力フレーム／形式|SHA-256|
|---|---|---|
|`short240ms.wav`|10,584／44.1kHz stereo Float32|`e9ede4e9ef338ed417e0084c053e7dde415692177191438a8461019c133c32eb`|
|`one_second.wav`|44,100／44.1kHz stereo Float32|`a004d713303a674daea553640c81815be3175c15fc2a33ffd5774edd5d495d74`|

原本は`build/phase62_e5_review_20261021_01/inputs/`。今回の`EXPECTED.json`にもサイズ・入力SHA・コマンドを記録する。F01機能試験の観測装置は48kHz／buffer512だったが、この有限gate試験を正常負荷の期限保証へ転用しない。

## 旧版の再現成功と修正版の64 check契約

旧比較の主2 modeを両Presetで実行する。各子は7 check中4 checkを完了し、実採用Aの要求ID不整合で終了コード1のFAILになることが期待である。親のPASSは「旧不具合の再現成功」を表す。子のFAILを通常試験PASSへ書き換えない。

再現成功には、AのB受付後と実採用後がReplaced、実初回BでA版のRAW/session/epochが存在、初回Bのcallback座標が入力Bと一致、Bは実PCM付きCompleted、Aの過去履歴はB適用後も不変、という全条件が必要である。`F01_selected_window.json`と`F01_actual_adoption.json`を照合する。旧比較4/4本でこの不一致を観測した。例えばCandidateの短曲ではA=ID2、B=ID3、入力世代1、初回B=callback frame10,584、A版の実session2／epoch3を観測した一方、Aの行はReplacedでsession/epochが0だった。1秒条件でも初回B=44,100で同じID不整合を観測した。これをPCM欠落や聴感劣化の実測とは呼ばない。

修正版は主2 modeと補助3 modeを両Presetで実行する。ここで64はcheck IDの実行総数であり、64個の速度要求を意味しない。主試験は各2 Accepted ID、補助は回復要求を含む各3 Accepted IDを持ち、受付ID集合と台帳ID集合を各processで完全一致させる。

|mode|1 programの必須check順序|両Presetの期待件数|
|---|---|---|
|`f01_dsp_done`／`f01_checkpoint`|`F01.normal_no_self_repeat_condition` → `F01.selected_job_then_latest_B_window` → `F01.actual_initial_B_session_epoch_PCM` → `F01.latest_B_Completed_and_A_past_immutable` → `F01.required_A_protected_and_Completed` → `F01.exact_IDs_and_terminal_types` → `normal_supply_heap_owner_audit`|4 program／28 checks|
|`f01_selected_stop`／`f01_selected_clear`／`f01_selected_failure`|`F01_CANCEL.normal_no_self_repeat_and_selected_A` → `F01_CANCEL.latest_B_accepted_no_false_facts` → `F01_CANCEL.action_effective_no_A_or_B_PCM` → `F01_CANCEL.prepared_owner_joined_and_followup_recovers` → `F01_CANCEL.direct_close_exact_IDs_reasoned_terminal` → `normal_supply_heap_owner_audit`|6 program／36 checks|

修正版の主試験では選択時点でAがPreparing・準備版付きであり、B受付後も非終端であることを確認する。初回BのA実PCMとA Completed、その後のB実PCMとB Completed、Aの履歴不変、初回自然周回1回、入力位置・境界座標、実行owner最大2、checkpoint最大2、旧epochのjoin完了を検査する。`f01_fixed_01`は10/10 program、64/64 checks PASSを確認済みである。

Stop補助は通常APIの別threadを開始し、既存`SeekCleanupWait`で取消確定を観測してselected gateを解除してからjoinする。Clear補助は初回jobの採用前に解除し、全曲B=EOFの固定Exact継続を確認する。失敗補助は次版の実WorkgroupJoinを1回失敗させる。Stop/ClearはA/B Cancelled、失敗はA Failed・B Cancelledで、全て未採用PCMと偽Completedがない。失敗版だけはjoinErrors=1、joins=leaves、promotions=restoresを要求し、正常版の既存Workgroup退役条件を緩めない。

各補助はowner全退役後、通常APIによる新入力世代のprepare、新Loop、125%要求のReadyForResume、明示Play、実PCM付きCompletedを確認する。旧callback構成のPCM監査を保存してから、新構成で0へ戻るcallback座標用の試験監査器を再初期化する。製品FIFOや消費位置を試験から補正しない。最後に直接破棄後のFinalLoopSpeedAuditを一度受信し、workersJoined／retirementComplete、全3 IDの一意性・終端種別・理由を値コピーで検査する。進行中の直接closeは既存Playing台帳の回帰も再実行対象にする。

## 実行例

以下はリポジトリrootで実行する。保存済みの`*_01`へ上書きしない。音声試験・ビルド・性能計測は他担当の同種作業と重ねず直列で行い、装置設定を変更した試験は元へ復元する。

```sh
task_python=/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
task_build=build/phase62_f01_20261021_01

# 保存済み比較版の再実行例。入力/実行体/共通試験/ソースSHAを再照合する。
"$task_python" -B results/phase62_f01/recipes/run_f01.py \
  --kind baseline --build-record "$task_build/baseline_01/BUILD.json" \
  --output "$task_build/baseline_repro_02"

# 修正版の再実行例。
"$task_python" -B results/phase62_f01/recipes/run_f01.py \
  --kind fixed --build-record "$task_build/BUILD_CANDIDATE_01.json" \
  --output "$task_build/f01_fixed_02"

# 影響する既存Engine機能群。新規output名を使う。
"$task_python" -B scripts/phase62_evidence.py \
  --guard-device-buffer "$task_build/REGRESSION_DEVICE_GUARD_02.json" \
  "$task_python" -B results/phase62_f01/recipes/run_regressions.py \
  --build "$task_build/candidate_build" \
  --build-provenance "$task_build/BUILD_CANDIDATE_01.json" \
  --output "$task_build/regressions_02"

# Release/Debug各20 CTest、configure/build/ctest計6 stage。
"$task_python" -B scripts/phase62_gate_runner.py --root "$PWD" \
  --build-base "$task_build/strict_builds" \
  --release-build "$task_build/candidate_build" \
  --output "$task_build/strict_02"

# runtime/release・debugは上の実buildへ対応付けた参照用パス。
# alias自体を再configureせず、EXPECTED内の各実行体SHAを確認する。
"$task_python" -B results/phase62_finish/recipes/run_remaining_gates.py \
  --group renderer --build-base "$task_build/runtime" \
  --output "$task_build/renderer_02"
"$task_python" -B scripts/phase62_evidence.py \
  --guard-device-buffer "$task_build/NATIVE_DEVICE_GUARD_02.json" \
  "$task_python" -B results/phase62_finish/recipes/run_remaining_gates.py \
  --group native --build-base "$task_build/runtime" \
  --output "$task_build/native_02"
```

隔離比較版の構築recipeは`results/phase62_f01/recipes/build_baseline.py`。初回のBASE、snapshot、configure/buildコマンドは`baseline_01/EXPECTED.json`に保存済みである。再構築時はrecipeの新しい一意なBASEを明示してそのrecipe自体のSHAを記録し、旧snapshotを削除して使い回さない。修正版も、現在のsource inventoryとbuild記録が異なる場合は新規buildへ再構築する。コマンド終了0だけでPASSにせず、期待ID集合、完了marker、最終統計、timeout=false、ソース・実行体の実行前後一致を検証する。

## 影響回帰と限定再利用

以下は事前定義した必要集合である。F01旧比較4/4再現、修正版10/10・64/64に加え、Engine既存75 program/326 checks、Release/Debug各20 CTest、renderer872 checksと独立handoff6 program、native41 program（内数の正常RT8本も含む）は新runで完了した。限定局所判定はPASS / GO、一般公開・Merodoa既定採用はNO-GO。原本と各最終統計は今回REPORTとMANIFESTを参照する。

|必要集合|期待|狙い|
|---|---|---|
|Engine adoption／fault／partial|28 program／154 checks|A1取消/Started、A2必須初回供給、D09、内部4096、部分混合、失敗版退役|
|control／Playing／API／Paused-Clear／Race|47 program／172 checks|全ID終端と直接close、Paused位置C・ReadyForResume・再開意思、Clear、入力世代・古い通知|
|Release／Debug CTest|各20件、計6 stage|既存必須集合を減らさず、証拠検証器75単体検査とD07/D08下位試験も含む|
|renderer再実行|4群、境界872 checks・独立handoff6 program|Engine.mmを直接includeする試験を新Engineから切り離したと扱わない|
|native再実行|5群、41 program。その内数で正常RT8|通常API独立比較・Paused/Clear/seek/供給。A=0/30/270秒と4100周を両Preset|

ゲート付きF01・故障注入群の期限承認は`RT_deadline_approval=NOT_ASSESSED`とする。品質はmissing／underrun／rejectedWrites／failure padding／safety stop=0、非有限PCM=0、RAW順序・境界数式監査エラー=0、callbackのC++ new／malloc／free=0を維持する。正常RT8はゲートなしの既存事前条件で別に期限・供給・最大owner・周期・完走を判定する。物理loopbackや人の試聴は実施した場合だけ別記録にする。

共有DSP・planner・renderer本体、既存Python driver、固定参照を今回の変更へ取り込まない。`recipes/audit_reuse.py`は実`.o.d`と`link.txt`の閉包、依存ソースSHA、compiler・flags、保存された旧実行体・入力・driver・参照SHA、期待/実行IDと終了コード・最終統計を照合する。対象は動的640（全161速度の実適用）・重点20・形式54、Exact896・Golden25・固定有限322・reuse322、worker8 program/48 checks、cache12 checksに限定する。監査自体は新PCM・実音声の実行ではない。

実行時sourceと今回適用先sourceを別欄に残す。Engine依存nativeやEngine.mm直接include rendererへ、旧「28点不変」や単なるDSP不変を自動転用しない。新旧binaryが異なる場合はそのまま異なると記録し、Engine非依存の閉包照合を適用根拠として示す。対象外の旧親runを丸ごと成功へ変えず、完了済みの対象子だけを接続する。

独立動的参照は旧Phase36/39/42由来のbb22efcbd27f999e8ffe85bbe3f03e20895be3f2系凍結素材、固定Exactは既存の固定凍結参照を使う。動的実行体SHAは`1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818`、固定実行体SHAは`de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。`results/phase62_e5_review/REFERENCE_VERIFIED.json`と保存された523参照ソースのGit blob/SHAを再照合し、変更後の製品DSPから参照を再生成しない。F01自身のRAWと境界式の検算は独立DSP oracleではなく、独立planner／DSP／Mapの既存比較を代替しない。

D07の同一owner履歴H≤1<512、下位planner512/513、D08のdescriptor距離d-c≤44<64・値コピー・64bit cycle照合・下位stale-cycle拒否は既存の完了項目として維持する。ID公開の同期以外に前提が変わっていないことを確認し、Loop上位から到達不能な上限状態を作る課題を再開しない。

## 判定と保存

F01と必要な影響回帰が完了した時点で、その範囲の局所完了を判定する。一般公開とMerodoa既定採用は別のNO-GOを維持し、allowExperimentalLoops等の公開・能力フラグを変更しない。観測されたseek worker期限超過の原因分離、FastLocal長尺の実採用mode、stereo Readyとcold/warm指標、開始/提示時計、物理loopback・試聴、実MerodoaのTCC/security scope/bookmarkと全owner join後解放は次作業の受入条件へ残す。

大きいPCM・WAV・実行体・全trace/logはGit管理外のbuildへ保存し、Git側には小さいreport、hash、manifest、復元/再実行recipeを残す。新規Git対象ファイルは50,000,000バイト未満。今回のstage・commit・push・PR・履歴書換え・証拠削除は行わない。
