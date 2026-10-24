# Progressive正式採用計画（D-1）

状態は **IN_PROGRESS / 実装・途中検証整理 v0.2**。契約v3と明示Loop先行準備は実装済みで、下表の範囲で機能実証が進んでいる。品質・通常実時間・性能・接続の未達を残し、包括的な正式採用とリリース許可は未確定である。新しい方式engineapprovalはExactだけtrue（数値・所有権の条件付き範囲）、Interactive / nativeLoops / currentCycleSpeedはfalse。Exactの方式承認を通常RT性能・アプリF・音響の承認へ広げない。正式承認は機能別に行う。過去のFAIL／NO-GOは当時の対象・実行体・条件に属する証拠として保存し、今回の正式採用に向けた実装を禁止する根拠にはしない。

## 開始点と証拠の置き場

- 基準commit：`f4f0e6187a643d9442216df87c04353eda4934e5`。開始時clean。
- ブランチ：`codex/progressive-adoption`。
- 作業先：`/Users/taro252/.codex/worktrees/progressive-adoption/TimeStretchLab`。
- 新しい生証拠の基点B：`/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01`。
- 開始原本：`B/INITIAL.json`。文書作成時に読み取ったSHA-256は `34633d7979fa4b626929efaeca31b540e460043708105c0e3e4d9578bd279c37`、2,722 bytes。最終集計時にも主担当が照合する。
- INITIALに記録されたMerodoa HEADは `c6ed9251fe6e6bb518039aa03332794dd72cea0c`、依存TimeStretchLabは上記基準commit。接続先の更新・既定化・配布は、この計画だけでは実施済みとしない。

既存REPORT、入力、Golden、manifest、原本SHA、凍結参照は変更しない。新しい実行は未使用の出力先へ保存し、旧失敗を成功結果で上書きしない。具体的な識別・実行・検証方法は [採用検証手順](PROGRESSIVE_ADOPTION_VALIDATION.md) に定める。

## 初期の実証範囲

| 項目 | 今回の範囲 |
|---|---|
| 実機 | Apple M1 / MacBookAir10,1 / macOS 26.6.2、arm64実行体 |
| 初期の音声装置 | 内蔵スピーカー、48,000Hz、buffer 512 frames |
| 製品入力 | Merodoaのデコード経路から得るFloat32 WAV、44,100/48,000Hz、mono/stereo |
| 入力の互換性 | 既存PCM16対応を維持する。Float32だけの成功でPCM16回帰を省略しない |
| 速度 | 40〜200%、1%刻みの161値、Baseline / Candidate両Preset |
| iOS | 共通ヘッダー等のコンパイル回帰。iOS音声実装・実機承認は追加しない |
| 資源 | 実行owner最大2、完全保存点最大2、FIFO 16,384、RAW/program 96,000、予約上限1GiBの内側に既存24MiB共有枠を含める |
| 範囲外の扱い | 未検証の機種・OS・装置・bufferを保証対象へ広げない。追加条件は別行・別証拠で承認する |

ownerはDSP状態・FIFO・plannerを持つ実行所有者、保存点は実行を止めた完全なDSP状態を指す。2個の保存点を2個の実行ownerと混同しない。Pythonや起動shellのx86_64表示と、製品binaryのarm64確認も分ける。

## 今回の確認結果と非採用案

以下はB内のSUMMARY / AUDIT / BUILD / INITIALだけから整理した途中結果。PASSの範囲と製品採用を分け、旧原本・凍結参照・SHAを変更しない。

