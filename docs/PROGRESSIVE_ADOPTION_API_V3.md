# Progressive採用候補・契約版3

この候補の機能別判定は[採用台帳](PROGRESSIVE_ADOPTION_PLAN.md)、新規実行の結果は`results/progressive_adoption/REPORT.md`を参照する。旧NO-GOは当時の範囲として保存し、今回の正式化を禁止する規則として使わない。未達の方法を承認済みに読み替えない。

## 方式、承認、設定、実行可能性

`ProgressiveFeatureContract.h`の`FeatureAvailability`はimplemented / approved / configured / effective / allowed / research / reasonを分ける。compiled `featureApprovals`は方式ごとのengine承認で、Merodoaのアプリ受入・物理音響承認とは別である。`SeekAvailability.exact`と`.interactive`、`LoopAvailability.nativeLoops`を使う。現在周期の実装は`currentCycleSpeedImplemented`、正式対応は`currentCycleSpeedChanges`、個別延期は既存LoopSpeedOperation.deferralを使う。現在周期内の即時変更を常時保証しない。

`ProgressiveOptions::macOSProduct()`は具体的な製品設定である。各方式をApprovedOnlyにし、承認表で合格した方法だけを実効化する。今回の表はExact=true、Interactive/nativeLoops/currentCycleSpeed=falseで、Exactの数値・所有権方式承認を通常RT・アプリF・音響の承認から分ける。未承認方法のResearchへの変更は、ホストの明示操作を必要とする。既存オプションのfalseを新しい既定値で上書きしないため、`featurePolicy`未指定なら従来boolを変換する。旧Exact要求は従来の研究実装として利用でき、Loop/Interactiveの旧falseはそのまま無効となる。明示v3設定があれば旧boolより優先する。

正規化はprepareごとに1回行う。同じnativeLoops.effectiveを、追加24MiB予約・boundedEpochReservations・有限callback観測・受付・診断へ使う。一時的なallowed=falseで必要な予約を外さない。Clear/Stop/closeは後始末なので承認フラグで禁止しない。

旧`Capabilities.seek`/`publicSeekApproved`はExactとInteractiveの両方が承認された場合だけtrueとなる保守的な互換値である。Exactだけの承認をInteractive有効化の根拠にしない。旧bool `seekToInputSeconds`はこの包括ゲートを維持する。v3利用者はrequestSeek*のExactとrequestInteractiveSeek*を区別する。

ヘッダーと実行体を一緒に更新・再ビルドする。`prepare`へ既定引数ContractV3Tagを追加してリンク名を変えたため、新旧ヘッダー/バイナリ混在はprepareのリンク時に失敗する。構造体を旧ABIのまま渡さない。policy.version不一致は旧入力を退役させる前に拒否する。contractVersion=3をbridgeへ渡す。

## 安定した理由コード

SeekReceipt/SeekOperation/LoopReceiptに数値固定のAvailabilityReasonを追加した。日本語reasonは説明用であり再試行制御に使わない。

|値|理由|扱い|
|---:|---|---|
|0|Available|受付可能。AcceptedはReady/Completedを意味しない|
|1/2|NotConfigured / NotApproved|設定・方式の承認を確認。自動再送しない|
|3/4|NoInput / InvalidState|入力準備または明示状態操作が必要|
|5/6|InvalidContext / StaleContext|全identityを取り直し、最新意図が残る場合だけ有界に再要求|
|7/8/9|InvalidRange / MinimumInput / MinimumOutput|範囲の恒久的な拒否。入力100ms・確定周期512fの制約を表示|
|10/11|InvalidPolicy / WholeTrackRequired|方針を明示選択。KeepPosition拒否をReturnToAへ置換しない|
|12/13|ProtectedBoundary / RetiringOwner|採用済み境界・所有者の必要な完了点を待つ|
|14|PositionUnavailable|静止位置/確定解析の観測待ち|
|15|LimitReached|現在有効な音声を保持し、監査とengine再生成の復旧へ|
|16|InputFailure|保持FD/選択pathの照合失敗をlatched診断で確認。再選択/再prepareが必要|
|17/18|ResourceBudget / ResourceBusy|予算/使用中資源を区別。予算を増やして通さない|
|19/20|InvalidArgument / EngineFailure|引数修正、または安全停止・原因保存|

コードは共通語彙で、全コードを全受付経路が返すわけではない。確定Map後に分かる非同期失敗は操作状態・理由も照合する。LoopSpeedReceiptCodeの既存数値とLoopSpeedOperation全終端フィールドは変更しない。

## Readyの量と停止中の契約

Ready閾値8192fの候補は、stereo実機120件でReady p95=194.20msを得た一方、worker期限超過2件が残り、製品から取り下げた。最終候補のReady/定常先読みは従来のCandidate16384/Baseline12288、FIFO容量16384である。preroll 500ms、FIR格子14336f、品質Preset、ゲイン0.5、短いsuffix/EOFの終端規則を維持する。`Diagnostics.readyLeadFrames / steadyLeadFrames / fifoCapacityFrames`で実値を確認できる。FIFO待ち削減は局所位相品質改善とは別判定である。

