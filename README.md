# TimeStretchLab — Phase 1 / Phase 2 / Phase 3

プロジェクト全体の設計方針は [DESIGN.md](DESIGN.md) を参照してください。
今回の Peak-based Phase Locking の要件は [PHASE2_REQUIREMENTS.md](PHASE2_REQUIREMENTS.md) に保存しています。
Transient Detection + Phase Reset の要件は [PHASE3_REQUIREMENTS.md](PHASE3_REQUIREMENTS.md) に保存しています。

Apple Accelerate と C++20 によるオフライン WAV タイムストレッチ。DSP は planar float32 で処理します。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
./build/timestretch input.wav output.wav --speed 0.5
./build/phase1_tests results/phase1
./build/phase1_validation
./build/phase2_tests results/phase1 results/phase2
./build/phase3_tests results/phase2 results/phase3/artificial
```

入力: mono/stereo、44.1/48 kHz、PCM int16 または IEEE float32 WAV。出力: IEEE float32 WAV。

既定の FFT は 4096 点、解析ホップは 1024 サンプル。合成ホップは `analysisHop / speed` で、フレーム位置を絶対座標から丸めるため、非整数ホップでも累積丸め誤差を避けます。周期 Hann 窓を解析と合成に適用し、重ね合わせた各サンプルを窓の二乗和で割ります。speed=1.0 は入力をそのまま通す経路です。

`--fft-size`、`--analysis-hop` で変更できます。`--phase-locking on` で Phase 2 のピーク位相固定を使い、`off`（既定）で Phase 1 と同じ処理を使います。`--debug-csv directory` を指定すると、ON 時のフレーム・ピーク情報をチャンネル別 CSV に記録します。過渡検出と複数解像度処理は含みません。

`TimeStretchEngine` は構成と処理の窓口、`STFT` は窓と FFT、`PhaseVocoder` は各チャンネルの位相状態、`PhaseLocker` はピーク検出・所有領域・相対位相の固定、`OverlapAdd` は復元と振幅補正を担当します。後続 Phase ではこれらの処理段階を拡張できます。

実録音の Phase 1/2 比較は、`bash scripts/phase2_real_ab.sh mix.wav bass.wav guitar.wav piano.wav vocal.wav drums.wav` で実行できます。0.75x/0.50x の ON/OFF を同じ条件で書き出し、`results/phase2/real/stems/` に一覧と処理時間を記録します。4 素材の旧形式の呼び出しにも対応しています。

Phase 3 は `--transient on` で、オフラインの過渡検出と左右共通タイミングの位相リセットを追加します。`--debug-csv directory` で `transients.csv` にスペクトル変化量、閾値、強度、検出・リセット位置を記録します。実録音の Phase 2/3 比較は `bash scripts/phase3_real_ab.sh mix.wav bass.wav guitar.wav piano.wav vocal.wav drums.wav` で生成できます。
