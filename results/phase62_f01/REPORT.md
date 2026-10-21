# Phase62 F01：初回供給jobと要求IDの同期修正

**限定局所判定：PASS / GO。一般公開・Merodoa既定採用：NO-GO。** F01は旧観測版4/4本で実採用と台帳の不一致を再現し、修正版10/10本・64/64 checksと必要な影響回帰を完了した。変更後Engineの実出力41本、その内数の正常RT8本もPASS。今回の局所完了、一般公開、Merodoa既定採用は下記で個別に判定する。

対象はTimeStretchLabのみ。開始時はmain@b0352c6f4c22f100f161297769b26561dc07701b、未コミット差分なし。終了HEADも同じで、今回のコード・試験・文書・証拠は未ステージ・未コミット。push・PR・履歴書換えは行わない。Merodoa本体・UI・submodule・ピッチシフトは変更していない。

原本の基点Bは `/Users/taro252/Docker/TimeStretchLab/build/phase62_f01_20261021_01`。入力、RAW、trace、全ログ、隔離比較ソース、実行体をGit管理外へ保存した。過去のe5レビュー、装置復旧前後の成功・失敗runは保持する。

## ソース・環境・入力・参照

|項目|識別|
|---|---|
|基準HEAD／開始ソース一覧|b0352c6f4c22f100f161297769b26561dc07701b／cefdb1294e89cb5280ad8f6df401eac59825212334e4110f958ca6f0d7c0199c|
|今回の最終ソース一覧|272b9a4da27ff86993993e03ade356a4b64705cce717228366ca40254bd490d1。CMake・src・tests・scriptsの733ファイル。文書・証拠はARTIFACTSで別途識別|
|製品／試験の差分|Engine.hの通常試験点追加・コメント、Engine.mmの公開区間移動、Phase62AdoptionReviewNative.cppのF01。共有DSP・planner・renderer関数本体・CMakeは無変更|
|ビルド|BUILD_CANDIDATE_01。Apple clang21.0.0、CMake4.3.3、C++20、Release/arm64、-O3 -DNDEBUG。Debugはstrict_builds/debug。FP条件の追加変更なし|
|実機|Apple M1 / MacBookAir10,1 / 16GiB、macOS26.6.2。shellはRosettaでx86_64表示、実行体はarm64。実装置・rate・bufferは各観測とguardに記録|
|Python|NumPy付き既存Python3.12。各EXPECTEDにinterpreterとdriver SHA|
|必須mix入力SHA|789d4c159e35b4c133a17913ad5a9c47b85970185e5d86b074d146afc1bb311e。44.1kHz/stereo/Float32/10秒|
|動的参照binary SHA|1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818。bb22efcbd27f999e8ffe85bbe3f03e20895be3f2由来の523ソースを照合|
|固定参照binary SHA|de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748。旧Phase36 ec087由来|

[SOURCE_DELTA](SOURCE_DELTA.json)、[SOURCE_MANIFEST](SOURCE_MANIFEST.json)、[BUILD_PROVENANCE](BUILD_PROVENANCE.json)、[MANIFEST](MANIFEST.json)、[ARTIFACTS](ARTIFACTS.json)で、基準SHAだけでは表せない未コミット状態と実行体を識別する。

## 再現した順序と最小修正

旧比較版はb035のEngineへ観測・順序制御hookだけを加え、共通の新試験を使った隔離版である。純未改変b035 binaryや独立DSP oracleとは呼ばない。比較ソース一覧SHAは1c7d096f775baad3b25e1c3b33e29e0150e15b4680aeda6ac02b259b3cb27e0f、比較binaryはe92762bbce17aa485b34a76bb14ccf49e21b641a1c5f79a9a7a3110f7fea23d0、修正binaryは919e7db68bb690cc4753fefa1801d5cc79233801e75a2435359324505603f030。比較差分と共通試験・入力SHAはB/baseline_01/EXPECTED.jsonとBUILDに記録した。

PlayingのKeepPosition初回で自己反復がない状態を作り、job選択前に通常APIからA=75%（ID2）、選択・next構築後／start前の最初のmutex解放直後にB=200%（ID3）を受理した。ゲートはmutex外の通常workerだけを有限待機させる。callbackを止めず、状態フィールドを試験から終端へ書き換えない。

