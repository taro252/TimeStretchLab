# Progressive正式採用の検証手順（D-1）

状態は **IN_PROGRESS / 実装・途中検証整理 v0.2**。契約v3と先行準備の実装、実施済みの範囲、未達・未完了、残る検証手順を分ける。方式engineapprovalはExactだけtrue（数値・所有権の条件付き範囲）、Interactive / nativeLoops / currentCycleSpeedはfalse。通常RT性能・アプリF・物理音響をこの承認に含めない。部分PASSを一括GOやリリース許可にしない。[採用計画](PROGRESSIVE_ADOPTION_PLAN.md) のP01〜P25を必須機能集合として扱い、具体的なcase ID、件数、反復、コマンドは実行前のEXPECTED/実行計画で固定する。

## 来歴と実行規律

開始点は `f4f0e6187a643d9442216df87c04353eda4934e5`、ブランチ `codex/progressive-adoption`、作業先は `/Users/taro252/.codex/worktrees/progressive-adoption/TimeStretchLab`。生証拠Bは `/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01`。開始原本 `B/INITIAL.json` の文書作成時SHA-256は `34633d7979fa4b626929efaeca31b540e460043708105c0e3e4d9578bd279c37`。基準のclean状態・装置・目標値をここから照合する。

重いbuild、音声、性能測定は主担当が直列実行する。並行する音声試験・高負荷処理を同じ測定窓へ混ぜない。各実行は新規ディレクトリに保存する。最低限、以下を所有するmanifestを作る。

| 記録 | 必須内容 |
|---|---|
| source | 基準commit、差分、全対象ファイルSHA、未追跡追加を含むinventory。HEADだけで変更版を特定しない |
| build | 成功buildのcompiler/SDK/構成/flags、CMake target、binary/library/headerのSHAとarm64確認 |
| input | 生成/デコードレシピ、元媒体/保護済みWAVのSHA、Float32/PCM16、rate/ch/frames |
| case | 機能P番号、固定case ID集合、Preset、全速度/位置/状態、反復数、順序、gate/故障注入の有無 |
| timing | 時計・単位・採取点、同操作ID、区間別の開始/終了、解析/保存点/先行準備状態 |
| result | コマンド、exit、timeout、EXPECTEDとの集合一致、完了marker、最終統計、品質/資源/期限の独立判定 |
| artifact | 絶対保存場所、サイズ、SHA、参照との対応、復元手順。再利用か新規実行かを明示 |

失敗build後に残った旧binaryを使わない。ソース変更後は影響群の依存を再評価し、実行済み結果のsourceを付け替えない。全binaryとheader/archiveを同時に再ビルドして整合させる。Pythonのplatform表示がx86_64でも製品binaryのarm64を別途検査する。

## 実施済みの範囲と残件

証拠の絶対保存先と要約SHAは [採用計画のE01〜E13](PROGRESSIVE_ADOPTION_PLAN.md) に固定した。本更新はB内の小さなSUMMARY / AUDIT / BUILDとINITIALのみを読み、raw/PCM/大容量traceや旧原本を変更していない。次表は実行済み結果であり、以下の必須行列全体の合格を意味しない。

