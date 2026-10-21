# Phase62：動的Loop・停止中準備・B直前進入

前回実装の開始点は `main@7c05319d8142ef53a70c95be4f214f293bb2428a`、当時の作業ツリーは空。今回のレビュー基準はc4bdbb44。
旧実装前設計を基に更新。c4bdbb44以後の現行仕様は [残件設計](PHASE62_REMAINING_DESIGN.md)、最新の成立範囲と未実施は `results/phase62_finish/REPORT.md`、以前の結果は `results/phase62_dynamic_loop/REPORT.md` を参照する。

## 状態と所有権

Playingの公開済みFIFOは旧producerが所有する。Preparingは第2スロットで準備し、Armedはcallbackへ不変の参照を公開する。Startedはcallbackが採用した状態で、出力継続中は取消不能。Done後にcallback参照が静止し、通常workerが旧producerをstop/joinして退役する。Stopは出力を先に静止させ、部分混合を完了するcallbackを待たず取消・退役する。退役中も1所有者として数え、第3スロットを作らない。制御workerのjoinは、そのworkerが必要とするエンジンmutexを解放してから行う。不変保存点は実行せず、保存領域・RAW・Map・監査も既存予約へ加算する。

PausedはPause要求時ではなくcallback応答・開始済み混合終了後の実消費位置を固定する。要求ID、inputGeneration、loopID、cycle、source session/epoch、Map版、停止入力C、準備版を結び付ける。Preparing中は旧producer・FIFO・入力解析を保持する。最新版だけを静止中に採用し、旧producerのstop/join・参照解放後にReadyForResumeを公開する。Resume/Playは意思を1つ保持し、最新Ready後に一度だけ開始する。再Pauseは意思を取消す。Preparedは可聴Completedと区別する。内部準備はユーザーseek台帳・周回・実消費へ加算しない。旧FIFOの破棄は専用監査量とする。

Clear受付はenabled=falseとする。clearPending中は有効な反復を供給し、通常継続が準備できた安全なBで接続する。速度要求は理由付き拒否し、Clear後の再要求を契約とする。内部epoch更新だけで有効なClearを失効させない。Paused Clearは再生を開始しない。取消・Stop・入力/装置変更・closeは準備版を失効させ、古い通知を復活させない。

| 状態 | DSP/FIFOとcallback参照 | Map・解析・FD/InputLease |
|---|---|---|
| Playing | 現所有者が生成・公開、callbackが確定FIFOを消費 | 採用Mapをproducerが借用、解析workerがplannerを所有 |
| Preparing | 現所有者の供給を維持、第2所有者のFIFOは未採用 | 入力lease/最終解析は共有、DSP作業領域と新固定Mapは別 |
| Armed | 第2所有者はReady/昇格済み、両参照をcallbackへ公開 | Map/入力identityを確定、要求ID公開後に動的commitを許可 |
| Started | 境界処理が参照中、両所有者を保持し取消しない | 確定した動的Bと次固定Mapを保持 |
| Paused Preparing | 実消費Cを固定、旧未消費FIFOを保持して第2版を準備 | C・入力世代・Loop・版が一致する新Exactだけ採用 |
| Paused Ready | callback静止、旧join/参照解放後に新所有者だけ保持 | 新版のleaseがFDを保持、再開意思があれば一度だけ再開 |
| Clear待ち | enabled=false、必要な自然反復を継続。確定境界版の後に通常版を準備 | 明示的固定ExactをBで接続、通常接続を周回に数えない |
| 取消/置換 | 未開始callback参照を閉じ、静止確認後に第2版を退役 | 古い版の通知を無効化。旧有効版のleaseは保持 |
| 退役 | callbackが旧参照を使わず、通常workerがlock外でstop/join | 保存点を含む旧資源を解放。最終利用者までFDを保持 |

## Playingの動的状態保持

固定checkpointを動的引継ぎに転用しない。producerのadvance間の生成フロンティアPで、位相・左右履歴・OLA・FIR・各カーソル・未公開部分PCM・採用Map/密度履歴を同じ所有者に保持する。planner要求/proposal/ack/commitの所有者は既存analysis workerの1つだけであり、producerは不変Mapを借用して既存Phase59の検査とackを行う。計画は通常policyで行い、公開済み区間と部分PCMを保護したL1/L2/safe-density以後へ適用する。制御threadからDSPをコピーしない。PはDSPのsinkへ渡したブロック末尾、実FIFO公開末尾はP−pendingCountであり、後者もcommit監査へ保存する。plannerへは保守的にPまでを公開済み保護範囲として渡す。既存凍結参照が再現する2048単位のDSP公開座標と、実FIFO部分公開を混同しない。

第2所有者の新速度固定A→BがReadyになり、実時間参加とcallback参照の公開を完了した後だけ動的取引を要求する。Requestedは取消可能、ApplyingへのCASが取消との確定点、Committed後は第2所有者をBまで保持する。callbackはその要求IDに一致する不変descriptorだけを採用し、commit後の通常threadによる追加公開を待たない。旧plannerの取消回収中はBusyとして再試行し、B延期と混同しない。取消済み境界版はPauseしたという理由で採用しない。旧所有者は「固定周期のprefix＋最後の動的1周期」で終了し、動的Mapへ固定seedを戻さない。末尾補正開始前に、動的Bと次先頭PCMの双方が確定している。動的Bは採用Mapの入力B（全曲末尾は採用Mapの最終長）から求める。追加の実行所有者・thread・FFT planを作らず、P前後を同じproducerだけが公開する。FIFO flush・無音消費・消費位置飛ばしを禁止する。

