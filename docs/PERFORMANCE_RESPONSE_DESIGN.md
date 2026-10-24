# 性能・応答の設計

演算精度・位相更新順序・左右履歴・OLA/FIR・TimeMap・確定PCMを維持する。
161速度、品質3dB、Ready200ms、cold AB1000ms、warm AB250ms、期限は不変。
実行owner/保存点各2、既存予約・FIFO16384・RAW96000上限は増やさない。

## B1/B2：観測されない重複計算

PVはlocking＋全bin sharedOwners＋非重複の既存reuseだけで、第一loopの
polarを遅延し、全入力cache確定後の昇順loopで最終polarを一度だけ書く。
phase/低振幅zero/DC/Nyquistを維持し、短ownerやaliasは旧経路を使う。
Coherenceは元のFloat32 abs/argを借用し、double hypotやoutput由来位相は変えない。
viewは入力pointer・bin数・vocoder実体・frame版へ対応付け、左右4組の非重複を確認。
低振幅phaseは読まず、reset/resync/copy/元ownerへの代入復元で寿命を失効する。

## B3：診断hashの設定

内部stage digestと入力identity SHA/最終PCM validatorを分離する。
研究/Golden/Phase57既定はON。native通常再生も最終候補08ではrecordStageDigests=true。
保存05の既定falseは同条件の全体CPU悪化を実測して撤回した。明示falseは研究用で、
CPU改善の承認はない。詳細/worker profile時はONを強制する。
OFF時のoptionalは未測定を表し、hash=0の実測ではない。
checkpointは同じdigest設定を継承し、異設定のruntime restoreを拒否する。
旧文書の「入力digest省略」実験は内部stage hash省略を指していた。入力SHAは省かない。

## D1：先行jobの目的移管

同一generation/session/renderEpoch/A/B/速度/構成のPending/Preparingだけを
明示ReturnToAへ関連付ける。非終端prepのtransferredToLoopIDとLoop側の
preparationRequestIDは別domain。Ready終端行は不変。
実行中configを変えず既存jobを完遂、stop/join/reset後に完全A状態を次ownerへ渡す。
第3ownerは作らない。未移管prewarmのPlay/Pause/Resume取消は維持。
移管後Pauseは音声停止を優先し準備を継続、Resume意思はA準備/退役完了後に採用。
Stop/新入力/異速度/異範囲は最新要求を優先し旧jobを回収する。
準備失敗時はLoopを理由付きFailedとし、勝手に再生/無限再試行しない。

## C3/D3

入力copy/hashは128KiB、Float32有限値検査は16384 sample単位で取消/期限を確認。
受付からの同じdeadlineをconstructorとReady待機へ渡す。mlock前後でも確認するが
OS呼出自体の即時中断は保証しない。途中例外はFD/mapping/lock/予約をRAII回収。
seek時刻はRenderTargetに対応する1indexだけを見て、first PCM/提示推定を一度ラッチ。
明示履歴と全終端監査は保持する。callbackの処理・通知は追加しない。
公開構造変更は契約v4/ContractV4Tagで旧v3実行体との混在をlink時に拒否する。

境界の準備が済み、scheduledBoundaryかつhandoff phaseがRequestedの間だけ、
seekWorkerの再確認に要求する待機を100μsから1msの有界timerへ変更する。実際の起床は
OSのスケジューリングにも依存する。callbackは既存の
atomicで開始/完了を公開し、通知を追加しない。Started後と通常seekは従来の
100μs待機を維持する。最新要求・Pause・Stop・Clearの判定とowner保持・退役barrierは
変えない。1msは通常threadの要求待機時間で、操作遅延の厳密な上限保証ではない。callbackの境界開始は
このtimerに依存しない。採用済みownerをtimer期限で破棄することはない。
CV待機は全体CPUが悪化したため採用しない。mutexを追加しないtimer案の機能回帰と
全体CPUを別に測定する。Pausedの無仕事wait全般を未測定で置き換えない。

初回Aのtarget採用と旧ownerの退役完了を別に追跡する。移管済み先行準備の
Readyは未使用保存点のavailableを再公開しない。Resume意思は初回採用workerが
旧ownerをstop/join/resetするまで保持し、自然Bの待機とは区別する。
Ready成功直後とconfigure完了後にも受付からの同じ期限を確認する。

未採用の明示ReturnToA中に停止中速度で置換する場合、元の実消費Cは採用まで
静止させ、元の明示要求の行先Aを新速度で準備する。sourceの消費座標と
resumeInputFrame=Aを分け、操作理由へ記録する。A採用時に内部停止位置もAへ更新し、
次の速度要求で旧Cへ戻さない。既に採用済みLoopの通常Paused速度準備はCを保つ。
初回採用を置き換えた最新jobも旧ownerのjoin/reset後に開始barrierを解除する。
古い版のcleanupで新しい版のbarrierを解除しない。