| 証拠 | 保存先 | 確認結果 | 範囲・未達・採否 |
|---|---|---|---|
| E01 | [native_all_mono_01/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/native_all_mono_01/SUMMARY.json) | 44 programs / 352 checks PASS、48kHz mono 16秒、22 modes × 両Preset | 品質gate=false / RT gate=false。source d9ddeb137b4be72ea521c353efdde6b89b3c4028d792ae2ce310e47c532c9d35。最終通常lead版の承認へ転記しない |
| E02 | [quality_baseline_known26_01/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/quality_baseline_known26_01/SUMMARY.json) | 102/102構造検証完了、24対照PASS / 78品質FAIL | 既知local品質の基準再現。品質閾値を保持しInteractive未達を閉じない |
| E03 | [quality_phase_replay_known26_01/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/quality_phase_replay_known26_01/SUMMARY.json) | 個別34件全bit一致の実験、集計INCOMPLETE、source_unchanged=false | 実行中repo変更で完了判定不可。Ready約7〜19秒、保存群別p95約9.52〜19.29秒。製品不採用 |
| E04 | [native_baseline_stereo120_01/AUDIT_01.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/native_baseline_stereo120_01/AUDIT_01.json) | 120/120完了、機能/RT PASS、Ready p95=213.09775175ms | 200ms未達、品質UNMEASURED、総合性能FAIL。最終版の結果ではない |
| E05 | [native_candidate_stereo120_01/AUDIT_01.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/native_candidate_stereo120_01/AUDIT_01.json) | 120/120完了、Ready p95=194.200425ms、遅延項目のみPASS | worker期限超過delta合計2件、機能/RT FAIL、品質UNMEASURED、性能FAIL。8192案撤回 |
| E06 | [prewarm_focus_pcm_audit_01/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/prewarm_focus_pcm_audit_01/SUMMARY.json) | 5/5 PASS、mono 48,128 RAW/output framesの独立Map/全bit/座標/gain設定検査 | 代表1件。stereo/全速度/通常RT/F/物理音響の承認を含めない |
| E07 | [no_digest_comparison_01/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/no_digest_comparison_01/SUMMARY.json) | 各side 5 process、30+30 PCMの30対全bit一致。CPU中央値2.826435→2.725057秒、約3.59%減 | 実験限定・非採用。入力digest省略を製品仕様へ導入せず、品質/性能ゲートも代替しない |
| E08 | [build_candidate_05/BUILD.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/build_candidate_05/BUILD.json) | Release / arm64 build PASS、source 8a17ac261f20470b6cfb3c00bbb3c0eb7c11ece0d63e1bfefbc7c44985dc8b58 | 通常lead維持の途中候補build。build成功を品質/通常RT/正式承認にしない |
| E09 | [regressions_01/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/regressions_01/SUMMARY.json) | 21 programs実施、全体INCOMPLETE。pure contract/Phase60/61/ledger/sync/fast_seek state、initial/prefix両形式両Preset PASS | 停止速度/summaryは不適fixture、inputwatchは16秒>12秒制約、limitはsandbox装置不可。失敗記録保持、E10で必要7件のみ再実施 |
| E10 | [regressions_02/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/regressions_02/SUMMARY.json) | 指定fixtureと装置権限で7/7 programs PASS。停止速度、summary24×2、inputwatch26×2、実4096上限10×2 | limitは旧Engine全4096終端+新Engine ID1回収、owner_alive=0/peak<=2。無再生API検査を音声/性能合格へ加算しない |
| E11 | [native_all_mono_03/SUMMARY.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/native_all_mono_03/SUMMARY.json) | 44 programs / 352 checks PASS、execution/full_suite_complete=true | 通常lead維持版build06/source a43d3c5e328cb488c632808cc06553adaef6d015d6c44f14d4e329149173e73a。quality/RT gate=false、Exact方式承認前の機能結果 |
| E12 | [build_candidate_06/BUILD.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/build_candidate_06/BUILD.json) | Release / arm64 build PASS | 通常lead復元後、E11の実行体sourceを固定 |
| E13 | [build_candidate_07/BUILD.json](/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01/build_candidate_07/BUILD.json) | Release / arm64 build PASS、source 302ac6b3a24423d86b02451297a49447093852f62cc8dcf8459bf06dcfb26e2b | Exact方式承認trueと製品factory検査への更新後。実行結果の最終集計は主担当追記 |

E05はReady p95が194.20msでもworker期限2件FAILを含むため採用しない。InteractiveだけReady閾値を8192へ下げる案は撤回し、最終方針は通常Ready lead（Baseline 12,288 / Candidate 16,384）とFIFO容量16,384の維持。phaseReplay（E03）とNoDigest（E07）も製品には採用しない。

E01は先行準備・取消・Play/Resume優先・速度/seek/置換・Stop/close・旧bool互換・予約差・終了監査の機能試験。品質/全161速度/通常RTの合格ではない。E06は独立固定Exact参照との代表PCM比較であり、物理loopbackやstereo全行列を代替しない。通常lead維持版のnative_all_mono_03はE11で44/352 PASS。native_all_mono_02の途中FAIL（撤回後に旧8192期待値が残ったhost検査）は別runで保存し、E11へ改名しない。Exact承認後の製品factoryを含む最終結果は追記欄へ残す。

## 機能別の採用台帳

全表は同じP番号で対応し、実装、正式承認、設定、実行時allowed、旧証拠、今回実証、残件と復旧を分ける。v3・安定理由・予約導出・先行準備は実装済み。P06だけ方式の数値・所有権を条件付き承認し、他行の新規正式承認は保留。E01のallowed確認は明示Researchと対象状態に限り、製品用macOSProduct()のApprovedOnly既定は未承認機能を有効化しない。

