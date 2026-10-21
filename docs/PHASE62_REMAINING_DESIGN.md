# Phase62 残件の実装設計

レビュー基準は `c4bdbb44d92a367369e8ecf3c51fd50cb3abed4c`。開始時mainは同SHAでclean。既存の同一producer内で完全状態を保持する方式を維持する。今回commit/push/PRは行わない。

## 外部要求の有限台帳

外部Loop速度要求はエンジン生存期間で最大4096件とする。通常制御側が一つの台帳を所有し、受付時Loop/input/session/epoch、速度、準備版、内部操作、動的Map/Bと適用結果を対応付ける。Pausedの既存準備台帳は内部の準備情報としてリンクし、外部要求の結果をそこから更新する。新入力でも外部IDと過去記録を消さない。

| 状態 | 所有権・確定点 | 置換・失敗 |
|---|---|---|
| Pending / Preparing | 受付枠を先に確保。旧PCMと既存再開意思を維持 | 未commit・未開始の要求だけReplaced |
| ReadyForResume | 停止CとLoopを保持。旧ownerのjoin/参照解放後の準備完了 | 準備完了は可聴適用ではない。未開始版だけ置換可能 |
| Committed | 必要な次固定版がReady、callback参照と採用IDを公開しDSPがMapを採用 | 新要求で未適用Replacedにしない。必要な境界版を保持 |
| FixedBoundaryCommitted | 保護済みFIFOと部分PCMを全て含むproducer周期末尾を固定Mapで確定 | 動的commitと区別。必要な第2版を保持し、直近の消費Bへ早送りしない |
| Applied / Completed | 内部Phase59の位置と実消費、または固定版のcallback採用を観測 | 開始済みの事実・座標を保存。停止時も過去を消さない |
| Replaced / Cancelled / Failed | 通常workerが結果と理由を確定 | Clear/Stop/入力/装置/closeで受理済みIDを残す |

Duplicateは有効な既存IDを返し枠を消費しない。初期速度と同じで外部要求が存在しない場合はID=0のDuplicateと明示理由を返す。上限検査は旧要求の取消、requested更新、準備版の破棄より前。4096件の製品上限を小さくする試験専用設定も同じ受付経路で判定する。callbackは台帳を操作しない。

拒否は入力なし・古い文脈・Clear待ち・上限・不正状態等を機械判読可能な理由へ対応させる。内部Busy、保護範囲、準備期限、未対応、失敗も区別する。Started済みの停止速度準備は、次回のPauseで新速度を要求してもReplacedへ書き換えない。

## KeepPosition・cache

実装前に選択した方式：KeepPositionは既存APIどおりA=0/B=EOF専用。通常producerを実行中のまま保持し、同じ入力/最終固定Mapから通常解析workerが未実行のゼロ保存点を作る。これはPCM生成・公開を行わない不変保存領域であり、実行所有者ではない。固定snapshot/Mapの同一lineageをproducerが確認し、既存FIFOと部分PCMを引き継いで、同じengine/threadの周期生成処理へ接続する。稼働中configの書換えはしない。

| 段階 | 現所有者・公開済みPCM | 第2所有者・Bの供給保証 | 保存点と確定条件 |
|---|---|---|---|
| Keep受付〜自己反復準備 | 通常producerがC以後をそのまま供給 | 最初の固定B→A版を保持。まだ取消しない | 通常workerがfinal固定Mapのゼロ保存点を構築。FFT/確保をcallbackで行わない |
| 自己反復Ready | producer安全位置で専用runtime modeを採用。PCMカーソルは連続 | 現owner自身でB→Aを供給でき、未開始第2版を安全に退役できる | 最終Map・snapshot・入力identity一致、先頭RAWとdescriptor、FIFO/部分PCMを確認 |
| 最新固定版Preparing | 現ownerの同じ完全状態と固定反復を維持 | 遅延/失敗中も旧供給を継続。退役後にだけ最新版を作る | 保存点は現owner用と次owner用の最大2、bytesは既存予約内 |
| Armed〜動的commit | 既存Phase59保護範囲より先で同じDSPへ新Mapを供給 | 最新固定版Ready・実時間参加・callback参照と採用ID公開後にだけcommit | Bは採用Mapから再確定。commit以降必要な版は取消不能 |
| 期限未達 | 有効な通常/固定出力を維持 | 最初のBへは既存版を使い、次に可能な周期へ延期 | 合法区間なしと準備期限未達を別理由・実測位置/時刻で残す |

