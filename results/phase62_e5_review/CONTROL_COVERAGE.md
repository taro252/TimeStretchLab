# e5レビュー修正の制御契約と証拠範囲

局所全体判定は **PASS / GO（本書に限定した実験機能の検証範囲）**。個別試験の完走したPASSと、全必須回帰を含む最終判定を分ける。製品機能の公開条件、物理loopback、試聴、Merodoa実統合は別のゲートであり、本書では変更しない。

以下は2026-10-21の読取確認時点の記録である。実装の接続点は関数・型名で示し、各実行ソースは証拠の一覧SHAで識別する。後続のソースや試験変更後へ旧PASSを自動的に移さない。下表は最終の限定来歴証明と、オフライン完走・復旧後実機5群41program・正常RT8本の完走を反映している。

**証拠の識別**

基点 `B` は `/Users/taro252/Docker/TimeStretchLab/build/phase62_e5_review_20261021_01`。下表の相対保存先はすべてこの基点からのパスである。プログラム名の `{candidate,baseline}` は両Presetの2件を表す。

| 呼称 | 保存先・ソース一覧SHA | 確認済みの結果と限界 |
|---|---|---|
| R-v2 | [review_functional_v2/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/phase62_e5_review_20261021_01/review_functional_v2/SUMMARY.json)、`795dd66a101c68f6f0f3cbd994365b62bef29400271c76318355802011375a44` | 36/36program、202/202checks、全子PASS。後続ソースの最終結果として再表示しない。 |
| R-final-0e24 | [review_functional_final/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/phase62_e5_review_20261021_01/review_functional_final/SUMMARY.json)、`0e24cebb9c567d6a6d04caa4490af4a2512b3b90142393b7ba823dd4c8a13ee2` | 全36program終了、200/202checks。`partial_replace_candidate` と `partial_replace_baseline` は観測窓未捕捉、exit1・executed0でFAIL。その他34子PASS。全体INCOMPLETE。 |
| R-final-v2 / 最終再実行 | `review_functional_final_v2/`、BUILD06、`dfcd0562c0ddf4dad1b7a1c181895544f4ea119e995f2d2f7c993619fd9e8b54`。最終部分混合はBUILD07 `cefdb1294e89cb5280ad8f6df401eac59825212334e4110f958ca6f0d7c0199c` | 06の36program/202checksすべてPASS。07の部分混合6program/6checksも `partial_final_v3/` で全件PASS。他30program/196checksと成功native184は最終 `FINAL_REVIEW_CERTIFICATE_v2.json` の28実行体・依存一致証明で接続。実行時source欄は付け替えない。 |
| F-playing | [focused_final_v1/playing/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/phase62_e5_review_20261021_01/focused_final_v1/playing/SUMMARY.json)、795dd | 12/12program、74/74checks。直接close両Presetの6/6を含む。旧72/74の未完2件を変更せず、新runとして保持。 |
| F-control / F-cache | `focused_final_v1/control/SUMMARY.json` / `focused_final_v1/cache/SUMMARY.json`、親EXPECTEDの795dd来歴に接続 | 5program/42checks、12program/12checksが各PASS。 |
| F-API | `api_final_v2/SUMMARY.json`、795dd | 16/16PASS。`focused_final_v1/api` のwrong Pythonによる0/16・INCOMPLETEは保存し、成功へ付け替えない。 |
| F-remaining | [remaining_focused_v1/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/phase62_e5_review_20261021_01/remaining_focused_v1/SUMMARY.json)、795dd | Paused/Clear 12program/24checks、Race candidate/baseline各8checks、計14program/40checksがPASS。 |
| I-smoke | [invariant_smoke_v1/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/phase62_e5_review_20261021_01/invariant_smoke_v1/SUMMARY.json) | 下位history8、descriptor7のログとexit0を保存。単独summaryにはソース一覧SHA・実行体SHAがないため、最終ビルドへ結び付いたRelease/Debugゲートの代用にはしない。 |
| E-75 | [finish_evidence75_e0chu9st/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/phase62_e5_review_20261021_01/finish_evidence75_e0chu9st/SUMMARY.json)、0e24 | Python証拠検証75/75PASS、ソース不変、製品/音声/ビルド実行0。旧 `verify_evidence_1k250crp` の35件中29PASS・6FAILは保存。 |