| 実施群 | 確認結果 | 未達・未完了・採否 |
|---|---|---|
| E01 native_all_mono_01 | 44 programs / 352 checks PASS、22 modes × 両Preset、Float32 48kHz mono 16秒 | quality_gate=false / RT_gate=false。8192候補sourceの機能結果で、最終通常lead版へ付け替えない |
| E02 quality_baseline_known26_01 | 102/102構造検証、24対照PASS / 78品質FAIL | 既知local長尺品質の未達を再現。3dB等の基準を緩めない |
| E03 phaseReplay | 個別34件の全bit一致、集計はINCOMPLETE / source_unchanged=false | Ready約7〜19秒で目標未達。repo変更による完了不成立も残し、製品不採用 |
| E04 通常lead stereo120 | 120件完了、機能/RT PASS、Ready p95=213.09775175ms | 200ms未達、品質UNMEASURED、総合性能FAIL |
| E05 8192候補 stereo120 | 120件完了、Ready p95=194.200425ms | worker期限超過delta合計2件で機能/RT FAIL。8192案撤回、最終は通常lead維持 |
| E06 prewarm独立PCM代表 | 5/5 PASS、48,128 framesのRAW/output/Map/座標とgain設定 | mono代表。全形式/全速度/物理音響やFの承認を含めない |
| E07 NoDigest | 各side5 process、30+30 PCM（30対）が全bit一致。CPU中央値約3.59%減 | 実験非採用。少数比較で製品の品質/性能ゲートを置き換えない |
| E08 途中build05 | Release / arm64 PASS、source=8a17ac261f20470b6cfb3c00bbb3c0eb7c11ece0d63e1bfefbc7c44985dc8b58 | 最終commit/archive-header/影響回帰の統合集計は主担当が確定 |
| E09 regressions_01 | pure contract、Phase60/61、ledger、sync、fast_seek state、initial/prefix両形式両Preset PASS | 全体INCOMPLETE。fixture/装置不適合の記録を保存し、必要7件だけE10で再実施 |
| E10 regressions_02 | 7/7 programs PASS：停止速度、summary24×2、inputwatch26×2、実4096上限10×2 | 指定fixtureと装置権限で別run。初回FAIL記録を削除・上書きしない |
| E11 通常lead native_all_mono_03 | build06、44 programs / 352 checks PASS、execution/full_suite complete | quality/RT gate=false。Exact承認前source a43d3c5e328cb488c632808cc06553adaef6d015d6c44f14d4e329149173e73a |
| E12/E13 build06 / build07 | Release / arm64ともPASS。build07 source=302ac6b3a24423d86b02451297a49447093852f62cc8dcf8459bf06dcfb26e2b | build07はExact方式承認と製品factory検査更新を含む。実行結果の最終対応は別 |

通常lead維持版build06のnative_all_mono_03は44/352全PASS（E11、品質/RT gate=false）。native_all_mono_02の旧8192期待値によるhost検査FAILは別runで保持する。Exact方式承認trueとmacOSProduct()検査を含むbuild07後の実行結果・最終件数/hashは主担当欄へ追記し、E11に後からsourceを付け替えない。8192案を撤回した後は通常Ready lead（Baseline 12,288 / Candidate 16,384）、steady lead、FIFO容量16,384を維持して必要な依存回帰を行う。E01/E05と最終候補のsourceの違いを残す。

E09で不適fixture、inputwatchの16秒入力対12秒制約、sandbox装置不可により実施できなかった群は、原記録のFAIL/exitを保存したまま実行条件不成立として区別する。正常実機のworker期限FAILや品質FAILとは混ぜない。E10は旧指定fixture・装置権限による別実行であり、初回をPASSへ書き換えたものではない。

## 実証範囲と行列

初期実機はM1/MacBookAir10,1、macOS26.6.2、内蔵スピーカー48kHz/512 frames。入力source rate 44.1/48kHzとdevice rate 48kHzを別列に記録する。別bufferや装置を使う補助試験は別群とし、終了時の元設定への復元も記録する。

- 製品経路の主行列はFloat32 44.1/48kHz × mono/stereo × Baseline/Candidate × 40〜200%の161値。受付だけの161成功と、独立PCMを検査した161実行を別件数で示す。
- PCM16の既存互換行列、Exactの形式/位置/終端、Golden、動的Map/PCM、Loopの境界/状態行列を維持する。新しい代表測定を理由に既存必須集合・品質閾値・反復数を削らない。
- 既存Exact 896、Golden25等の集合を使う場合は、その集合自身のEXPECTED/レシピと照合する。過去の件数を今回の実施件数へ転記しない。
- iOSは共通部compileだけを別台帳へ記録する。macOS音声試験やiOS音声対応の件数には加算しない。

## 候補実行前に固定した性能目標

以下はINITIALの目標であり、実測を見て緩めない。200ms/1000ms/250msは異なる操作・採取点の基準である。

| 群 | 必須の入口状態 | 測定区間 | 合格基準 |
|---|---|---|---|
| Interactive手動Seek | 確定解析を取得済み。Fresh/warm等を別タグ | 同じ要求のnative accepted→新FIFO Ready | p95<=200ms |
| fresh未訪問AB | 対象位置未訪問、保存点なし、事前準備なし | 同じ新Loop IDのnative accepted→first A PCM | p95<=1000ms |
| warm AB | 互換保存点の存在・由来・hitを実測 | 同じ新Loop IDのnative accepted→first A PCM | p95<=250ms |
| 先行準備完了AB | 準備完了をON前に確認し、所要費用を別保存 | 同じ新Loop IDのnative accepted→first A PCM | p95<=250ms、準備コストも報告 |
| 正常Release | gate/故障注入なし、実装上の正常条件 | 全観測窓・終了統計 | unexpected missing/padding/rejected/PCM欠陥/callback禁止操作=0、既存期限基準を維持 |

