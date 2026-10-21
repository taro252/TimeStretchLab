# 制御契約の検証範囲

最終実装ソース一覧SHAは `fa2b6f4fea83e06b4d31433478ae01cae5d98c3465267c990625d4a30a171c8a`。ここでは試験名だけから成功範囲を広げず、実assertの範囲を示す。完走したrunはSUMMARY、必須ID集合、ソース・binaryの対応を再検査して確定した。実行予定・途中結果をPASSとして扱わない。

| 最終ソース向けrun | 保存先 | 本文更新時点の状態 |
|---|---|---|
| 台帳・Playing・API・cache等の局所検証 | `build/phase62_finish_20261021/focused_final_v3/` | 全6群完走。台帳42/cache12/API16/Race各8 PASS、Playing72/74 INCOMPLETE |
| Paused／初回Clear | `build/phase62_finish_20261021/paused_clear_final_v4/` | 12program / 24checks PASS |
| 既存native回帰 | `build/phase62_finish_20261021/extended_native_v3/` | 全5群PASS。14+8+4+2+13 program完走、正常RT8ゲートPASS |

今回のソース更新では、再開意思があるPaused Clearの完了通知を、音声再開の開始API成功後へ移した。PausedClearNativeの`committed_preparing`には、`clearPending=false`を観測した時点でPlayingかつ`resumePending=false`であることのassertを追加した。この追加条件を含め、Paused Clearの12program / 24checksがPASSした。

| 契約 | 試験コードで検査した具体的条件 |
|---|---|
| 未commit連打・全ID | Playingの75_cancelled_before_commit / 100_completed_noop / 40_replaced_before_commit / 200_completed_actual_PCM / all_four_IDs_terminal。全receipt集合と終端集合の一致 |
| commit後の必要版保持 | 75_committed_before_B / required_fixed75_B_and_PCM / 75_and_200_completed / past_immutable_all_IDs_terminal。実Bと固定75先頭RAW、次200の適用 |
| Clearと速度移管 | 100_transferred_to_Clear_before_B / Clear_rejects_speed_with_reason / Clear_normal_continuation_no_extra_cycle / latest100_Clear_PCM_all_IDs_terminal_past_immutable |
| 初回採用前／開始後Clear | initial_return_clearは未開始IDのCancelled。initial_started_clearはStarted **またはDone** 後のClear継続とCompleted |
| Paused新準備とClear | committed_preparing / ready / started_no_pcm。停止C・周回・PCM量不変、破棄専用監査、移管先Ready/Completed。committed_preparingでは再開意思付きClearのclearPending=false時にPlayingかつresumePending=falseも確認する。started_no_pcmは開始API成功であり音響時刻ではない |
| Clearを手動seekが置換 | manual_seek。元速度IDは新seek IDを理由にCancelled、新C、古いLoopの復活なし |
| 準備中Resume・意思取消・100→75→100 | PausedSpeedLoopのpreparing_resume_latest_once / preparing_resume_cancelled_by_pause / latest_100_75_100_preparing_ready_duplicate |
| Resume前Ready・複数周期C | ready_without_resume_identity_discard / ready_after_cycles_cumulative_fifo_audit |
| 開始済み履歴 | LedgerNative started_history_immutable。旧state/outputStarted/readyNs/session不変と外部ID Completed |
| 上限・拒否の副作用なし | LedgerNative limit_before_side_effects_duplicate_and_repause。実外部4096境界、試験用外部6/停止中6。Playing limit_rejection_preserves_latest_and_PCM / duplicate_keeps_ID_at_limit |
| Stop・別内容入力・古い完了 | Stop_then_different_input_no_stale_revival。PausedSpeedLoop stale_preparation_stop/input/device/close。通常worker解放後の音声・Loop・再開意思を確認 |
| 正常供給・所有者・heap | Playing/PausedClear normal_supply_and_owner_cap。missing/padding/rejected PCM、RAW加工誤差、NaN/Inf、callback new/malloc/freeは0。実行owner peak≤2、停止後0 |

