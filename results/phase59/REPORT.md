# Phase 59 REPORT

判定 **B：条件付き成立、Gate 2未合格**。動的速度変更と同一計画の全PCM一致は成立した。起動時host/sample時計の不連続1件、固定長尺の作業期限超過、旧製品のFIFO不足を観測しており、原因は未特定。後続の成功でこの失敗を除外しない。製品・Merodoaへの統合は行っていない。

## 1. 実装内容

閉鎖イベントから確定prefixを作り、既存Phase39の50ms遷移、L1/Phase50、L2/C、Phase42 safe-densityを共有する。未来情報不足はPendingAnalysis。通常側で作った不変Mapを、同じPhase57 DSPの位相・OLA・FIR状態へ有界に適用する。FIFO容量16384、先行量16384/12288、生成2048、ゲイン0.5を維持した。

TimeMapは入力位置を出力位置に対応させる表、prefixは先頭から確定した範囲、FrontierはDSPの現在の処理境界を表す。PCMは音声サンプル列、FIFOは生成順に渡す有限の音声バッファである。

## 2. 変更ファイル

`src/prototype/Phase59*`、`Phase58RealtimePipeline`、`Phase57ProgressiveSynthesis`、`Phase36SynthesisCore`、`Phase39TimeMap`、研究用Native、診断とメールボックス、CMake、Phase59テスト・検証スクリプト・4文書を追加/変更。共有変更は確定prefix入口と動的モードに限定。基準HEADは `bb22efcbd27f999e8ffe85bbe3f03e20895be3f2`、main。開始時clean。最終実行体/全src SHAは [FINAL_CANDIDATE](FINAL_CANDIDATE.json)。保護対象54461ファイルの変更監査は [protected_assets_delivery](protected_assets_delivery.json)。

## 3. 動的TimeMapの一致結果

全Map node、適用/完了境界、保護区間、密度切替、出力長を独立参照と照合した。旧全曲入口と確定prefix入口は同じsubmit算術を使用。単体検査では168 prefix、両presetの2非最終適用、古い版/入力世代/処理済みnode拒否、取引rollback、公開時bad_allocを確認。実際のDSP Frontierが進んだ候補は再計画し、既使用nodeを変更しない。

## 4. PCM完全一致結果

最終版の決定論的動的検証 **1140条件**。全Float32生ビット、順序、長さ、SHAが一致した。解析保留後は実際の適用Frontierを旧全曲解析＋Phase39/42/50/36へ再現し、元の予定適用位置との同一性は主張しない。

| 試験 | 全PCM条件数 | 結果 |
|---|---:|---|
| priority | 252 | 合格 |
| all161 | 640 | 合格 |
| materials | 88 | 合格 |
| long | 16 | 合格 |
| incremental_chunks | 112 | 合格 |
| incremental_formats | 32 | 合格 |

参照SHAは [FROZEN_REFERENCE](FROZEN_REFERENCE.json) と [CAPTURED_REFERENCE](CAPTURED_REFERENCE.json)。変更前ヘッダー/ライブラリを保存し、基準Gitからの再構築も代表3件で元と一致した。[再構築検査](rebuilt_reference_validation/summary.json)。変更後コード同士のCTestは独立証拠に混ぜない。

旧Phase51の先行全計画Phase35参照との比較では3セッションに1 ULPの差が出た。最初の例はframe66701/channel1、actual3161988845/reference3161988846。全Mapは一致。変更前の動的Phase36でも同じ差を再現し、そちらとの全PCM・Frontier・直近フレーム・OLA重みは3/3一致した。旧参照間の算術差の箇所は未特定。[元の比較失敗を保持した監査](native_reference_scope_audit.json)。許容誤差への変更はない。

## 5. 161速度の実施範囲

全161値を初期・目標の双方で検査。隣接160組×双方向×両preset＝640/640条件、640適用。重点試験には指定15遷移、昇順/降順の連続1%列、0.50/1.00境界、極端な往復、全8形式を含む。最終論理試験の要求上の初期/目標組は652組だが、置換・取消も含むため全組の物理適用とは異なる。25921組、長尺全161値、実機全161値の各初期/目標適用は未実施。

## 6. Latest-Winsと要求状態

最新Pending1件＋実行中1件。旧Requested/Applied/Rejectedと高水準の操作状態を併記。Acceptedは保留受付、低水準送信成功とは区別。Appliedと、callbackが完了座標を越える時点、通常側のCompleted確認も分けた。最終論理状態集計は [MEASUREMENTS](MEASUREMENTS.json)。実機burstでは1024要求×6セッションを検査し、161速度が要求されても全要求を適用したとはしない。512適用履歴・4096操作監査の研究上限、Invalid/Duplicate/Stopped/LimitReached、旧session/入力世代、Stop/失敗時の取消を検査。

## 7. L1/L2/safe-density

Candidateは精密L1＋L2、Baselineは既存境界＋C。保護算術を独自近似に置き換えていない。論理試験でL2保持を含む適用63件、密度切替146件を旧参照と照合。非EOSでは密度候補から32768入力サンプル先まで確定している条件だけを検査する。全7チャンクと非最終合成・適用・解析保留の内訳は各incremental summaryに保存。