fresh ABの主条件はFloat32 48kHz mono/stereo、A=30秒/270秒、速度40/100/200%。Exact候補とlocal候補を別群で評価し、両Presetの適用範囲を固定計画に明記する。一般の161速度の品質・契約行列を、この性能代表速度3点で代用しない。

p95は、事前宣言した母集団の有効な同操作差分を昇順に並べ、nearest-rank `ceil(0.95*n)` 番目を用いる。母集団ごとのn、反復数、試行順、ウォームアップ、許容中断条件を候補測定前に固定する。少数の探索試行は正式p95達成の根拠にしない。必要な反復数の確定がない群はIN_PROGRESSのままにし、実施後の都合で形式・ch・Preset・速度群を結合しない。n、median、p95、max、目標超過件数、timeout/失敗/無効数を併記する。

成功した試行だけからp95を作り、失敗を分母から隠さない。失敗/timeoutがあればその群の合否も明記する。再実行は別runとして原試行を保持し、除外理由・事前ルールを記録する。p95同士を引いて内訳にせず、同一操作の各時刻差から分布を作る。

保存済みE04/E05 AUDIT_01は、要約内のstatistics_methodにある(N-1)*qの線形補間を使用している。本書当初案のnearest-rankとは計算法が異なるため、記録済みの213.09775175ms / 194.200425msを別方式の値に付け替えない。目標200ms、全試行・期限FAIL・母集団は維持し、最終主担当は統計法と必要な再集計を末尾で確定する。今回の文書更新では再集計試験を実行していない。

### fresh・warm・先行準備の分離

freshは各反復で新しい入力準備・所有状態を構成し、対象Aへの訪問、互換保存点、事前Loop準備、先行レンダーの有無を受理前に証拠化する。保存点総数、利用有無、P、各hit、準備版、入力世代を保存する。要求前から保持した保存点や対象Aの事前処理があれば、その試行をfreshへ入れない。OSのファイルcacheを消していない場合はその事実を記録し、OS coldとは呼ばない。

warmは同prepare/同入力の再訪と、完全固定保存点の厳密互換条件を証拠化する。P→Aの再合成・破棄量と、`checkpointStartFrame+coldDiscardedFrames=OA` 等の座標を記録する。稼働中の動的DSPを固定保存点として扱わない。

先行準備APIは実装済み。requestLoopPreparation / cancelLoopPreparation / loopPreparationSnapshot / loopPreparationHistoryを使用し、ON前の準備開始/Ready、CPU/wall/RSS/予約、入力/速度/Preset/A/Bの失効を別に記録する。E01はC/FIFO/epoch/Loop/周回の無変更、Ready時の全join、同範囲ONのinitialCheckpointHit、取消/Pause/Stop/速度/明示seek/置換/closeを確認した。明示Play/Resumeでは通常worker gate保持中のCancelling公開、解放後のCancelled/全join、元FIFOの実出力を区別する。Ready終端行は失効後も全値不変で、availableだけがfalseになる。

先行準備中の費用をwarm操作応答の短縮として隠さない。未完了・hitなし・cold fallbackは別群に分類し、fresh未訪問の1000ms実証には転記しない。E06代表PCMの5検査とE01機能352検査を全速度・全形式・通常RT・250ms性能達成に拡張しない。

### 時刻とFの接続測定

first A PCMは、要求した新Loop ID/epochのAを含むRAWが実際の出力spanへ寄与した最初のcallbackの単調時刻と、その入力/出力座標で証明する。準備workerがAを生成しただけ、FIFO Ready、取消されたownerのRAW観測だけをfirst A PCMにしない。混合中のnew寄与と、自然B後のA復帰も区別する。callback時刻やHAL推定は物理音響時刻ではない。

