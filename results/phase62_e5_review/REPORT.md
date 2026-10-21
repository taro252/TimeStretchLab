# Phase62 e5レビュー修正・検証REPORT

**局所判定：PASS / GO（本書に限定した実験機能の検証範囲）。公開・Merodoa既定採用はNO-GO。** ユーザーの装置復旧報告後、同じ最終ソース・実行体・参照・条件で実機5群41programを新規実行し、全件PASS。その内数の正常RT（実時間の供給・期限）8本も全件PASSした。復旧前の開始待ち失敗、当時のINCOMPLETE判定と未実施件数は履歴として保存し、成功へ書き換えていない。

対象はTimeStretchLabのみ。main@e5dc91675723b7163b10cc3ea2323710033caeaa、開始時clean。コード・文書は未コミットで、ステージ・commit・Push・履歴変更は行っていない。Merodoa本体・submodule・UI・ピッチシフトは変更していない。大きいWAV/RAW/trace・全ログ・実行体はGit管理外の /Users/taro252/Docker/TimeStretchLab/build/phase62_e5_review_20261021_01（以下B）へ保存する。

## ソース・ビルド・参照

| 項目 | 識別と範囲 |
|---|---|
| レビュー基準 / HEAD | e5dc91675723b7163b10cc3ea2323710033caeaa / main、変更なし |
| 最終ソース一覧SHA-256 | cefdb1294e89cb5280ad8f6df401eac59825212334e4110f958ca6f0d7c0199c。CMakeLists.txt・src・tests・scriptsの733ファイル。docs/resultsはARTIFACTSで別途識別 |
| ビルド | BUILD_REVIEW_07、Release/arm64、Apple clang21.0.0 (clang-2100.3.34.2)、C++20、-O3 -DNDEBUG。Debugはstrict build。ビルド前後ソース一致・終了0・全29実行体SHAを記録。fast-math追加等のFP条件変更なし |
| 実機 | MacBookAir10,1 / Apple M1 / 16GiB / macOS26.6.2。実行体arm64、shellはRosettaでx86_64表示。device72 / 48kHz / buffer512 / 2ch |
| Python | NumPy付き既存Python3.12。/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3。各EXPECTEDに実interpreter/driver SHA |
| 必須mix入力SHA | 789d4c159e35b4c133a17913ad5a9c47b85970185e5d86b074d146afc1bb311e。44.1kHz/stereo/Float32/10秒 |
| 動的凍結参照binary SHA | 1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818。bb22efcbd27f999e8ffe85bbe3f03e20895be3f2由来の523ソース・driver/include/libraryを照合 |
| 固定凍結参照binary SHA | de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748。旧Phase36翻訳単位と固定host/driverを照合 |

参照同一性は10/10監査PASS。参照を今回の製品DSPから作り直していない。[MANIFEST](MANIFEST.json)、[SOURCE_DELTA](SOURCE_DELTA.json)、[BUILD_PROVENANCE](BUILD_PROVENANCE.json)、[REFERENCE_VERIFIED](REFERENCE_VERIFIED.json)、[ARTIFACTS](ARTIFACTS.json)で未コミット状態を識別する。基準SHAだけを最終コードの識別に使わない。

## 修正内容

- A1：DSP取消・native Requested取消CASの勝敗を確定してから旧IDをReplacedにする。Started/Doneが勝った版は実PCM採用・Completedまで保持する。終端後の復元や未発生のcommit/PCM記録を置かない。
- A2：自己反復できないKeepPosition初回Bの必須供給版と旧IDを保持し、最新要求はその採用後に適用する。Clearでも採用済み旧IDと最新継続IDを分ける。
- B：同一ownerの実4096内部operation上限を、外部Failed/InternalLimitへ伝播する。以前のBusyRetryへ戻さず、今回確定した型付き原因を保持する。
- C / D01：destructorで音声静止、全worker join、pipeline stop/join・最終退役後に、長寿命sinkへ全外部台帳を値コピーする。Completed/Replaced/Cancelled各1、全受付ID一意一致、既完了履歴不変を直接close後に監査する。
- cache旧A→新B：受付と同じoperationMutex内で現在IDとRequestedを再確認してreason/CASする。旧Aの遅い期限判断で新Bを拒否しない。
- 部分混合、故障、有限予約：実Startedかつ0<cursor<Nで置換/Clear/Stopを検査。実join戻り値、checkpoint permit、owner構築前のepoch予約、worker開始後の実steady_clock期限を通し、旧PCM/停止C・失敗版退役・再開拒否・次要求回復を確認する。