| ID / 機能 | 現在の実装 | 今回の正式承認 | 現在の設定・契約 | 現在allowedの条件・残件 |
|---|---|---|---|---|
| P01 製品入力・形式検査 | Float32/PCM16、44.1/48k、1/2ch | IN_PROGRESS | 入力上限と形式を版付きで公開 | prepare受付と非同期形式検査を分離 |
| P02 増分prepare・通常再生・EOS | Accepted→Preparing→Readyと実再生 | IN_PROGRESS | 初期速度・Preset・予約予算 | Readyと全曲解析完了は別 |
| P03 Playingの通常動的速度 | 161値、同じownerで動的計画 | IN_PROGRESS | 通常速度機能の承認・有効設定 | 現owner・状態・文脈・内部上限を受付時検査 |
| P04 Pause・Resume | 静止と明示再開意思 | IN_PROGRESS | 非同期再開の受付を維持 | resumePendingとPlayingは別 |
| P05 Ready/Pausedの通常速度準備 | 固定Exactの新owner、ReadyForResume | IN_PROGRESS | 停止中速度機能を独立表示 | 有効位置標本と明示Play/Resumeが必要 |
| P06 Exact Seek | frame/seconds、固定Exact再合成、v3個別設定 | 方式承認true（数値・所有権限定） | macOSProduct()はExactだけApprovedOnlyで非Research有効。旧bool互換維持 | 入力・状態・文脈のruntime条件を別判定。通常RT性能/F/音響は承認外 |
| P07 Interactive Seek | FastLocal標準500ms、短い混合。8192案は撤回 | IN_PROGRESS（新規承認なし） | Exactと独立したv3設定、旧研究引数も維持 | E02品質未達、E05通常RT未達。確定解析待ちは別段階 |
| P08 AB ReturnToA | 100ms以上の入力半開区間、先行A保存点hit | IN_PROGRESS（新規承認なし） | v3 nativeLoops実効設定。P09等の合否は別行 | 入力・状態・3識別子、確定B待ちは拒否。fresh性能は未閉鎖 |
| P09 全曲KeepPosition | 固定Mapの現在位置維持・自己反復 | IN_PROGRESS（新規承認なし） | 実効gateはnativeLoopsと共通、承認台帳はP08と分ける | 全曲限定、動的Map・Clear退役窓等は理由付き拒否 |
| P10 自然周回・短周期cache・非cache反復 | A保存点復元、固定RAW、境界補正 | IN_PROGRESS | 有効Loop入口に従う | 完全出力周期512以上、callback最大4096などの条件を維持 |
| P11 Playing Loop速度変更 | 動的commitと固定B延期、実装/承認を分離表示 | IN_PROGRESS（新規承認なし） | currentCycleSpeed承認はfalse。Research経路と正式承認を区別 | nativeLoops設定・現owner・保護B等を判定。全161速度の最終合否は別 |
| P12 Ready/Paused Loop速度変更 | 停止C維持、固定Exact準備、同ID追跡 | IN_PROGRESS | 停止中Loop速度を独立承認 | 新しい準備版のReadyForResume後、明示再開だけで出力 |
| P13 Playing Clear | B継続と未終端要求の移管 | IN_PROGRESS | 解除を新規有効化設定で塞がない | Requested取消とStarted/Done採用保持を区別 |
| P14 Ready/Paused Clear | 停止Cの固定Exact継続、専用破棄計数 | IN_PROGRESS | Clear計数と要求別計数を維持 | 停止位置標本待ちは理由付き拒否。自動Resumeしない |
| P15 Clear中の再ON | 最新ReturnToAを受付、旧必要採用を保持 | IN_PROGRESS | 専用cancelClearを必須にしない | 未採用は取消、Started/Doneは退役後に新A。KeepPositionは別判定 |
| P16 Loop範囲の連続置換 | Ready/Playing/Paused/Clear後の再要求 | IN_PROGRESS | 最新文脈と開始方針を維持 | 使用しない保存点共有を解放し、第三ownerを作らない |
| P17 Stop・再prepare・直接close | 静止→worker join→退役→解放 | IN_PROGRESS | 通常制御キューの所有を維持 | 古い完了を新入力・新準備版へ混入させない |
| P18 位置・Map・時計・最終診断 | 入出力対応標本、epoch、HAL推定、最終公開 | IN_PROGRESS | 未取得値と実測0を区別 | 位置標本の時点と現在出力を混同しない |
| P19 装置変更・入力喪失・準備失敗 | 安全停止、旧有効出力保持、入力identity監視 | IN_PROGRESS | 安定理由と復旧可能状態を公開 | 装置変更だけで自動再開しない |
| P20 台帳・上限・終了監査 | engineSerial / historyUsage / 全join後FinalOperationAudit | IN_PROGRESS（新規承認なし） | Engine全寿命の各台帳、安定理由、所有コピー | E10で実4096件・Stop/reprepare保持・新Engine再作成を確認 |
| P21 資源・制御負荷 | 2owner/2保存点、有限予約、軽量要約・通常側通知 | IN_PROGRESS（新規承認なし） | nativeLoops.effectiveから24MiB・2epoch制限を同時導出 | 旧bool単独依存を解消。通常lead最終版のRT判定は別 |
| P22 fresh未訪問AB初回の性能 | 保存点なしExact前置処理が残る | IN_PROGRESS（新規承認なし） | 未訪問・保存点なし・事前準備なしを別群で固定 | p95<=1000msの全必須群は未閉鎖。先行済み結果で代用しない |
| P23 warm/先行完了ABの性能 | requestLoopPreparation / cancel / snapshot / historyを実装 | IN_PROGRESS（新規承認なし） | 準備費用とON後first Aを分離、厳密A保存点を共有 | E01で無消費・失効・全join確認。p95<=250msは最終性能群待ち |
| P24 Merodoa/F境界・Sandbox・UI | 既存bridge接続あり。今回のF実証は未実施 | IN_PROGRESS | 能力v3・理由・archive/header整合を別に受入 | Engine受付からの計測でUI全体の応答を保証しない |
| P25 iOS共通部互換性 | 共通ヘッダーと既存分岐 | IN_PROGRESS | 音声実装はmacOS限定のまま | compile回帰のみ。iOS runtime allowedを捏造しない |

