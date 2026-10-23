# Progressive 正式採用作業D・結果（2026-10-23）

**追加した契約・先行準備・全量監査の局所機能検証はPASS。依頼範囲全体の正式採用は未完了。** Exact方式の数値・所有権契約だけを承認し、製品設定へ反映した。Interactive/FastLocalの品質・応答・実時間、未訪問cold AB、実アプリF・音響の未達を残す。過去のNO-GOを永久禁止へ転用せず、過去の失敗も保存した。

## 候補・構成・証拠

- 開始HEAD：`f4f0e6187a643d9442216df87c04353eda4934e5`、original `main` clean。Merodoa `c6ed9251fe6e6bb518039aa03332794dd72cea0c`（開始時clean、依存確認原本はINITIAL）。Merodoa gitlink/承認設定は`f4f0e6187a643d9442216df87c04353eda4934e5`のまま。
- 独立ブランチ：`codex/progressive-adoption`、`/Users/taro252/.codex/worktrees/progressive-adoption/TimeStretchLab`。原checkout・Merodoa・submoduleは変更しない。
- 最終CMake/src/tests/scriptsインベントリSHA-256：`2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392`。基準SHAだけで未commit差分を識別しない。本REPORTを含むcommitを固定候補とし、そのSHAは作業終了時の回答とGit管理外`B/COMMIT.json`へ記録する。
- 生証拠B：`/Users/taro252/Docker/TimeStretchLab/build/progressive_adoption_20261023_01`。既存証拠を消去しない。新WAV/RAW/trace/binaryもBだけに置く。
- [manifest](manifest.json) にソース全リスト・実行体SHA・入力・参照・compiler/flags・事前条件・コマンド・実件数を対応付けた。[小さい証拠](evidence/) は原本パスとSHA付き。途中stage07の実行体は`B/pinned_build07`、最終実行体/archiveは`B/pinned_final`、参照は元の凍結保存先で保持する。
- M1 MacBookAir10,1 / 16GiB、macOS 26.6.2 (25G83)、Xcode 27.0 (27A266a)、Apple clang 21、CMake 4.3.3、arm64 Release `-O3 -DNDEBUG` / C++20。内蔵スピーカー、device 72、48kHz、512f。各実機runのENVIRONMENTと各操作の実装置値を保存。未確認機種・OS・装置へ承認を広げない。
- 製品派生入力はFloat32 WAV、44.1/48kHz、mono/stereo、両Preset、40〜200%の1%刻み。既知180秒RT再現だけは旧条件と同じPCM16を使う互換試験であり、製品入力をPCM16へ変更したものではない。

## 実装

1. `ProgressiveFeatureContract.h`で契約v3。実装・方式承認・設定・実効機能・現在許可・研究使用・安定理由コードを分離した。`ProgressiveOptions::macOSProduct()`はExactのみApprovedOnlyで有効にする。InteractiveをExactへ差し替えない。旧falseオプションの意味を維持し、明示v3設定だけが優先する。
2. Loopの同一実効値から24MiB追加予約、有限観測、boundedEpochReservations、受付、診断を導出する。`prepare(...,ContractV3Tag)`のリンク記号を変え、旧v2ヘッダー/実行体の混在を防ぐ。
3. `requestLoopPreparation`はA/B確定後の明示・最新1件の先行準備。既存の完全固定Exact状態をAで保存し、準備ownerの全stop/join/破棄後にReadyを返す。C・FIFO・epoch・周回は進めず、完了後は保存点だけを保持する。早いON/Play/Resume、速度変更、seek、Pause/Stop/入力変更/closeでは取消・退役を優先する。古いReady行を書き換えずavailableを失効する。
4. `historyUsage`と全join後`FinalOperationAudit`を追加。実4096件上限、理由付き拒否、Stop→prepareで回復しない寿命、close→新UUID/engine再作成の復旧を明記した。
5. 最終監査で通常速度の旧owner全量が表示用256件切詰め前に回収できない問題を確認し、`receiveFinalEpochAudit`を追加した。全join・callback参照解放後に通常threadから全終端を借用spanで渡す。producer sessionごと一度、所有コピーが必要。拒否はengine寿命の`epochAuditRejected`へラッチし、destructor内の最後の拒否も最終監査で可視化する。16epoch×256件の表示保持、4096操作/512計画は増やさない。D07のH<=1を通常速度へ一般化しない。
6. 入力identity異常をラッチし、InputFailureとEngineFailureを区別した。既存共有10ms検査の期限・path/保持FD照合は維持した。

