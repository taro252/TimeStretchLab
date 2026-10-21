# Phase62 D07: Loopの動的履歴512を不変条件で閉鎖する

レビュー開始点は `e5dc91675723b7163b10cc3ea2323710033caeaa`。D07の対応先は `results/phase62_finish/CONTROL_COVERAGE.md` の「動的履歴512到達」である。この文書は同一の実行所有者（DSPの処理状態、FIFO、plannerを持つ `RealtimePipeline`）に蓄積する履歴を扱う。外部Loop速度台帳4096件、内部operation台帳4096件、独立した所有者をまたぐ速度変更回数とは区別する。

判定方法は **不変条件による閉鎖**。Loopで512件を実際に枯渇させたPASSではない。下位plannerには単一plannerの実512件と513件目の拒否試験を別途用意する。実行済みかどうかは今回runの必須ID集合・完了marker・来歴で決め、この文書の静的証明だけを試験実行のPASSへ置き換えない。

## 成立範囲と結論

対象は `ProgressiveMacPlaybackEngine` の実装済みLoop制御から到達する経路である。`ReturnToA`、全曲 `KeepPosition`、Loop中のシーク、停止中の速度変更、新しい範囲による再設定、速度変更後の次固定版を含む。下位 `RealtimePipeline` APIを独自順序で組み合わせる任意のクライアントや、通常再生中の連続速度変更には到達不能を一般化しない。

この範囲では、各Loop所有者のplanner履歴数 `H` は次を満たす。

- 入口の固定Mapでは `H=0`。速度・密度（DSP処理の入力間隔）の変更履歴も空。
- 未確定proposal（DSPへ採用を提案するMap）は一つだけで、一時的に `H=1` になり得る。
- proposalの取消・DSP再検査不採用は `confirmPlan(false)` で `H=0`、以前のMap、末尾速度、密度履歴へ戻る。応答前のproposalに次のplanを重ねられない。
- DSP採用後は `H=1`。所有者は確定したterminal B（この所有者が最後に出す周期末尾）で終了し、次の速度変更を同じ所有者へ確定しない。
- 固定B延期は `FixedBoundaryCommitted` となり、動的proposalを確定しない。未応答の一時proposalがあれば応答・最終joinでrollbackされ、最終的な `H=0` を保つ。

したがってLoop所有者では、未確定proposalを含めても `H<=1<512`。640回の独立遷移をこの主張の根拠にしない。

## 全入口の確認

位置指定は入力座標であり、Map内の出力座標やFIFOの累積位置とは別である。以下の関数名は行番号変動後も確認できる根拠の接続点である。

