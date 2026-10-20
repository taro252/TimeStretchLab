# Phase62 動的Loopの検証手順

結果と未実施は [REPORT](../results/phase62_dynamic_loop/REPORT.md)、契約は [設計](PHASE62_DYNAMIC_LOOP_DESIGN.md) を参照する。オフラインの完全一致、macOSの供給試験、物理出力の品質承認を分ける。過去Phaseの成功件数は今回の実施件数に含めない。

## 参照を固定する

動的参照は `results/phase59/FROZEN_REFERENCE.json` と `CAPTURED_REFERENCE.json` が指定する旧 `bb22efcbd27f999e8ffe85bbe3f03e20895be3f2` 由来のライブラリを使う。`build/phase59_frozen/captured_reference` のSHA-256は `1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818`。製品変更をこの参照へ取り込まない。復元は既存 `scripts/phase59_rebuild_reference.py` と文書の手順に従い、復元できなければBLOCKEDとする。

固定Exact参照は `results/phase62_fix/recipes/oracle_manifest.json` の `build/phase61/oracle_release_v1/phase61_frozen_reference`。SHA-256は `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。上記動的参照とは別に、次周期・停止中のC・明示的Exact継続を検査する。

実行前に参照binary、入力、製品binary、ソース一覧のSHA、条件、期待件数を保存する。実行後のソースと参照の不変も確認する。独立plannerへ実測Frontier（各解像度の処理位置・生成保護範囲）を渡して再計画し、採用計画のDSP再生とMap全nodeも比較する。壁時計を同期させる必要はない。

## 分離した試験

各出力先は存在しない一意な `build/` 配下を指定する。大量のWAV/RAW/JSONLをGitへ追加しない。以下のdriverは実行前EXPECTED、逐次台帳、最終統計、入力レシピ、コマンド、SHAを保存する。

Apple Accelerate/CoreAudioを使うmacOSで、まず新規のbuild領域を構成する。今回の実行はarm64、C++20、Release `-O3 -DNDEBUG`。Debugは別領域である。次は新しい検証を始める例で、既存の実施記録を上書きしない。

```sh
cmake -S . -B build/phase62_dynamic_repeat/release -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64
cmake --build build/phase62_dynamic_repeat/release --parallel 2 --target phase62_dynamic_pcm_tests phase62_dynamic_boundary_tests phase62_dynamic_handoff_tests phase62_dynamic_controls_native phase62_dynamic_loop_probe phase62_paused_pcm_tests phase62_dynamic_seek_native phase62_clear_pcm_native phase62_race_native paused_speed_loop_tests phase62_fix_safety_tests
cmake -S . -B build/phase62_dynamic_repeat/debug -DCMAKE_BUILD_TYPE=Debug -DCMAKE_OSX_ARCHITECTURES=arm64
cmake --build build/phase62_dynamic_repeat/debug --parallel 2 --target phase62_fix_safety_tests phase62_dynamic_boundary_tests paused_speed_loop_tests
```

下記コマンドのbuild/outputは今回保存した実行先を示す。再実行では上記等の新規buildと、存在しないoutputへ置き換える。音声装置を使うhostは一つずつ実行し、他のビルド・重いPCM比較を同時に行わない。ビルドの終了値と新しいbinaryのSHAを確認してから実行する。個別条件のコマンドと期待件数は各EXPECTED/COMMANDSを正とし、補助driverの保存先変更は [再実行の注意](../results/phase62_dynamic_loop/recipes/README.md) に従う。

```sh
python3 -B scripts/phase62_dynamic_validation.py --suite dynamic161 --build build/phase62_dynamic_20261020/release --output build/phase62_dynamic_20261020/final_dynamic161
python3 -B scripts/phase62_dynamic_validation.py --suite dynamic-priority --build build/phase62_dynamic_20261020/release --output build/phase62_dynamic_20261020/final_priority
python3 -B scripts/phase62_dynamic_validation.py --suite boundary --build build/phase62_dynamic_20261020/release --output build/phase62_dynamic_20261020/final_boundary
python3 -B scripts/phase62_dynamic_validation.py --suite regression --build build/phase62_dynamic_20261020/release --output build/phase62_dynamic_20261020/final_regression
python3 -B scripts/phase62_dynamic_validation.py --suite paused --build build/phase62_dynamic_20261020/release --output build/phase62_dynamic_20261020/final_paused
```

`dynamic161` は隣接160組×双方向×2Presetの640遷移。受理やReplacedだけで全161速度を網羅したことにせず、実Applied・独立RAW・Map・最終統計の検証済み行だけを数える。オフライン消費側は要求位置で通常plannerの取引を待つ。これは音声callbackを止める試験ではなく、実時間のFrontierは下記native hostで別に測る。

`boundary` は100msの `[17,17+rate/10)` と0.40/1.00/2.00、両Preset、callback 64/128/512/4096。旧固定oracleで全整数入力位置を先に計算し、R=0、N−1、N、N+1、B−1、A、中点を選ぶ。丸めにより指定Rが実現不能ならその事実と実現可能な両側を残す。Nは出力フレーム単位。最終PCM、窓外不変、補正窓、自然Bの数、累積位置を検査する。

追加の長さは `phase62_dynamic_boundary_tests INPUT SPEED PRESET ORACLE_RAW OA OB LOOP_MS`。末尾 `--old-near-b` で、旧側の進入混合もBを跨ぐvariantを追加できる。oracleの `-` は独立DSP比較なしの試験であり、独立合格として集計しない。

`--period512` は内部下限専用のfixture。採用MapでAから512出力フレームとなる整数入力Bを探索し、旧oracleのOA/OB・RAWへ照合する。公開APIの100ms入力下限を変更しない。最低3回は4096フレームのcallbackを実行し、各callbackサイズでBの位置が1、callback/2、callback−1となる観測をすべて要求する。`--old-near-b` と併用する場合は `--period512 --old-near-b` の順に置く。再現レシピは `results/phase62_dynamic_loop/recipes/run_final_min512.py`。

100ms本行列もケース名だけで判定せず、独立oracleから決めた入力C・残量R・混合長N・callback・旧側variantを照合する。初期の弱い集計は保存し、強化した行列の結果で該当184件を再検査する。

## macOSで直列実行するhost

`phase62_dynamic_loop_probe INPUT PRESET --require-fixed NEW_DIR` は8秒Loopの前半での現在周期適用、速度変更なしの動的履歴Pause/Resume、Resumeを一度も呼ばない新速度Readyを記録する。その後、次で実測Frontierの独立planner・Map(B)・全チャンネルRAW prefixを照合する。

```sh
python3 -B scripts/phase62_dynamic_native_audit.py INPUT PRESET NEW_DIR build/phase59_frozen/captured_reference --native-binary build/phase62_dynamic_20261020/release/phase62_dynamic_loop_probe
```

`phase62_dynamic_controls_native INPUT PRESET NEW_DIR` は通常workerだけを遅延させ、commit済み75%の必須境界版を保持した200%置換、commit後Clear、取消直後Pauseを検査する。音声callbackを試験ゲートで停止しない。最大2所有者はImpl生成から破棄までのカウンターで検査し、停止後0を要求する。callbackのC++newとmalloc/free検出器は自己試験後に使う。

`phase62_paused_pcm_tests INPUT SPEED PRESET NEW_DIR FIXED_ORACLE` は停止CとLoopを保持したResume前Ready、その後のC→BとA→Bを独立固定Exactと比較する。

`phase62_dynamic_seek_native INPUT PRESET NEW_DIR` は3速度で21件の実seek APIを検査する。Paused Exact準備、B−1のC保持、B/B以後のA補正、FastLocal/Interactive要求に対する実採用Exactとreason、Resume後の実PCMフレーム数とMap残量から求めた自然B回数を記録する。末尾へ `R0_INPUT_B` を指定すると、2倍速のB−1が実際にR=0であることを要求する専用1件を実行する。Bは先に独立旧oracleのMapから選ぶ。通常範囲でR=0が実現しなければ、その事実を残す。このAPI試験の製品RAW加工検算を独立DSP比較へ算入しない。

`phase62_dynamic_handoff_tests INPUT INITIAL TARGET PRESET NEW_DIR DYNAMIC_ORACLE FIXED_ORACLE CALLBACK` は実rendererをオフライン駆動し、現在動的RAW・次固定RAW・独立境界数式・L_iとΣL_iを比較する。これは手動接続hostであり、通常制御の全競合やHAL期限の代わりにはしない。hostゲイン式0.5と実mixerの音響測定も区別する。

## 判定

全ビット、チャンネル順、長さ、Map、適用/完了座標、NaN/Inf、欠落/重複を別々に検査する。正常時missing/padding/underrun/callback allocationは0。実時間期限・時計の異常は観測値を残し、機能合格で期限合格を代用しない。タイムアウト、最終統計欠落、0件、ビルド失敗後の旧binaryはINCOMPLETE/FAIL。選択suiteのPASSは局所全体GOではない。

全方式・全競合・故障・長尺位置・Debugの必要条件が残れば、公開フラグと `currentCycleSpeedChanges=false` を維持する。物理loopback、試聴、MerodoaのTCC/統合は実施した場合だけ記録する。

## 保存トレースと追加ゲート

`callbacks_all_spans` は既存名で、実体は末尾256 callbackの循環領域。異常前後は別の33領域を使う。長時間の全PCMや全callback履歴を保存したという意味ではない。累積フレーム・周回・不足・確保・期限のカウンターと、オフライン全列PCM比較を分ける。

`phase62_clear_pcm_native` は事前生成した凍結固定75% RAW、OA/OB、binary/RAW SHAを受け取り、実Clearの旧RAW末尾/新RAW B以後、独立線形混合式、窓外を比較する。自然周期の局所末尾補正はClear窓へ適用しない。mainMixer前の観測であり、実ゲイン・物理出力の承認とは分ける。再現driverは `results/phase62_dynamic_loop/recipes/run_clear_pcm_native.py`、2Presetの台帳は `run_final_clear_pcm.py`。

`phase62_race_native` は通常workerのSwitchPublished（DSPへ要求を渡す前）だけを遅延し、75→100→40→200の未commit置換を明確にする。最新200の元周期内Completed、Paused75のResume前Ready、Clear供給、Stop、入力世代、最大2所有者を記録する。8件目はKeepPosition未対応の理由表示・供給維持だけで、その現在周期機能を合格に数えない。commit後の版保持は別の `phase62_dynamic_controls_native` で検査する。
