# 再現手順

checkout `/Users/taro252/Docker/TimeStretchLab`。原本はGit管理外 `build/phase62_terminal_initial_20261022_01`、入力・binary・source・各出力hashは各EXPECTED/BUILD/MANIFEST JSON。上書きせず新規出力先で実行する。macOS実出力・性能試験は他の重負荷試験と重ねない。

```
cmake -S . -B build/phase62_terminal_initial_20261022_01/a1_build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DBUILD_TESTING=ON
cmake --build build/phase62_terminal_initial_20261022_01/a1_build --target phase62_history_clear_native phase62_initial_loop_native phase62_loop_speed_ledger_tests phase62_paused_clear_native phase62_playing_ledger_native phase62_adoption_review_native -j2
python3 -B results/phase62_terminal_initial/recipes/run_history_regressions.py --build-record build/phase62_terminal_initial_20261022_01/BUILD_A1_01.json --fixture build/phase62_terminal_initial_20261022_01/inputs/artificial_48000_mono_6s.wav --output build/phase62_terminal_initial_20261022_01/a1_fixed_02
```

BUILDにはビルド直前/直後のsource inventoryと成功コマンド、実行binary SHAが必要。失敗buildの旧binaryを使わない。通常sandboxから装置が見えない場合は、実機アクセス可能な実行環境を使う。A1の期待値28program/147checks、全ID一致、正常終了、SUMMARY完了、timeoutなし。各子チェックの失敗・未実施を集計へ隠さない。測定は期限合否と分ける。

```
python3 -B results/phase62_terminal_initial/recipes/run_initial_bench.py --build-record build/phase62_terminal_initial_20261022_01/baseline_02/BUILD.json --input build/phase62_fix/run_01/final_v9/evidence/release_longA/same_300s_48000_2_pcm16.wav --output build/phase62_terminal_initial_20261022_01/bench_before_02
```

このbeforeはe4のEngine.mm＋新測定hostの隔離sourceで、純e4binaryとは区別する。新製品のA1helperは未使用で、A2最適化を含まない。7program/14samplesを要求し、途中driver例外のbench_before_01はINCOMPLETEのまま保存する。数値受入はACCEPTANCE_PLAN_01.jsonで実装前に固定済み。A2候補は別BUILD・同じhost/入力/条件・新出力先で測る。old結果への件数付替えはしない。

固定Exact参照は旧独立binary `build/phase61/oracle_release_v1/phase61_frozen_reference`（SHA-256 de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748）を使う。

```
phase61_frozen_reference INPUT.wav SPEED_MICROS baseline REF.f32 A_INPUT B_INPUT > REF_MAP.json
python3 results/phase62_terminal_initial/recipes/validate_initial_pcm.py --help
```

参照RAWとMapは入力・参照binary/source manifestを照合してから使う。`validate_initial_pcm.py`はRAW/Map/全bit/全channel/座標/非有限値と独立境界式を照合する。大容量ファイルはGitへ入れず、各manifestのレシピから復元する。旧frozen sourceのmanifestおよび退避素材の復元は既存Phase59/61手順を使い、製品変更を参照へ取り込まない。