## C1：確定座標の共有

旧TimeMap/研究Phase39の算術を維持し、Phase59の公開Mapを不変ページに分ける。
解析延長では確定済みページを共有し、最大5速度のMapPrefixBuilderへ新しい
closed event/anchorだけを渡す。最終ramp終端R以降は、旧submitと同じ整数式
`fixedTarget[i] + current[R] - fixedTarget[R]`で追記する。過去の要求は再submitしない。

速度要求時は通常threadで必要な連続座標を明示復元し、最後の採用generation、
published境界、完了座標をPhase39へ渡す。最新の確定eventsから保護indexを作るため、
旧Map末尾へのclipを誤って永続化しない。公開候補とrollbackはページrootを保持し、
DSPはmailboxが寿命を固定したページをraw参照する。callbackへ所有権操作を追加しない。
全量Mapの明示取得・研究exportは通常threadの操作として残す。

診断モードでは旧方式の全履歴replay/全ノード比較を併走させ、Plan全fieldと
firstChangedNodeを検算する。診断の追加CPUは通常性能の値と混ぜない。
ページ、builder、現行/旧view、rollbackの容量を計数し、既存予算を増やさない。

## C2：解析producerの寿命

InputLeaseが唯一の解析producer、最新不変snapshot、終端/errorを保持する。
render epochは購読と計画だけを持つ。旧epochのstop/joinで解析を止めず、最後の
lease利用者が終了するときに通常threadで取消・joinしてからFD/常駐PCMを解放する。
共有producerのCPUはowner別集計へ二重加算しない。

各epochはconstructor完了からstopの全worker join後まで購読tokenを1件持つ。
未開始の置換先も数えるため、旧ownerを先にstopしてもproducerを失わない。
最後のtokenを返すと取消を通知し、producerが必要とするmutexを保持せずjoinする。
FD/私有snapshot/常駐PCMはInputLeaseの最終破棄まで保持する。producerは唯一の
Phase56解析sessionを持ち、PCM/FIFO/音声callbackを持つ実行ownerにはしない。
各epochのanalysisWorkerは不変snapshotの購読・必要速度Mapの差分変換・plannerだけを
担当する。解析・Map変換ともclosed eventの確定順を維持する。producerの失敗は全購読者が
検出し、1epochの取消・planner失敗は共有解析の失敗へ書き換えない。

通常Exactは対象入力の`floor(C/1024)+1`までの補間ノードが確定した後に開始する。
これはReadyの十分条件ではなく、既存Phase57が3解像度の位相合成・OLA/FIR先読みの
認証範囲を各blockで検査し、不足時は後続snapshotを待つ。速度別Mapは同じ閉鎖eventと
anchorからMapPrefixBuilderへ追記する。末尾N、FastLocal、Loopの完全保存点はfinal待ちを
維持する。通常Exactの改善をこれらの待機削減として集計しない。

`requiredAnalysisAvailable()`はそのepochの必要Map確定、`finalAnalysisAvailable()`は
共有入力全体の解析完了を示す。nativeのanalysisReadyNsは前者を記録する。
診断のanalysisProducerThread/Starts/Received/CpuSは入力世代ごとの共有値であり、
epochのanalysisWorkerCpuS（購読・計画）とは別。終了epochのproducer値はstop時に固定し、
他epochの解析継続で終了監査の値が後から変わらないようにする。

最初の対象位置には閉鎖event・補間2ノードが必要で、3解像度/FIR先読みの不足は
既存NeedsMoreAnalysis/NeedsMoreInputで待つ。未確定PCMを作らない。早期採用後も
snapshotを更新し、旧owner join後の全suffixとEOSを独立RAWへ照合する。
final解析を必要とするLoop/局所初期化の条件は別に扱い、通常seekだけの早期化を
AB/FastLocal全体へ読み替えない。

## checkpointの安全拒否と明示復旧

追加のmono16秒chain素材では、0.50→0.40の動的要求に安全な区間がなく、
旧5674と候補の両方がNoSafeIntervalを返した。これはcheckpoint復元による
Mapの差ではない。元の肯定試験はmix.wavを使い、0.40/1.50へのApplied、
密度切替、Map、復元後の全suffix一致を引き続き必須にする。

専用負例は`phase61_checkpoint_tests INPUT --expect-no-safe-interval OLD_RAW NEW_RAW`。
異速度Mapの誤採用を拒否し、拒否前後の全生成/公開座標・DSP履歴・Map root・
速度履歴を保つ。同速度の再要求もDuplicateとして処理し、残りPCMを独立した
0.50倍固定参照へ照合する。旧合成実体とcheckpointを破棄した後に、別の明示的な
0.40倍固定Exact再準備を行い、全PCMを独立参照へ照合する。