F-control42＋F-cache12＋F-playing74＋F-API16＋F-remaining40＝184は、795dd来歴の成功した子の確認数である。`focused_final_v1` 親はAPI失敗を含んでINCOMPLETEのままであり、この184を親全体PASSや最終ソースの完走数へ読み替えない。

**接続点と検査した契約**

実装本体は [ProgressiveMacPlaybackEngine.mm](/Users/taro252/Docker/TimeStretchLab/src/platform/macos/ProgressiveMacPlaybackEngine.mm)、[Phase58RealtimePipeline.cpp](/Users/taro252/Docker/TimeStretchLab/src/prototype/Phase58RealtimePipeline.cpp)、[Phase58FixRealtimeWorker.cpp](/Users/taro252/Docker/TimeStretchLab/src/prototype/Phase58FixRealtimeWorker.cpp)。試験は公開要求ID、実session/epoch、実PCM観測を結び付ける。採用の保護のために未発生のcommit・outputStarted・最初のPCM時刻を作らない。

| 対象 | 実装上の接続点・条件 | 試験program / 主要check ID | 確認済み証拠・現在の扱い |
|---|---|---|---|
| A1 取消勝ち / Started勝ち | `setSpeedImpl()` の外部枠検査・受付後、DSP取消→native Requested取消CAS→再同期→`replaceUnstarted(...,retained)`。`SpeedReplacementDecision` は同期後/CAS前の通常制御点。Started/Doneが勝った旧IDを保持。 | `a1_cancel_{candidate,baseline}` / `a1_started_{candidate,baseline}`。`A1.Requested_decision_window_observed`、`A1.cancel_wins_old_Replaced_no_old_PCM` / `A1.Started_wins_old_Completed_actual_PCM`、`A1.latest_Completed_actual_PCM`、`A1.exact_IDs_and_terminal_types`。各6checks。 | R-v2、R-final-0e24の各子PASS。取消勝ちは旧ID Replacedかつ旧PCMなし、採用勝ちは旧ID Completed・実PCMあり、最新もCompleted。最終限定証明で来歴接続済み。 |
| A2 初回Bの必須供給保持 | `seekLoop()` の `retainInitialSupply` と `setSpeedImpl()` の `initialSupply`。KeepPosition初回で自己反復がない旧通常ownerには、第2版が初回Bへ供給するまで旧IDを保持。 | `a2_initial_supply_{candidate,baseline}`、全曲240ms・dspDone＋未消費Playing。`A2.Keep_no_self_repeat_old_ID_bound`、`A2.latest_retains_required_old_without_false_facts`、`A2.actual_B_old_Completed_and_latest_Completed`。各6checks。補助 `a2_clear_started_*` はClear取消にcallback Startedが勝つ場合の7checks。 | R-v2、R-final-0e24の各子PASS。初回Bの実採用と次の最新適用を確認。`a2_clear_started` は旧75 Completed、最新200はClear/EOFでPCMなしCancelled、旧履歴不変を確認。最終限定証明で来歴接続済み。 |
| B / D06 内部operation4096拒否のLoop統合 | 同一通常ownerで同値要求4096件を各Duplicate確定まで蓄積し、`requestNormalLoopReuse()` から同ownerのKeep自己反復へ接続。`seekLoop()` の局所typed `finalFailure` がLimitReachedをInternalLimitとしてcatchの外部Failedへ渡す。過去のBusyRetryで上書きしない。 | `b_internal4096_{candidate,baseline}`。`B.normal_Playing_same_owner_4096_Duplicate`、`B.all_internal_records_exact_and_no_Accepted_history`、`B.Keep_same_owner_self_repeat_Ready`、`B.external_Accepted_then_real_InternalLimit_Failed`、`B.old_PCM_history_and_preparation_retirement`、`B.exact_external_ID_and_final_cause`。各7checks。 | R-v2、R-final-0e24の各子PASS。内部4096全ID・同session、外部新規ID1件、旧PCM継続と新準備退役、所有者上限を照合。外部台帳4096やD07のplanner履歴512とは別。最終限定証明で来歴接続済み。 |
| D01 直接close後の全ID終端 | `Impl::~Impl()` が全worker join・最終retire後、メンバー破棄前に `FinalLoopSpeedAudit` を長寿命sinkへ値コピー。音声callbackから監査しない。 | F-playingの `limit_close_{candidate,baseline}`。`direct_close_quiesces_and_retires`、`post_close_owned_sink_exact_IDs_and_terminal_kinds`、`normal_supply_and_owner_cap` を含む各6checks。 | F-playing 74/74PASS。各 `limit_close_*/sink.jsonl`、`receipts.jsonl`、`pre_close_ledger.jsonl` を照合し、Completed/Replaced/Cancelled各1、全Accepted IDの一意一致、既完了履歴不変、join/退役/受取1回を確認。795ddの個別成立。最終限定証明で来歴接続済み。 |
| D02 実DSP Applying再検査→Requested→取消 | `repeatWithEngine()` のRequested→Applying CAS後に、版不一致のMapを実 `trySupplyBorrowedDynamicMap()` へ渡す。実拒否後Requestedへ戻り `ApplyingRejected`。取消・settled・再受付を通し、旧応答を新IDへ混入させない。 | `applying_cancel_{candidate,baseline}`。共通6IDは下記W。`real_window` で旧ID/session/Requestedを確認、注入消費・実proposal/rollbackもassert。 | R-v2、R-final-0e24の各子PASS。直接Requestedを設定する局所模型の成功を転用していない。最終限定証明で来歴接続済み。 |
| D03 実planner進行中の取消 | `transitionStep()` の `PlannerBeforePlan` / `PlannerProposal`。取消後の実plan結果処理・`confirmPlan(false)` とsettledを経て新IDを受付。cache旧A期限窓も `operationMutex` 内でID/Requestedを再検査してreason/CASする。 | `planner_cancel_*`、`proposal_cancel_*`、補助 `cache_old_new_*`。各共通6ID W。cacheは `old_new_transaction.json` に旧/新IDと期限判断IDを記録。 | R-v2、R-final-0e24の各子PASS。新Bのreason None・Requested、旧/新各Cancelled、最終履歴0、owner/resourcesを照合。最終限定証明で来歴接続済み。 |
| D04 Started部分混合で置換/Clear/Stop | 実callbackは試験観測有効時だけatomic `observedMixCursor` をコピー。通常側 `partialMixTestEvent()` がStartedかつ `0<cursor<N` を再確認し、Replace/Clear/Stopの実決定点へ接続。callback待機なし。 | `partial_{replace,clear,stop}_{candidate,baseline}`、各1ID `D04_{candidate,baseline}_{replace,clear,stop}`。実装置64/128frame、前の新旧PCM・部分cursor・通常側決定点を同時に要求。全取り逃し・timeoutを不合格にする。 | R-v2は6/6PASS。R-final-0e24はClear/Stop4件PASS、replace2件は「実Started部分混合を観測できない」でFAIL/0件。製品不具合確定とは区別するがD04全体PASSにはできない。callback停止なし即poll＋有限retry、Stop前故障検査、取り逃し理由保存を修正し、最終07の6件すべてが実Started部分窓とPCMを確認してPASS。旧窓未捕捉2件は保存する。 |
| D05 Workgroup参加失敗 | pipelineの `realtime->promote(testFail(WorkgroupJoin))` → worker `promote()` の参加成否を処理する箇所へEINVALを注入し `demote()` へ接続。昇格前throwとは別。 | `workgroup_{candidate,baseline}`、各共通7ID P。失敗sessionのclosed epochでjoinErrors=1、promotions=restores、joins=leaves、inactiveをassert。 | R-v2、R-final-0e24の各子PASS。旧Loop/PCM、失敗版退役、次要求回復を確認。OSが自然に失敗した実測や正常RT測定とは呼ばない。最終限定証明で来歴接続済み。 |
| D07 Loop履歴512 | 新固定Map/planner入口、proposalの一件制限とrollback、commit後terminal Bまでの供給と所有者終了、次固定ownerの履歴0を接続。証明の対象は実装済みLoop制御の同一owner。 | `phase62_history_invariant` / `phase62_history_invariant_tests`。`D07_PLANNER_FIXED_START`、`D07_PLANNER_ROLLBACK_640`、`D07_PLANNER_PUBLICATION_ROLLBACK`、`D07_PLANNER_HISTORY_LIMIT_512` の各 `_candidate` / `_baseline`、計8ID。 | 下位I-smokeはexit0/8IDログ。静的根拠は後述の不変条件による閉鎖。実Loopで512件を枯渇させたPASSではない。最終Release/Debug各20CTest、下位8ID、および独立動的640/境界872等の維持回帰へ接続済み。限定したLoop履歴の不変条件はPASS。復旧後の指定正常RT8本はPASS。実Loopで512件を枯渇させた結果へ読み替えない。 |
| D08 descriptor64 | 製品 `loopPcmDescriptor()` と下位試験は同じ `LoopPcmDescriptorRing` / `readLoopPcmDescriptor()` / `ValueMailbox` を使用。64bit cycle完全一致、戻り値は値コピー。 | `phase62_descriptor_invariant` / `phase62_descriptor_invariant_tests`。`D08.empty_unpublished`、`D08.slot_wrap_identity`、`D08.forced_stale_cycle_rejected`、`D08.descriptor_value_lifetime`、`D08.two_source_independence`、`D08.capacity_bound`、`D08.full_width_cycle_identity`、計7ID。 | 下位I-smokeはexit0/7IDログ。安全距離の不変条件と強制古cycle拒否を分離。正常4100周を異常追越し再現へ転用しない。最終Release/Debug各20CTest、下位7ID、および最短512/空R0/old-new B跨ぎを含む境界872へ接続済み。限定したring距離/古cycle拒否はPASS。今回の正常4100周は両PresetでPASSしたが、異常追越しの再現へ読み替えない。 |
| D09 checkpoint permit拒否 | `InputLease::reserveCheckpoint()` の実permit予約位置で一度だけ拒否。旧通常sessionの準備拒否と、次版準備sessionの拒否を別に設定。RAIIによりpermit返却。 | `checkpoint_{candidate,baseline}` 各P7ID、および `a2_checkpoint_supply_*` 各7ID。後者は `D09.real_CheckpointPermit_failure_and_initial_ID_bound`、`D09.required_old_supply_retained_without_false_facts`、`D09.actual_B_old_Completed_and_latest_Completed`、`D09.checkpoint_budget_and_later_preparation_recovery` 等。 | R-v2、R-final-0e24の各子PASS。1秒入力、旧producer dspDone=falseからnormalPreparation=LimitReachedを実確認。自己反復なしの初回B必須供給・旧/最新Completed、checkpoint peak≤2、後続回復を確認。最終限定証明で来歴接続済み。 |
| D10 次版の予約予算拒否 | `reserveEpoch()` の二つのshareからなる有限予約を、新owner構築前に拒否。既存24MiB追加枠・1GiB予約予算を増やさず、構築例外もRAIIで返却。厳密なRSS上限の証明とは区別。 | `reservation_{candidate,baseline}`、各P7ID。`actual_failure_branch`、`old_PCM_or_paused_C_preserved`、`failed_preparation_retired` 等。 | R-v2、R-final-0e24の各子PASS。この拒否では次ownerは生成されず、alive=1・RetiringPreparationなしを確認。存在しないworkerの退役を成功条件にしない。旧Loop継続・次要求回復あり。最終限定証明で来歴接続済み。 |
| D11 次版期限/準備失敗 | `seekLoop()` の `NextPreparationDeadline` から実steady_clock期限検査。worker開始後の期限をReady待ち途中と公開準備開始時に検査。失敗IDのtyped原因はPreparationFailed、旧出力またはPausedのCを保持。 | `deadline_*` / `paused_deadline_*`、各P7ID。prepareTimeout2000msに対し通常制御を2100ms遅らせ、実失敗・旧PCM/C不変・退役中Play拒否・その後125要求Completedを確認。 | R-v2、R-final-0e24の各子PASS。失敗版RetiringPreparation後はalive=1、失敗IDは回復後も不変。機能故障注入であり正常RT期限の合格に加算しない。最終限定証明で来歴接続済み。 |

