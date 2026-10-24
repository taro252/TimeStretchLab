# 性能改善用の凍結スカラー参照

基準コミットは `5674bd982d98caacaa3e87cdeae5bfc0b01c66ef`。PV（各周波数成分の位相を進める処理）、左右位相補正、依存する PhaseLocker を、そのコミットの Git blob から取得した。変更は `PROVENANCE.json` に列挙したクラス名と include の置換のみで、演算、条件、順序、状態更新は変更していない。元 SHA-256、Git blob ID、置換後 SHA-256 を同ファイルに保存している。

候補側の DSP 関数を参照実装から呼ばない。標準ライブラリの数学関数とコンパイラは共用するため、同じビルド条件で全ビット比較するための参照である。凍結した全曲 Exact、動的 Map、Golden、実機、実時間、性能の検証とは別の範囲である。

`tests/PerformanceDspEquivalenceTests.cpp` の登録時には、以下の3ファイルもコンパイルする。

- `tests/reference/performance_response/Frozen5674PhaseVocoder.cpp`
- `tests/reference/performance_response/Frozen5674StereoPhaseCoherence.cpp`
- `tests/reference/performance_response/Frozen5674PhaseLocker.cpp`

試験は引数なし。実行前に `EXPECTED`、各ケースの `CHECK`、最後に `SUMMARY` を JSON で標準出力へ出す。失敗は終了コード1、不正な起動引数は2。156 IDを固定し、すべて成功した場合には以下の計数になる。件数が不足しても成功にはしない。

| 対象 | 固定件数 |
| --- | ---: |
| 1024 / 4096 / 8192 FFT の主系列 | 141 ケース、各32フレーム |
| 空 / 1 / 2 / 半長の owner 配列の process | 12 ケース、各8フレーム |
| 同じ入力アドレスを使う view 寿命 | 3 ケース、各7フレーム |
| 分岐継続を含むフレーム比較 | 5052 |
| 再同期の呼び出し | 891 |
| コピーした状態からの3フレーム分岐 | 141 |
| 状態の代入復元 | 144 |
| 左右補正の view 選択 / 再同期後の失効確認 | 3159 |

主系列は、非重複・同一領域・両向きの部分重複・隣接境界、左右交差と同一出力を含む。床値 `1e-7f` の前後1 ULP（隣り合う表現可能な値）、無音からの再出現、正負ゼロ、DC / Nyquist、前後を向く owner と無効値 `-1/0`、リセット、選択的リセット、解析ホップ変更を使用する。出力と領域周辺、公開ピーク情報、左右補正の重みと累積平均を全ビット比較し、非有限値を拒否する。

公開 `InputPolarView` の有効・欠落・古いフレーム・別owner・片側のみを左右補正へ渡す。コピー、元オブジェクトへの代入復元、reset、resynchronize 後には借用キャッシュが失効することを確認する。短い owner 配列は従来安全に呼べた `process` だけで使い、配列の全幅を要求する再同期や左右補正へは渡さない。範囲外の owner や過大な配列による元から未定義の操作は実行しない。

このファイル群の作成段階ではビルド、試験、音声、性能測定を実行していない。`PROVENANCE.json` の `FROZEN_SOURCE_ONLY_NOT_EXECUTED` は作成時点の状態であり、後の実行証拠は主担当のビルド・実行 manifest に保存する。