## 8. FIFO/Callback

最終版の動的音声セッション **190/190合格**。全PCM/接頭部PCMを別に照合した。

| 条件 | 計測合格/セッション | 全PCM / 接頭部PCM一致 |
|---|---:|---:|
| normal | 30/30 | 30 / 0 |
| load | 90/90 | 90 / 0 |
| lifecycle | 30/30 | 18 / 12 |
| burst | 6/6 | 6 / 0 |
| materials | 30/30 | 30 / 0 |
| long | 4/4 | 4 / 0 |

最終版の不足フレーム0、書込み拒否0、callback期限超過0、HAL逸脱0、host cadence異常0、sample異常0、実時間作業期限超過0。失敗一覧はMEASUREMENTSに保持する。

それ以前のV7 Candidate試験では最初のcallback sample0→1192（期待512）、host間隔24.833ms（期待10.667ms）、余分680frames/14.167msを観測。最初の要求より前に発生。FIFO/PCMは正常でもこの条件は不合格。[時計解析](native_smoke_v2/case_000/native/clock_discontinuity_analysis.json)。追加試験の成功を原因解決の証拠としない。Sandbox内の音声デバイスなし1試行は有効な音声セッションに数えない。

## 9. 実時間CPU・メモリ

Apple M1/MacBookAir10,1、16GiB、macOS26.6.2、Release arm64、内蔵出力72、48kHz/512。専用Audio Workgroup/Mach、実測優先度97、入力常駐。昇格/離脱/復元と最大3メールボックス所有権を確認。実時間C++ new合計0、callback new合計0。C/Objective-C確保全般の計測とは異なる。検証用capture配列とcallback記録配列は開始前に値初期化するが、専用の全ページ書込みタッチやmlockは行っていない。これらの物理ページ常駐やcallbackのVM fault 0を証明したとはしない。

実時間38231ブロックの最大Wall 38.570ms、最大非CPU 0.399ms。Wall−CPUの負値は時刻分解能によるため集計下限0とし、非CPUをすべてPreemptedと呼ばない。操作ごとの全計画試行累計CPU/Wall、要求→Map適用と提示到達の中央値/p95/p99/最大はMEASUREMENTS（ms）。要求→Map適用は中央値31.023、p95 467.883、p99 970.215、最大1114.219ms。全速度で一定時間内の適用保証ではない。

固定Frontier受渡しは4160bytes、監査予約要素は8454144bytes、適用履歴予約要素は86016bytes（STRUCT_LAYOUT、allocator領域別）。

最大RSS 203.91MiB（入力、検証用PCM、診断、128MiB負荷配列を含む）。Map容量推定最大516936bytes、Snapshot計数容量最大795040bytes。allocator総量やOS全体の圧迫とは異なる。最大所有は解析3、Map3。計画試行479、古いFrontier再計画14、解析保留0。

スレッド標本の前後が同じRT生成区間に入ったのは35054ブロック、該当標本がなかったのは3177ブロック。該当標本の優先度は97だった。未標本区間を観測済みとして埋めない。

追加OSトレースの実時間98ブロック中、既知OS状態で全区間を覆えたのは64、34はUnknown/未観測。既知区間でPhaseLocker::analyzePeaks内Zero Fillを1件（5.708µs）観測した。期限違反はなかったがページ割当0とはしない。[観測範囲](startup_trace_known_coverage.json)。元の起動時計異常は再現せず、OS原因は未確定。

## 10. 長尺・高負荷

決定論的180秒/300秒、実機180秒境界素材・300秒自然音反復を両presetで検査。CPU競合2、メモリ128MiB保持、両方、Pause/Resume、途中Stop、EOS近傍、大量置換を分けて保存。動的高負荷の判定は合格、動的長尺の判定は合格。固定長尺での期限超過も含む総合のlong_track_verified/high_load_verifiedはfalseとした。長尺の全161速度やOS全体のメモリ逼迫は未実施。入力SHA、要求位置、適用Frontier、callback、worker、容量計測を各manifest/rowsへ保存した。

## 11. Golden・CTest

Golden 25/25、Release決定論的CTest 91/91（従来88＋新規3）、Debug関連 16/16。その後に制御テストへEOS再始動・EOS保留取消を拡充し、対象1件をRelease/Debugで再検査して合格した。[最新の制御検査](eos_pending_final/summary.json)。機能検査の通常優先度排出と、13節の実時間ストレス失敗を区別する。Debug準備時の存在しないtarget指定2件はログを保持し、正しいtargetを構築して全検査を完了した。TSANおよびASAN/UBSANでFrontier値メールボックスと借用メールボックスの4実行が合格。[競合・メモリ検査](sanitizers_final/summary.json)。

## 12. 既存製品回帰