W（worker transaction）の必須6IDは `real_window`、`cancel_old`、`accept_new`、`old_completion_isolated`、`history_rollback`、`owners_and_resources`。P（preparation fault）の必須7IDは `stable_old_loop`、`actual_failure_branch`、`external_final_cause`、`old_PCM_or_paused_C_preserved`、`failed_preparation_retired`、`subsequent_request_recovers`、`normal_supply_and_owner_cap`。全IDと件数を各子のEXPECTED/SUMMARY/checks.jsonlで照合する。

試験コードの対応は [Phase62AdoptionReviewNative.cpp](/Users/taro252/Docker/TimeStretchLab/tests/Phase62AdoptionReviewNative.cpp)、[Phase62PlayingLedgerNative.cpp](/Users/taro252/Docker/TimeStretchLab/tests/Phase62PlayingLedgerNative.cpp)、[Phase62WorkerTransactionTests.cpp](/Users/taro252/Docker/TimeStretchLab/tests/Phase62WorkerTransactionTests.cpp)、[Phase62PartialMixNative.cpp](/Users/taro252/Docker/TimeStretchLab/tests/Phase62PartialMixNative.cpp)、[Phase62PreparationFaultNative.cpp](/Users/taro252/Docker/TimeStretchLab/tests/Phase62PreparationFaultNative.cpp)。同じinclude/helperを再利用する場合も、各modeの入口と実assertの範囲を上表から広げない。