詳細は [設計](../../docs/PHASE62_E5_REVIEW_DESIGN.md) と [CONTROL_COVERAGE](CONTROL_COVERAGE.md)。既存1GiB、追加予約24MiB、FIFO16384、RAW96000、実行DSP最大2、checkpoint permit最大2を増やさない。予約管理は受付予算であり厳密なRSS上限の追加証明とは呼ばない。callbackへ待機・mutex・join・I/O・planner・FFTを追加しない。禁止操作の個別動的検出器がない項目はコード監査の範囲に限定する。

## 今回の検証結果

| 群 | 期待 / 実施・結果 | 原本・制限 |
|---|---|---|
| レビュー機能 A/B・D02〜D06/D09〜D11 | 36program / 202checks PASS | BUILD06の30本196checks＋BUILD07の部分混合6本6checks。実行時sourceを付け替えない |
| 既存重点制御・D01 | 184checks PASS | control42＋cache12＋Playing74＋API16＋Paused/Clear24＋Race8＋8。795ddの成功子だけを依存・実行体一致で限定接続 |
| Release / Debug | 各20/20CTest PASS、全6stage完走 | 既存18件を維持、履歴8ID/descriptor7IDを追加。JUnit failure/skipped=0 |
| 証拠検証器 | 75/75単体回帰PASS | 製品の音声75件ではない |
| 凍結参照同一性 | 10/10 PASS、動的523/523ソース一致 | 参照のPCM実行件数へ数えない |
| 動的全速度 | 640/640 PASS | 両Presetで161値が実適用。独立planner・Map・動的RAW一致 |
| 動的重点 / 形式 | 20/20＋46/46＋8/8 PASS | 全速度と別の層別条件 |
| 固定回帰 | Exact896、Golden25、有限322、reuse322すべてPASS | 新binaryの今回実行。旧成功件数の転記なし |
| 境界 / 独立handoff | 872checks / 6program PASS | 184＋368＋128＋192＝872。handoff6を872へ加算しない |
| 復旧後native第1群 | 14/14program PASS | 制御、実再生観測・独立動的比較、形式別Paused PCM |
| 通常Paused | 8/8program PASS | 代表条件・制御の既存判定を維持 |
| seek API | 4/4program、44/44cases PASS | R0を両Presetで実現。要求Interactive/FastLocalの実Exact fallbackを含む。採用Interactive/FastLocal一般対応の承認ではない |
| Clear PCM | 2/2program PASS | 明示的な固定Exact再準備の独立参照方式を維持 |
| native供給・故障 | 13/13program PASS | Release/Debug Paused4＋故障1＋正常RT8 |
| 正常RT（上の41本の内数） | 8/8 PASS | A=0/30/270秒×両Preset、100ms/速度2.00/4100周×両Preset。オフラインPASSの代用なし |
| 復旧前の開始待ち | FAILを保持 | native_final/v2の同じ先頭1programが各0/3checks/first callback timeout。当時残り40本NOT_RUN |
| seek機能試験の期限観測 | worker期限超過1、RT承認NOT_ASSESSED | Candidate通常21caseの機能PASSと別記。旧fa保存runにも同じ観測。原因・発生局面・一般無退行は未証明 |
| 物理loopback / 試聴 / Merodoa実統合 | NOT_RUN、別公開ゲート | 本書の局所PASSへ含めない |

選択したoffline9群と復旧後native5群は、完了marker・全必須IDの一意な完全一致・最終統計・終了0・timeoutなし・ソース/実行体不変を確認した。offline先頭4群の原SUMMARYの selected_suite_pass=true だけを採用し、選択外NOT_RUNと全体PASS=falseは原本に保持する。[GROUP_RESULTS](GROUP_RESULTS.json)、[REVIEW_CERTIFICATE](REVIEW_CERTIFICATE.json)、[DETERMINISTIC_CERTIFICATE](DETERMINISTIC_CERTIFICATE.json)を参照。

