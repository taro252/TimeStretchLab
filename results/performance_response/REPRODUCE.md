# 再現・復元手順

この台帳の大容量素材・RAW・実行体は`build/performance_response_20261023_01/`（B）に保存する。
Gitへは追加しない。`manifest.json`、各runの`EXPECTED.json`、`BUILD.json`、`CLIENT.json`を
順に確認し、パスだけでなく全SHAを照合する。凍結素材・実行体を復元できなければ
該当ゲートはBLOCKEDとし、簡易素材や製品DSP由来oracleへ置換しない。

## 前提

- 基準commit5674のソース台帳は`2dae7749...`。保存05は`0d8d2e86...`、最終設定08は`b17217d8...`（完全値はREPORT）。
  `timer_source_05/SOURCE.json`は全768ファイル、`timer_archive_05/ARCHIVE.json`は54保存物を対応付ける。
- baselineは別checkout／別build。現在の作業ツリーをreset／checkoutしない。
  凍結clientの本文・旧v3ヘッダー・9archive＋heap probeは`frozen_clients_02/CLIENT.json`で確認する。
- macOS arm64のPythonを使う。この環境では
  `/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`。
  Rosetta Pythonを使用しない。全recipeは`-O`を付けず、`PYTHONOPTIMIZE`を無指定にする。
- Release `-O3 -DNDEBUG`、C++20、装置48kHz/512fの実値を確認する。通常性能は詳細profile OFF。
  1担当がbuild、重いoffline試験、音声、profilerを直列に実行する。新しい出力先を必ず指定する。
- 固定Release oracleはde70db5f…、Debugは4ee8f3d6…、動的参照は1c860210…。
  出自・全SHAはREPORT／各EXPECTEDに記録する。現在の共通libraryから再リンクしない。

## buildと必要な回帰

`recipes/build_candidate.py --build NEW_BUILD --output NEW_BUILD_RECORD --targets TARGET...`を使う。
今回の43target集合は`B/build_timer_candidate_05/BUILD.json`、追加7targetは
`B/build_d3_regressions_02/BUILD.json`の`binaries`キーから復元する。compiler/flagsと
全ソース台帳の開始・終了一致、新実行体のSHAが揃わなければ旧binaryで続行しない。
Debugは`--configuration Debug`と別buildを使う。

共有DSPの回帰は`run_fixed.py`、既存`phase62_dynamic_validation.py`、
`phase62_fix/recipes`のExact／Golden／Loop手順を使い、各元EXPECTEDのID集合と条件を維持する。
今回の依存を変えない再実行では、`evidence/CORE_GATES.json`と`FINAL05_REUSE_AUDIT`に従って
同じbinary／数学依存だけを限定再利用する。旧native性能を最新実行へ転記しない。

checkpointは次を独立に実行する。

```text
run_final_units.py --build-record BUILD --base BASE --output NEW --only checkpoint_mix checkpoint_stereo441_16s
run_checkpoint_rejection.py --build-record RELEASE_BUILD --output NEW
run_debug_functional.py --build-record DEBUG_BUILD --base BASE --output NEW
run_debug_checkpoint_rejection.py --build-record DEBUG_BUILD --output NEW
```

肯定2fixtureのApplied／全suffixを維持し、負例は安全拒否・Duplicate・別操作のExact復旧の
固定3ID、全bit・count・NaN/Inf・最終統計を必須とする。Release参照をDebugへ渡さない。

## 最終比較

今回の一括直列コマンドは`B/final_response_queue_02/EXPECTED.json`に全19stepを保存した。
このdriverは旧失敗を含む実行記録用である。新規再現では下記の修正版を個別に直列実行する。
当時実行した命令（履歴として保存）は次のとおり。

```text
run_final_comparison_queue.py
  --candidate-build BUILD.json
  --candidate-snapshot SOURCE.json
  --candidate-archive ARCHIVE.json
  --source-sha 64桁のソース台帳SHA
  --run-suffix 新しい英数字
  --output 新規出力先
```

