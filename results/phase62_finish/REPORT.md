# Phase62 残件修正

レビュー基準・開始時HEADは `c4bdbb44d92a367369e8ecf3c51fd50cb3abed4c`、main、clean。以前の `7c05319d...` は旧検証時点であり今回の実行ソースではない。今回は未commitの変更。commit/stage/push/PR/履歴書換え、Merodoa本体・UI・submodule・ピッチシフトの変更は行わない。

最終実装ソース一覧SHAは `fa2b6f4fea83e06b4d31433478ae01cae5d98c3465267c990625d4a30a171c8a`。限定再利用5群の実行ソースは `958f402ad625d1a9e5c38e210f6afb8c44589dae327f783bb1756051f20fedf2` であり、両者を区別する。SOURCE_MANIFESTとFINAL_SOURCE_DELTAで未commit差分を識別する。作業途中のrunや過去のPASSを最終ソースの証拠へ付け替えない。

## 変更した挙動

外部Loop速度要求を最大4096件の有限台帳へ保存し、全Accepted IDについて受付文脈、準備版、内部操作、実Map/B、適用・完了・置換・取消・失敗と理由を追えるようにした。上限検査を取消より先に行い、初期速度duplicateはID0、既存duplicateは元IDを返す。Ready→Resume→Pause→新速度で、開始済みの過去をReplacedへ書き換えない。

KeepPosition初回は通常producerの完全状態と公開済みFIFOを維持し、不変のゼロ保存点を通常workerで準備して同じDSPへ自己反復を接続する。初回Bの供給版は自己反復Readyまで保持する。必要な次速度版のReady・参照・採用ID公開後、Phase59の最初の合法な未来へ動的変更する。

短周期は長さだけの動的拒否を除去した。部分区間cacheでは、同じDSPを保持中のA保存点から現在周期の生成位置へ有限時間で追付かせ、cache RAWの全bit一致・周期・cursorを確認する。公開済みFIFO・未公開部分PCMは変えない。合法区間がない場合と250ms等の再構成期限未達を区別し、producerが保護範囲より先の固定Bを確定する。動的Bは採用Mapから求める。cacheへ動的な長いRAWを書き込んだ開発時の範囲外書込みも修正した。

Clearは既存の明示固定Exact継続を維持する。Pausedでは静止Cから再準備し、旧ownerのstop/join後までResume意思を保持する。最新未commit速度を使う場合は同じ外部IDをClear先へ移管し、旧準備の取消通知で失効させない。初回ReturnToAの採用前なら継続を作らずIDをCancelledへ確定する。Startedが競合で勝った場合は新targetも確認して継続を保持する。手動seekによる置換も元IDを終端化する。最終native回帰で、Clear完了通知が保持したResumeの開始成功より先に見える競合を再現した。旧owner退役・開始成功の後にclearPending=falseを公開する順へ修正し、既存の判定を緩めず再検証した。修正後のPaused Clear 24チェックはPASS。長尺の同条件A=0を先に再実行してPASSし、最終全群でもA=0/30/270・両PresetがPASSした。旧未消費FIFOの置換破棄は専用カウンタで監査する。

主な変更は `ProgressiveMacPlaybackEngine.h/.mm`、`ProgressiveLoopContract.h`、`LoopSpeedLedger.h`、`Phase57ProgressiveSynthesis.h/.cpp`、`Phase58RealtimePipeline.h/.cpp`、`Phase59Control.h`、追加native/oracle/台帳/集計試験とdriver。詳細は [設計](../../docs/PHASE62_REMAINING_DESIGN.md)、[検証手順](../../docs/PHASE62_REMAINING_VALIDATION.md)。

## 所有権・座標・資源

