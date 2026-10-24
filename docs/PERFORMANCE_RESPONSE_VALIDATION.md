# 性能・応答の検証

baselineは5674の独立checkout/build、candidateはcodex/performance-response。
arm64 Release、通常詳細診断OFF、M1/内蔵48kHz/512fを基本とし実値も保存する。
実機、CPU、build、profilerは直列。CPUは100*(user+system)/wall、1core=100%。
前後を交互に比較し、n>=3とばらつきを保存。分位点は(N-1)q線形補間。

| 集合 | 事前条件・期待 | 合格条件 |
|---|---|---|
| AB探索 | A30/A270、fresh/prewarm/途中ON各3、Candidate1x mono48 Float32 | cold<=1000ms、warm<=250ms。探索n3を全面承認へ転記しない |
| Interactive | 4速度×2Preset×3×5位置=120 | Ready p95<=200ms、期限/欠落/確保0 |
| CPU | 通常30秒×3、mono/stereoと0.4/0.5/1/2を層別 | 同条件のCPUとRTを別評価 |
| B1/B2 | 3FFT/threshold/無音/owner/alias/連続/復元 | 凍結スカラー全bit/継続状態一致 |
| DSP回帰 | 固定161、影響Golden、同履歴動的Exact | 凍結PCMの全bit/ch/count/hash、NaN/Inf0 |
| D1 | ON直後/途中/完了直前/完了後、取消/置換等 | 別IDの終端、仕事再利用、owner/checkpoint<=2 |
| C3 | copy/scan/lock前後の取消/期限/異常 | 全join・FD/予約回収・旧候補復活0 |
| D3 | 履歴0/1/100/1000/上限近傍 | 常時訪問量の有界化、全監査維持 |
| C1 | 両Preset26項目、非final複数履歴/6速度以上の退避・復元/Busy境界 | 旧全履歴replayのPlan全決定値とMap全ノード一致。通常replay=0 |
| C1費用 | 30/300/600秒×履歴0/4×両Preset×n3×旧新=72 | 同一解析入力・要求・全Map/Planを先に照合しupdate/plan/confirm CPUを別計測。座標試験をPCM/RTへ流用しない |
| C2 | mono48/stereo441 Float32各30秒、両Preset、48実行384項目 | 全解析前のExact Ready・初回pull、旧stop後同一producerで全suffix/EOS。24全suffixを凍結RAW全byte照合 |

FastLocal品質は既知26×3＋24対照=102で先に確認し、未解消のまま品質承認しない。
解析未完了は実値falseが必要。Ready、first PCM、先行費用、総費用、物理音声は別。
各runのEXPECTEDに全ID・入力/ソース/実行体/参照/validator SHAとコマンドを保存。
timeout、統計不完、欠落はPASSにせず、FAIL/NOT_RUN/NOT_EXERCISED/BLOCKEDを区別。
通常比較へ物理出音の新しい必須条件は追加しない。旧証拠は上書きしない。

C2の通常worker gateは8秒の不変解析snapshot公開後にだけ置く。callbackは用いない。
最後の購読token取消はInputAnalysisJoinWaitで観測してからgateを解除し、epochの
Joining（まだ他workerのjoin前）と区別する。final_fast/final_loop/final_eosでは、
gate中にReady/PCMが無いことも検査する。独立RAWは既存固定oracleのソースmanifestと
binary SHAを検証して再生成する。専用30秒fixtureは共有寿命の試験用であり、既知300秒の
FastLocal品質・120実機条件・長尺性能の代用にはしない。

代表的な再実行は`recipes/build_candidate.py`でソースと全新binaryを対応付け、
`recipes/run_partial_analysis.py --build-record BUILD.json --references REFERENCE_DIR
--output NEW_DIR`を実行する。全48ID・384項目・24PCM監査、最終統計が揃うことを要求する。
PCM監査の参照区間は独立oracleの入力1秒に対応するOAから全曲出力末尾まで。

checkpointの追加mono失敗は`checkpoint_fixture_repro_02`で旧5674と候補を同条件に
して再現し、両方がNoSafeInterval、Map値一致と確認した。元のFAIL記録は保持する。
元mixとstereoの肯定試験を`checkpoint_positive_final_02`で再確認し、
`recipes/run_checkpoint_rejection.py --build-record BUILD.json --output NEW_DIR`では
明示したNoSafeInterval、異速度Map拒否、状態不変、Duplicate、旧0.50倍suffixと
別操作の新0.40倍固定Exact全曲を検査する。独立oracleのSHA・入力・速度・Preset・
生成コマンドを先に保存し、3つの固定IDと最終統計がすべて揃うことを要求する。
この負例を、任意素材での動的Appliedの承認やPausedの実時間承認には使わない。