| 入口 | 実装経路・拒否条件 | 履歴0を確保する根拠 |
|---|---|---|
| ReturnToA初回、別Loop範囲への再設定 | `requestLoopRange()` → `seekLoop()` の `pendingLoop` → `createLoopSeek(A,B,speed)` → `enableLoopReuse(A)` | `createSeek()` は入力lease（固定入力・確定解析）だけを共有し、新しい `Impl` を作る。`createLoopSeek()` はplannerをいったん破棄し、`enableLoopReuse()` が新plannerを作る。`seekAnalysis()` が指定速度の固定Mapを構築する。親の動的Mapやaccepted履歴はコピーしない。Playingの採用確定済み境界は範囲変更を先に拒否する。 |
| 全曲KeepPositionの現在所有者 | `requestLoopRange()` のKeepPosition検査 → `fixedOutputFrameForInput(EOF)` → `requestNormalLoopReuse()` → `prepareNormalLoop()` → `synthesize()` のruntime接続 | `fixedOutputFrameForInput()` は内部operationに `acceptance==Accepted` が一つでもあれば拒否する。確定した同値 `Duplicate` は履歴を作らない。`prepareNormalLoop()` は最終かつ `hasTransitions==false` の採用Mapだけを使用し、`makeFixedLoopOriginCheckpoint()` はさらに `modes.empty()` と固定Map同一性を検査する。producerは自身のMap版と準備Map版が一致する場合だけ接続する。 |
| KeepPositionの初回B供給用第2版 | `seekLoop()` の `loopKeep&&loopInitial` でも `createLoopSeek()` → `enableLoopReuse()` | 通常所有者の自己反復準備が失敗／未完了でも、初回Bに必要な第2版は新しい固定所有者。必要版保持や後続要求の扱いで親の動的履歴は継承しない。 |
| PlayingのLoop速度変更の次固定版 | `seekLoop()` の `pendingLoop` → 新しい `createLoopSeek()` → `enableLoopReuse()` | 次版は履歴0。次版Ready後にのみ、現在所有者へ `requestLoopTransition()` を出す。現在所有者と次版の履歴を合算しない。 |
| Loop内の明示シーク | `seekLoop()` の `pendingSeek`、`loopLive()` 分岐 → `createLoopSeek(requestedInputFrame,B,speed)` → `enableLoopReuse(A)` | 方式は固定Exactへそろえ、新しいplannerを使用する。途中位置CからBまでの初回部分区間も、A→Bの固定Mapと同じ履歴0で始まる。短い／空の初回出力区間は履歴を追加しない。 |
| Ready/PausedのLoop速度変更 | `seekLoop()` の `pendingStopped` → `createLoopSeek(resumeInputFrame,B,speed)` → `enableLoopReuse(A)` | 停止位置Cを保持した新しい固定Exact所有者であり、旧所有者の動的履歴はコピーしない。開始せずReadyForResumeになっても履歴0。 |
| Standard schedulingの固定Loop | `enableLoopReuse()` はAudioWorkgroup構成の場合だけ動的plannerを作る | 動的変更能力を持たない固定経路では `H=0`。AudioWorkgroup構成の証明を、別構成で実行した統合試験へ読み替えない。 |

新しい所有者の初期化根拠は `Phase58RealtimePipeline.cpp` の `Impl` コンストラクタ、`createSeek()`、`createLoopSeek()`、`enableLoopReuse()`、`seekAnalysis()`。planner側は `Phase59ProgressiveTransition.cpp` のコンストラクタで `accepted_`、`plans_`、`modes_` が空、`publish()` の `hasTransitions=!accepted_.empty()`、`outputFrames` の固定長分岐で確認する。

保存点を使う場合も例外にはならない。`Phase57ProgressiveSynthesis.cpp` の `cloneFixedCheckpoint()`、`makeFixedLoopOriginCheckpoint()`、`restoreFixedLoopCheckpoint()`、`captureFixedLoopCheckpoint()` は動的Mapや密度履歴を拒否する。`trySupplyBorrowedDynamicMap()` のcheckpoint再結合も最終固定Mapと空modesの同一性を要求する。処理済みDSPを動的履歴付きの保存点として再利用する経路はない。

## proposal取消と再受付

`ProgressiveTransitionPlanner::plan()` は、proposalを作る前に `rollbackTimeline_` の有無を検査する。存在すれば次のplanを例外で拒否する。適用可能proposalでは旧timeline、旧view、旧tail、旧modes長を退避し、accepted履歴を一つ追加する。`confirmPlan(false)` は全てを復元し、accepted/plansの最後の一つを削除する。Map公開の確保失敗も同じrollbackを通る。

実pipelineでの接続は `transitionStep()` にある。`pendingMap` をDSPへ渡し、同じ公開tagの応答を待ってから `planner.confirmPlan(accepted)` を呼ぶ。`Requested/Rejected→Cancelled` の取消が先に勝った場合、DSPの `Requested→Applying` は成功しないためそのproposalは採用されない。実DSP再検査で `Applying→Requested` に戻った場合も応答の `accepted=false` に従ってrollbackし、再計画はその後で行う。取消後の再受付は `loopTransitionSettled` を要求するので、未応答proposalへ新要求を重ねない。