**D07/D08を不変条件で閉じる範囲**

- D07の証明は [PHASE62_HISTORY_INVARIANT.md](/Users/taro252/Docker/TimeStretchLab/docs/PHASE62_HISTORY_INVARIANT.md)。ReturnToA、KeepPosition、Loop内seek、Ready/Paused速度変更、次固定版の各入口は固定Map・空の履歴で開始する。一件の未応答proposalだけが一時H=1となり、取消/再検査拒否はrollbackでH=0。採用後H=1の同ownerはterminal Bで終了し、次ownerはH=0となる。この範囲で `H≤1<512`。通常再生の任意の連続速度変更や、独自順序の下位APIクライアントへ一般化しない。下位の単一plannerで512件確定・513件目拒否を別途検査し、640件の別owner遷移を同owner512蓄積と数えない。
- D08の証明は [PHASE62_DESCRIPTOR_INVARIANT.md](/Users/taro252/Docker/TimeStretchLab/docs/PHASE62_DESCRIPTOR_INVARIANT.md)。FIFO16384＋未公開pending2048＋callback最大4096＝22528。最古必要cycle cの正の残量を1以上、完全周期を512以上とすれば `1+(d-c-1)×512≤22528`、従って `d-c≤44<64`。44は安全側上限であり実測最大ではない。初回C→Bが512未満でも残量1で成立し、R0=0では必要cycle自体が1から始まる。B/次descriptorの先行公開を累積座標で数え、terminal dynamicは周期開始を変えずそのBでproducer終了する。old/new sourceのringとconsumerは各独立に44以下であり距離を合算しない。lookup結果は値コピーで、callbackを跨いで保持するのはpreviousTail等の値だけである。
- 下位D08の `forced_stale_cycle_rejected` は同slotへc+64を強制公開した古cycle拒否試験。正常製品経路でc+64の異常追越しが発生した証拠ではない。実rendererの短い初回、空R0、B_minus_1、phase_first、最短512、old/newのB跨ぎは `Phase62DynamicBoundaryTests.mm --period512 --old-near-b` 等の維持回帰で別途確認する。
- 最終的な閉鎖には、静的証明、最終source/binaryへ束縛した下位全ID完走、実Loop/renderer維持回帰の三つが必要。証明文書やI-smokeだけから最終PASSを作らない。