| 経路 | DSPとFIFO | B・採用・退役 |
|---|---|---|
| 通常producer/KeepPosition | 同じproducerと完全状態を保持。ゼロ保存点は実行しない | 自己反復Readyまでは初回B版保持。次版Ready後にだけ不可逆Map commit |
| 再利用producer | 位相/左右履歴/OLA/FIR/Map密度/位置/部分PCMを保持 | 同一commit標本のMapから動的B。旧/新のPCM所有範囲を分割 |
| cache | 固定RAW供給を維持。要求時だけ同じDSPを追付かせる | 合法性と期限を別判定。動的commit後は固定cacheの保存先へ書かない |
| Paused | C・Loop・Mapを静止。旧epoch/FIFOを準備成功まで保持 | 旧worker join・callback静止後にReadyForResume。実PCMのCompletedと別 |
| Clear | Playingは有効Loop出力、Pausedは旧Cを保持 | 明示固定Exact。自然B→Aだけ周回計数。通常接続は周回にしない |

実行所有者はPreparing・Armed・Started・退役待ちを含め最大2。不変保存点はInputLease全体で最大2、保持見積り8MiB/状態を既存準備予算に計上。FIFO16384、RAW96000/プログラム、動的履歴512、descriptor64、予約1GiBを拡大しない。FD/InputLeaseは最終利用・退役まで保持。callbackで台帳/解析/確保/解放/lock/join/I/O/planner/FFTを行わない。

`publishedAtCommit`はMap内座標である。非0A・複数周期では同一標本の `cumulativeStart + publishedAtCommit - localStart` をFIFO writeと照合し、後刻のcursorと比較しない。入力、周期内出力、producer周期、Loop周期、callback累積位置を別に保存する。

## 実施結果

Apple M1/16GiB、macOS26.6.2、Apple clang21、CMake4.3.3、arm64。Releaseは-O3/-DNDEBUG、Debugは別build。通常の装置は48kHz/512、重点API入力は44.1kHz/stereo/Float32。構成・バイナリSHAはBUILD_PROVENANCE、実行時参照・入力SHAは各EXPECTEDに保存した。

| 検証 | 期待 | 実施 | 結果（指定以外はsourcefa） |
|---|---:|---:|---|
| 決定的Release/Debug | 各18試験、6stage | 各18、6 | PASS |
| 集計器・証拠の完全性 | 36条件（正例1/負例35）+10 | 36+10 | PASS |
| 外部台帳・4096境界 | 42checks/5program | 42/5 | PASS |
| 短周期/cache重点 | 12program | 12 | PASS |
| Paused/初回Clear | 24checks/12program | 24/12 | PASS |
| Playing競合 | 74checks/12program | 72checks、全12起動 | INCOMPLETE、直接close後照会2件 |
| 通常API全列の独立比較 | 16program | 16 | PASS |
| 既存Race更新版 | 8checks×2Preset | 8×2 | PASS、独立DSP/期限判定とは別 |
| 動的全速度 | 640遷移、両Preset全161値 | 640、全161値 | PASS、source958を同一性証明付き再利用、独立planner/全RAW/Map |
| 動的重点／形式・中点 | 20＋46＋8 | 20＋46＋8 | PASS、source958再利用 |
| Exact／Golden／固定有限／reuse | 896／25／322／322 | 同数 | PASS、source958再利用 |
| B境界／内部512周期 | 680／192 | 680／192 | PASS、sourcefaで再実行。強化184を重複加算しない |
| 手動接続host最終PCM | 6 | 6 | PASS、通常API16とは別 |
| 既存native制御/probe/RAW prefix/Paused独立比較 | 14program | 14 | PASS、役割は別記録 |
| 通常Paused速度準備 | PCM36／制御84 | 36／84 | PASS、失敗退役中Playの追加assertを含む |
| B直前seek実API | 44（準備8） | 44（8） | PASS、R=0を含む |
| Clear独立PCM | 2Preset | 2 | PASS、明示固定Exact |
| 既存native期限・故障・長尺・stress | 13program | 13 | 機能PASS、正常RT8ゲートPASS。Paused40checks・故障13checksは別集計 |
| 追加必須の制御・資源異常 | CONTROL_COVERAGEの11対象 | 未閉鎖11対象 | NOT_RUN／INCOMPLETE。下記の局所NO-GOに反映 |
| 物理loopback・試聴・Merodoa実統合 | 別の公開ゲート | 未実施 | NOT_RUN |
| 必須環境・凍結素材 | macOS・入力・参照 | 全確認 | BLOCKEDなし |
| 修正前・開発中の失敗 | DEVELOPMENT_RESULTS | 記録を保持 | FAIL／REPRODUCED、最終ソースの成功とは別 |