取消・失敗・stopとplanner処理が重なる場合、`transitionStep()` の取消後plan結果処理、および全worker join後の `finalizeTransition()` が未応答proposalを確定またはrollbackする。既にDSP採用されたMapは取消で消さず、応答が採用を示せば履歴1を保持する。これは既に出たPCMの事実を保存する条件でもある。

ここで状態を直接Requestedへ設定する模型を、実DSPのApplying再検査や取消の統合証拠には数えない。D02/D03の実ID・実planner窓の回帰で、取消前後の実履歴と遅い完了の非混入を別途確認する。

## commit以後の出口と次所有者

| 出口・継続操作 | 実装根拠 | 不変条件 |
|---|---|---|
| 動的commit | `repeatWithEngine()` が実DSPの `trySupplyBorrowedDynamicMap()` 成功後に `Committed` とMap版・operation ID・最終Bを公開 | 一つのproposalだけを確定し `H=1`。`requestLoopTransition()` が再利用可能とする状態はIdle、またはsettled済みCancelledだけなので、Committedから2件目は受け付けない。 |
| 固定B延期 | `repeatWithEngine()` のRejected→Applying→FixedBoundaryCommitted | dynamic commitと混同しない。未採用proposalはrollbackされ、最終 `H=0`。この終端も次要求を同じ所有者へ受け付けない。 |
| terminal Bまで供給 | `pullAudio()` のterminal `cumulativeEnd` 上限、`repeatWithEngine()` の `generatedEnd && terminalLoop() && cycle>=loopTerminal.cycle` でbreak | FIFOとpendingを供給してからproducer終了。A保存点への次周回復元より先にbreakするため、履歴1の所有者を反復再利用しない。 |
| 次固定版への採用 | `seekLoop()` が旧pipelineをretiringへ、新しい固定pipelineをcurrentへ移し、旧版stop/join後に破棄 | 次所有者は入口表の履歴0。session、Map、operationの対応をまたいで履歴を連結しない。 |
| 速度を変えないPause/Resume | `pause()` は静止と実時間処理の解除、`acceptStart()` は同じpipelineを開始 | 履歴を消去・再生成しない。既存 `H=0/1` を維持し、2件目を追加しない。 |
| Paused速度変更・明示シーク・範囲変更 | 入口表の新固定所有者へ置換 | 旧履歴は旧所有者で確定・退役し、新版は0。 |
| Playing/Paused Clear | `seekLoop()` の `continuation` 分岐は `createSeek()`、固定ExactのBまたは停止Cへ接続 | Clearは動的履歴継続方式ではない。新plannerへ旧accepted履歴を渡さない。固定continuation seedを使える場合もPhase57の固定条件を保つ。 |
| Stop・入力変更・失敗・直接close | 静止後、通常workerのstop/join、`finalizeTransition()`、退役・解放 | 未採用proposalをrollbackし、採用済みの履歴・PCM事実は終端監査へ残す。次の入力／再開は新しい所有者で始まる。 |

cacheは固定RAW（加工前PCM）の再生と、速度要求時のDSP追付き再構成を区別する。A保存点の復元は固定Mapだけで、追付き中のproposal取消は上記rollbackに従う。動的commit後は最終Bで終了するため、動的MapをA保存点へ戻して同じ所有者に履歴を追加することはない。

また `RealtimePipeline::requestSpeed()` は `loopMode()` ならStoppedとして拒否する。通常再生用の速度変更APIを使ってLoopの単一commit制約を迂回できない。エンジンのLoop受付前には、KeepPositionに入れる通常所有者のAccepted操作を固定Map検査で拒否する。通常再生で既に512履歴を蓄積した所有者はReturnToAで新固定版を作る必要があり、その履歴をKeepPositionへ持ち込めない。

## 維持する回帰と判定の接続