旧証拠の参照名は次を使う。いずれも当時の条件の記録で、今回の新規PASSへの転記元ではない。

- R60：[Phase60](../results/phase60/REPORT.md)、R61：[Exact](../results/phase61/REPORT.md)、RI：[Interactive](../results/phase61_interactive_seek/REPORT.md)、RF：[FastLocal](../results/phase61_fast_seek/REPORT.md)。
- RS：[寿命・再始動](../results/phase61_sync_restart_fix/REPORT.md)、RP：[停止中速度](../results/paused_speed_change/SUMMARY.json)。
- RL：[Phase62 finish](../results/phase62_finish/REPORT.md)、R01：[F01](../results/phase62_f01/REPORT.md)、RA：[終端Clear A1](../results/phase62_terminal_initial/A1_REPORT.md)、RAB：[制御負荷・AB入口](../results/phase62_control_ab/REPORT.md)。

| ID | 旧証拠 | 未閉鎖・今回確認すべき点 | 今回実施済みと残件 | 再利用の状態・条件 |
|---|---|---|---|---|
| P01 | R60/R61/RAB | 製品Float32経路の全対象形式 | E01はFloat32 48k mono 16秒。E09はinitial/prefix両形式両Preset。全製品形式/PCM16回帰は最終確定待ち | PENDING：同一入力SHAと解析/DSP依存を照合 |
| P02 | R60/R61 | 初期実機条件での新binary、100%もDSP経由 | E01のReady/静止は部分実証。通常再生/EOS・全161速度の最終結果は追記待ち | PENDING：既存Goldenを改変せず再確認 |
| P03 | R60/RAB | 新制御・承認設定からの全速度接続 | 既存経路を維持。全161値・動的独立比較・最終通常RTは追記待ち | PENDING：固定参照だけで動的品質を代用しない |
| P04 | RS/RP | 準備中/採用後の再開意思と静止 | E01でPaused、明示Play/Resume、準備取消、C/FIFO保持を機能PASS。通常RTは別 | PENDING：旧局所成功と新実施を分離 |
| P05 | RP/RAB | 通常速度の停止位置と失敗復旧 | E01で受理速度の先行準備失効・自動再開なし。E10で停止速度回帰PASS | PENDING：新設定・理由追加の依存を確認 |
| P06 | R61/RI | Exact/Goldenと新実装の互換性 | 旧Exact896の依存12項目現SHA・8input/112ref logを再監査、新fixed PCM/Map回帰を根拠に主担当が方式承認 | 旧896は再利用で今回実行件数へ加算しない。auditパス/hashは最終追記 |
| P07 | RI/RF | stereo Ready p95旧295.678ms、長尺スペクトル旧78/1080失敗等 | E02は24対照PASS/78品質FAIL。E05はReady194.20msだがworker期限2FAIL。phaseReplay/8192不採用 | PENDING：旧失敗と閾値を保持。局所方式とExactを混同しない |
| P08 | RL/RAB | 新正式設定、未訪問ABの初回 | E01の先行済みReturnToAとE06代表PCM PASS。fresh A30/A270性能は別群・未閉鎖 | PENDING：旧warmでfreshを代用しない |
| P09 | RL/R01 | 固定Map入口とClear退役窓 | 既存固定Map/拒否契約を維持。最終実機回帰は追記待ち | PENDING：D07の入口前提を照合 |
| P10 | RL/R01 | 新経路の境界と両ch品質 | E06代表48,128 framesが独立全bit一致。全cache/非cache/短周期/左右は別途確定 | PENDING：D07/D08前提不変なら閉鎖を維持 |
| P11 | RL/R01/RAB | 全161速度、動的採用と固定B延期の区別 | v3の実装と承認を分離。全速度/部分混合/Map/B実PCMの最終結果は追記待ち | PENDING：旧独立参照と今回source依存を確認 |
| P12 | RP/RA | 新設定下の全39fields・C不変 | E01は先行準備と停止速度干渉の機能PASS。旧39fields/同ID Resumeの影響回帰は別 | PENDING：旧14checksの原本を保持 |
| P13 | R01/RAB | 新正式設定・資源導出と採用保持 | Requested/Started/Done保持を維持。新sourceでの再利用・回帰判定は追記待ち | PENDING：phase差を明示して再利用 |
| P14 | RA/RAB | Clear計数と終端履歴の分離 | 終端不変/実discardの旧原本を保持。今回の影響回帰は追記待ち | PENDING：旧13/14失敗も保持 |
| P15 | RAB | 新機能選択からの再ONとFの待機 | 既存5主状態を維持。先行準備取消はE01 PASS、Clear再ON集計は別 | PENDING：Done観測を部分Started実施へ変換しない |
| P16 | RAB | 保存点の不要参照再発 | E01で先行準備の置換/owner<=2/保存点<=2。旧4連Rangeの最終再利用認定は別 | PENDING：旧3回目枯渇FAILを保持 |
| P17 | RS/RAB | 新設定/入力切替時の全member寿命 | E01でPreparing/Ready Stop/close・全join・旧履歴不変、E10でsummary24×2 PASS | PENDING：旧summary残存FAILを保持 |
| P18 | R60/RI/RS | 起動時時計・最終統計・世代一致 | E01で世代/epoch/所有コピーを確認。時計/最終統計の全群は追記待ち | PENDING：非確定0を実測0へ読み替えない |
| P19 | R61/RI/RAB | 実機装置・入力権限と失敗理由 | E01で不正文脈拒否とPreparing/Ready保護、E10でinputwatch26×2 PASS。実権限/routeは別 | PENDING：TCC実行と通常ファイル模型は分離 |
| P20 | RA/R01/RAB | 理由追加・v3互換・全ID保持 | E01の全Accepted準備ID監査とE10の4096実上限10×2 PASS。上限増加/履歴削除なし | PENDING：Engine全寿命と直近履歴を区別 |
| P21 | RAB | 正式Loopだけが24MiB/2epochを迂回しないこと | E01でpolicy優先/24MiB差/2枠/全退役。E05通常RT FAILは残す | PENDING：CPU内訳とアプリ全体値を分離 |
| P22 | RAB | fresh保存点なしのp95目標 | fresh全必須群は未閉鎖。先行準備・既訪問結果を転記しない | PENDING：旧A270遅延は比較記録に限定 |
| P23 | RAB | 先行準備の費用・失効・上限 | E01/E06でAPI/hit/代表PCM実証。warm/先行完了p95<=250msと先行費用は最終集計待ち | PENDING：単発約49msをp95実証へ昇格しない |
| P24 | RI/RABとMerodoa現行資料 | UI/service待機、実Sandbox/TCC、実アプリ計測 | Engine側とFを分離。実アプリservice/JSON/UI/Sandbox/TCCは追記待ち | PENDING：単体/Mock/compileで実アプリ実施を補わない |
| P25 | 既存共通部build | 新header・条件分岐 | build成功とiOS共通部compileを区別。iOS対象の最終結果は追記待ち | PENDING：音声試験件数には加算しない |