レビュー202と重点184の来歴は限定証明である。29実行体中28点はBUILD04/06/07で不変、部分混合1点だけ変更し最終6本を再実行した。BUILD06源dfcd0562…、重点源795dd66…、最終源cefdb129…を各行に残す。旧証明の all_30_binaries_identical というキー名は件数誤記で、実列挙は29点。旧記録は保存する。

D07は実装済みLoop同一ownerの履歴H≤1<512、D08はFIFO/pending/callbackからの必要cycle距離d-c≤44<64の不変条件で閉じる。下位512/513拒否・強制古cycle拒否と、正常4100周の成功を区別する。Loopで実512枯渇や異常64追越しを再現したとは呼ばない。

## 復旧後の正常実機統計

長尺は48kHz/stereo/PCM16、3秒区間、速度1.00。短周期は必須mixの44.1kHz/stereo/Float32、入力100ms、速度2.00。装置は72/48kHz/512frames。各値は今回の原本から取得した。

| 条件 | 実消費周回 | 周期frame | Ready ms | cold prefix秒 | warm破棄frame | warm FFT | worker生成 |
|---|---:|---:|---:|---:|---:|---:|---:|
| longA_0_candidate | 4 | 144000 | 705.352 | 0.015155 | 0 | 0 | 2 |
| longA_30_candidate | 4 | 144000 | 3879.059 | 3.188555 | 1024 | 0 | 2 |
| longA_270_candidate | 4 | 144000 | 29586.459 | 28.896674 | 1024 | 0 | 2 |
| stress_4100_candidate | 4100 | 1804 | 46.058 | 0.036450 | 0 | 0 | 2 |
| longA_0_baseline | 4 | 144000 | 865.900 | 0.018614 | 0 | 0 | 2 |
| longA_30_baseline | 4 | 144000 | 3866.083 | 3.194229 | 1024 | 0 | 2 |
| longA_270_baseline | 4 | 144000 | 30650.952 | 29.962569 | 1024 | 0 | 2 |
| stress_4100_baseline | 4100 | 1804 | 39.810 | 0.034248 | 0 | 0 | 2 |

正常8条件のmissing/padding、callback new/malloc/free、callback/worker/最終退役統計の期限超過、Workgroup異常はすべて0。warm FFT再生成0、worker生成2。A=30/270のwarm破棄1024は既存上限内で、0とは表記しない。生成先読み周期を実消費4100周へ加算しない。外側guardと故障試験guardの両方でbuffer512・既定装置72の復元を確認した。

seek機能のCandidate通常SUMMARYはworker_deadlines_observed=1、callback=0、21/21機能PASS、RT_deadline_approval=NOT_ASSESSED。旧fa保存runの同SUMMARYと全byte一致（SHA f13da9647d5a33226d865cbc6754223b9695798b5ba753bed8e061d2995464d9）。[FUNCTIONAL_DEADLINE_OBSERVATION](FUNCTIONAL_DEADLINE_OBSERVATION.json)に旧source/binary・原本SHAを残す。41本すべて期限超過0とは主張しない。seek切替の一般RT承認は別に残す。

## 実行コマンド・履歴の保存

復旧後に再ビルドや製品コード変更はしていない。Release29実行体、native使用Release8＋Debug1、凍結参照、全41必須ID・元条件、第1群入力bytes/SHAが復旧前の宣言と一致することを [RECOVERY_PROVENANCE](RECOVERY_PROVENANCE.json) で確認する。

```sh
PHASE62_PYTHON=/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$PHASE62_PYTHON scripts/phase62_evidence.py --guard-device-buffer build/phase62_e5_review_20261021_01/RECOVERY_DEVICE_GUARD_01.json $PHASE62_PYTHON results/phase62_finish/recipes/run_remaining_gates.py --group native --build-base build/phase62_e5_review_20261021_01/runtime --output build/phase62_e5_review_20261021_01/native_recovered_01
```

実行済みの保存先は再利用しない。全コマンド・入力/参照/driver/実行体SHAはBの各EXPECTED、BUILD_REVIEW_07、strict_final、offline_final、native_recovered_01に保存。再生成・復元は [検証手順](../../docs/PHASE62_E5_REVIEW_VALIDATION.md) と [recipes](recipes/README.md) に従う。参照を変更後DSPから生成しない。全速度×全形式×全競合の直積や、選択した実機buffer以外の実機実施を主張しない。

