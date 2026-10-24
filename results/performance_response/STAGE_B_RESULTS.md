# 性能改善 Stage B04 証拠台帳（下書き）

対象は `build/performance_response_20261023_01` の指定16 attempt。Stage B04のsource SHAは `5c3166fe78dbf410d32d06590e334cf77f21e8d032078b1261d0725cbc613928`。**最終候補の結果ではなく、性能目標は未達で、新たな正式承認を付与しない**。旧REPORTと生証拠は変更していない。機械可読の詳細・全参照SHAは [STAGE_B_SUMMARY.json](STAGE_B_SUMMARY.json) に保存した。

B1/B2の局所DSP改善、B3の段階digest設定、C3の入力準備取消・受付deadline、D1の進行中先行準備引継ぎ、D3のtarget時刻確定先index化までの段階。**C1（Map再構築）とC2（finalAnalysis待ち・解析producer寿命）はこの段階では未実装**。後続source、steady旧新比較、D3専用履歴計画の実行結果は本台帳に含めない。

環境記録はMacBookAir10,1、arm64、macOS 26.6.2、16 GiB、AC給電。AB各行の装置値はID 72・48 kHz・512フレーム。これらはnative hostの測定であり、実アプリのservice/native/bridge/UIを通るF計測、人による操作確認、スピーカーからの物理音響測定は未実施。

## ビルドの履歴

|記録|結果|source SHA|実行形式数|
|---|---|---|---:|
|build_baseline_01|PASS|`2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392`|4|
|build_candidate_01|FAIL|`a10d3f6860540e8f32b4a873d1ecf1759ab7d9ed9dc64213082b174731b5f224`|0|
|build_candidate_02|PASS|`e610150775047001eb1f945411a5a00099a5c531e5f4512fdab5775d49cf991a`|17|
|build_candidate_03|PASS|`110645cf3ee11ef2ff1f461a2be9b79f51d1c6386364174211c38ae213f6f2aa`|34|
|build_candidate_04|PASS|`5c3166fe78dbf410d32d06590e334cf77f21e8d032078b1261d0725cbc613928`|34|

全記録はRelease/arm64。旧比較のcommit labelは `5674bd982d98caacaa3e87cdeae5bfc0b01c66ef`、旧ソースmanifestは `2dae7749…`。candidate_01はDSP等価試験内の`equal`と`std::equal`の名前解決衝突でcompile失敗（build exit 2）。製品PCMの比較FAILではなく、失敗記録を保持したまま02以降を別attemptとして扱う。

## 局所機能・数値証拠

|証拠|実測件数と結果|範囲・再利用の条件|
|---|---|---|
|dsp_equivalence_final_01|156/156 PASS、5,052フレーム比較|complex 178,017,236値、float 43,607,357値。全曲PCM・RTは未判定。RESULTはprefix付きJSON行形式。起動binary SHAの単独wrapperがないため、主担当による最終対応付け欄を保留。|
|dsp_bench_01|27/27完走PASS|FFT/FIR/再生を含まないscalar位相・coherence処理だけ。B02記録のbinaryはB04と同一SHA。|
|input_final_02|12/12 program、110/110 check PASS|6 mode×両Preset。通常workerで取消・Stop・close・新入力・deadline・Ready直後deadlineを検証。source B03、対象binaryはB04と同一SHA。|
|preparation_final_01|34/34 program、272/272 check PASS|17 mode×両Preset。同一Preparing引継ぎ、Pause/Resume/Stop/速度/範囲/入力/close等。source B03、対象binaryはB04と同一SHA。|
|dynamic_formats_01|PCM 32 session PASS、解析不足保留20 session|44.1/48 kHz×mono/stereo×PCM16/Float32、7 chunk形式。非最終解析PCM/plan各32、nonfinal plan72。各単位を足して試験数にしない。対象binaryはB04と同一SHA。|
|fixed_digest_smoke_01|48 reference group、192/192 PCM比較PASS|8形式×3速度×両Preset、digest on/off×chunk1024/5003。有限float32全bit一致のsmoke。全161速度・実機音質の代用ではない。source B03、対象binaryはB04と同一SHA。|

機能用gateは通常workerだけでcallbackを停止していない。上記二つのnative機能試験のowner peakは2以下。異なるsourceの再実行件数へ付け替えず、B04の対象実行形式SHAが一致することを再利用根拠とした。異種のcase/program/check/PCM値数に総合PASS件数を付けない。

