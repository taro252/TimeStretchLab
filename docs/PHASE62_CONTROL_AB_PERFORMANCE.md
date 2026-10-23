# Phase62 制御負荷・AB入口

基準はff1f677f7bcb6095b0f1d74538910f9c3e4b5d5d。独立checkoutの作業ブランチcodex/phase62-control-ab-performanceを使用する。Merodoaの資料は測定済みの引継ぎ資料として読む。アプリの約30–40%とTSL単体のprocess CPU、Running標本の割合、内側のCPU/wall計測を混ぜない。

## 制御と観測

比較基準はff＋両版共通の任意・通常スレッド用カウンターとnative測定host。無効時は時計を読まず、有効時だけInput.validate、速度全履歴コピー、monitor、同期、seek起床を固定容量で累積する。親区間と内側の区間は包含値なので足さない。callbackへ通知・計測・割当て・ロック・I/Oを追加しない。

CPU条件はMerodoaと同一SHAの240秒人工stereo PCM16、Candidate100%、48kHz/512、通常取得5Hz。TSL hostにはUI/Swift/JSON/描画を含まない。非接続の30秒×3を主比較とし、寄与カウンターを有効にした短試行は別集合。短ABは出力周期<=96,000かつ全曲以外のRAW cache、長ABは非cacheとして分離する。速度bypass/音質/Preset/ゲインは変えない。

## Clearの最新ReturnToA

既存requestLoopRangeはclearPending中も新鮮なinputGeneration/session/renderEpochで受付可能。未採用Clearの準備版を失効し、そのstop/join後に第二スロットで新Loopを準備する。旧確定FIFOは供給を維持し、第三ownerを作らない。

Requestedの取消CAS勝ちとStarted/Doneを区別する。Started/Doneは旧Clear混合・採用と参照解放/退役を完了してから新Loopを準備する。外部clearContinuation速度IDは勝敗確定前にCancelledにしない。実際に開始したIDを保持し、終端回収は旧jobの実PCMで行う。旧IDを新IDへ書き換えない。未開始の取消は理由付き終端として保持する。Paused直接採用後のCとReturnToA後のAは別座標で、明示Resume意思がなければ音声を出さない。

同速度・同入力の不変固定A保存点をClearの通常Exact prefixへ使う場合も、B直後の未公開PCM保存点とは呼ばない。PからB/Cまでを実際に再合成する。現在の動的DSPを固定状態と見なさず、完全固定状態のcloneと新Map全ノード/出力長の照合を通す。将来のLoop再ON用不変状態と実行ownerを区別し、上限2枠を維持する。

## cold初回

互換な完全固定保存点P<=OAがある場合だけ初回Loopへ流用する。通常seekのopt-inを暗黙に有効にせず、C>Aの稼働DSPを巻き戻さない。既存保存点がないfresh初回はcold Exactを維持する。先行準備APIはCPU改善と別に評価し、今回導入しない場合はfresh初回高速化を未完了と報告する。

原本はbuild/phase62_control_ab_20261022_01、Gitには小さいREPORT/manifest/レシピを保存する。A1の終端39fields不変・全Accepted回収・終了監査、A2の厳密互換性/準備版、最大2owner/2checkpoint/FIFO16,384/RAW96,000/既存メモリ予約、独立RAW/Map/混合の完全一致を守る。公開・既定採用・Merodoagitlinkの承認を追加しない。

## 状態・所有範囲

| 局面 | 所有と確定点 | 次操作 |
|---|---|---|
| Playing/Paused、同期対象なし | 現epochのDSP/FIFO/採用Mapを保持。通常monitorは軽量要約、入力検証はInputLease単位で共有 | 速度受付で未終端索引へ追加、通常threadのrevision通知でplannerを起こす |
| Clear Preparing | 旧ownerが確定FIFOを供給。第二ownerが新しい固定Exact MapとB/CのPCMを準備。A保存点は不変状態だけ | ReturnToAは版を失効し、未採用workerを停止・joinしてから同じ第二枠を使用 |
| Clear Armed/Requested | callback切替はまだ取消CAS可能 | CAS取消勝ちは未出力Cancelled。Started/Done勝ちは旧速度IDを保護 |
| Clear Started/Done | 旧/新RAWの混合と採用済みownerを保持、callback参照を解放して旧ownerを退役 | 新ReturnToAは受付できるが、使用中の二枠解放前に第三ownerを作らない |
| Applying/Committed/FixedBoundaryCommitted | DSPの動的Bの所有は既存の不可逆契約を維持 | 範囲変更は理由付き拒否し、安全なB完了後の新鮮なcontextで再要求 |
| Paused Clear準備/採用 | 静止Cを固定。旧FIFOは成功まで保持し、採用後stop/join/参照解放を確認して専用破棄監査へ計上 | 再ON後の新Aも静止。明示Play/Resume意思がある場合だけ旧退役完了後に再開 |
| Started保持中のStop/close | callbackを通常の静止手順で止め、実開始/PCM/session事実を残して取消又は既に完了したCompleted | 未開始Replacedへ偽装せず、独立終了監査に同じAccepted IDを回収 |