具体例：A0_cold_candidateは現在cycle=0で75%を要求し、最初の変更PCMは出力47,104、完了49,352（旧固定B=352,800より前）。採用Map版2のBは454,435、次固定周期470,219、実出力長は454,435＋470,219＋末尾623＝925,277で独立参照と一致した。非0A/cacheのpartial_map_96000_candidateはcycle=2で、localStart=44,100、cumulativeStart=192,000、published=77,824からFIFO write=225,724を同一commit標本で照合した。

API16件は実測frontierから独立plannerが全Mapを再計算し、全RAW、次固定RAW、最終callback PCM、L_iとΣL_iが全bit一致した。両channel、長さ、NaN/Inf、窓外/補正窓内を確認。callback/worker期限超過の観測は各0だったが、API suite単独では全実時間ゲートを承認しない。正常供給でmissing/padding/rejected PCMとcallback new/malloc/freeは0、実行ownerは最大2・停止後0（検査した各hostの範囲）。

## 独立性と再利用

動的参照は旧bb22efc...の523ファイルをGit blobと照合し、保存済み4driverのSHAとcaptured_reference SHAも確認した。固定参照は旧ec087...のPhase36ソース、参照host/driver、凍結binaryのSHAを確認した。製品修正から再生成していない。詳細はREFERENCE_VERIFIED.json。

通常API試験は自然Bと次固定全周期まで通す。動的planner/Map/RAW、次固定Exact、独立境界数式による最終callback PCMを別に照合する。Phase62PcmAuditだけを独立DSP oracleと呼ばない。観測位置はmainMixer前。ゲイン0.5のhost計算は実mixer/音響の実測ではない。物理loopbackと試聴は未実施。

直前source958で今回完走したDSP5群（動的640、重点20、形式46+8、Exact896/Golden25/固定有限322/reuse322）は限定再利用した。最終修正はengine.mmとPausedClearNative、PausedSpeedNativeTestsの3ファイルであり、5binaryへのCMake/コンパイラ依存がない。新build成功後もbinary SHAが全て同じで、11入力/driverファイルと凍結参照を再照合した。REUSED_DSP_CERTIFICATE.jsonに元runと最終buildを対応付け、元runをsourcefaの再実行にしない。renderer/nativeは再利用せずsourcefaで実行し直した。凍結参照、検証済み固定RAW、条件定義、旧schema原本監査の再利用も別に記録する。旧実測gateは両構成各16件の完走・結果は監査できるが、旧binaryと全実行ソースの対応が不足し、来歴判定はINCOMPLETE。旧結果が偽PASSだったという意味ではない。旧ファイルへマーカーを追記していない。

## 判定・引継ぎ

[制御範囲と未検証境界](CONTROL_COVERAGE.md) にEの具体的不足を記録した。直接close後の全ID、実DSP Applying/Requestedの取消、通常APIのStarted部分混合、参加API自体の故障、内部資源拒否の統合等は未確認であり、局所全体はINCOMPLETE / NO-GO。allowExperimentalLoops既定false、publicLoopApproved=false、Capabilities.seek=false、currentCycleSpeedChanges=falseを維持する。FastLocal長尺、stereo Ready、開始時計、Debug期限、主観音質、物理loopback、Merodoa実TCC/統合、一般公開承認は別ゲートとして残す。

MerodoaへはrequestLoopSpeedのtyped receipt、loopSpeedHistory/loopSpeedOperation、ReadyForResumeとCompletedの区別、Clear移管・取消理由、停止C、inputGeneration/session/renderEpoch/Loop/cycle/準備版の対応を渡す。DuplicateInitialのID0へ完了通知を待たない。LimitReached/Busy/ClearPending/StaleContextの理由と再要求条件を表示側が保持する。製品採用には残る受入ゲートを閉じる必要がある。Merodoa側は今回変更していない。

