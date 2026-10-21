# F01の制御契約と検証範囲

対象はmain@b0352c6f4c22f100f161297769b26561dc07701bからの未コミット差分。基準のD01〜D11を再開せず、F01と実依存のある回帰を検査する。判定と最終件数は [REPORT](REPORT.md)、機械可読の確定結果は [MANIFEST](MANIFEST.json) を参照する。

保存基点Bは `/Users/taro252/Docker/TimeStretchLab/build/phase62_f01_20261021_01`。大きいRAW、trace、全ログ、実行体はBに保持し、過去runを上書きしない。

## F01の因果と同期

|区間|観測・契約|実装／証拠|
|---|---|---|
|job選択前|通常APIで要求AをAccepted。KeepPosition初回、Playing、通常ownerは自己反復なし|`LoopJobDispatch`、`f01_dsp_done` / `f01_checkpoint`、両Preset|
|次版構築後、start前|最初のmutex解放直後、通常workerだけを有限待機。callbackを止めずBを通常APIでAccepted|`LoopJobSelected`、各 `F01_selected_window.json`|
|旧比較版|active IDはまだ0。BがAをReplacedにし、その後Aの版が実際に初回Bへ供給|b035へ観測hookだけを加えたEngineと共通の新試験。`baseline_01/EXPECTED.json`に差分・source、BUILDにbinary SHA。純未改変binary／独立DSP oracleとは呼ばない|
|修正版|next有効構築と保護ID・非終端Preparing/version/timeを、最初のmutex内で同時公開|`seekLoop()`共有の`if(next)`。Loop／Loop内seek／stoppedが同じ接続点。待機・start・joinはmutex外|
|可聴前|Aを保護してもcommit、outputStarted、first PCM、adoptionPendingを偽造しない|A/B両方の選択窓記録とassert|
|初回B実採用|Aのsession/epoch、最初の非空RAW区間、callback座標と台帳IDが一致しCompleted|各 `F01_actual_adoption.json`。旧比較もここまで到達後に不一致で失敗させる|
|後続B|Bも実PCMを伴いCompleted。Aの確定済み履歴は全フィールド不変|`F01.latest_B_Completed_and_A_past_immutable`、全Accepted IDの一意完全一致|

旧不具合の再現成功は、子FAIL／exit1／7件中4件までPASSの後に、Aの実採用との不一致で失敗したことを意味する。期限超過・窓未捕捉・装置停止では成功にしない。比較親のPASSを製品の正常PASSへ加算しない。

## 追加試験の全ID集合

主試験は2原因×両Preset、4 program×7 checks。

1. `F01.normal_no_self_repeat_condition`
2. `F01.selected_job_then_latest_B_window`
3. `F01.actual_initial_B_session_epoch_PCM`
4. `F01.latest_B_Completed_and_A_past_immutable`
5. `F01.required_A_protected_and_Completed`
6. `F01.exact_IDs_and_terminal_types`
7. `normal_supply_heap_owner_audit`

補助試験はStop／Clear／準備失敗×両Preset、6 program×6 checks。

1. `F01_CANCEL.normal_no_self_repeat_and_selected_A`
2. `F01_CANCEL.latest_B_accepted_no_false_facts`
3. `F01_CANCEL.action_effective_no_A_or_B_PCM`
4. `F01_CANCEL.prepared_owner_joined_and_followup_recovers`
5. `F01_CANCEL.direct_close_exact_IDs_reasoned_terminal`
6. `normal_supply_heap_owner_audit`

補助試験は選択窓のA/Bに実PCMなしを要求する。Stop/Clearは各Cancelled、実Workgroup参加失敗はA Failed・B Cancelled。その後の新prepare、入力世代・Loopの更新、要求CのResume前ReadyForResume、明示Play、実適用Completedと直接close後の全3 ID終端を確認する。CancelledをCompletedへ戻す処理を追加しない。

`F01_action_cleanup.json`、`receipts.jsonl`、`F01_after_action_ledger.jsonl`、`final_close_ledger.jsonl`、`checks.jsonl`で理由と所有者退役を照合する。通常側sinkはEngine破棄完了まで生存し、参照を値コピーする。

## 品質・資源・旧契約

F01の全10本は既存のPCM列・境界検算、非有限値、unexpected missing/padding、callback new/malloc/free、所有者退役、最大2実行DSP／最大2checkpointを維持する。`Phase62PcmAudit`は製品RAWからの加工検算であり、独立DSP参照ではない。有限ゲートを通した試験の期限観測は正常RT承認へ流用しない。

|既存の完了項目|今回の対応|
|---|---|
|A1／A2／D09／内部4096、直接close D01|変更後Engineでadoption・Playing・全ID台帳を再実行。採用勝ちと取消勝ちを保持|
|D02/D03／cache旧A→新B|共有workerとdriverの実依存・ビルド条件・入力・旧実行sourceを照合して限定再利用|
|D04実Started部分混合|変更後EngineのReplace/Clear/Stopを両Presetで再実行。観測窓未捕捉をPASSにしない|
|D05/D06、予約・期限・停止中失敗・再開拒否|変更後Engineでfault群を再実行。意図した故障と正常供給の統計を分離|
|D07履歴／D08 descriptor|共有実装無変更、実LoopのH≤1<512、必要距離d-c≤44<64を維持。下位512/513・stale-cycleとRelease/Debug各20CTestを再実行。上位から到達不能な枯渇を再現したとは呼ばない|
|D10/D11、Paused/Clear/Race／通常API独立PCM|変更後Engineの該当群と正常nativeを再実行|
|共有DSP／plannerの全161速度、固定Exact|実依存・source・driver・入力・凍結参照のSHAとコンパイル条件が不変の群だけ限定再利用。新規実施数へ移さない|
|境界renderer|Engine.mm直接includeがあるため新binaryで872 checksと独立handoff6 programを再実行|

再利用の実行時sourceと今回の適用先sourceは [REUSE_AUDIT](REUSE_AUDIT.json) に分ける。旧「28点不変」の証明を新Engineへ転用しない。新実行の期待ID・exit・timeout・完了marker・最終統計は各EXPECTED/SUMMARYに保存する。

一般公開、Merodoa既定採用、物理loopback、人の試聴は本書の局所判定と別である。各capabilityの現行falseを維持し、次の公開課題と具体的完了条件はREPORTへ引き継ぐ。