Requested取消の判断前に終端レコードを書かない。古い完了はjobLoopID/seekVersion/入力世代/採用ownerで対応付け、新LoopのclearPendingやAを上書きしない。KeepPositionはClearの採用先と制御ownerが分かれている退役窓では理由付き拒否し、最新contextでの再要求を要求する。通常ReturnToAとの受付範囲を混同しない。

DSPの動的phase/左右履歴/OLA/FIR/未公開PCMの移管方式は既存Phase59/62を変更しない。新しいprefix流用はその代用品ではなく、最終固定Map・履歴なし・生成=公開の不変保存点だけをcloneする専用の固定Exact経路である。全ノード・出力長・入力世代・resident identity・Preset/速度・解析を照合し、通常保存点のP>OAやMap不一致はcoldへ戻る。取消版が新しい有効版の保存点を奪わない。資源上限で準備できない場合は採用前に失敗し、有効な旧出力を保持する。

`initialCheckpointHit`は同A/B保存点、`initialPrefixCheckpointHit`は通常seek保存点P<=OAの流用を区別する。後者はP→Aの合成・破棄が残る。`checkpointStartFrame+coldDiscardedFrames=OA`を実測し、Aの絶対位置をCとの差へ言い換えない。新たな常駐worker/FFT plan/PCM cache/先行prepare APIは増設しない。

メモリは既存の1GiB予約上限、24MiBの二epoch共有枠、各完全状態の既存8MiB見積、checkpoint総数2、RAW/program96,000、FIFO16,384を維持する。追加の未終端索引は8,192 bytes固定、計数は固定atomic、旧未使用のB越えPCM退避16,384 bytesを除去した。予約を増やさず既存制御メタデータ枠内へ計上し、実測RSSと所有者ピークはmanifestへ残す。InputLease/FD/解析の共有参照は全workerの停止・joinとcallback解放まで保持する。

## 保存点の不要参照解放

最終資源レビューで、同速度の範囲置換の3回目が保存点上限2に達することを新しく再現した。通常Clear向けのcontinuationSeedがcreateLoopSeekにも渡り、反復側では使わないまま新A保存点と併存していた。

反復の開始前enableLoopReuseでこの不要共有を解放し、通常ExactのmakeSynthesisでも完全clone後に元共有を解放する。どちらも通常thread・RT昇格前で行う。cloneは解析/Map/DSP状態を所有コピーし、入力FD/resident領域は新PipelineのInputLeaseが保持する。現反復の必要なA保存点は保持する。Ready/Playing/Paused/Clear後に同速度Rangeを各4回に資源監査と新prepare初期化2件を加え、両Preset計38 checksで、旧owner退役後の保存点1・準備時ピーク2・FIFO/PCM/停止位置/終了監査を確認する。旧CP1→CP2→上限失敗と修正後を別証拠に残し、最終binaryの性能・回帰を再測定する。

## 入力切替時の要約初期化

retire時の軽量速度要約は停止後の明示参照用に保持する。新prepareのlaunchでは旧履歴と同時に要約も空へ初期化し、Accepted/PreparingとPipeline生成前Failedへ旧入力の速度・pending/active/lastResultを持ち越さない。普通の動的75%→Stop→100%準備を通常workerの資源取得前で観測し、生成前失敗も別に検査する。callbackを試験ゲートで止めない。

任意カウンターの累積範囲は、monitor/sync/seek起床がEngine寿命、入力検証がInputLease寿命、速度履歴コピー/analysisIdleWakesがepoch寿命。同じ寿命内の前後差を使い、InputLease/epoch切替を跨ぐ差を取らない。入力検証は同leaseの二ownerで共有するため合算しない。無効時の0は未計測であり、0コスト実測とは扱わない。seekDispatchWakesは通常dispatch選択回数で、OSのinterrupt wakeupsとは別。性能hostは各窓の開始・終了差分を比較する。

入力監視・monitor同期・idle seekの従来周期処理は、引継ぎ資料にある旧e4版にも存在する。今回のCPU改善対象をA1/A2で導入された退行とは断定しない。空履歴の実コピー量と各処理の実測寄与を別に扱う。