## コマンド・保存先・再現

実際に使用した入口（リポジトリ直下。再実行ではNEW等の未使用保存先へ変更する）：

```sh
python3 -B results/phase62_finish/recipes/build_record.py \
  --build build/phase62_finish_20261021/release \
  --output build/phase62_finish_20261021/BUILD_ALL_V5.json
python3 -B scripts/phase62_gate_runner.py --root . \
  --build-base build/phase62_finish_20261021 \
  --output build/phase62_finish_20261021/deterministic_final_v7
PYTHON=/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$PYTHON -B scripts/phase62_finish_validation.py --suite paused-clear \
  --build build/phase62_finish_20261021/release --input results/phase31/input/mix.wav \
  --output build/phase62_finish_20261021/paused_clear_final_v4 \
  --build-provenance build/phase62_finish_20261021/BUILD_ALL_V5.json
$PYTHON -B results/phase62_finish/recipes/run_focused_final.py \
  --build-base build/phase62_finish_20261021 \
  --output build/phase62_finish_20261021/focused_final_v3 \
  --build-provenance build/phase62_finish_20261021/BUILD_ALL_V5.json
$PYTHON -B results/phase62_finish/recipes/run_remaining_gates.py --group renderer \
  --build-base build/phase62_finish_20261021 --output build/phase62_finish_20261021/renderer_final_v2
$PYTHON -B results/phase62_finish/recipes/run_remaining_gates.py --group native \
  --build-base build/phase62_finish_20261021 --output build/phase62_finish_20261021/extended_native_v3
```