## DSP局所CPUの記述統計

各セルはn=3の平均process CPU秒。512フレーム/条件で旧5674 frozen、B1、B1+B2を同一process内で順序交替した。減少率は平均の比で、因果的有意差や全体再生CPUの改善率ではない。

|FFT|旧CPU秒|B1 CPU秒|B1+B2 CPU秒|B1減少率|B1+B2減少率|
|---:|---:|---:|---:|---:|---:|
|1024|0.041708|0.040066|0.033145|3.94%|20.53%|
|4096|0.238991|0.226981|0.209608|5.03%|12.29%|
|8192|0.518959|0.499169|0.469458|3.81%|9.54%|

## 旧版の性能基準値

`baseline_stereo120_02`は120/120完走、監査22/22 PASS、機能/RT PASS（差分・寿命カウンターとも0）。ただしInteractive Readyの全120操作p95 **210.111 ms > 200 ms**で性能目標FAIL。Preset別Ready p95はBaseline 196.012 ms、Candidate 211.429 ms。旧版の測定であり、候補のInteractive合格とはしない。PCM品質は未測定。

`baseline_cpu_01`は旧hostの2 program・10窓が完走。plain 8窓と計測ONのattribution 2窓は別条件で、同一clientによる旧新比較ではない。RT承認はNOT_ASSESSED。CPUは`100×process(user+system)秒差÷wall秒差`、1コア=100%。

|旧plain窓|CPU %|実窓 秒|interrupt wakeup|
|---|---:|---:|---:|
|unprepared|0.512|10.141|3559|
|off1|14.715|30.065|24105|
|off2|15.277|30.025|23998|
|off3|15.281|30.030|23858|
|loop2s|3.259|30.175|25893|
|loop30s|17.713|30.007|23651|
|paused|1.393|30.024|23131|
|stopped|0.626|30.064|10668|

## AB比較attemptの区別

|attempt|完走|整合性|RT|採用する扱い|
|---|---:|---|---|---|
|ab_pairs_01|0|親Pythonがx86_64で事前停止|未測定|NOT_RUN。nativeの測定FAILに換算しない。|
|ab_pairs_02|48/48|fresh 12行のpreparing_at_on誤出力でFAIL|48/48 true|実prepなしの既定Pendingをtrueにしたclient観測不整合。値を訂正せずattemptを保持。|
|ab_pairs_03|48/48|48/48 true|48/48 true|fresh観測boolを直した同一client旧新比較。cold目標FAIL。|

AB03はmono48 kHz/300秒、CandidatePreset、速度1.0、100 ms AB、Playing/C=0、各層n=3×両版。freshは未訪問・保存点なし・事前準備なし。prewarmは完了後、early0は準備開始直後、midはA30で500 ms/A270で2,500 ms先行してON。奇数反復は旧→候補、偶数反復は候補→旧。同一client SHAは `f217906c1d35b0da93ddaaf39f42b65bf23d8bc4faac5159c569806f8a1e351e`。

## ON受付→最初のA：待ち時間だけの表

native受付時刻から新epoch最初AのRAW観測まで。ON前の先行費用は含めない。p95は`(n−1)×0.95`で線形補間した標本値で、n=3は記述統計。独立PCMの最終照合・物理音響の判定ではない。

|A 秒|段階|旧 p95 ms|候補 p95 ms|候補 標本SD ms|目標 ms|候補判定|
|---:|---|---:|---:|---:|---:|---|
|30|fresh|1327.893|1156.212|47.726|1000|FAIL|
|30|prewarm|19.908|19.036|1.651|250|PASS|
|30|early0|1250.358|1248.216|90.821|1000|FAIL|
|30|mid|1207.049|688.150|70.170|1000|PASS|
|270|fresh|10480.394|9969.721|158.030|1000|FAIL|
|270|prewarm|18.686|17.931|1.593|250|PASS|
|270|early0|10461.847|10680.791|508.955|1000|FAIL|
|270|mid|10364.647|7326.910|136.259|1000|FAIL|

完了prewarmは両Aで250 ms以内。候補midのON待ちは小さくなるが、ON前に使ったCPUと壁時間は下表へ残す。freshはA30/A270とも1,000 msを超え、cold条件の達成を宣言できない。early0も両Aで未達。

## 先行準備を含むCPU費用（壁時間と加算しない）

