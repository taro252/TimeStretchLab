# 再実行・証拠の復元

リポジトリ直下を作業ディレクトリにする。基準HEADは`7c05319d8142ef53a70c95be4f214f293bb2428a`だが、製品は未commit差分を含む。先に`SOURCE_MANIFEST.json`、`CHANGESET.json`、`FINAL_SOURCE_ARCHIVE.json`を照合する。基準HEADだけをcheckoutして今回の修正版と呼ばない。

1. `docs/PHASE62_DYNAMIC_LOOP_VALIDATION.md`の参照復元手順を使い、凍結動的binary・ライブラリ・固定Exact binary・入力のSHAをMANIFESTと比較する。欠落を製品側の新しいDSPで埋めない。復元不能はBLOCKED。
2. 同文書のCMakeコマンドで新しいRelease/Debug領域へビルドする。`lipo -archs`が`arm64`、ビルド終了値0、新binaryのSHAを記録する。失敗後の旧binaryは使わない。
3. `scripts/phase62_dynamic_validation.py`は`--build`と`--output`を新しい場所へ指定できる。既存outputは開始前に拒否する。動的全161、重点、境界、固定回帰、通常Pausedはこのdriverを使う。
4. 本フォルダーの`run_final_*.py`は今回の実行recipeをそのまま保存したもの。実行済みoutput名や依存する凍結RAWの場所を含むため、そのまま再実行しない。Git管理外へコピーし、先頭の`base`/`build`/`out`と依存入力先を、新規build・新規output・SHA確認済み入力へ明示的に変更する。変更したdriver自身のSHAと全引数を新しいEXPECTEDへ記録する。期待件数・比較方法・合格条件は変えない。
5. native音声試験は1つずつ実行し、他のビルドや高負荷PCM比較を重ねない。装置、sample rate、buffer、CPUと実測Frontierを記録する。オフラインcallback64/128/512/4096の成功を、実機でそのbufferを測定した結果へ読み替えない。
6. `run_final_min512.py`は強化境界行列の1.00倍凍結RAW/Map、`run_final_ordinary_paused.py`は通常Pausedの36凍結RAWを再利用する。依存先は各EXPECTEDのSHAで照合する。`prepare_r0_fixture_v10.py`は旧oracleのMapからR=0を実現するBを選び、2.00倍専用API試験へ渡す。任意のBでR=0だったことにしない。
7. 最終SUMMARYに全期待件数が揃い、終了値と各比較が成功した場合だけ当該suiteをPASSにする。現在のMANIFESTは局所INCOMPLETEであり、選択suiteの成功で上書きしない。元のwrapper誤集計FAIL、途中失敗、再現ログも残す。

修正前再現は基準SHAを**別ディレクトリ**へ`git archive`で展開し、製品ソースを変更せず試験hostだけを追加してビルドする。`BASELINE_RACE_SOURCE.json`には追加CMakeと主要6ファイルの基準一致、`BaselineRaceProbe.cpp`には観測コードを保存した。`run_baseline_race.py`はその既存実行体を実行するrecipeであり、修正版のbinaryを流用しない。境界の修正前再現もBASELINE_BOUNDARY_V6_SOURCE/EXPECTEDの試験ソース・製品・binary SHAを先に確認する。

大容量証拠は`build/phase62_dynamic_20261020/`に保持する。`ARTIFACTS.json`は保存場所・サイズ・SHAの索引で、`EXECUTABLES_USED.json`は実際に測定した旧版binaryの保存先を示す。ソースarchiveを復元するときは、SHAを照合してから空のGit管理外ディレクトリへ展開し、現checkoutへ上書きしない。入力生成recipe、各EXPECTED/COMMANDS、凍結参照を使って新規outputへ再生成し、保存済み証拠を削除しない。

`assemble_manifest.py`はこの作業の固定実行先を集計する補助であり、音声・性能試験がすべて終了した後だけ実行する。新しい実行先へ使う場合はsuites一覧を明示的に変更し、元の結果を付け替えない。参照・期待件数・ソース識別のない出力は集計しない。