停止中速度準備はCとLoopを保持する。ReadyForResumeと音声Completed、明示Resumeを区別する。速度を変えないPause/Resumeは動的履歴を保持する。今回のAB先行準備は[専用契約](PROGRESSIVE_LOOP_PREPARATION_DESIGN.md)であり、停止中速度準備・ユーザーseek・周回には加算しない。

## 有限履歴・入力条件・復旧

入力は512MiB以下かつ28,800,000入力フレーム以下。48kHzで600秒、44.1kHzで約653.061秒であり、常に10分ではない。実装レート44.1/48kHz、mono/stereo、両Preset、161速度。Merodoa製品派生WAVはFloat32。PCM16互換を製品入力変更の代用にしない。予約1GiBはRSS上限ではない。

|資源|上限と寿命|
|---|---|
|実行owner / 不変保存点|入力leaseごと各2。Preparing・退役・callback参照中を含める|
|FIFO / 短周期RAW|16384f / programあたり96000f。全曲cacheは不可|
|通常速度操作 / 採用計画|pipelineごと4096 / 512。次epochへ同一履歴として転記しない|
|seek|engine生存中4096。Rejectedも枠を使う|
|停止中速度 / 外部Loop速度|engine生存中各4096。Stop→prepareはbaseだけ更新|
|AB先行準備|最新同時1件・engine履歴4096件。拒否はID0で履歴を消費しない|
|終了epoch / 内部速度の閉鎖表示|直近16epoch / 各直近256件。全寿命累計と区別|
|Loop境界履歴|直近64件。実際の自然周回累計とは別|

`historyUsage()`はengine生存累計と現在ownerのsession別使用量を返す。上限増加、無言の確定履歴削除、Stop/Playでの回復は行わない。ID0/LimitReachedでは現在有効なFIFOを壊さず、次をホストの直列制御キューで行う。

1. 最新の入力asset、検査済み派生PCM identity/lease、速度、採用Mapに対応するC、Loop範囲/方針、停止状態と明示再開意思を保存する。
2. ユーザーへの理由を示し、Stop/取消を受け付ける。履歴枠の復旧目的で勝手に再生・seekしない。
3. 通常速度は`receiveFinalEpochAudit`で各ownerの全join後・切詰め前に回収する。閉鎖16epoch/256件の表示だけを全寿命監査と呼ばない。
4. close/破棄は全join・退役を完了させる。`receiveFinalOperationAudit`でseek/停止速度/Loop速度/先行準備の所有コピーを回収する。旧Loop専用最終監査も維持する。FD/security scope/PCM leaseはこの確認以前に解放しない。
5. 新しいアプリengine UUIDとprepare UUIDでengineを作る。`engineSerial`はprocess内の識別補助であり、外部UUIDの代替ではない。ID1再利用を旧engineのID1と混同しない。入力を再prepareし、位置/Loopを明示復元し、元がPausedなら明示Resumeまで停止を維持する。

停止中速度の終端監査では、ReadyForResumeとoutputStartedの組を読む。準備Readyを音声Completedに読み替えない。先行準備Readyはjoin済み不変保存点の完成で、その後のavailable失効は終端行の書換えとは別である。

D07のH<=1とD08の距離上限を通常速度履歴へ一般化しない。今回の先行準備は既存Exact保存点の取得前置だけで、Loop周期生成・descriptor公開方式を変えない。閉鎖済み結果の前提照合を記録し、新方式へ無条件に承認を拡張しない。


## 通常速度の全量epoch監査

`ProgressiveOptions.receiveFinalEpochAudit`は、通常thread上で該当ownerの全worker joinとcallback参照解放後、表示履歴を256件へ切詰める前に、全`SpeedOperation`を借用spanとして渡す。構造体は`EpochOperationAudit`で、engineSerial/preparation/sequence/renderEpoch/session/inputGeneration、ordinarySpeeds、preparedOnly/workersJoined/callbackReleasedを含む。内部Loopは同ownerのepochだけを更新するため、配送の一意性はproducer sessionで判定する。Stop後のdestructorで同じcurrentを再配送しない。外部通常速度要求をまだ受けられない初期prepare取消・失敗の空ownerは監査対象外であり、Accepted欠落の例外ではない。

ホストはこの呼出し中に値を所有コピーする。engine mutexを保持する通常threadから呼ぶのでengineへ再入しない。callbackでは呼ばない。ホスト側も有界な領域を用意し、受渡し不能ならfalseを返す。返値falseは`epochAuditRejected`へengine寿命中ラッチし、prepareで消さない。`epochAuditCalls`は配送試行数。音声を壊したり、履歴枠を増やしたり、監査完了と偽ったりしない。末尾16epoch/各256件の表示保持、通常ownerの4096件とplan512件の上限は維持する。

最後のcurrent ownerの拒否はdestructor中にも起こり得る。`FinalOperationAudit.epochAuditConfigured/epochAuditCalls/epochAuditRejected`で最終状態を回収し、configuredかつ拒否0、期待session/ID集合の全終端・全フィールド回収を確認した場合だけ全量監査の成功とする。外部UUIDを一緒に保持する。sink未設定で閉鎖表示だけを読む利用者には全Acceptedの最終監査完了を保証しない。D07のH<=1は使わない。

互換availabilityの`optIn`/`interactiveOptIn`は内部の実効有効化を表す。研究承認の判定には新しい`.research`/`.approved`を使い、包括boolや名称から正式承認を推測しない。
