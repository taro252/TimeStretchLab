# 再実行入口

リポジトリ直下で実行する。WAV/RAW/trace/binaryは新規のbuild配下へ置く。既存の実行先を再使用しない。今回の確定source/binary SHAは一つ上のMANIFEST、実際のコマンドは各EXPECTEDを参照する。

1. `scripts/phase62_gate_runner.py` でRelease/Debug各18試験を実行する。
2. 追加targetは `python3 -B results/phase62_finish/recipes/build_record.py --build build/NEW/release --output build/NEW/BUILD.json`。configureとbuildが成功し、前後のソースが同じ場合だけ23binaryのSHAを記録する。今回のBUILD_ALL_V5はこの入口で実行したbuildの記録である。
3. `run_focused_final.py --build-base build/NEW --build-provenance build/NEW/BUILD.json --output build/NEW/focused`。NumPy2.xを使えるarm64 Pythonを使う。close照会が未観測なら結果はINCOMPLETEのままになる。
4. `scripts/phase62_finish_validation.py --suite paused-clear` を同じbuild/input/provenanceと新出力先で実行する。
5. 全DSP行列の再実行には `run_remaining_gates.py --group offline` を使う。今回の最終Clear修正では5群の同一性証明を伴う再利用とし、影響するrendererだけ `--group renderer`、続いて `--group native` を直列実行する。必要な旧入力・RAWは旧EXPECTED/LEDGERのSHAと原manifestで検査する。原レシピと条件のSHAを新EXPECTEDへ保存し、適応版を新出力先へ作る。native故障試験は親で装置bufferを復元する。

今回の最終実行sourceはfa2b6f4f…（限定再利用5群の元runは958f402a…）、レビュー基準はc4bdbb44…。`assemble_finish.py`は今回の一意な実行名・source SHAを固定しており、別sourceや別保存先を無条件に今回へ集計しない。再実行時は新たな計画を作り、その差を記録する。

動的oracleの復元は `scripts/phase59_rebuild_reference.py`、固定oracleは `scripts/phase61_freeze_reference.py` と保存済みmanifestを使う。`../references/`に検証済みの元manifestとソース一覧を保存した。製品コードを参照へ取り込まない。元binary/inputのSHAが一致しない場合は復元または独立再検証が必要であり、単純に新SHAを正解へ差し替えない。

旧source958の`focused_final_v1/EXPECTED.json`に記録した実行driverは `focused_final_v1/EXECUTED_DRIVER.py`にも保存した。実行後、再実行レシピの子exit検査を明示したが、元EXPECTED/実行結果は変更していない。DRIVER_PROVENANCE.jsonで両SHAと今回の全子exitを追える。

最終ソースの正式保存先は deterministic_final_v7 / focused_final_v3 / paused_clear_final_v4 / renderer_final_v2 / extended_native_v3。未完走は各SUMMARYでINCOMPLETEのまま残す。旧source958のnative長尺3件FAILと中断stressも開発記録へ保存し、最終成功件数へ混ぜない。

最終faソースの実行は `build/phase62_finish_20261021/RUN_FINAL_SERIAL_V3.py` で直列化した。全5段階の実コマンドとdriver SHAは同配下のSERIAL_FINAL_V3_EXPECTED.json、結果はSERIAL_FINAL_V3_SUMMARY.json。Playingの既知close2件によるexit2を個別に検査し、INCOMPLETEのまま後続検証へ進む。その他の予期しない非0終了では停止する。