| ID | 合格条件（最終判定は保留） | 未達時の復旧・保留 |
|---|---|---|
| P01 | 対応形式を正しく受理し、上限/形式不正を副作用前に拒否 | 理由付き拒否。既存対応形式と証拠を維持 |
| P02 | 受付/Ready/実出力/EOSを区別し、独立品質・供給・時計・寿命基準を満たす | 安全停止し機能承認を保留。100%迂回で高速化しない |
| P03 | 全161値・両Preset、動的Map/PCM/実適用とIDが一致 | 未採用準備を失効し旧有効出力を保持。履歴を改変しない |
| P04 | Pause中のC/PCM静止、明示意思だけで有効な最新版を再開 | 静止を維持し理由表示。勝手に再開しない |
| P05 | 同じ停止C・最新準備版・ReadyForResume・明示再開 | 旧owner/停止位置を保持し、再要求またはStop |
| P06 | 凍結Exactの全frame/全ch/全bit・Map・長さと一致 | Exactを保持。local出力をExact成功と扱わない |
| P07 | 確定解析の受付→FIFO Ready p95<=200ms、局所品質/切替/寿命も合格 | Interactive承認を保留。理由付きExact選択は性能未達として別記 |
| P08 | 指定A/B・新Loop ID・初回位置・独立RAWが一致 | 旧出力を保持し理由付き拒否/準備失敗。新Loop成功を偽らない |
| P09 | C維持と固定Mapの条件、初回B供給・後続自然周回が一致 | ReturnToAまたは解除後の明示再要求を案内 |
| P10 | 反復RAW/境界式/周期/左右が独立一致、供給0 | 失敗として安全停止。paddingを成功PCMにしない |
| P11 | commit/固定B/実PCMを同IDで結び、全速度・競合・資源を満たす | 未採用だけ置換。Started/commitの事実を保持し終端回収 |
| P12 | C静止・同ID・最新準備版と全過去不変 | 自動Resumeせず失敗を表示、再要求/Stopへ戻す |
| P13 | 未採用取消とStarted/Done保持、B継続・RAW/混合・同IDが一致 | 有効供給を保持。継続失敗は理由付き停止/再要求 |
| P14 | 実discardの所属・Snapshot計数、終端39fields不変、C無消費 | 旧静止出力を保持。成功扱いの偽discardを記録しない |
| P15 | 最新Aを採用し、旧必要混合・全ID・owner/保存点上限を維持 | 必要退役を待つ。未採用だけ取消し、未達遅延を隠さない |
| P16 | 連続要求で保存点が蓄積せず、静止/Playing条件と監査を満たす | 未採用共有を通常側で解放。上限を増やさない |
| P17 | 全worker/callback参照解放後に入力権限を解放、旧値の新入力混入0 | 明示Stop・破棄・新prepare。入力/準備版を再照合 |
| P18 | 時刻/世代/Map/標本の対応が一貫し、最終公開後だけ全量を読む | 未取得をnull/未確定で表示し、最終統計を待つ |
| P19 | 既存期限・入力異常検出条件を維持し理由・停止・復旧が正しい | 自動再開しない。新形式/権限/入力を確認後、明示prepare |
| P20 | ID完全集合、上限拒否無副作用、Duplicate無消費、終端不変と終了監査 | 既存IDを保持し新要求を拒否。別Engineは全退役後に明示生成 |
| P21 | 2owner/2保存点/FIFO/RAW/予約上限・callback禁止操作0 | 準備失敗を採用前に確定。予算/上限を緩めない |
| P22 | fresh未訪問・保存点なし・事前準備なしでaccepted→first A p95<=1000ms | 選定を保留。Exactの遅い安全経路は遅延未達のまま表示 |
| P23 | warm/先行完了は各accepted→first A p95<=250ms、先行費用・失効も記録 | coldへ戻る場合はcold群へ分類。warm成功を転記しない |
| P24 | F各区間の実アプリ測定、最新意図/文脈、権限・監査の接続を確認 | Engine側と接続側の未達を分け、既定化/配布判断を保留 |
| P25 | 新共通部が既存iOS構成でcompileしmacOS専用依存を漏らさない | 共通契約/条件分岐を修正し、音声対応とは表示しない |