ユーザー報告「装置側を復旧した」は [USER_DEVICE_RECOVERY](USER_DEVICE_RECOVERY.json) に分離した。復旧前は通常再生・標準afplay・旧成功ビルドも開始できず、原因は未確定。今回確認できたのはcallback供給の回復と上記試験結果であり、復旧操作の詳細や根本原因ではない。音声daemon・他アプリの強制終了をこちらで行っていない。

旧MANIFEST/ARTIFACTSは [history](history/BEFORE_AUDIO_RECOVERY.json)、旧コード・文書・証拠55ファイル全byteはB/metadata_before_audio_recovery_01/filesへSHA検証して保存。旧native_final、native_final_v2、final_pipelineは変更していない。旧pipelineはnative失敗のまま、復旧後nativeは別の成功runである。wrong PythonのAPI16FAIL、部分混合窓未捕捉2件、証拠検証器旧35中29PASS/6FAIL、初回cache比較configure失敗も [DEVELOPMENT_RESULTS](DEVELOPMENT_RESULTS.json) に保持する。

## 修正前再現・復元の限界

A1/A2/Bは観測・注入を加えた旧挙動比較版source31ba1ae56c5489e9e557ad96340be75a49c1c96b35d26f2cd776e78329666802、binary43cf4637898625f7d117f81885f46280ab51e16a6c1d9b78be62352bbebd406b。A1取消勝ちは6/6対照PASS、Started勝ち・初回B必須供給・内部4096はそれぞれ旧不具合を検出しexit1。純e5未改変binaryとは呼ばない。

当時cache04の保存binaryはcea0f508457098b12c0e98928fb8cd239c3129ff71f02e578f06374007f110c3と一致するが、当時sourceとの結び付き不足を後付けしない。新しい隔離比較版source72b8319e3d88edeb344d279f27196c9ff7b86680d3f6977e119a4bf8b84f3ce8、binary879ed2edd5b774d09ea97522458c5c5a27a872518b1a86a33bac10722b616980で、両Presetの旧A→新B Rejectedを2/2再現。子は各exit1/FAIL、親PASSは旧不具合の再現成功だけを意味する。独立DSP oracleではない。

旧732ファイルのうち、当該比較binaryの依存外である旧PartialMix/Fault試験2件の復元は未完。A/B実依存122、cache実依存104はSHA一致で構成できる。[BASELINE_PROVENANCE](BASELINE_PROVENANCE.json)、[CACHE_BASELINE_REPRO](CACHE_BASELINE_REPRO.json)に保存元と限界を記録する。初期保存索引7行中3行の不一致はFINAL_BASELINE_FILESと当時期待SHAで解決し、その索引だけから復元しない。凍結DSP参照の欠落とは区別する。

## 判定とMerodoaへの受入条件

今回指定された局所の機能・独立PCM/planner/Map/境界・有限資源・正常RT8本のゲートはPASS。allowExperimentalLoops=false、publicLoopApproved=false、Capabilities.seek=false、currentCycleSpeedChanges=false、publicSeekApproved=falseは維持する。FastLocal長尺既存失敗、stereo Ready目標、開始時計、Debugやseek切替の一般RT、主観音質・物理loopback、Merodoa実TCC/実アプリ統合、一般公開承認は閉じない。

Merodoaへ渡す契約はLoopSpeedReceiptと全ID履歴、Resume前ReadyForResume、最新要求ID/入力世代/Loop/停止C/準備版の一致、失敗版退役中の再開拒否、直接close後のFinalLoopSpeedAuditである。AcceptedをReady/Completed表示に使わない。全Accepted ID終端・過去不変、実PCMと座標・自然周回、最大2所有者、旧版join/参照解放を受入条件にする。sink contextはEngine破棄完了まで保持し、受取spanは値コピーし、callbackへ監査を接続しない。

Git側に大きな音声・実行体・トレースを追加しない。新規各ファイルは50,000,000 bytes未満を確認する。今回の局所GOを公開やMerodoa既定採用へ広げない。