|両Presetで確認した条件|入力世代／選択版|初回Bのcallback frame|A実採用session／epoch|最初の実RAW区間|旧A／修正A／後続B|
|---|---|---:|---|---|---|
|全曲240ms、通常producer dspDone＋未消費FIFO|1／2|10,584|2／3|[0,236)|Replaced／Completed／Completed|
|全曲1秒、実normal checkpoint permit拒否|1／2|44,100|2／3|[0,118)|Replaced／Completed／Completed|

このcallbackFrameはrender側の連続出力座標であり、fixtureの出力rateは44.1kHzである。実deviceの48kHzフレーム、HAL推定提示時刻、物理音響の開始時刻とは分ける。選択版2はjobのseekVersionで、旧比較の外部行はPreparing公開前のため準備版0だった。

旧版では選択jobが存在してもactive IDはまだ0で、BがAをReplacedへ進めた。その後Aの供給版は初回Bに実採用されたが、terminal guardのため台帳はReplaced・採用session/epoch未記録のまま残った。4子は各7 checks中4件を完了後、この不一致でexit1/FAIL。親のPASSは旧不具合の再現成功だけを表す。PCM欠落、可聴ノイズ、音質劣化をこの観測へ付け加えない。

修正版はnextの有効構築・enable後、最初のEngine mutex内でactiveLoopSpeedRequestIDと非終端Preparing・準備版・時刻を公開する。Bがmutexを取得できる時点では、採用され得るjobの保護IDも公開済みになる。Loop／Loop内seek／stoppedの共有接続点を修正し、start・待機・stop/join・退役はmutex外に維持した。構築例外はID公開前、取消・失敗等は既存の版失効と共通cleanupで回収する。

保護をcommitやPCM開始と誤記録せず、Aの実採用Completed、後続Bの実PCM付きCompleted、B適用後のA履歴全フィールド不変を確認した。補助6本では選択直後のStop/ClearはA/B Cancelled、Workgroup参加失敗はA Failed・B Cancelled。owner全退役、新入力世代のprepare、回復要求CのResume前ReadyForResume・明示再開・Completed、直接close後の全3 IDと理由を確認した。詳細は [CONTROL_COVERAGE](CONTROL_COVERAGE.md)、[設計](../../docs/PHASE62_F01_DESIGN.md)、[検証手順](../../docs/PHASE62_F01_VALIDATION.md)、[F01_CERTIFICATE](F01_CERTIFICATE.json)。

## 検証台帳

事前宣言はB/VALIDATION_PLAN.jsonと各EXPECTED。新runと限定再利用を分ける。後続の確定結果は [GROUP_RESULTS](GROUP_RESULTS.json) に保存する。

|群|期待数|今回の実施・結果|保存先・制約|
|---|---:|---|---|
|旧F01実不一致の再現|4 program|4/4再現成功。各子FAILを保持|baseline_repro_01。通常PASS数へ加算しない|
|F01修正版|10 program／64 checks|10／64 PASS|f01_fixed_01。主4本＋取消/失敗/close補助6本|
|既存adoption／fault／部分混合|28 program／154 checks|28／154 PASS|regressions_01、A1/A2/D09/Internal4096を含む|
|control／Playing／独立API／PausedClear／Race|47 program／172 checks|47／172 PASS|regressions_01。cache12は下の限定再利用|
|Release／Debug必須CTest|各20、6 stages|各20/20 PASS、6/6 stages完了|strict_01、skipped/failure=0。証拠検証器75単体を含む|
|凍結参照同一性|10 checks|10/10 PASS|REFERENCE_VERIFIED_01。新しいPCM比較数ではない|
|境界／独立handoff|872 checks／6 program|872／6 PASS|renderer_01。184＋368＋128＋192、handoff6は別単位|
|native5群|41 program|41/41 PASS|native_01。14＋8＋4＋2＋13|
|正常RT（nativeの内数）|8 program|8/8 PASS|A=0/30/270秒×両Preset、100ms/速度2.00/4100周×両Preset|
|動的全161速度／重点／形式|640／20／54 program|旧PASSの限定再利用|実行source cefdb129…、全161値の実適用・独立planner/Map/RAW判定を維持|
|固定Exact／Golden／有限／reuse|896／25／322／322|旧PASSの限定再利用|実行source cefdb129…、変更後DSPから参照再生成なし|
|worker／cache|8 program・48 checks／12 checks|旧PASSの限定再利用|実行source dfcd0562…／795dd66a…を維持|
|物理loopback／人の試聴／Merodoa実統合|別公開ゲート|NOT_RUN|今回の局所GOへ含めない|