## 実装済みの能力v3・設定・理由・資源

契約版は3。FeaturePolicyはDisabled / ApprovedOnly / Research、FeaturePolicyOptionsはExact / Interactive / nativeLoopsを独立指定する。実装、承認、設定、effective、現在allowed、research、理由を分ける。現在のfeatureApprovalsはExactのみtrue、Interactive / nativeLoops / currentCycleSpeedはfalse。包括Capabilities.seek / publicSeekApprovedはfalseのまま。macOSProduct()はExactだけ非Researchで実効有効とし、他方式を有効化しない。ReturnToA / KeepPosition / Loop速度は採用台帳で個別判定するが、実効受付gateはnativeLoopsを共有する。共通gateの実装を全機能の正式承認と読み替えない。

prepareで設定を一度解決し、nativeLoops.effectiveから受付、追加24MiB、2epoch制限、有限診断領域を同時導出する。Preparingで現在allowed=falseでも予約を省略しない。明示featurePolicyは旧boolより優先、未指定はlegacy変換。旧Loop/Interactiveの明示falseを有効化しない。旧研究Exact経路、旧bool seek API、受付と非同期完了の意味を維持する。macOSProduct()はApprovedOnlyを明示し、未承認をResearchへ昇格しない。prepareのv3タグによる混在検出と、最終配布archive/headerの同一性を区別する。

安定理由はAvailabilityReasonと表示文字列を分け、設定/承認、入力/状態、文脈、範囲/最小区間、方針/全曲条件、保護B/退役/位置待ち、上限/予算/競合、入力/Engine障害を表す。E01/E09で対象分岐を確認したが、全理由分岐、Merodoa旧decoder/日本語全文分類、実Sandbox/TCCは未閉鎖。

先行準備APIはrequestLoopPreparation / cancelLoopPreparation / loopPreparationSnapshot / loopPreparationHistory。元のC/FIFO/epoch/Loop/周回を動かさず、共有入力と確定解析から厳密なA前置保存点を作る。Readyは準備workerの全join/解放後に公開。取消/Pause/Stop/受理速度/明示seek/置換/close、明示Play/Resumeを優先し、Ready終端行を変更せずavailableを失効する。入力世代、速度、Preset、A/B、解析/Map/保存点identity、revisionの一致だけで再利用する。CPU/wallの先行費用とON応答は別測定。

履歴はEngine全寿命でSeek（Rejectedも含む）4096、停止中速度4096、外部Loop速度Accepted最大4096、先行準備Accepted最大4096。通常内部速度は各Pipeline4096、計画512。Stop/prepareでEngine履歴を削除せず、engineSerial / 入力世代 / session / 準備版とhistoryUsageで寿命を区別する。closed epoch直近16・各内部操作256・境界64は全量監査と別である。FinalOperationAuditは全join/退役後にSeek/停止速度/Loop速度/先行準備spanを一度配送し、sinkはその呼出し中に値を所有コピーする。E10の実4096件試験は旧全4096終端回収と新Engine ID1の無再生Completed・終了回収を各Presetで確認した。