この旧実行のABI stepは依存ファイルのSDK alias重複で0/9となったため、修正版
`run_generic_abi_header_checks_v2.py`を別runへ実行する。旧失敗を成功に書き換えない。
同様に一括手順内のDebug追加負例は旧O3参照版なので、その失敗を保存し、上の
`run_debug_checkpoint_rejection.py`で同構成Debugを別に検査する。
一括driverのreturn codeだけで全体PASSとせず、各SUMMARYの完全性・RT・性能を読む。

主な固定集合は、steady48、Interactive48program/240cases、fresh AB72、
nonfresh36、実checkpoint hitが必要なwarm12、Paused deep6。
全72freshはmono/stereo48k Float32、A30/A270、0.4/1/2倍、Candidate、旧新n3交互。
warmとprewarm完了は別集合で、先行費用を含む。RT不良をlatency成功と相殺しない。

Interactiveとwarmの共通clientは新しいgeneric builderで作り、旧v3／候補v4を各版の
同じヘッダー・library・依存SHAへ対応付ける。観測領域180秒/65536だけを旧新版へ
対称に用意し、製品のFIFO／callback／期限を変更しない。

独立最終PCM検査は`validate_ab_captures_v2.py`（108capture/540checks）と
`validate_warm_ab_captures_v2.py`（24capture/120checks）。de70凍結RAW、独立Mapと境界式を
使い、全フレーム・チャンネル順・全bit・ゲイン・窓外不変・欠落重複・周回を確認する。
validatorの8192行上限を超えた場合はBLOCKED。traceを切り詰めてPASSにしない。

CPUの未判定2条件だけの追加確認は`run_steady_followup_v2.py`。
元48をそのまま保持し、追加12programの単独n3と併合n6を別に集計する。
profilerのsampleは別集合であり、標本割合をCPU秒へ換算しない。

## 保存容量と測定区間

通常はRAWを保管できる十分な空き容量（今回の全証拠とは別に数GiB）を用意する。
今回の容量整理はB以下でのみ行い、全パス・全byte・SHAを保持した。
`share_capture_prefixes.py`は必須quiescence record、事前/事後lsof、元と一時fileの
全SHA一致を要求する。測定中、writer生存中、将来writerが起動できる状態では使わない。
Python最適化でも省略されない検査と独立したwriteを用いる。

外部の起動用driverだけを、音声子の終了・計測・wait4回収後に一時停止して共有処理を
実施した。`ORCHESTRATOR_*`、`AB_CAPTURE_BOUNDARY_*`、`AB_*QUIESCENCE*`、
`AB_*PREFIX_SHARING*`がその記録。音声callback・DSP workerへ信号やゲートを入れていない。
nativeのaccepted→PCM時刻と採取済み子CPUは調整していない。親driverの総wallは
保守待ちを含むため性能値に使わない。case31後は旧新pair間の外部待ちがあることも保持し、
ABから因果的CPU改善・温度条件の同一性を主張しない。

旧runを上書きしない。途中失敗／未完了／不採用案は`evidence/FAILURE_HISTORY.json`と
最終追加台帳へ残す。物理音声・アプリF・一般公開の未実施をnative PASSで補わない。

## 容量不足試行の回収（旧記録は保持）

`final_response_queue_02`は19/19段階を終了したが、fresh末尾2件以降は入力複製の
容量guard（入力byte＋256MiB）で再生前に停止した。製品のguardは緩めない。
今回の`run_disk_recovery_queue.py`は先にCPU追加12件の終了を要求し、次を直列実行する。

- `recover_ab_main_pairs.py`: 完了済み70件の元パス・全artifact SHA・実行記録を保持し、
  指定した容量拒否2IDだけを新規実行する。72件を新たに実行したとは記録しない。
