# Phase62 制御負荷・AB入口の検証

## 比較範囲

基準ff1f677f7bcb6095b0f1d74538910f9c3e4b5d5d、独立checkoutのcodex/phase62-control-ab-performance。変更前は同SHAへ通常thread用の任意カウンターと同じ測定hostだけを加えた版を用いる。比較するTSL native processにはMerodoaのUI/Swift/JSONを含まない。Merodoa資料にある約30–40%全体値やRunning標本の割合とは別指標である。

実行原本は`build/phase62_control_ab_20261022_01/`。CPU plainは詳細カウンターOFF、Candidate100%、48kHz/512、同一240秒stereo PCM16、通常API取得5Hz、30秒×3。短AB 2秒は出力96,000以下のcache、長AB30秒は非cache。準備時間を定常測定窓へ含めない。寄与は別の5秒試行で計測し、包含関係のあるCPU/wall値を足さない。既存の3秒以内入力異常検出は不変。10msは通常側の共有検証間隔であり厳密な検出時間保証ではない。

CPU合格条件は変更前測定後・変更後実行前に固定したACCEPTANCE_PLAN.jsonによる。30秒×3中央値が変更前の95%以下、空台帳の全履歴コピー0、待機seekの反復起床0。少数の直列比較で、統計的有意性やアプリ全体の改善率は主張しない。

## 再生成・実行

大容量PCM/RAW/trace/binaryはGit管理外へ保存する。既存証拠を再実行で上書きしない。以下のOUTには未使用のbuild下のパスを指定する。実音声・性能・重いbuildは一担当が直列実行する。

```sh
python3 results/phase62_control_ab/recipes/generate_inputs.py --output build/NEW/inputs
python3 results/phase62_control_ab/recipes/build_suite.py --build build/NEW/release --record build/NEW/build --targets phase62_control_cpu_native phase62_control_summary_tests phase62_input_watch_tests phase62_clear_reenable_native phase62_prefix_checkpoint_tests phase62_warm_reenable_native phase62_initial_loop_native
python3 results/phase62_control_ab/recipes/run_cpu.py --build-record build/NEW/build/BUILD.json --input build/NEW/inputs/artificial_240s.wav --output build/NEW/cpu
python3 results/phase62_control_ab/recipes/run_control_regressions.py --build-record build/NEW/build/BUILD.json --input-dir build/NEW/inputs --output build/NEW/control
```

変更前はff1f677fの`CMakeLists.txt/src/tests/scripts/examples`を独立したbuild下へ取り出し、`recipes/baseline_instrumentation.patch`を適用する。AB比較版には続けて`recipes/baseline_ab_additions.patch`を適用する。追加は同じwarm測定hostとCMake target、既存InitialLoop hostのhit診断JSON 1項目だけである。性能最適化を変更前へ取り込まない。各成功BUILD.jsonのsource一覧・compiler・arm64/Release・実行体SHAを記録する。失敗buildの旧binaryを使用しない。

CPU比較は固定計画・変更前SUMMARY SHA・同入力/host/装置・窓・ID・有限値・終了統計を再確認する。

```sh
python3 results/phase62_control_ab/recipes/compare_cpu.py --baseline build/OLD/cpu --candidate build/NEW/cpu --plan build/PLAN/ACCEPTANCE_PLAN.json --output build/NEW/CPU_COMPARISON.json
```

## 品質・競合

制御局所試験は24program/280 checks。要約と旧全履歴APIからの独立走査の一致、4096件保持・上限、未終端索引、個別進捗、全終端39field不変、全Accepted回収を検査する。入力監視はCandidateでdynamic/standard各26件（新しいコピーだけを変更）。Clear再ONは両PresetでPreparing/Requested/Started-or-Done/Paused preparing/adopted、最新準備のStop/reprepare/close、採用保持中のStop/closeを分離する。workerの有限gateを用い、callbackをブロックしない。部分Startedを実測できずDoneが先行したケースを同一視しない。

独立固定Exact参照は既存の凍結phase61_frozen_reference、SHA de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748。参照ソースの由来・復元手順は既存`results/phase62_terminal_initial/REFERENCE_AUDIT.json`に従い、製品から再構築しない。

```sh
phase61_frozen_reference INPUT.wav 1000000 candidate REF.f32 A_INPUT B_INPUT > MAP.json
/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 results/phase62_control_ab/recipes/run_ab_quality.py --candidate-record build/NEW/build/BUILD.json --baseline-record build/OLD/ab_build/BUILD.json --input-dir build/NEW/inputs --output build/NEW/ab_quality
```