Phase58固定PCM 6216件、Phase57全PCM 51344件。既存の拒否条件は別に照合した。Phase56、Phase54 cache/seek、Phase39/42/50/51はCTestでも検査。固定速度実機 38/40、従来製品の旧/再構築EOS・smoke 7/8。[既存PCM回帰](regression_final/summary.json)、[初回実機実行](device_final/summary.json)、[容量中断分の再開](device_resume_after_trace_archive/summary.json)。固定長尺180秒/2倍/CPU競合2でCandidateに作業期限超過2件、Baselineに3件を観測した。両方とも全PCM一致・FIFO不足0だが不合格。最長RT生成区間はCandidateでWall/CPUとも約49.541ms、BaselineでWall約48.877ms/CPU約48.877msで、設定周期46.44msを超えた。この区間には大きな非CPU待ちは見られないが、処理内の負荷原因や変更との因果は未確定。[時系列](DEVICE_FAILURE_TIMELINES.json)。300秒の固定速度2件は合格。旧製品の変更前バイナリCandidate smokeでFIFO不足1319フレームを観測し、全PCM一致でも不合格とした。再構築側の成功で相殺せず、因果や原因は未確定。[回帰失敗一覧](DEVICE_REGRESSION_FAILURES.json)。`fifo_underrun_free`はこの旧製品試験も含む実機全体、`dynamic_fifo_underrun_free`は最終動的行列の範囲で分けた。過去の製品host/sample異常の原因解決は主張しない。旧results、Golden、独立参照のSHAを保持した。

## 13. 未解決問題

起動直後の時計不連続1件の原因未特定。最終版の追加失敗はMEASUREMENTS一覧を参照。EOS再始動の追加検査では、実時間workerを音声周期より速く排出したReleaseに約4.8秒の非CPU区間と20秒待ち超過を観測した。周期を付けたReleaseは成功したが、Debugの実時間実行は30秒待ちを超えた。OSの予算制限が疑われるもののOS状態は未取得であり断定しない。失敗はeos_restart_diagnostic*とeos_restart_pacedへ保持。通常優先度へ復元して排出する同一プロセスEOS→別音源Play機能検査はRelease/Debugとも別に検査し、実時間性能とは区別した。旧先行全計画Phase35と動的Phase36の1 ULP差の算術位置未特定。OS状態未観測域と実時間Zero Fillあり。実際のApple API失敗とOS全体のメモリ不足は未測定（昇格前拒否・bad_alloc・計画失敗・解析/DSP失敗・入力置換/削除・取消の注入は検査）。履歴512/操作4096の研究上限あり。

容量はSTART_STATEの予算を使用。新規成功PCMの作業領域は再利用、レシピ/SHAを保存。空き容量低下で動的loadは14条件後、lifecycle/burst/materials/longは音声開始前に当初4GiBの保存下限で中断した。通常30条件と完了済みload14条件は再実行せず、残りだけを再開した。成功済みDebugビルド・派生XML・回帰行データを全バイトSHA照合後に無損失圧縮し、再生成可能な成功PCM作業領域を解放した。[整理台帳](STORAGE_COMPACTION.json)。当初4GiBは作業側の保守的予算だったため、残りの有界な保存量を再確認して再開前に下限3GiBへ更新した。[予算更新](STORAGE_REBUDGET.json)。DSP、速度行列、反復数、FIFO、PCM基準は変更していない。ユーザーの明示許可後、Instrumentsに未保存記録がないことを確認して通常終了し、関連DTServiceHubも終了した。今回の一時ktrace 1475388768bytesを136860552bytesへ無損失圧縮し、復元SHA一致と開放済みを確認して元一時ファイルを解放した。保存済みtrace bundleと過去のktraceは保持した。[圧縮・復元台帳](CURRENT_TRACE_ARCHIVE.json)。取得時のバックエンド一時トレースと保存済みtrace bundleの合計は少なくとも約1.56GBで、当初のトレース予算512MiBを超過した。最終保存量と取得時ピークを分け、予算を守れたとは報告しない。FAIL素材・固定参照・元トレース・旧Phase成果物は保持した。最終量は [STORAGE](STORAGE.json)。

## 14. Gate 2の最終判定

**B、未合格**。同一計画の品質と161速度対応を確認したが、有効な実機試験で時計異常が1件残り、固定長尺の期限超過と旧製品FIFO不足も観測した。後続の成功件数で相殺しない。`realtime_worker_safe`、`realtime_transition_verified`、`gate_2_passed` はfalse。各指標の範囲と最終値は [VERDICT](VERDICT.json)。

## 15. 次Phaseへ進めるか

Gate 3/製品統合へは進めない。次はPhase59 Fixとして起動時計異常を同じ装置・時刻条件で再現し、音声開始手順/装置時刻の原因を特定する。Zero Fillと未観測範囲も調べる。固定180秒/2倍/CPU競合2では、失敗した生成位置での詳細CPU測定と変更前実行体の同条件比較を行う。旧製品smokeのsession2/epoch2、callback270〜272のFIFO不足もOS状態を含めて調べる。PCM品質、参照、FIFO容量は維持する。解決後に同じ失敗条件と負荷・長尺・回帰を再検証する。製品化ではcache付きStop→Play、入力寿命・資源予算、装置/権限/API/UIを別途検討する。