再利用監査は [REUSE_AUDIT](REUSE_AUDIT.json)。7対象実行体の新旧SHA一致、116 project依存、385 Python source、import閉包14、compile/link条件、旧run固有sourceと適用先272b9a4d…を確認した。Exact8入力・896行・112凍結参照ログ、Golden5入力・25保存参照WAVと固定suite入力もSHA接続した。Engineを含む新binaryへ旧「28点不変」を転用しない。Engine.mm直接includeのrenderer翻訳単位は再実行に分けた。

監査途中には全曲RAWとseek suffixのSHAを同一視した監査式の誤りがありFAILを保存した。部分と全曲を区別する式へ訂正した最終監査はPASS。旧PCMを新たに生成・上書きしていない。初回PASS・途中FAIL・各recipeはB/reuse_audit_history_01/02と最終監査の履歴連鎖に残す。

F01と故障注入の正常RT承認はNOT_ASSESSED。製品RAWの加工検算は独立DSP oracleと呼ばない。新しい通常API・nativeの独立参照比較と、ゲートなし正常8条件の供給・期限判定を別々に確認する。実機で選べないcallback分割を実機実施と表記しない。

最終集約は各EXPECTEDのID一意完全一致、完了marker、各行exit/timeout、子summaryのSHAと値、F01必須観測とclose全3IDを再検査する。Race2本は実行開始前にB/RACE_EXPECTED_01.jsonへ既存8 case ID・実コマンド・binary SHAを補助宣言し、observationsの全IDと失敗/未完/再現数0を最終集約で照合する。親の総数だけで完了としない。

seek機能試験の今回のworker期限観測はCandidate通常/R0が各0、Baseline通常/R0が各1、callback期限観測は4本とも0だった。4本44 casesは機能PASS、RT承認は全てNOT_ASSESSED。旧記録のCandidate通常1件とは異なる今回の値をそのまま残し、発生case・処理区間・根本原因や一般無退行は推定しない。[FUNCTIONAL_DEADLINE_OBSERVATION](FUNCTIONAL_DEADLINE_OBSERVATION.json)に各原本SHAを対応させ、正常RT8本へ混ぜない。

## 既存完了項目と今回の判定

b035時点の局所PASS、D01〜D11、装置復旧後41本／正常RT8本のPASSは歴史的記録として維持する。今回の新runと混ぜず、過去の「検証時未コミット」等の記述も書き換えない。F01で影響するA1/A2/D09、全ID・直接close、部分混合、失敗版退役、Paused/Clear/Raceは新Engineで再評価する。D07のH≤1<512、D08のd-c≤44<64と下位上限・古cycle拒否は前提不変で維持し、上位で到達不能な枯渇試験を再開しない。

過去の [e5レビューREPORT](../phase62_e5_review/REPORT.md) と機械証拠は当時のsource／runの記録である。旧ARTIFACTSはb035に保存された当時の内容を識別するもので、今回変更したソースやHANDOFFの現状を識別する索引には流用しない。

|判定対象|判定|
|---|---|
|b035で報告済みの限定局所試験|既存PASSを維持。新実行件数へ付け替えない|
|F01再現・修正本体|再現4/4、修正版10/64 PASS|
|今回差分を含む限定局所完了|PASS / GO：F01と本書の必要回帰・正常RT条件を完了|
|一般公開|NO-GO：下記公開ゲートが残る|
|Merodoa既定採用|NO-GO：実アプリ受入が残る|

allowExperimentalLoops=false、publicLoopApproved=false、Capabilities.seek=false、currentCycleSpeedChanges=false、publicSeekApproved=falseを維持する。1GiB既存予算、追加予約24MiB、FIFO16384、RAW96000、最大2実行DSP／2checkpointを増やしていない。callbackへ確保/解放、mutex、join、I/O、planner、FFTを追加しない。個別動的検出器がない禁止操作まで検出済みと主張しない。

## 正常RT8本の今回の統計

長尺は48kHz/stereo/PCM16、3秒区間・速度1.00。短周期は必須mixの44.1kHz/stereo/Float32、入力100ms・速度2.00。device72、48kHz、buffer512で直列実行した。値は新runの原本から取得し、coldとwarmを分ける。