cacheではA保存点をB継続用へ上書きせず保持する。通常warmは既存RAW供給を維持し、速度要求時だけ同じDSPをAから現在producer周期の生成位置まで追付かせる。2048出力フレーム以内の区間ごとにcache供給を優先し、既存FIFO/部分PCMを変えない。再構成した固定RAWとcacheの一致、周期/Map/カーソル一致を確認した後だけPhase59へfrontierを渡す。96000以下という長さだけで延期しない。

固定A保存点を維持するためcacheのB継続保存最適化は使用せず、Clearは既存の明示Exact再準備へ戻る。Clearのcold準備時間と待機中供給を、warm反復のFFT/worker/prefix指標から分けて再計測する。保存点を無条件に追加したり上限を増やしたりしない。短い全曲非cacheは再構成不要で同じ現在DSP状態を使う。

## 証拠と集計

新しい実行先は `build/phase62_finish_20261021/`。各実行前のEXPECTEDへ必須ID集合・期待件数・ソース/binary/input/reference SHAを保存し、完了マーカーと最終統計の両方を検査する。旧runは不変のまま、旧schema専用監査へ分離する。旧件数を今回実行へ付け替えない。

## 短周期の生成位置と固定B延期

cache供給時は固定RAWの読出し位置とDSP位置を別に保持する。速度要求時の再構成は同じDSPをA保存点から戻し、cacheの公開位置と同じ2048単位の境界へ追付く。再生の不足を避けるため、FIFO残量が先行量の半分以上ある場合にだけ再構成を進める。再構成PCMはcacheとの全bit一致・有限性を検査し、FIFOへは公開しない。再構成の対象周期が進んだ場合、250msを越えた場合、1周期＋2048frameを越えた場合は、その要求を期限付き延期へ移す。要求IDごとに再構成frame・CPU・所要時間・延期数を測る。cache条件と96000上限は維持する。

Phase59の保護条件・遷移長・Bの余裕を満たせないときは、producerが `FixedBoundaryCommitted` を一度だけ公開する。現在生成中周期のBに最大callback4096＋補正窓の余裕が残ることを確認し、FIFO writeと未公開pendingを含む固定Bを選ぶ。次所有者はその確定cycleのBまで待つ。単なるRejected通知や下位Stopped応答だけではcallbackを切り替えない。同速度への復帰はNoOp完了として準備版だけ退役させ、既存FIFOを維持する。

動的commitと固定B確定のどちらも、取消と同じRequested/Rejectedの原子的状態遷移で競合を決める。取消が先に成功した後の遅いplanner/DSP拒否は、CancelledをRejectedへ戻せない。Applyingは取消の観測点ではなく、処理側の再検査後にRequestedへ戻り得る予約状態である。

## 停止・Clear・退役

Pausedの固定Cはcallbackが開始済み境界処理を終えて静止した実消費位置である。最新の速度・入力世代・Loop・停止位置・準備版が一致し、旧所有者のstop/joinと参照解除を完了してからReadyForResumeを公開する。Resumeを待って準備完了にする循環待ちはない。準備中Play/Resumeの意思は最新準備へ保持し、再Pauseで取り消す。失敗は停止のまま残す。速度を変えないPause/Resumeは同じ動的履歴を保持する。

PlayingのClearは明示固定Exact継続を選ぶ既存契約を維持する。動的Mapの確定Bから新速度の固定Exact入力Bへ接続する。履歴継続方式とは呼ばない。採用済みの境界版はClearで壊さず、その後に通常継続を準備する。clearPending中の速度要求は専用理由で拒否し、Clear完了後の再要求を求める。内部epoch進行だけでClearを失効させない。Pausedでは自動再生しない。

全callback参照の静止後、通常workerがstop/join・最終監査・解放する。joinはworkerが必要とするengine mutexの外で実行する。InputLease/FD・解析・Mapは最後の実行所有者と不変保存点まで保持する。不変保存点の枠は入力lease全体で最大2、確保前に予約し失敗時の返却主体を一つにする。通常ownerの自己反復保存点準備失敗は専用Failed/LimitReachedへ隔離し、既存B供給版と有効な旧PCMを止めない。