各値はn=3の平均CPU秒。合計はON前＋ON後だけ。初期input prepareを除き、通常threadでfirst Aを確認するまでのprocess全threadの費用を含む。全process列は起動・初期prepare・後続周回・停止も含むwait4値で、合計列と重複するため足さない。取消prefix単独CPUはnull/未分離であり0ではない。

|A 秒|段階|版|ON前 CPU秒|ON後 CPU秒|合計 CPU秒|全process CPU秒|
|---:|---|---|---:|---:|---:|---:|
|30|fresh|old|0.000004|1.363388|1.363392|1.827243|
|30|fresh|candidate|0.000004|1.246004|1.246008|1.714538|
|30|prewarm|old|1.322338|0.014753|1.337092|1.815039|
|30|prewarm|candidate|1.213923|0.012555|1.226478|1.692802|
|30|early0|old|0.001239|1.356195|1.357435|1.842285|
|30|early0|candidate|0.001313|1.283661|1.284974|1.779196|
|30|mid|old|0.573361|1.325872|1.899233|2.366595|
|30|mid|candidate|0.575152|0.684471|1.259623|1.736138|
|270|fresh|old|0.000004|11.839738|11.839742|12.334100|
|270|fresh|candidate|0.000004|11.124278|11.124282|11.601728|
|270|prewarm|old|11.961479|0.013974|11.975452|12.480165|
|270|prewarm|candidate|11.086101|0.013219|11.099321|11.591116|
|270|early0|old|0.000863|11.906578|11.907441|12.387738|
|270|early0|candidate|0.001065|11.308869|11.309934|11.777275|
|270|mid|old|2.789903|11.824790|14.614693|15.110088|
|270|mid|candidate|2.785067|8.219131|11.004198|11.484086|

## 壁時間の区間（CPU秒とは別）

各値はn=3の平均ms。先行壁時間は先行要求直前→ON呼出し直前。ON後壁時間はON呼出し→通常threadのfirst A確認で、上のnative受付→RAWと観測点が違う。初期Ready/解析完了はともにinput prepare開始を起点とする累積到達時間なので、二つを足さない。CPUは並列threadの実行時間を加算するため壁時間を上回ることがある。

|A 秒|段階|版|先行 壁ms|ON後 確認壁ms|初期Ready ms|初期解析完了 ms|
|---:|---|---|---:|---:|---:|---:|
|30|fresh|old|0.005|1233.659|505.344|505.353|
|30|fresh|candidate|0.005|1112.781|499.154|499.163|
|30|prewarm|old|1148.066|18.166|507.362|507.374|
|30|prewarm|candidate|1073.528|17.746|493.478|493.487|
|30|early0|old|1.355|1215.089|523.388|523.396|
|30|early0|candidate|1.361|1168.363|600.978|600.985|
|30|mid|old|504.340|1170.250|489.845|489.854|
|30|mid|candidate|507.489|619.960|527.273|527.281|
|270|fresh|old|0.005|10410.544|512.176|512.184|
|270|fresh|candidate|0.005|9866.510|481.538|481.545|
|270|prewarm|old|10684.883|17.521|519.481|519.488|
|270|prewarm|candidate|9913.481|17.164|488.950|488.959|
|270|early0|old|1.341|10427.049|494.421|494.430|
|270|early0|candidate|1.349|10189.154|478.991|478.999|
|270|mid|old|2505.414|10270.058|505.619|505.627|
|270|mid|candidate|2504.189|7245.495|475.172|475.180|

## 未達・未測定と最終統合欄

cold AB 1,000 msと旧Interactive Ready 200 msの性能目標は未達。C1/C2は未実装。scalar DSP、有限PCMの一致、機能gate、nativeのRT成功は、それぞれの検証範囲に限る。アプリF、人の操作、物理音響、全161速度の最終品質、AB独立PCMの主担当最終監査は本台帳で合格としていない。既存Exact方式承認の条件・旧採用台帳は書き換えない。

|最終統合項目|主担当追記欄|
|---|---|
|最終source SHA / build|未確定。この文書のB04と混同しない。|
|後続steady・D3・C1/C2・回帰|本台帳対象外。最終記録へ別途対応付け。|
|独立PCM / アプリF / 人 / 物理音響|未確認・未測定のまま。|
|最終判断・承認|未記入。新たなGO/正式承認なし。|