**正常RT・PCM・資源の範囲**

通常側ゲート、planner/DSP拒否、Workgroup戻り値、permit/予約/期限注入は制御契約を確認する機能試験である。音声callbackは止めないが、これだけで正常負荷の実時間期限（RT）を承認したとは扱わない。各子が `RT_deadline_approval=NOT_ASSESSED` とする範囲を維持する。

native試験の `normal_supply_heap_owner_audit` / `normal_supply_and_owner_cap` は、実PCM不足・underrun・拒否書込み・failure padding・出力影響、RAW/混合演算誤差、NaN/Inf、callback new/malloc/free、実行owner peak≤2・停止後0を個別にassertする。独立DSP参照比較を未実施の子では、独立一致を主張しない。callbackのmutex/join/I/O/planner/FFTはコード監査と有限構造の確認であり、それぞれ専用検出器で実測0を得たとは呼ばない。

**最終の検証台帳**

| 必須群 | 今回の結果と範囲 |
|---|---|
| A1/A2/B・D02〜D06/D09〜D11・cache旧A→新B | **36program/202checks PASS**。最終部分混合6件をBUILD07で再実行。他30件196checksはBUILD06のdfcdソース、28実行体と依存不変の証明で限定接続。実行時sourceを最終cefへ付け替えない。 |
| D01・外部台帳・Playing・API・cache・Race・Paused/Clear | **184checks PASS**。795ddの成功子だけを実行体/依存/driver/import一致で接続。Playing12program/74checks、direct closeはCompleted/Replaced/Cancelled各1と全ID一意一致を要求。親focused/API初回失敗は対象外。 |
| 決定的Release/Debug、D07/D08下位 | **各20/20 PASS、6stage完走**。JUnit/必須ID/実行体/環境/ソース不変を記録。既存18件を保持。履歴8ID、descriptor7IDも両構成で確認。 |
| 共有Phase58/workerの独立DSP・固定回帰 | **選択したoffline9群PASS**。動的640、重点20、形式46＋8、Exact896、Golden25、固定有限322/reuse322。全161値を両Presetで実適用。Goldenも今回再実行し、旧証拠の候補監査を実施数に加算しない。 |
| 境界・handoff | **境界872checks PASS**（184＋368＋128＋192）と独立handoff6program PASS。部分初回/R0/最短512/最大callback4096等を維持。872へhandoff6を重複加算しない。 |
| 最終native行列 | **41/41program PASS**、全5群完走。14＋8＋4＋2＋13。復旧前native_final/v2の同じ先頭1本が各0/3で失敗した履歴は保存。復旧後は同じsource/binary/条件の新run native_recovered_01で実施。 |
| 正常RT / 長尺 / 4100周 | **8/8 PASS**。上の41本の内数。A=0/30/270秒×両Preset、短周期4100周×両Preset。今回のmissing/padding・callback確保/解放・callback/worker期限超過0。装置72/48kHz/buffer512復元を外側guardでも確認。旧8条件の成功数を転記していない。 |
| 証拠集計 | **75/75単体回帰PASS**。bool/float/不正ID/矛盾結果等を拒否。製品の音声75件ではない。最終manifestはPASS、local_overall_go=true。公開・Merodoa既定採用false。 |