checkpoint試験追加後のソースは`bfa05533e0d5bef0f5543a09a40e5ee181111bf4e557ca066310ef8f779c7688`
（Git commitではなくソース台帳SHA-256）。直前のc230からの差は試験4ファイルだけ。
`final_archive_03/ARCHIVE.json`と`final_source_03/SOURCE.json`に、製品srcの全byte一致、
全実行体のSHA、差がある4試験バイナリを保存する。変わらない実行体の既実施結果と、
変更した試験の再実行を区別して最終REPORTへ対応付ける。

その後の有界timer候補は
`0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e`。
`build_timer_candidate_05/BUILD.json`、`timer_source_05/SOURCE.json`、
`timer_archive_05/ARCHIVE.json`を同じ組として使う。`FINAL05_REUSE_AUDIT`は
変更のない共有DSP／試験実行体を対応付け、変更されたnative性能を旧値から転記しない。
CV試行の`02b81...`は全体CPU悪化で不採用。成功した機能検査を性能成功へ流用しない。

最終設定08は`b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94`。
05からnative内部hashの既定ONだけを戻し、全49targetをReleaseで再ビルドした。
同じ05でON/OFFを明示した9実行の全体CPU比較を根拠に、既定OFFを撤回した。
保存05の応答・CPU・native RTを08の結果として使わない。08の未実施はNOT_RUN、
容量guardにより実行不能ならBLOCKEDと記録し、以前のPASSと分ける。
下位checkpoint等の再利用はソースと実行体SHAが一致した依存範囲に限る。

残る比較の直列recipeは`recipes/run_final_comparison_queue.py`。
候補BUILD／完全保存ソース／ARCHIVE／64桁source SHA／新しいsuffix／出力先を必須にする。
Interactiveは各版120の同一ID、計48program/240cases。旧新の同じ5位置本文へ通常側の
条件selectorだけを追加し、逆変換byte一致・両ABI・全依存を検証してから使う。
合算120件だけでなく各速度／Preset15件と2倍Candidate群のp95を別に判定する。
Release単独120と新交互240の結果は別集合であり件数を加えない。

fresh AB主集合は48kHz Float32 mono/stereo、A30/A270、0.4/1/2倍、Candidate、n3、
旧新計72program。common hostの有限観測だけを180秒／65536記録へ広げ、旧新版へ
同条件で使う。製品FIFO／期限／callbackは変えない。旧40秒観測の不完全attemptを
主集合へ足さない。nonfreshはmono1倍の準備完了／開始直後／途中の36program。
warmは実際のcheckpoint hitが必要な再ON12programで、missはNOT_EXERCISED。
先行CPU、操作後CPU、プロセス総CPUを分け、親子区間を足し合わせない。
各captureのRAWと加工後PCMの全byte、Mapと境界式を独立参照で別監査する。

Debugの機能回帰は計画52項目、設定20項目、checkpoint肯定2fixtureをReleaseとは別に
実行する。異なる最適化構成の凍結RAWとのbit比較失敗を無条件にcheckpoint破損と
扱わず、元の失敗を保存し、同一compiler/flagsの独立対照で原因を検査する。
Debugの機能PASSをReleaseのRTへ、ReleaseのRAW PASSをDebugへ転記しない。

## 2026-10-24の候補評価確定

現行source08は`b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94`。
通常hashはON。CPU48＋事前固定追加18でmono1倍n6全増加となり、性能一式は不採用。
Phase57分岐特殊化09、hash判定除去のON専用probe10も各9実行で改善を示さず棄却した。
05の時間・RTを08へ付け替えず、Interactive/AB/Paused深部/ABI等の広い08行列はNOT_RUN。
同一実行体による限定再利用は`results/performance_response/evidence/NATIVE08_REUSE_AUDIT.json`
の許可行だけ。現行08のcheckpointは保存済み独立RAWを検証して新規3case PASS。
[確定REPORT](../results/performance_response/REPORT.md)と同ディレクトリのSUMMARY/manifestを参照。
過去の計画・途中結果は残し、局所全体INCOMPLETE、公開WITHHELD、Merodoa既定UNCHANGEDを分ける。