|条件|実消費周回|周期frame|Ready ms|cold prefix秒|warm破棄frame|warm FFT|worker生成|
|---|---:|---:|---:|---:|---:|---:|---:|
|longA_0_candidate|4|144000|685.129|0.014565|0|0|2|
|longA_30_candidate|4|144000|3901.180|3.222335|1024|0|2|
|longA_270_candidate|4|144000|31676.487|30.998900|1024|0|2|
|stress_4100_candidate|4100|1804|40.458|0.034666|0|0|2|
|longA_0_baseline|4|144000|711.185|0.014288|0|0|2|
|longA_30_baseline|4|144000|3916.442|3.243432|1024|0|2|
|longA_270_baseline|4|144000|30118.518|29.436221|1024|0|2|
|stress_4100_baseline|4100|1804|39.718|0.033871|0|0|2|

正常8本のmissing/padding・非有限PCM・RAW/境界監査エラー、callback new/malloc/free、callback/worker/最終退役統計の期限超過、Workgroup異常は全て0。warm FFT再生成0、worker生成2。A=30/270のwarm破棄1024は既存上限内であり、0とは記録しない。生成先読み周回を実消費4100周へ加算しない。外側と故障試験のguardでbuffer512と既定device72の復元を確認した。

[NATIVE_NORMAL_RT](NATIVE_NORMAL_RT.json)に全測定値、[GROUP_RESULTS](GROUP_RESULTS.json)に5群の必須IDと完了統計を保持する。上記のcold Ready約30秒を、既存のstereo Ready目標達成とは扱わない。Debugの機能回帰PASSもDebug一般RTや物理提示時計の承認へ広げない。

## 次の公開課題と閉じる条件

|優先|次作業|具体的完了条件|
|---:|---|---|
|1|seek機能試験のworker期限観測|旧Candidate通常1件と、今回Baseline通常/R0各1を、発生case、session/epoch、処理区間、worker時刻とFIFO供給へ対応付け、計測誤分類か実負荷かを特定。採用mode別に修正・再測定し、正常RTの独立条件を通す。集計値の一致・相違だけで原因や一般無退行を判断しない|
|2|FastLocal長尺|要求modeと実採用mode、fallback理由、実PCM/位置/期限を記録。実FastLocalの対象範囲を独立参照と比較して承認する。Exact fallback成功はFastLocal承認へ数えない|
|3|stereo Ready目標・長いA|Readyの対象指標とcold/warmを分ける。A=270秒のcold prefix再構成時間と既存Ready目標を混同せず、対象形式・速度・準備方式ごとに所定目標を満たす|
|4|開始時計・提示時計|callback座標、HAL推定提示時刻、物理音響の意味・誤差・許容値を定義し、測定で照合。callback成功だけで物理開始を承認しない|
|5|物理loopback・試聴|入力fixture、接続/レベル/遅延校正、録音照合、異速度境界/seek/Clearの聴感項目と記録様式を用意し実施。人の試聴は実施者・条件・所見を記録し、Codexが聴いたとしない|
|6|Merodoa実TCC／security scope／bookmark／UI|実アプリで初回選択、拒否/取消、再起動、曲変更、装置変更を試験。全owner join後のscope解放、古い完了の遮断、最新要求とUI一致、全Accepted ID終端・過去不変を確認|

Merodoaへ渡すAPI・状態はLoopSpeedReceipt、全ID履歴、Resume前ReadyForResume、実PCMのsession/epoch/位置、直接close後FinalLoopSpeedAudit。AcceptedをReady/Completed表示に使わない。必要な初回供給Aを保持し、最新Bは採用後に進み、最新要求ID・入力世代・Loop・停止C・準備版を照合する。失敗版退役中の再開拒否、最大2所有者、FD/InputLeaseを全joinまで保持する契約も受入へ含める。Merodoa自体の変更は別作業とする。

## 再実行と容量

実コマンドと合格条件は [検証手順](../../docs/PHASE62_F01_VALIDATION.md)、`recipes/`、Bの各EXPECTEDへ保存した。新しい一意のoutputを指定し、既存runを上書きしない。入力・凍結参照の復元は既存Phase59/61とe5レビューの手順を使い、簡易入力で必須ゲートを代用しない。

新規Git対象はすべて50,000,000 bytes未満。ARTIFACTSが変更一覧・SHAとサイズを記録する。今回ステージは作らず、容量検査の読取り確認のみ行う。重要証拠の削除、履歴書換え、LFS移行は行っていない。