SourceNode/DSP演算/位相/左右履歴/OLA/FIR/TimeMap数式/Preset/ゲイン/100%経路は変更しない。実行owner/保存点各2、FIFO16384、RAW96000/program、入力上限、予約1GiBを維持。予約はRSS上限ではない。準備履歴4096件は有界な通常側管理領域で、第三の実行ownerではない。

## 新規検証と未達

件数はこの作業で実行した各集合を示す。重複実行を合算して成功数を増やさない。期待ID、統計完了、exit/timeout、SHAを確認したものだけをPASSにした。

| 対象 | 実施・結果 | 限界・証拠 |
|---|---|---|
| 最終Releaseビルド | 23 target PASS | `build_candidate_08`、ソース上記SHA。失敗後の旧binary流用なし |
| v2/v3混在防止 | 新ヘッダーのlink成功・旧ヘッダーのprepare未解決を期待通り検出 | `abi_mix_01`、2/2。実行はしない。archive SHAはmanifest |
| v3・影響回帰 | 21/21 programs PASS | `regressions_final_02`。v3固定20ID・432設定組、初回保存点4program、prefix16×4、summary24×2、inputwatch26×2、実上限10×2、停止速度/同期等 |
| 先行準備・取消・再開・設定 | mono 44 programs / 352 checks PASS | `native_final_mono_02`、22 modes×両Preset。新設定・C静止・最新要求・close後の所有監査。通常RT/独立PCMとは別 |
| stereo代表 | 12 programs / 96 checks PASS | `native_final_stereo_01`は監査口追加前stage302ac6…の代表。最終mono全群と分ける。stereo先行Aの独立照合は2 programs / 10 checks PASS |
| 通常速度の全量監査 | Release 4×14=56、Debug 4×14=56 PASS | `epoch_audit_01` / `epoch_audit_debug_01`。各300Accepted＋切替後ID1、298Replaced/2Cancelledの全field、closed256+dropped44、Stop/再prepare/直接close一度、最大2owner、確保/解放0。半数は監査拒否注入であり通常RT承認ではない |
| 最終AB PCM | 7 programs / 35 checks PASS | `ab_pcm_02`。独立de70 Map/RAW全bit・ch/フレーム/区間所有・境界/混合式。ゲインは0.5設定ソース確認、実ゲイン/物理音声は未測定 |
| A1/A2/F01代表 | 14固有条件 / 92項目 PASS | A1は`review_final_01`の4件、他は`review_final_02`の9件と`review_final_03`の1件。前提未成立11試行を成功へ書換えない（下記） |
| 最終起動時計 | 20/20 PASS | `clock_final_02`、旧同一Float32 48k stereo入力・0.5倍・両Preset各10。最初のcallback除外0、独立RAW prefix全bit、host/sample/HAL・missing/padding・callback new/C malloc/free・worker new/期限0。旧sample0→1160は今回非再現、原因解明・全環境保証とはしない |
| 180秒固定2倍・CPU競合2 | 両Preset各1、EOSまで全90秒 PASS | `long_final_02`。独立RAW全3,969,000f/全ch/SHA一致、供給/期限/CPP確保0。`phase59_native`は最終build08でも実行体がstage07と全byte同一。C malloc/free全呼出しはこの旧hostでは未測定。旧当時の欠けたOS記録を補完しない |
| 最終stereo Interactive応答/RT | 120/120完走、監査22/22、性能FAIL | `native_final_stereo120_02`。Ready p95 **211.090ms >200ms**。2倍Candidate・repeat0・C=6,615,000入力fでworker期限1。missing/callback期限/host/sample/HAL/new/C malloc/freeは0。原因は未解明、失敗を平均化しない |
| FastLocal既知品質 | 102/102完走、24対照PASS / 78 FAIL | `quality_final_known26_01`。26固有失敗×3、最大 **3.593187876dB >3dB**、座標/欠落/重複0。最終実行体も同SHA。音質FAILを位置障害へ言い換えない |
| Debug機能 | 先行準備2 programs / 16 checks、上記監査56 PASS | `build_debug_02` / `debug_native_02`。Debug RT性能は承認しない |
| iOS共有型/既存build | 新ヘッダーdevice/simulator各1 PASS、既存iOS app Debug build PASS | `ios_headers_final_01` / `build_variants_01`。appは不変f4依存・iOS native音声スキップ。新v3 Swift/macOS統合の証拠にしない |
| Exact896 / Golden25 | 旧証拠の依存・入力・参照SHA再監査 | 新896/25実行ではない。[独立再利用監査](REUSED_EVIDENCE.json)。12数学依存は最終時も同SHA。8入力/112参照log、Golden25全WAV/5入力/旧probeを確認。Pipeline変更は新入口/保存点/停止回帰で別に確認 |
| 長尺全1440・短尺648品質集合 | NOT_RUN（最終候補の全面合格判定） | 既知26条件が未解消のため全品質承認不可。旧stereo360の数値PASSは旧条件のまま保持 |
| 全161速度/通常動的/境界音質の全面再承認 | INCOMPLETE | 旧結果・独立参照・D07/D08の閉鎖は保存。今回は全数学方式変更なし。今回の新全面実時間・音響PASSへ転記しない |
| 実アプリ/TCC/物理loopback/人の試聴 | NOT_RUN | [F受入12項目](F_ACCEPTANCE.json)（最終sourceの固定AB実収録4WAVも`B/current_audition_02`へ用意、人は未試聴）、[手順・記入表](../../docs/PROGRESSIVE_ADOPTION_F_ACCEPTANCE.md)。ピッチシフト、push、公開リリースなし |