最終の各単位と原本SHAはREPORT、GROUP_RESULTS、REVIEW_CERTIFICATE、DETERMINISTIC_CERTIFICATE、NATIVE_BLOCKERを参照する。offline先頭4群の原SUMMARYには選択外の明示NOT_RUNと全体PASS=falseがある。選択した群の完走だけを採用し、独立PCM・制御・seek・資源/RT・公開課題の全体成功へ拡張しない。

各群のPASS確定には、実行前EXPECTED、終了コード0、timeout/中断なし、完了marker、必須IDの一意な完全一致、期待/実施件数、入力・参照・driver・実行体SHA、およびビルド/実行ソースの対応が必要である。未実施・途中・窓未捕捉はPASSへ変換しない。

## 最終再実行の追加確定

`FINAL_REVIEW_CERTIFICATE_v2.json` は実行体29点中、部分混合試験を除く28点のBUILD04/06/07一致、製品・依存コード・driver/import不変を再確認した。実行時ソース795ddの成功native184、およびBUILD06のreview30program/196checksを限定保持し、BUILD07の部分混合6本と対応する全36program/202checksを確定した。旧失敗run/親の状態は変更しない。旧証明のall_30というキー名の件数誤記は実一覧29点に訂正して別記録とする。

最終ソースcefdb1でRelease/Debug各20CTest、configure/build/ctest全6stageがPASS。history8IDとdescriptor7IDは両構成の実行体・ログ・JUnit・必須IDへ接続済み。選択したoffline9群は完了PASS。復旧前の実機開始失敗と当時のINCOMPLETE判定はhistoryへ保存した。ユーザーの装置復旧後、native_recovered_01で全41programと正常RT8本・装置復元がPASSし、今回の局所ゲートを閉じた。