旧ソース `958f402ad625d1a9e5c38e210f6afb8c44589dae327f783bb1756051f20fedf2` の `build/phase62_finish_20261021/focused_final_v1/playing/` では追加Playingが72/74チェックだった。これは旧runの記録であり、最終ソースの実施件数へ転用しない。直接closeの2件は所有者0・音声静止を確認したが、破棄後に公開台帳を照会できずINCOMPLETEだった。最終runでもこの観測上の限界は残る。代わりにStopの結果をcloseの全ID結果へ転記しない。

既存Native --faultsの13件は公開ゲート1件と両Presetのreservation_budget_failure、ready_a_replace_reject_clear、before_workgroup_failure、before_publication_failure、route_safe_stop_and_explicit_replay、input_path_lossである。最終binaryでの実行結果は別台帳を参照する。初期prepare予算拒否を動的準備の予約失敗と呼ばない。

## 残る必須の証拠

| 対象 | 判定・不足の理由 |
|---|---|
| 直接close後の全受付ID終端 | INCOMPLETE、2件。破棄後照会APIがない。通常側の終端監査の受取手段が必要 |
| 実DSP Applying→Requestedと取消 | NOT_RUN。FixSafetyは局所模型でRequestedを直接設定する。実DSP再検査の戻りと公開API取消の統合注入が未整備 |
| 実DSP Requested/planner進行中の取消 | INCOMPLETE。SwitchPublishedゲートはofferDynamicより前であり、内部plannerの状態を確定していない |
| Started部分混合で外部ID付き置換/Clear/Stop | INCOMPLETE。SwitchStartedOrDoneはDoneも許容。オフライン実rendererのcursor1/64のPause/Stopは別証拠。nativeの該当窓と外部IDを同時に確定する観測が不足 |
| Workgroup実参加失敗 | NOT_RUN。before_workgroup_failureとpromotionFailureOnAttemptForTestは昇格前throwであり、参加API自体の失敗注入ではない |
| 内部operation4096拒否のLoop統合 | INCOMPLETE。Phase59Controlは下位通常pipelineの実4096上限を検査するが、Loopへの理由伝播・旧PCM保持は別 |
| 動的履歴512到達 | NOT_RUN。640遷移は単一ownerで512履歴を蓄積する試験ではない |
| descriptor64の異常追越し・古いcycle | NOT_RUN。正常な多数周回・環状再利用とは区別。異常を作る注入が未整備 |
| checkpoint予約失敗と旧PCM維持 | NOT_RUN。正常時の保存点数peak≤2を、予約失敗時の動作へ読み替えない |
| 動的変更中の予約予算拒否 | NOT_RUN。初期prepare予算1の拒否だけでは不足 |
| 次版準備の期限切れ／失敗から旧Loop維持 | INCOMPLETE。遅延中の供給は確認したが、失敗・期限切れを最新外部IDの結果まで結ぶ統合故障試験が不足 |
| callback禁止操作の個別動的検出 | heapは実測。mutex/join/I/O/planner/FFTはコード監査・有界構造であり、個別検出器の実測0とは呼ばない |

これらは環境不足を理由にBLOCKEDへしたものではなく、必要な試験・観測が未整備の残件である。局所全体GOとcurrentCycleSpeedChangesのtrue化は行わない。物理loopback・試聴・Merodoa実統合は別の公開ゲートであり、この表の不足の代替にはならない。

直前source562のfocused/API/rendererは完走したが、通常Paused故障注入で退役中Playの誤受付が見つかった。再開禁止の判定順を修正し、上記faのrunで再実行し、通常Paused全84制御チェックがPASSした。過去結果は履歴として保持する。

通常Pausedの追加failure試験は、Failed公開後の失敗版退役中にもPlayを拒否しReady・再開意思なしを保つことを検査する。通常workerゲートはmutex外で、callbackは止めない。ゲートには15秒の自動解放があり、今回の制御program4本は全体が15秒未満で完走した。極端な15秒以上の制御停止や失敗後の再要求/seek復旧、音響出力・参加API自体の失敗まで、この追加assertで検査したとは呼ばない。