| 時刻 | 所属と目的 |
|---|---|
| UI ON意図 | F：最新の利用者意図と操作revision |
| service enqueue / 実行開始 | F：直列キュー待ち、旧Clear待機等 |
| native API開始 / accepted | native入口。API処理時間と受付後準備を分離 |
| worker取得 / analysisReady / FIFO Ready | native準備。確定解析待ちとDSP/供給準備を分離 |
| switchReady / Started / first A PCM / Done | native採用と実出力。Readyを完了扱いしない |
| reading生成 / MainActor受信 / UI反映 | F：値コピー/JSON/通知/表示の区間 |
| HAL推定 / 物理loopback | 推定値と実測値を別欄にする。未実施はnull/NOT_RUN |

ON→service→native→worker→first A→UIは同じ意図・IDに結ぶ。nativeのp95合格をUI全体のp95へ置き換えず、F側の合否・目標・測定状態を別項目にする。P22/P23の1000/250msを手動Seekの200msへ読み替えない。Fの実アプリ測定は本書作成時NOT_RUNである。

## 品質・所有権・競合の必須群

| 群 / 対応機能 | 検査の要点 |
|---|---|
| 通常・動的速度 / P01〜P05 | 製品Float32、両Preset161値、100%も実DSP、適用/完了座標、停止C、Resume意思、EOS |
| Exact / P06 | 凍結フル参照から全suffix・全ch・全bit・長さ・Map・入力座標を照合。保存点有無を分離 |
| Interactive/local / P07 | 確定解析/解析待ち、開始前Latest-Winsと開始後保持、短callback混合、長尺/左右/位相/スペクトル・過渡品質。Exactとは異なる局所方式として検証 |
| Loop入口と反復 / P08〜P10 | ReturnToA/KeepPositionを別ID、入力100ms、出力512下限、cache/非cache、短い/空R0、自然B・周期・全ch独立RAW/補正/混合 |
| Loop速度 / P11〜P12 | 全161値・両Preset、動的commit/固定B延期、C不変、ReadyForResume/同ID実出力、旧FIFO保護 |
| Clearと再ON / P13〜P16 | Preparing/Requested/Started/Done/Paused準備/採用、未採用取消と必要採用保持、最新A、Keep拒否窓、4連Range、実部分混合、Stop/reprepare/close |
| 寿命・障害 / P17〜P19 | callback静止、全join後解放、入力FD/resident/権限保持、入力/装置/準備失敗、明示再開、Finalized前の未取得 |
| 履歴・資源・契約 / P20〜P21 | 全Accepted集合、39fields終端不変、上限/Duplicate無副作用、所有コピー、2owner/2保存点/予約/設定・v3・理由 |
| F接続 / P24 | 実際のservice/native/JSON/UI時刻、最新意図、旧文脈拒否、security scope/TCC、終了監査context寿命 |
| 共通部 / P25 | macOS用型の変更によるiOS共通header/分岐のcompile回帰 |

Exactは許容誤差0の独立比較を維持する。localは位相原点等の契約が異なるため、Exactとのbit一致成功へ付け替えない。旧長尺インパルス列78/1080失敗・既存3dB閾値等は過去の原本のまま保持し、採用候補の未閉鎖品質として評価する。今回の手順では品質閾値・比較区間を緩めない。局所参照が必要な場合も製品候補から期待PCMを生成する循環比較を避け、由来と独立性を記録する。物理loopback/主観試聴は実施した証拠だけを、その範囲で別判定する。

既存の凍結参照は改変しない。

| 参照 | 凍結binary SHA-256 | 用途 |
|---|---|---|
| Phase61固定Exact | `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748` | 固定全曲/Exact suffix・Map |
| bb22由来captured reference | `1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818` | 実測Frontierから動的planner/DSPを独立再計算 |

復元・source/library/driverの由来は [既存参照監査](../results/phase62_terminal_initial/REFERENCE_AUDIT.json)、[直近参照監査](../results/phase62_control_ab/REFERENCE_AUDIT.json) を参照し、現artifactのSHAと照合する。binaryが同じだけで入力/参照/検証器/条件を省略しない。既存Golden/WAV/PCMのSHAを候補へ合わせて更新しない。

## 実装済みv3・理由・資源の検証対応

v3のFeaturePolicy / resolveFeatures / legacyFeatures / updateRuntime、明示policy優先、予約24MiB、historyUsage / engineSerial / FinalOperationAuditを実装済み。以下のD4/D5名は検証要件の対応名であり、実行済みhostのcheck IDへ読み替えない。E09でpure contract実行PASS、E01で対象API機能をPASS、E10で実4096件保持と再作成をPASSとしている。全要求分岐・F接続・最終通常RTは別途確定する。