## P06 Exact方式の条件付き承認

主担当は旧Exact896の数学/解析依存12項目の現SHA一致、8 input / 112 reference logの再監査、新しいfixed PCM/Map回帰を根拠としてExactだけ方式engineapproval=trueにした。旧896件は旧実行の再利用根拠であり、今回新規実行件数に加算しない。再監査・新回帰の詳細証拠パス/hash/件数は主担当の最終欄へ追記する。

承認軸は方式の数値正確性と所有権。通常RT性能、全アプリF、実Sandbox/TCC接続、物理音響、包括的Seek機能の承認とは別である。Interactive品質FAIL等により全体の正式採用は未達。Capabilities.seek / publicSeekApprovedはExactとInteractiveの両承認が必要なためfalseを維持する。明示DisabledはExact承認後も無効、旧Loop/Interactive falseの互換意味も変えない。

## 変更依存と採用の確定

D07のLoop所有者履歴H<=1<512、D08のdescriptor距離d-c<=44<64は閉鎖済み前提として維持する。[履歴不変条件](PHASE62_HISTORY_INVARIANT.md) と [descriptor不変条件](PHASE62_DESCRIPTOR_INVARIANT.md) の入口、terminal B、FIFO/pending/callback上限、単一consumer、値コピー等が不変なら上位から到達不能な枯渇試験を再開しない。前提を変更する差分だけ、影響範囲を限定して再証明・必要な下位回帰を行う。

合格は機能ごとに、品質・性能・寿命・通常実時間・接続範囲を揃えて記録する。未実施、証拠不整合、試験不能、対象外、故障注入の期待失敗、通常実行の失敗を区別する。既存NO-GOの文言を消す代わりに、新source/binary/入力/環境へ結び付いた正式判定を追記する。本更新にはE01/E06/E09/E10/E11等の範囲限定実証とP06の条件付き方式承認がある。包括採用は未達で、旧証拠の最終対応・除外軸・配布判断は主担当が確定する。

## 主担当の最終確定・追記欄

| 確定項目 | 現在 | 最終結果・source/hash・証拠（主担当追記） |
|---|---|---|
| 最終source / commit / build / archive-header | build07 source=302ac6b3a24423d86b02451297a49447093852f62cc8dcf8459bf06dcfb26e2b、commit/配布整合は未確定 | 未記入 |
| 通常lead維持後の全native機能群 | E11 native_all_mono_03の44/352 PASS。承認後factory確認は別 | 未記入 |
| 最終通常RT・時計・品質・全161値/形式 | 品質/期限/能力の未達を個別維持 | 未記入 |
| Exact方式承認・再利用監査 | 数値/所有権の条件付きtrue。旧896件は新実行数へ不加算 | 詳細auditパス/hash/新回帰件数は未記入 |
| Interactive | E02品質FAIL、E04遅延FAIL、E05 RT FAIL。承認false | 未記入 |
| fresh AB / warm / 先行完了 | INITIALの1000ms / 250msを維持 | 未記入 |
| D5実4096件 | E10の10×2 PASS、最終artifact照合・統合集計待ち | 未記入 |
| F実アプリ・Sandbox/TCC・UI / iOS共通部 | nativeと分離、最終結果待ち | 未記入 |
| 機能別承認・未達復旧・リリース | Exact方式のみ条件付きtrue。他方式false、包括採用/配布判断未確定 | 未記入 |

### 本更新で参照した要約のSHA-256

原本・凍結参照のSHAを書き換えたものではない。最終主担当は現artifactと照合し、異なるsourceの結果を付け替えない。

| 証拠 | SHA-256 |
|---|---|
| E01 | `8c5955d30497026fce9e9ccfb2e2bc37ed76b7412301f9ee6b84fd268d49c864` |
| E02 | `e77cf7eb1aec5aae4b2a67e117ce7c16bb61fb60a7b67a0612ec5b2f95309066` |
| E03 | `ce18e8f4a5baae9f464ab9f6315685fdf42a915110d60453bed57024731e0746` |
| E04 | `8454faea5668790fc7696576e14f12f551e280d55554afca82dc27c076493569` |
| E05 | `c3590ae99331ee0dac0d13c50a17a4105c4feaee62e2dec0ae70283f82ad6a64` |
| E06 | `8358e68e1ef68d4adf92b3265f69a06069b9c4353ea11715cb44d00ec371599d` |
| E07 | `b2d766e91167fe860cd682f0a477f9a0a21300bfc685b8f12d905a729e13a732` |
| E08 | `79357dca19ec34369278cb606630a80338eacbe3c79c956e65893d19fd18c6fe` |
| E09 | `441d4aaad564b2000eceb3f08fc73955d3baad8d24a024872e641fde280ffe0b` |
| E10 | `7db784749cfc07b5b1b211cdee4761e5e0a164b147c189accdca7367c742ae19` |
| E11 | `17cbdf105cf48fb20a451a6d6dd2e2b1d7bde56a52876f601486cd4c6ada0d9c` |
| E12 | `dd3a6da126fcc2763ad16a59feee608a9df31b3cdac419a8759abffb7232f3e1` |
| E13 | `4b439a36fc8a269c18464f5e6448489a669cef5748d0639b46889c39857c4bf3` |