`tests/Phase62HistoryInvariantTests.cpp` は引数なしの下位planner試験。合成解析は48kHz、8,388,608入力frame、過渡イベントなし、最終Map確定済み。PCMや実音声所有者は作らず、baseline/candidate（既存の二つの計画方式）をそれぞれ検査する。frontier（処理済み範囲を表す数値）とpublishedもplannerへの合成入力であり、実DSPで512件を実行した証拠ではない。大きな入力frame数はMapの長さを定義する値で、同量のPCMを生成・保存しない。

| 必須ID（各末尾 `_baseline` / `_candidate`） | 実assert |
|---|---|
| `D07_PLANNER_FIXED_START` | 新plannerは履歴0。最初のfinal MapはhasTransitions=false、modes空、baseVersion=0、指定速度の固定Mapと一致。 |
| `D07_PLANNER_ROLLBACK_640` | **同じ**plannerへ適用可能proposalを640回作り、毎回confirm(false)。proposal時H=1、取消後H=0。旧viewの同一性、Map全節点、tail、modesを維持し、proposal版番号は単調に進む。未応答中のplan/updateを拒否。640履歴確定とは呼ばない。 |
| `D07_PLANNER_PUBLICATION_ROLLBACK` | 実Map公開箇所のbad_alloc注入が同じrollbackを通り、H=0と旧view/tailを保持。後続planを受理し再度取消可能。 |
| `D07_PLANNER_HISTORY_LIMIT_512` | **一つのplannerに512件全てconfirm(true)**。一時的512件目を取消すと511へ戻り、再度512件目を確定できる。513件目はDecided＋limitReached＋Invalidで、履歴512・同じview・tail・Map保持量に副作用なし。 |

8 ID全て成功時だけ `PHASE62_HISTORY_INVARIANT_COMPLETE expected=8 executed=8 passed=8 lower_planner_only=true loop_exhaustion_reproduced=false` を出す。途中例外やID不足では完了markerを出さない。単なる標準出力の件数だけをPASSにせず、実行元source、binary、コマンド、終了コードと結ぶ。

実Loopの維持試験では、D02/D03/D06等の統合ハーネスおよび既存Loop/cache/API独立比較の該当assertを利用し、少なくとも次を要求する。

1. ReturnToA／Loop内シーク／Paused速度変更／次固定版の新sessionで、最初の固定Mapと履歴0を確認する。KeepPositionは同じ通常sessionの最終固定Map、自己反復Ready、履歴0を確認する。
2. 実planner進行中または実Applying再検査後に取消が勝ち、settled後に履歴0、旧Map/tail、古いIDの非採用を確認する。未応答時の一時H=1と最終H=0を混同しない。
3. 実Committedでは採用IDと履歴1、FixedBoundaryCommittedでは応答・join後の履歴0を確認する。終端状態から次の異速度要求がStopped、取消がfalseになることを検査する。
4. `cumulativeEnd` まで実PCMを消費し、producer終了とそれ以後のPCM受取0を確認する。独立参照PCM、FIFO位置、terminal B、次所有者sessionの既存assertを維持する。
5. Pause/Resumeは同じsession・採用Map・履歴を保持し、Clearと次固定版は履歴の引継ぎなしを確認する。

注意: レビュー開始点の `Diagnostics::transitionHistory` はplan直後および最終joinで更新され、通常のack直後には取消前の一時値1が残る場合がある。取消直後の真値を証拠にするときは、通常解析側の `confirmPlan()` 直後の値を採るか、join済みの最終diagnosticsを使う。未更新の観測値を「履歴が蓄積した」証拠にも「rollback完了」証拠にも使わない。

今回runの結果とD07の最終判定は `REPORT.md` / `CONTROL_COVERAGE.md` および対応summaryから参照する。この文書作成時点では新規下位試験を作成し静的証明を整理した段階であり、ビルド・実行は親作業で直列に行う。既存640独立遷移、通常4100周回、別sourceの過去runを新試験の実施済みPASSへ転記しない。