| 要件対応名 | 必須assert・最終確認 |
|---|---|
| D4.feature_approval_separation | 実装/正式承認/設定/現在allowedを独立に表現。ExactとInteractive、ReturnToAとKeepPosition、Playing/停止速度を混同しない |
| D4.configuration_precedence | 正式設定の明示true/false、未指定時の旧opt-in変換、既定/互換APIの意味を固定 |
| D4.runtime_state_matrix | Empty〜Failedの全状態、解析/位置標本/退役/確定B等の許可理由。照会で取消・待機・資源消費を起こさない |
| D4.stable_receipt_reasons | 入力/状態/古い文脈/範囲/短区間/開始方針/境界待ち/退役待ち/上限等の全受付分岐。表示文言と機械コードを分離 |
| D4.compatibility | 既存enum番号・ID・例外・0識別子・受付/完了・旧bool APIを維持または版付きで明示。Merodoa旧decoder/全文理由分類の影響を記録 |
| D5.reservation_derivation | 正式Loopのみ、旧opt-inのみ、両方、明示無効で、同じ正規化設定から追加24MiBと2epoch制約を導く |
| D5.reservation_boundaries | 入力0/上限/上限+1、予算ちょうど/1byte不足、資源競合/準備失敗で採用前拒否と解放を確認 |
| D5.owner_checkpoint_lifetime | 退役中・取消・反復置換・clone・失敗でもowner<=2/保存点<=2、不要参照を通常側で解放、現ownerの必要状態を保持 |
| D5.history_scopes | Engine全寿命の台帳とPipeline/入力寿命・直近16/64/256保存を区別。Stop/reprepareで過去IDを失わない |
| D5.admission_before_effects | 実上限と試験用低上限、full時Duplicate、拒否後のrequested/C/Resume意思/旧39fields不変 |
| D5.final_owned_audit | 全Accepted IDの一意対応、直接closeを含む全join/退役後の一度配送、借用span即時所有コピー |
| D5.prepare_summary_reset | 普通の非Loop75%→Stop→100%のPreparing/生成前Failedに旧pending/active/lastResult/適用速度を持ち越さない |

D5実上限はProgressiveAdoptionLimitNativeの10固定IDで確認する。INPUT PRESET NEW_OUT SOURCE_SHA、1本の通常制御threadでAPIと破棄を行い、Play/Resumeは呼ばない。Float32 16秒の代表入力、実4096枠のまま実行し、上限増加や履歴削除を行わない。E10の両Presetは各10/10 PASS、旧4096行と新1行を全join後の所有コピーで回収、owner_alive=0 / peak<=2、audio_playback=NOT_RUN / performance=NOT_ASSESSEDである。

| 固定check ID | 必須確認 |
|---|---|
| D5L01_initial_v3_fixture | 初期Ready、v3/実上限/入力identity、無再生 |
| D5L02_rejected_ids_1_to_4096 | 範囲外Exactを4096件Rejected、ID1..4096 / InvalidRangeで枠を消費 |
| D5L03_full_history_stationary | Seek全29fieldsを保存、C/FIFO/Loop保持、historyUsage=4096 |
| D5L04_limit_preserves_state | 次の有効seekがid0 / LimitReached、履歴・C・FIFO無変更 |
| D5L05_stop_prepare_keeps_history | Stop→prepareでも同じEngineの4096枠を保持、新入力世代/ownerとは区別 |
| D5L06_reprepared_limit | 再prepare後も有効要求をid0 / LimitReached、過去全値不変 |
| D5L07_old_owned_final_audit | 旧Engine全join/退役後、4096終端を一度配送・即時所有コピー |
| D5L08_new_engine_identity_and_id1 | 旧Engine破棄後に新serial/入力世代/session、ID1再利用を区別 |
| D5L09_exact_completed_without_play | Ready中に最初のExactがCompleted、要求C、消費端=開始座標、callback/firstPCMなし |
| D5L10_new_owned_final_audit | 新ID1も全join後回収、旧コピー不変、所有者残存なし |

資源予約はallocator/RSS実測と別である。2epochは既存24MiB共有枠の有限分割を維持し、正式承認を理由に第三owner・第三保存点・全曲PCM cacheを足さない。制御計測はEngine/InputLease/epochで寿命が違うため同じ寿命内の前後差を取り、包含するCPU/wallを合算しない。