## 最終候補・今回の確定結果

最終コードのCMake/src/tests/scriptsインベントリは `2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392`。本項が途中集計の追記欄より新しい。[最終REPORT](../results/progressive_adoption/REPORT.md)と[manifest](../results/progressive_adoption/manifest.json)を参照する。方式承認はExactのみtrue。包括seek/publicSeekApproved、Interactive/nativeLoops/currentCycleSpeedはfalseを維持する。これは過去の禁止の継続ではなく、下記の現候補の未達による個別判断である。

- 最終Release影響回帰21/21 programs、mono44 programs/352 checks、通常速度300Acceptedの全量監査4×14=56 checks（半数は拒否注入）、起動時計20/20、AB独立PCM7×5=35 checks PASS。Debugの監査も56、先行準備16 checks PASS。新共有ヘッダーiOS device/simulator compile各1、既存不変依存のiOS app Debug build PASS。
- 通常速度の全量監査を追加した。`receiveFinalEpochAudit`は全join・callback解放後、表示256件切詰め前に全終端を渡す。`epochAuditConfigured/Calls/Rejected`と全session/ID集合を最終監査で照合し、拒否を成功にしない。D07 H<=1を使わず、実300Acceptedの298Replaced/2Cancelledと全field・履歴保持・Stop/再prepare/close一度を確認した。
- 最終stereo120件はReady p95=211.090msで200ms未達、2倍Candidate/C150s/repeat0にworker期限1。欠落・callback期限・host/sample/HAL・new/C malloc/freeは0。原因未解明としてRT/応答FAILを残す。既知FastLocal102件は対照24PASS/既知78FAIL、最大3.593187876dB。全品質集合の全面承認は未完了。
- A270の初回A PCMは未訪問cold10345.906ms、先行完了後21.150ms（先行wall10.425s）。A30は1300.741/19.973ms。各1標本でp95承認ではない。cold1000ms目標はFAIL。先行準備を総CPU削減に読み替えない。
- 180秒/2倍/CPU2両Presetの全EOSは独立RAW/供給/期限PASS。そのhostは最終でも全byte同一で再利用範囲をmanifestに記録。新engineの時計は旧同input/0.5で20回非再現だが、旧不連続の原因解明や物理連続性まで閉じない。
- Exact896/Golden25は旧証拠の現SHA・数学依存照合であり今回の新実行件数に足さない。D07/D08の既存閉鎖を保存し、新監査の証明へ一般化しない。過去/途中のFAIL・未成立・INCOMPLETEを保存した。

今回の追加契約・先行準備・全量監査は局所PASS。全体正式採用・一般公開・Merodoa既定採用は未完了。FastLocalの品質/200ms/RT、cold ABの方式/性能、実アプリF/TCC/試聴/物理確認を個別に閉じる。新API・理由・予約・寿命・復旧は[契約v3](PROGRESSIVE_ADOPTION_API_V3.md)、Fの必須12項目は[受入表](PROGRESSIVE_ADOPTION_F_ACCEPTANCE.md)。Merodoaソース/gitlink/承認SHAは変更しない。


## 2026-10-23開始の性能・応答候補

現在の追加変更は契約v4の未commit候補である。上のv3時点の件数・採用範囲は保存する。
今回の実装・ソース台帳・新規実行・限定再利用・未達は
[性能・応答REPORT](../results/performance_response/REPORT.md)で機能別に対応付ける。
全161速度の固定/動的Exact、Golden、解析寿命、先行job移管、checkpoint、監査の
機能結果と、定常CPU、cold/warm AB、Interactive Ready、FastLocal品質は別の判定軸とする。
旧v3 binaryとv4 headerを混在させず、正式承認フラグを今回の性能結果だけで変更しない。
Merodoaのgitlink/既定engine/承認SHAは変更しない。アプリFと物理確認も未実施のまま保存する。

## 性能候補08の評価確定（2026-10-24）

性能候補は未commitのsource08 `b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94`。
checkpointの安全拒否/状態保持/明示Exact再準備3caseは現行実行体でPASS。
CPUは固定n6のmono1倍で全pair増加し、一式として性能採用しない。隔離09/probe10も棄却。
Closed済みPhase62の機能証拠は維持するが、08の全面native回帰・性能採用へ拡張しない。
契約v4は候補で、今回Merodoaへ固定する承認済みcommit SHAは作っていない。
本体/gitlink/承認SHA/既定engineを変更せず、[確定REPORT](../results/performance_response/REPORT.md)
のNOT_RUN・品質/応答FAIL・実アプリFを引き継ぐ。