全バイナリSHAは [BUILD_PROVENANCE](BUILD_PROVENANCE.json)、入力・凍結参照SHAは [REFERENCE_VERIFIED](REFERENCE_VERIFIED.json)、条件・コマンド・RAWのSHAは各EXPECTED/LEDGERから追える。代表的な通常API binaryは `30401650e30951a028db4f16a5136b28044b2c12c8b8cf71caddf50a5124f048`、Clear nativeは `d7c435134e21e5c27ac08a430a7fc9814c69d091d363f1e3c22701611443e9e0`。必須入力mix.wavは `789d4c159e35b4c133a17913ad5a9c47b85970185e5d86b074d146afc1bb311e`、動的参照は `1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818`、固定参照は `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。

修正前の最小再現は `build/phase62_finish_20261021/repro/attempt2/`、追加で発見したClear不整合は `initial_return_clear_before_v2/` と `extended_native_v1/` に保持した。Started履歴の書換えと拒否理由の欠落は2/2再現、最終Clear通知競合の長尺3件は最終統計の無いFAILであり成功に加算しない。開発時abort/誤チェック/中断・旧ソース完走も [DEVELOPMENT_RESULTS](DEVELOPMENT_RESULTS.json) へ分離した。再現には各EXPECTEDのコマンドと対応ソース/バイナリが必要で、現行binaryを修正前として使わない。

大型証拠はGit管理外の `build/phase62_finish_20261021/` に保存し、既存証拠を削除していない。小さい確定summaryと全ID集合・ハッシュをGit差分へ置く。新規ファイルは50,000,000バイト未満。今回の最新指示はstage/commit/pushを含まないため、ステージは作成していない。

最終回帰中に通常Pausedの失敗版退役中Play受付競合を検出した。seekBusyより再開禁止を先に判定へ修正し、通常workerのRetiringPreparationゲートで修正前FAILを決定的に再現した。最終ソースfaで影響する全群を再実行した。直前source562の成功記録を新ソース結果へ付け替えていない。

失敗版退役中の再開競合は `failure_retirement_before/` で決定的に再現し、`failure_retirement_after/` で21/21チェックPASS。Failed後はPlay/Resumeで再開意思を登録せず、新要求まで停止を保つ。

今回、macOS・必須入力・凍結参照の不足によるBLOCKEDはない。未閉鎖の制御/故障試験はNOT_RUNまたはINCOMPLETEであり、環境不足へ読み替えない。通常Pausedの「failure auto resumed」という旧assert名で検出した事実は、Failed後・退役中のPlay誤受理と再開意思登録である。物理的に音が再開したことを測定した記録ではない。

## 長尺・短周期の最終実機統計

長尺は48kHz/stereo/PCM16、3秒区間、速度1.00。短周期は必須mix.wavの44.1kHz/stereo/Float32、入力100ms、速度2.00。装置はID72、48kHz、512frames、2ch。下表の周回は実消費で、生成先読み周期とは分ける。

| 条件 | 実消費周回 | Mapの周期長 | Ready ms | cold prefix秒 | warm破棄総frame | warm FFT | worker生成 |
|---|---:|---:|---:|---:|---:|---:|---:|
| longA_0_candidate | 4 | 144000 | 686.23 | 0.015 | 0 | 0 | 2 |
| longA_30_candidate | 4 | 144000 | 3929.53 | 3.239 | 1024 | 0 | 2 |
| longA_270_candidate | 4 | 144000 | 30073.78 | 29.213 | 1024 | 0 | 2 |
| stress_4100_candidate | 4100 | 1804 | 42.06 | 0.034 | 0 | 0 | 2 |
| longA_0_baseline | 4 | 144000 | 692.24 | 0.015 | 0 | 0 | 2 |
| longA_30_baseline | 4 | 144000 | 3859.24 | 3.185 | 1024 | 0 | 2 |
| longA_270_baseline | 4 | 144000 | 29716.61 | 29.031 | 1024 | 0 | 2 |
| stress_4100_baseline | 4100 | 1804 | 42.07 | 0.035 | 0 | 0 | 2 |

8正常条件のmissing/padding、callback new/malloc/free、callback/final worker期限超過とWorkgroup異常はすべて0。A=30/270のwarm破棄総量1024は既存の `(reuse_count+1)*2048` 上限内であり、0とは表記しない。保存点復元4回・Map生成1回・warm FFT 0を最終退役統計でも確認した。短周期は両Presetとも実消費4100周、生成先読みはCandidate4109/Baseline4106周期で、先読み分を周回へ加算していない。故障試験後の装置bufferは親guardが512へ復元確認した。実機全体の一般性能承認や、物理音響測定の結果とは別である。


## 後続e5レビュー修正の装置復旧前の記録（2026-10-21）

この文書の未完表・実機統計は当時の証拠として保持する。後続修正は [e5レビューREPORT](../phase62_e5_review/REPORT.md)、[制御対応表](../phase62_e5_review/CONTROL_COVERAGE.md)、[MANIFEST](../phase62_e5_review/MANIFEST.json) に分離した。A/B/CとD01〜D11の追加接続点・不変条件・個別成功、Release/Debug各20CTest、独立PCMを含む選択offline9群を確認した。旧未完2件を含む過去の件数を後から成功へ書き換えていない。

この時点の後続作業の局所全体は **INCOMPLETE / NO-GO**。最終実機の予定41program中、同じ最初のcontrol1本を2回試行し、0/3checks/first callback timeoutで失敗した。残り40program（正常RT8本を含む）は未実施である。標準afplayと旧成功ビルドも開始不能で、根本原因は未確定。上に記載した旧8正常条件の統計を今回の結果へ流用しない。bufferは512へ復元、公開初期値・Merodoa採用は変更しない。


## 後続e5レビュー・装置復旧後の局所完了

最新の [e5レビューREPORT](../phase62_e5_review/REPORT.md) / [MANIFEST](../phase62_e5_review/MANIFEST.json) は今回限定の局所PASS/GO。復旧後の新runで実機5群41program・指定正常RT8本が完走PASSした。この文書の旧統計・未完表は当時の記録のまま保持する。公開・Merodoa既定採用、seek切替の一般RT（機能試験でworker期限1件観測）、物理loopback・試聴等は別ゲート。