### 同条件の性能比較

M1/内蔵48k/512、Float32 44.1k stereo300秒、同4速度×両Preset×3×5位置、確定解析済み。p95は保存validatorの`(N−1)q`線形補間。FIFO Readyと初回PCMを区別し、初回decode/SHA/複製/mlock込みの総時間とは呼ばない。

| 候補 | Ready p95 | worker期限 | 判定 |
|---|---:|---:|---|
| f4 baseline |213.098ms|0|200ms未達|
| 8192f Ready実験（stage04）|194.200ms|2|RT FAIL、製品から撤回|
| 通常leadへ戻したstage07 |215.612ms|0|200ms未達|
| 最終stage08 |211.090ms|1|200ms・RT未達|

8192案だけが期限違反の原因だとは立証していない。最終も通常leadのまま違反1を観測した。期限を緩和せず、通常供給の成功と区別する。定常CPUの今回の全面比較は未実施。制御CPUの旧f4結果を新候補の実測へ流用しない。

### AB応答（最終stage08）

Float32 48k mono impulse train300秒・Candidate1.00、解析利用可能、Playing、C<A、各1標本。事前目標はfresh<=1000ms、準備完了済み<=250ms。p95合格とは判定しない。

| A | 未訪問/保存点なし/先行なし→初回A PCM | 先行完了後→初回A PCM | クリック前の先行wall |
|---|---:|---:|---:|
|30s|1300.741ms **FAIL**|19.973ms|1.135s|
|270s|10345.906ms **FAIL**|21.150ms|10.425s|

A270は12,960,000出力fを前置合成・破棄。先行準備はその費用をクリック前へ移す方式で、総CPU削減でも保存点なしcold高速化でもない。旧Merodoa27.6秒とは素材/速度/UI区間が異なるので短縮率を算出しない。早いONは1202.837ms、Paused準備後の明示Resumeは53.315ms（性能対象NOT_EXERCISED）、実C>=BのReturnToAは1151.751ms。VM→service/UI観測、HAL/物理出音は未測定。Aの絶対位置に依存するExact前置DSPが支配し、解析待ち/Mapは別記録。