## Exact方式承認と件数の分離

P06は主担当により方式engineapproval=true（数値正確性・所有権の条件付き範囲）。根拠は旧Exact896の数学/解析依存12項目の現SHA、8 input / 112 reference log再監査、新fixed PCM/Map回帰。旧896は再利用で、今回の新規実行件数へ加算しない。詳細auditパス/hash/新回帰件数は最終主担当が追記する。

macOSProduct()のApprovedOnlyではExactだけ非Researchで有効となるが、現在入力・状態・文脈を別に検査する。明示Disabled、旧Loop/Interactive false、包括Capabilities.seek / publicSeekApproved=falseを維持する。Interactive / nativeLoops / currentCycleSpeedは未承認で、P07品質FAIL、通常RT性能、F実アプリ、物理音響は別判定。Exact承認だけで全体GOやSeek全方式の承認を宣言しない。

## 通常実時間、故障注入、閉鎖済み不変条件

通常Releaseの実時間判定はgateなしの実機群で行う。callbackのC++ new/malloc/free、FFT、解析、I/O、mutex、待機、ログ等の禁止操作、予期しない供給不足/失敗padding/rejected、非有限PCM、順序/境界監査エラーを0とする。既存のworker/callback期限・時計・入力異常検出受入条件を緩めない。平均値が良くても単発の期限超過を消さない。

競合を決める通常worker gateは有限にし、全例外経路でreleaseしてからdestructor/joinする。callbackを試験のために止めない。故障注入の期待失敗は正常Releaseの失敗/期限群と別集計する。Requested、Started、部分Started、Doneの実観測を区別し、取り逃したStartedを試験済みとしない。

D07はH<=1<512、D08はd-c<=44<64の現在前提を照合する。承認表示/設定/理由だけの変更で到達不能な上限を上位から再現する課題を再開しない。固定Map入口、単一proposal/terminal B、FIFO16,384/pending2,048/callback4,096、最小完全周期512、単一consumer、64bit identity・値コピー等を変える場合だけ依存を列挙し、限定した再証明/下位試験/影響統合回帰を要求する。新規多数周回を旧証明の代用品にしない。

## 再利用と最終集約

再利用群は実行元source/依存差分、binary、入力、凍結参照、検証器、条件、期待ID、完了/最終統計、現artifact SHAを照合し、理由を機能P番号へ結ぶ。共有DSP、worker、制御、公開契約の変更に影響する群は新binaryで再実施する。再利用した旧実行と今回の新しいSHA監査は別件数とする。原本が欠けるものは再利用PASSにしない。

| 状態 | 記録する意味 |
|---|---|
| IN_PROGRESS | 設計・実装・実行・承認が未完了 |
| NOT_RUN / NOT_IMPLEMENTED | 未実施 / 未実装。成功の根拠なし |
| NOT_ASSESSED | その軸を判定していない。例：gate付き機能試験のRT期限承認 |
| BLOCKED / NOT_RUN | 装置や権限等で実行不能。製品FAILとは分ける |
| FAIL | 実施した試験が固定合格条件を満たさない |
| PASS | 固定必須ID集合、来歴、完了、最終統計、対象軸の合格条件が全て揃う |

最終REPORTはP01〜P25それぞれの実装、承認、設定、現在許可、旧証拠、未閉鎖、新規実施、再利用、合否、未達復旧を更新する。全機能の承認を一括boolへ縮めない。未達の場合は機能を保留/理由付き無効とし、有効な旧出力・明示停止・Exact選択などの復旧を採用計画の該当行に結ぶ。fallbackで動作を継続できても元の性能/品質未達は残す。

大容量WAV/PCM/CSV/trace/binary/archiveはB等のGit管理外に保存し、Gitには小さい結果・manifest・SHA・レシピを記録する。50,000,000 bytes以上の新規blobを追加せず、コミット前は `python3 scripts/check_git_blob_sizes.py staged`、Push前は送信全履歴を監査する。容量を理由に品質基準・行列・反復・実機条件を縮小せず、旧原本や凍結参照を削除しない。


## 主担当の最終結果・追記欄