最後の動的周期をrelease公開する不変descriptorはproducer cycle・Map版・localStart/End・cumulativeStart/End・要求ID・P・実FIFO公開末尾を持つ。旧固定周期prefixには従来のLを使い、終端動的周期だけ別のL_iを使う。callbackは累積消費から該当周期のBを選び、自然反復のrenderEpochと意味的なLoop周回を別々に進める。次所有者は独立した新速度固定Exact Mapから始める。

同じproducer内の引継ぎでは、実FIFO公開末尾をP_fifo、DSPブロック末尾をP_dspとし、未消費FIFOの`[read,P_fifo)`と部分PCMの`[P_fifo,P_dsp)`を保持する。新Mapの変更域はPhase59が保護した未来に限る。同じproducerだけがこの連続列を公開するので、Pで別producerのPCMを継ぎ足さない。境界での旧所有者の可聴範囲は累積終端`Σprefix+L_dynamic`未満、新所有者の初回範囲は新MapのOAから始まる。新FIFOの事前生成は、callbackの可聴累積位置を進めない。

既存Diagnosticsの`consumed`は再利用Loopでは周期内、`published`はストリーム累積であり、両者を直接引いてFIFO残量を求めない。内部の`diagnosticFifoCursors()`/`available()`と停止速度操作の専用破棄量を使う。停止試験では初期A=0の同じ所有者について実出力の累積値と退役時公開末尾から別に検算し、2周後でも専用破棄量・C・周回が一致することを確認する。

callback採用IDは `requestLoopTransition` 内でRequested公開より先に既存handoffのatomic領域へ書く。APIが戻った後の制御threadの継続をcommit条件にしない。Idle/Cancelled中のcallbackはhandoffの非atomic通常フィールドを読まず、Requested/Startedのacquire確認後だけ読む。producer cycleは所有者内の周回、LoopBoundaryEvent.settingCycleはLoop全体の周回である。session/operationID、旧/新epoch、callback累積座標と境界台帳で両者を対応付ける。

Applyingを観測しただけでは取消予約にならない。供給位置の再検査でRequestedへ戻ることがあるため、取消側はDSP取引の取消成功を再確認してからcallback経路を閉じる。Committedの場合は必要な境界版を保持する。明示Stop/失効では出力静止・inRender=0後にStartedを取消せる。非periodicの部分混合はcallbackのtargetが既に準備版を指すため、生存ownerへ参照を付け替えたことを確認してから準備版をstop/join・監査・破棄する。これは静止後の寿命処理であり、可聴PCMの巻戻しや再開ではない。正常なStop取消を音声供給障害へ分類しない。

c4bdbb44以後はKeepPosition初回と96000以下/cacheも専用protocolで接続する。現行の状態・所有権・固定延期・Paused Clearは [残件設計](PHASE62_REMAINING_DESIGN.md) を正とする。単に短いから延期するのではなく、公開済みFIFOと未公開PCMの保護、合法な遷移区間、準備期限を区別する。動的commit後の範囲変更等の制限は検証記録へ分離する。全必須範囲の証拠が揃うまでcurrentCycleSpeedChangesはfalseを維持する。機能の一部の観測だけで一般対応としない。

基準c4bdbb44ではKeepPosition初回の完全状態接続が未対応だった。通常ownerは有限の全曲producerであり、最初のB→A版を早期退役すると準備失敗時の供給を失う。今回追加した接続は、その版を自己反復Readyまで保持し、同じDSPの完全状態とFIFOを維持して反復を可能にする。その後に最新固定版を準備し、保護条件と準備期限を満たす代表例で初回B前の実適用を検証する。全対象の承認までは能力falseを維持する。

Playing中のClearは、動的Bに必要となった固定境界版を先に安全に使い切り、その後に通常継続の第2所有者を準備する。最大2所有者を越えない。通常継続は既存契約の明示的な固定Exact再準備であり、B以後へ動的位相履歴を継続したものとは呼ばない。Clear受付後のenabledはfalseのままで、待機中の実際の自然反復だけを数える。commit後の新速度/手動seekは現在必要な境界版を保持して、退役後に最新要求を処理する。範囲変更はこの短い確定期間には理由付き拒否し、境界後の再要求を求める。

## B直前の進入

入力[A,B)のCを維持する。R=round(Map(B))−round(Map(C))は出力単位、Nは進入混合出力長。R<Nでも拒否せず、Bと周期補正窓でspanを分割し、混合cursorは継続する。新RAWへ周期末尾/先頭補正、その後に旧/新の進入相補混合を適用する。旧側が反復中なら同様にBで分割する。初回Cへの移動は周回でなく、出力したC→Bの自然B→Aは1回数える。

R=0はPCMやゼロ長spanを作らず、指定Cを記録したまま有限の状態遷移でAへ接続する。この初期正規化は周回へ加算しない。全周期L>=512、最大callback4096、span32は維持する。C→Bだけに512下限を適用しない。

## 失敗と有限資源

遅延中は有効な旧PCMを保持する。準備失敗/取消はReadyを公開せず、停止中なら勝手に旧速度で再開しない。4096操作、512動的履歴、64descriptor、FIFO16384、短区間RAW96000出力フレーム、予約1GiBを拡大しない。callbackは有界コピー・数式・原子通知のみで、確保/解放・mutex・join・I/O・planner・FFTを行わない。全所有者退役までInputLease/FDを保持する。

## 検証

修正前と修正後を別binaryで記録する。独立Phase59 planner/動的DSP、固定Exact、Paused Exact、動的履歴継続、境界加工の参照を区別する。Phase62PcmAuditだけを独立DSPとしない。SHA・条件・期待件数を実行前manifestへ記録し、NOT_RUN/BLOCKED/FAILを残す。公開フラグと既存未達ゲートは維持する。