旧cacheの当時記録不足は上書きせず、source72b8319・binary879ed2eで事前固定した新しい隔離比較版を追加した。関連104依存を旧保存内容へ一致させ、両Presetで旧Aが新BをRejectedにする不具合を2/2再現。子のexit1/FAILを保持し、比較版の再現成功を修正版の成功や独立DSP oracleへ数えない。CACHE_BASELINE_REPROに当時cache04との区別を記録する。


## 装置復旧後の最終閉鎖

USER_DEVICE_RECOVERYの申告後に、native_recovered_01を1担当で直列実行した。ソースcefdb129…、Release29実行体、native使用Release8＋Debug1、凍結参照・元条件・必須41ID・第1群入力bytes/SHAの一致をRECOVERY_PROVENANCEで確認する。SOURCE/BUILD/strict/offlineは変更せず、無関係な再実行は行っていない。全41programと指定正常RT8本はPASS、親終了0・timeoutなし・全ID・最終統計・装置復元を確認した。旧native_final/v2/final_pipelineは書き換えない。

seek Candidate通常機能試験は21/21PASSだがworker期限超過1件、callback期限0、RT承認NOT_ASSESSED。旧fa保存runにも同じ観測があり、SUMMARYは全byte同一。原因や発生局面・一般無退行の証明ではなく、正常RT8本の全0と分けてFUNCTIONAL_DEADLINE_OBSERVATIONへ記録する。41本すべて期限超過0とは言わない。要求Interactive/FastLocalが実Exactへ切り替わる試験も、採用Interactive/FastLocal一般対応へ拡張しない。

公開初期値4つとpublicSeekApproved=false、物理loopback・試聴・Merodoa/TCC実統合等の別公開ゲートは維持する。過去の文書・小証拠55ファイルはhistory/BEFORE_AUDIO_RECOVERYのSHAとB/metadata_before_audio_recovery_01/filesで復元できる。