## 監査用の公開標本

`loopSpeedHistory()` / `loopSpeedOperation(id)` は外部要求の結果、`loopSpeedPcmEvidence(id)` は所有者が生存する間の同一commit標本と採用Mapの通常スレッド用コピーを返す。後者はMapがDSP ack済み版と一致するときだけ存在する。参照PCMを正解へ合わせるAPIではなく、独立plannerへ渡す実測frontierと検査対象を採取するためのもの。callback内で照会しない。

`cumulativePublished = cumulativeStart + publishedAtCommit - localStart` を同じ標本のFIFO writeと照合する。動的commitの未公開PCMは `[P-pending,P)`、Pは実DSP生成位置。cacheによる固定B確定ではDSP生成位置がRAW供給位置と異なるため、両者を別フィールドで残す。入力位置・Map内絶対出力・producer周期・Loop周期・callback累積位置を混同しない。

この文書は実装方式を記録する。局所GOや実施済み件数は `results/phase62_finish/REPORT.md` と確定manifestだけで判定する。

### PausedのClearと外部IDの移管

Paused/ReadyのClearは、静止Cを固定し通常ExactのCへ再準備する。旧動的commitがあってもcallback静止を確認した停止中置換として旧境界準備を取消し、旧producerは新区間Readyまで維持する。Clear新準備中のResumeは意思だけ保持し、旧ownerのstop/join後に一度だけ開始する。失敗時は旧CとPCMを保持して停止を続け、再要求または明示seekで復旧する。PausedでのLoop解除接続を自然周回へ加算しない。旧FIFOの破棄は `pausedClearDiscardedFrames` と外部要求の `discardedForPausedClearFrames` に記録し、消費・不足・seek・周回へ混ぜない。

最新の未commit速度をClearのExact速度に使用する場合は、その同じ外部IDを `clearContinuation=true` で通常継続へ移管する。開始API成功済みでも実PCM未観測なら移管でき、開始済みの事実を保持する。内部stopped準備の取消で移管先を取消さず、Clear新session/epochの実PCMでCompletedを確定する。Clear待ちを明示seekが置換した場合は元IDを理由付きCancelledとし、以後の位置・速度は新しいseek台帳へ明示的に委ねる。Stop/入力/装置/closeには移管IDの取消免除を適用しない。

ReturnToA初回の採用前にClearされた場合は、通常ownerが既に通常再生を供給しており、Clear継続を作らない。このとき最新未開始速度IDはCancelledへ確定し、通常速度の変更には新しい文脈でsetSpeedを再要求する。候補IDを一時保護してからRequestedの取消とStartedの競合を確定し、実際の新targetも確認して移管可否を決める。Startedの公開とtarget更新の間にも、保持中handoffの新targetを参照してClear継続を失わない。

保存点の保持見積りは従来どおり1状態8MiB、最大16MiBを準備予約内へ計上する。厳密なallocator/RSS上限とは区別する。Loop追加予約24MiBと全体1GiB、RAW上限96000、FIFO16384は拡大しない。

### Clear完了通知と再開意思の確定順

Clearの置換先がReadyになり、旧ownerのjoin・参照解放を終えた後、保持したResume意思があれば通常制御mutex内でstartAudio成功まで進め、それからclearPending=falseを公開する。観測者がClear完了とPausedを同時に見て、開始の成否を判断できない窓をなくす。Resume意思がなければPausedを保つ。開始失敗はFailedとして記録し、成功を装わない。長尺A=0/30/270の既存assertでこの通知競合が再現したため、判定を緩めず実装順を修正した。

### 停止中新速度の失敗と退役中Play

準備失敗を公開した後も失敗版のstop/join中はseekBusyが残る。再開禁止を準備待ちより先に判定し、この窓のPlay/Resumeを拒否する。失敗通知後に新しい再開意思を登録しない。試験では通常workerのRetiringPreparationを止めて窓を固定し、callbackをブロックせずReady・再開意思なし・Play拒否を検査する。
