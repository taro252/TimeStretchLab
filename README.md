# TimeStretchLab — Phase 1

プロジェクト全体の設計方針は [DESIGN.md](DESIGN.md) を参照してください。

Apple Accelerate と C++20 によるオフライン WAV タイムストレッチ。DSP は planar float32 で処理します。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
ctest --test-dir build --output-on-failure
./build/timestretch input.wav output.wav --speed 0.5
./build/phase1_tests results/phase1
./build/phase1_validation
```

入力: mono/stereo、44.1/48 kHz、PCM int16 または IEEE float32 WAV。出力: IEEE float32 WAV。

既定の FFT は 4096 点、解析ホップは 1024 サンプル。合成ホップは `analysisHop / speed` で、フレーム位置を絶対座標から丸めるため、非整数ホップでも累積丸め誤差を避けます。周期 Hann 窓を解析と合成に適用し、重ね合わせた各サンプルを窓の二乗和で割ります。speed=1.0 は入力をそのまま通す経路です。

`--fft-size`、`--analysis-hop` で変更できます。後続 Phase のスイッチは予約済みですが、Phase 1 では `off` のみ受け付けます。Phase 2 以降の位相補正、ピーク位相固定、過渡検出、複数解像度処理は含みません。

`TimeStretchEngine` は構成と処理の窓口、`STFT` は窓と FFT、`PhaseVocoder` は各チャンネルの位相状態、`OverlapAdd` は復元と振幅補正を担当します。後続 Phase ではこれらの処理段階を拡張できます。