- nonfresh36、`run_generic_warm_ab_pairs_v2.py`のwarm12、Paused deep6、sample2は新しい出力先へ全件実行。
- 完了した音声suiteの間に、writer退役を示す台帳とlsofの前後検査を経てAPFS共有を行う。
- 最後にAB全108capture、warm全24captureを同じ凍結validator・RAW・Map・境界式で数値監査する。

回収validator v2は、通常の全集合監査に加えて明示`disk-preplay-recovery-v1`だけを許可する。
70＋2の分割、旧行不変、元の容量拒否、実captureパスを検査し、全72件の数値比較を省略しない。
初回試行のFAIL/INCOMPLETEは残す。経過時間は各nativeの計測窓だけを用い、
保存共有や外部driver停止のwallを性能値に含めない。

warm collector v2は欠損費用がnullのときの集計例外だけを修正した。
nullを0へ変えず、未実施・無効測定をFAIL/INCOMPLETEとして扱う。正常値の旧集計との一致を小fixtureで確認した。
CPU followup v2はリンク実体9archive＋probeを正確に選択する（無関係の旧再生archiveを除外する）。
これらの初回driver失敗と修正は製品のPCM/RT失敗とは区別する。

`run_final_followups.py`は自動承認レビューで起動拒否され、未実行である。
既存測定終了・プロセス不在・空き容量の確認後、上の個別直列手順へ変更した。
過去の`share_capture_extents.py`は当時の通常Python実行の記録用に保持する。
新規保存共有は省略不能な検査を持つ`share_capture_prefixes.py`を用いる。

## Stop後の予約見積と実予約の区別

`reservationBytes`は保存された予約見積額で、Stop後のlive予約量ではない。
旧hostの`!final.reservationBytes`失敗はwarm/deep双方で保存した。
新規再現では`warm_ab_native_v2.cpp`／`paused_deep_native_v2.cpp`と
対応`build_generic_*_clients_v2.py`を使う。元engineの全join/close、所有者0を確認し、
別sinkの独立engineをprepare→Ready→stop→closeして実予約の再取得と解放を検査する。
再生は開始せず、元のAccepted ID監査を汚さない。probe前のprimary費用、probe費用、
probe込み費用を分け、external wait4はprobe込みであると記録する。

実行入口は`run_reservation_probe_validation.py`。主回収10stepの終了を先に要求する。
warm collectorは`run_generic_warm_ab_pairs_v3.py`、deepは`run_paused_deep_pairs_v2.py`、
独立warm監査は`validate_warm_ab_captures_v3.py`を使う。元12/144＋6/72、
全24capture/120項目と凍結RAW・境界式・8192行制約を維持する。

## hash既定ONへ戻した最終設定08

05のhash既定OFF、分岐特殊化06、block分岐07はCPU採用失敗として保存する。
同じ05 libraryでhash ON/OFFを明示した`steady_digest_cpu_pairs_01`の9実行により
OFF悪化を再現し、native既定を従来のONへ戻した。詳細profileはOFFを維持する。
`native_source_08/SOURCE.json`、`native_archive_08/ARCHIVE.json`、
`build_native_default_08/BUILD.json`を同じ組として使い、05の時刻を転記しない。
以下はrepo直下、arm64 Pythonで実行する。出力先が既存なら新しい名前を選ぶ。

```sh
python3 -B results/performance_response/recipes/run_pairs.py \
  --baseline-client build/performance_response_20261023_01/frozen_clients_02/CLIENT.json \
  --candidate-build build/performance_response_20261023_01/build_native_default_08/BUILD.json \
  --suite steady --output build/performance_response_20261023_01/steady_pairs_native08

python3 -B results/performance_response/recipes/run_interactive_generic_pairs.py \
  --client build/performance_response_20261023_01/interactive_clients_native08/CLIENT.json \
  --output build/performance_response_20261023_01/interactive_pairs_native08

python3 -B results/performance_response/recipes/run_d3_regressions.py \
  --build-record build/performance_response_20261023_01/build_native_default_08/BUILD.json \
  --extra-build-record build/performance_response_20261023_01/build_native_default_08/BUILD.json \
  --output build/performance_response_20261023_01/d3_related_native08
```