この負例は動的要求を自動的にExactへ変換する製品変更ではない。安全条件を
満たさない動的要求は理由付きで拒否し、既存の確定出力を維持する。新速度の
明示Exact再準備は別の操作・別の状態として扱う。

## mono2倍の全体CPU増加を受けた限定再実験

05の通常steady48と追加固定12の結果、mono2倍は追加n3の全組でCPUが増え、
元n3と合わせたn6でも平均20.243423→20.496426%となった。05一式をCPU改善として
採用しない。C1計画費用やstereo改善・Armed待機の成功で相殺しない。

次の06実験ではPhase35の同じbin処理本体をprivate `template<bool Reuse>`へ移す。
公開processは同じ借用witness失効と同じreuse条件を一度実行し、true/falseへ分岐する。
cache有無と最初のpolar有無だけをコンパイル時条件にして、演算式、昇順更新、
低振幅、DC/Nyquist、alias/短ownerのfallbackを維持する。構造体のlayout・公開API・
保存状態・位相方式・品質Presetは変えない。witnessの失効は省略しない。

変更前に測定条件を固定する。mono48k Float32 300秒、Candidate、2.00倍、同じ
通常client、30秒窓、旧5674/05/06を順序ローテーションで各n3（9実行）。
入力複製と全曲解析は窓前、供給/期限/callback禁止操作/owner回収は同時監査する。
旧版・05の実行体を保存archiveで固定し、06は成功した新buildだけを使う。
全体CPUが改善しない実験は戻す。局所loop速度やFFTだけのCPUで採用しない。

有望な場合だけ156全bit・alias・checkpoint・借用寿命、固定/動的独立参照と、
最終候補の形式/速度別通常CPU・必要なnative代表回帰へ進む。低負荷の未達を
全体中央値へ平均して消さず、実験05と06の実行件数は別台帳にする。

06の固定9実行は完了した。平均CPUは旧20.659297%、05が21.291055%、06が21.169721%。
06は旧より全3組で増加し、05に対しても2減/1増のため不採用・2fileのみ05へ復元。
元の全source SHA0d8d2e86…一致を確認し、実験の実行体・archive・変更元/先を保存した。
156下位全bit PASSは、このCPU採用失敗を相殺しない。

診断専用の旧/05各n3も全6実行・48項目・RTを完了した。process CPU平均は
20.723485→21.247195%、IDを確認したDSP threadは5.815727→5.966722 CPU秒だった。
一方waitCallsは12135→12066へ減った。待機回数増加を原因とは判断せず、
満杯時待機を一律8msへ延ばす案は未実装とする。OSのthread CPUと既存advance区間の
計算CPUを別に記録する最小診断を次に行う。診断集合を通常CPUの反復数に加えず、
稼働中0の終了時worker CPU値を計算負荷0と誤認しない。

追加診断02は6実行/48項目を完了し、advance/公開区間のCPU平均は旧5.635579→
05の5.870450秒、区間外も含む残差は0.118179→0.114664秒だった。採取端点の誤差を
含むため残差を待機CPUとは呼ばない。増加は測定された計算区間に現れる。
そこで07ではPhase57の混合forだけを`renderBlock<bool Digests>`へ移し、設定分岐を
blockの先頭へ移した。旧/05/07固定9実行の平均CPUは21.027914/21.552131/21.711305%。
旧r1はRT=falseで原因未帰属、残り8件はRT=true。07は05比でも2増/1減のため不採用とし、
54保存物とソース05を復元した。checkpoint肯定2件のPASSを性能採用へ読み替えない。
後続は製品を変更せず、同じ保存05でdigest ON/OFFの寄与を確認する。

## 2026-10-24の候補評価確定

現行source08は`b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94`。
通常hashはON。CPU48＋事前固定追加18でmono1倍n6全増加となり、性能一式は不採用。
Phase57分岐特殊化09、hash判定除去のON専用probe10も各9実行で改善を示さず棄却した。
05の時間・RTを08へ付け替えず、Interactive/AB/Paused深部/ABI等の広い08行列はNOT_RUN。
同一実行体による限定再利用は`results/performance_response/evidence/NATIVE08_REUSE_AUDIT.json`
の許可行だけ。現行08のcheckpointは保存済み独立RAWを検証して新規3case PASS。
[確定REPORT](../results/performance_response/REPORT.md)と同ディレクトリのSUMMARY/manifestを参照。
過去の計画・途中結果は残し、局所全体INCOMPLETE、公開WITHHELD、Merodoa既定UNCHANGEDを分ける。