AB品質集合は12program/88 checks。fresh A=0/30/270秒とsame-prepare再要求、旧接続のClear完了待ちと即時ReturnToA要求、通常seek完全P<=OA保存点の流用を分ける。全RAW・全ch・全bit・フレーム長・独立Mapを比較し、境界窓の旧末尾/新先頭を凍結RAWから独立に算出する。validate_fixed_capture.pyは製品ヘッダーを使わない既存のfloat32境界式を再利用し、RAW observerの所有区間と出力spanの順序・混合・最終ゲイン設定を別に確認する。0.5倍のAVAudioEngine最終設定を確認しても、物理loopbackの測定にはならない。

共通制御の動的影響はPhase59凍結captured_reference（bb22由来、SHA 1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818）で実測Frontierから独立planner・独立DSPを再計算する。固定参照で動的品質を代用しない。A1/A2/F01の代表回帰、通常Pausedの制御、Release/Debug各20件の決定的ゲートを新binaryで実行し、実施集合をmanifestへ残す。

供給missing/padding/rejected=0、callback C++new/malloc/free=0、execution owner<=2・checkpoint<=2、旧FIFO保護・退役join・入力寿命を必要条件とする。deadline/worker確保・メモリも保存する。期限の値を緩めず、正常と故障注入を別に集計する。実機未実施、独立品質未測定、最終統計欠落、timeoutはPASSにしない。

## 判定の分離

機能正確性、native CPU、warm再ON、fresh初回を別判定にする。先行準備APIは導入しない。互換保存点のないA270の前置Exactが残る場合、初回高速化はINCOMPLETE。一般公開・Merodoa既定採用・実アプリ/TCC・主観音質・物理loopback・既存の長尺FastLocal等の別ゲートはこの結果で閉じない。

### 今回の追加独立監査

最終集計では変更前cold3programの同一binary/input/referenceを再利用し、保存点寿命修正後の変更版cold3programは新binaryで再実行した。音声再実行を省く場合も、全capture/RAW/span/測定/参照Map/binary/validatorの現SHA、全6品質checks・2round・3周期を次の監査で再確認する。warmの補正窓必須判定・自然B・限定されたClear退出RAW混合の区別も独立JSON座標から監査する。`run_ab_quality.py`の集計だけで最終品質承認にせず、この監査の22/22を併せて必要条件とする。

```sh
python3 results/phase62_control_ab/recipes/audit_reused_quality.py --base build/phase62_control_ab_20261022_01 --current build/phase62_control_ab_20261022_01/ab_quality_06 --previous build/phase62_control_ab_20261022_01/ab_quality_04 --final-build 9 --cpu-build 9 --control-build 9 --cpu-run cpu_after_03 --control-run control_regressions_03 --output build/phase62_control_ab_20261022_01/NEW_REUSE_AUDIT.json
```

01/02の未完了は保存する。01はOA=0へP>0を要求した旧検証器条件、02はprefixの16 ID完全集合が一致しても宣言順の違いを誤拒否した集計条件だった。専用診断と重複なし完全集合比較で修正し、未実施や失敗をその場でPASSへ書き換えていない。A1/Paused/F01の代表回帰、worker/通常Paused/動的Clear、実部分混合の実行コマンドは今回manifestの対応するEXPECTED/SUMMARYに保存する。

保存点寿命の最小再現と修正後は別集合として保存する。`repeat_range_repro_01`は旧版の3回目で2枠上限に到達したFAIL。`run_range_replacements.py`はReady/Playing/Paused/Clear後の各4連要求を両Presetで19×2=38 checks実行する。`run_final_suite.py`は最終sourceを固定し、制御24program、A1/A2/F01代表28program、通常Paused/worker/動的Clear12program、実部分混合6program、独立動的20ケース、Release/Debugゲートを直列で集約する。source変更・非zero終了・timeoutでは中止し、部分集計はINCOMPLETEとする。

停止後の新prepareへ旧軽量要約が残る最小再現も保存する。追加2 checks/PresetはAccepted/Preparingの資源取得前と、Pipeline生成前Failedをそれぞれ観測する。最終集約はPASS文字列に加え、EXPECTEDのbuild record/source/binaryと最終成功BUILDを照合し、旧版の成功を最終版へ転記しない。