## 不採用・失敗記録と再現

- 位相だけの先頭再演実験は個別34件で全bit一致したが、実行中ソース変更により全体INCOMPLETE。Ready7〜19秒で200msを満たさず、製品へ入れない。Exact内へ新局所方式を導入していない。
- 未使用digest省略の別実験は30PCM対すべて一致、CPU中央値2.826435→2.725057秒（3.59%減）。RT問題を閉じる根拠がなく不採用。GoldenのdigestとDSPは不変。
- `build_candidate_01`はcmake起動PATH失敗。FAIL/旧binary不使用を保存し、絶対PATH環境で再buildした。
- `regressions_01`の不適fixture/12秒上限/装置sandbox拒否、`native_all_mono_02`の撤回後に残った8192試験期待値、`review_final_01`の不適16秒fixture10件、`long_final_01`の空要求列未指定2件を保存。正しい既存fixture・環境で必要対象を再確認した。
- `review_final_02/a2_initial_supply_candidate`は短曲のKeepPosition受付期限超過で正当に拒否され、採用競合はNOT_EXERCISED。同fixture一度の有界再確認`review_final_03`で6/6 PASS。失敗の元記録をPASSへ変更しない。
- 既知品質FAILは `recipes/quality.py --suite known26 --repeats 3 --mode local`、RT/Ready FAILは `recipes/run_final_performance.py` と各EXPECTED.commandで再現する。最大スペクトル誤差、期限違反ID、全期待IDをSUMMARY/AUDITに保存した。満杯・timeout・統計未完をPASSにしない。

## 実行手順・引継ぎ

[検証手順](../../docs/PROGRESSIVE_ADOPTION_VALIDATION.md)、[API v3](../../docs/PROGRESSIVE_ADOPTION_API_V3.md)、[先行準備設計](../../docs/PROGRESSIVE_LOOP_PREPARATION_DESIGN.md)を正とする。代表コマンド（R/Bは上記絶対パス）：

```sh
python3 R/results/phase62_control_ab/recipes/build_suite.py --source R --build B/candidate --record NEW_RECORD --targets TARGETS...
python3 R/results/progressive_adoption/recipes/run_regressions.py --base B --build-record B/build_candidate_08/BUILD.json --output NEW_RUN
python3 R/results/progressive_adoption/recipes/run_native_suite.py --build-record B/build_candidate_08/BUILD.json --input B/inputs/mono48_16s.wav --output NEW_RUN
python3 R/results/progressive_adoption/recipes/run_epoch_audit.py --build-record B/build_candidate_08/BUILD.json --input B/inputs/mono48_16s.wav --output NEW_RUN
python3 R/results/progressive_adoption/recipes/run_measurements.py --base B --build-record B/build_candidate_08/BUILD.json --suite clock --output NEW_RUN
```

実際の絶対コマンド、Python（numpy用runtimeを含む）、期待件数と新規出力先は各EXPECTEDに保存。凍結参照を変更後の共通libraryから再リンクしない。最終ABは保存de70実行体SHA `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`から独立Mapも再計算した。全RAW/traceはB、入力・参照の復元手順は対応recipe/旧manifestに従い、復元できない必須ゲートはBLOCKEDとする。

Merodoaへ渡すのは本commit候補＋契約v3、Exact個別availability、typed理由、Loop先行API、`receiveFinalEpochAudit`/`FinalOperationAudit`、上限後のclose・新UUID復旧である。専用非メイン直列キュー、入力FD/security scope/PCM leaseの最終join・退役後解放が必要。**全機能の既定採用・一般公開は未承認**。FastLocalの新しい安全な局所初期化と200ms/RT、cold ABの方式/性能、残る実アプリ・機器・人の受入を閉じてから判定する。