| 項目 | 本更新時点 | 最終判定・件数・source/hash・根拠 |
|---|---|---|
| 最終source/build/commit/header/archive | build07 source=302ac6b3a24423d86b02451297a49447093852f62cc8dcf8459bf06dcfb26e2b | 未記入 |
| 通常lead native_all_mono_03 / 承認後factory | E11の44/352 PASS、build07後factoryの実行結果は別 | 未記入 |
| 最終通常lead下のRT/時計/供給/PCM | E05期限FAILを保持、8192案は撤回 | 未記入 |
| Exact方式承認 / 全161速度・形式・Golden | 数値/所有権のみ条件付きtrue、旧896を今回実行数へ不加算 | 依存監査パス/hash/新回帰件数は未記入 |
| Interactive/local品質・遅延 | E02品質FAIL、E04遅延FAIL、E05 RT FAIL。phaseReplay不採用 | 未記入 |
| fresh / warm / 先行完了 | 1000ms / 250ms、準備費用分離を維持 | 未記入 |
| p95母集団・統計法・再集計 | 旧案nearest-rankと保存AUDIT線形補間の差を明示 | 未記入 |
| 実4096件・所有監査・再実行分類 | E10の10×2 PASS。初回不適条件/失敗記録も保持 | 未記入 |
| F実アプリ / Sandbox・TCC / iOS共通部 | native単体とは別、結果待ち | 未記入 |
| 機能別承認・復旧・配布判断 | Exact方式のみ条件付きtrue、他方式false。包括採用は未達 | 未記入 |


## 最終候補・今回の確定結果

最終コードのCMake/src/tests/scriptsインベントリは `2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392`。本項が途中集計の追記欄より新しい。[最終REPORT](../results/progressive_adoption/REPORT.md)と[manifest](../results/progressive_adoption/manifest.json)を参照する。方式承認はExactのみtrue。包括seek/publicSeekApproved、Interactive/nativeLoops/currentCycleSpeedはfalseを維持する。これは過去の禁止の継続ではなく、下記の現候補の未達による個別判断である。

- 最終Release影響回帰21/21 programs、mono44 programs/352 checks、通常速度300Acceptedの全量監査4×14=56 checks（半数は拒否注入）、起動時計20/20、AB独立PCM7×5=35 checks PASS。Debugの監査も56、先行準備16 checks PASS。新共有ヘッダーiOS device/simulator compile各1、既存不変依存のiOS app Debug build PASS。
- 通常速度の全量監査を追加した。`receiveFinalEpochAudit`は全join・callback解放後、表示256件切詰め前に全終端を渡す。`epochAuditConfigured/Calls/Rejected`と全session/ID集合を最終監査で照合し、拒否を成功にしない。D07 H<=1を使わず、実300Acceptedの298Replaced/2Cancelledと全field・履歴保持・Stop/再prepare/close一度を確認した。
- 最終stereo120件はReady p95=211.090msで200ms未達、2倍Candidate/C150s/repeat0にworker期限1。欠落・callback期限・host/sample/HAL・new/C malloc/freeは0。原因未解明としてRT/応答FAILを残す。既知FastLocal102件は対照24PASS/既知78FAIL、最大3.593187876dB。全品質集合の全面承認は未完了。
- A270の初回A PCMは未訪問cold10345.906ms、先行完了後21.150ms（先行wall10.425s）。A30は1300.741/19.973ms。各1標本でp95承認ではない。cold1000ms目標はFAIL。先行準備を総CPU削減に読み替えない。
- 180秒/2倍/CPU2両Presetの全EOSは独立RAW/供給/期限PASS。そのhostは最終でも全byte同一で再利用範囲をmanifestに記録。新engineの時計は旧同input/0.5で20回非再現だが、旧不連続の原因解明や物理連続性まで閉じない。
- Exact896/Golden25は旧証拠の現SHA・数学依存照合であり今回の新実行件数に足さない。D07/D08の既存閉鎖を保存し、新監査の証明へ一般化しない。過去/途中のFAIL・未成立・INCOMPLETEを保存した。

今回の追加契約・先行準備・全量監査は局所PASS。全体正式採用・一般公開・Merodoa既定採用は未完了。FastLocalの品質/200ms/RT、cold ABの方式/性能、実アプリF/TCC/試聴/物理確認を個別に閉じる。新API・理由・予約・寿命・復旧は[契約v3](PROGRESSIVE_ADOPTION_API_V3.md)、Fの必須12項目は[受入表](PROGRESSIVE_ADOPTION_F_ACCEPTANCE.md)。Merodoaソース/gitlink/承認SHAは変更しない。