CPUは8条件×旧新×3反復の48実行、手動シークは48実行/240件、関連回帰は12driver。
音声・build・重い検査を直列にする。CPUのrunner PASSは供給/完全性を表し、
全体CPU改善の採用判定ではない。既存の入力複製容量guardとPaused用0.5GiBを保つ。
容量で開始できない項目はBLOCKED、未実施はNOT_RUNとして成功へ足さない。
過去の19step queueや失敗hostを08へそのまま再使用しない。

## 2026-10-24の評価確定と直近追加

上の05/08計画は履歴として保持する。CPU08は48＋固定追加18を終えたが、mono1倍
n6全増加で性能採用しない。新しい08の広い13step queueは実行していない。
未実施を容量BLOCKEDやPASSへ付け替えない。索引はSUMMARY/manifest/FINAL_GATESを読む。

直近の09/10は各3targetを独立Release buildし、checkpoint3caseを保存済み独立RAWへ
照合してから固定9programを比較した。09の初回configure FAILは残す。10はOFF設定を
実装しないON専用の因果切分けprobeで、性能採用できる製品版ではない。

以下は実行済みrecipeの再現例である。`NEW_*`はB内の存在しない出力先に置き換える。
08ソース・保存49target/54＋6保存物・入力/凍結参照のSHA一致を先に確認する。

```text
ARM64_PYTHON -B results/performance_response/recipes/run_checkpoint_saved_raw.py --build-record build/performance_response_20261023_01/build_native_default_08/BUILD.json --output NEW_CHECKPOINT
ARM64_PYTHON -B results/performance_response/recipes/run_mono1_digest_on_ablation.py --new-build build/performance_response_20261023_01/build_digest_on_experiment_09_02/BUILD.json --new-source d38474d21a0484a7e923009474ab39b65b864fae40d9c1e839ea0199cd96a50f --output NEW_CPU09
ARM64_PYTHON -B results/performance_response/recipes/run_mono1_unconditional_probe.py --new-build build/performance_response_20261023_01/build_unconditional_digest_probe_10/BUILD.json --new-source 4d9b4a1e0ea4e74a3a969abdb59bfd767ec7641101471102fd9cad35463102bf --output NEW_PROBE10
```

09は`prepare_digest_on_experiment09.py`でroot08をAPFS cloneし、保存07のafter.cpp
（SHA c12dee6510abcc9295f72634b127c144ad01c21abd6dfeade9a9aa8d81e0d76b）だけを置換した。
CMake構成用examples2ファイルも元SHA付きで複製し、対象3targetにはcompile/linkしない。
10はroot08の完全cloneへ`evidence/PROBE10_ON_ONLY.patch`を適用した2file差分で、
`UNCONDITIONAL_DIGEST_PROBE10_PLAN.json`と保存SOURCEを照合する。現在のrootに適用しない。
全768ソースSHA一致後に`build_isolated_candidate.py`で3targetを別buildする。
cloneが失われたときは元root08を復元し、この手順で同じsource SHAを作る。
参照de70/旧5674/入力が失われた場合は製品側から代替参照を作らずBLOCKEDとする。

無音監督dummy v2は4/4 PASSだが、内側Popen.kill未対応でD3/queueには未採用。
元v1はAPI利用不可でchild開始前FAIL。この補助試験をnative PCM/RT回帰へ数えない。

最終索引の再生成は`finalize_native08_evidence.py`へ
`--native-runs steady_pairs_native08 steady_followup_native08_01 checkpoint_native08_recheck_01`
`--decisions B/DECISIONS08_FINAL.json --output NEW_INDEX`を渡す。
索引は全768ソース/54＋6保存物/現行49実行体とGit未commit差分を確認するが、
過去PCMの新規比較や製品承認は行わない。
