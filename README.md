# TimeStretchLab — Phase 1〜5

**現在の製品向け音質基準は Phase 12 の Experimental 3500 Hz** です。設定、15本の無加工ゴールデンWAV、リアルタイム化との差分・計画は [正式音質基準](PHASE12_QUALITY_BASELINE.md)、[ゴールデン参照](results/phase12/golden/REPORT.md)、[音源保管設計](PHASE12_ARTIFACT_CUSTODY.md)、[リアルタイム化計画](PHASE12_REALTIME_PLAN.md) を参照してください。既存CLIの既定値は互換性のため変更しておらず、この基準を使うときは `--quality experimental --high-crossover-hz 3500` を明示します。

プロジェクト全体の設計方針は [DESIGN.md](DESIGN.md) を参照してください。
今回の Peak-based Phase Locking の要件は [PHASE2_REQUIREMENTS.md](PHASE2_REQUIREMENTS.md) に保存しています。
Transient Detection + Phase Reset の要件は [PHASE3_REQUIREMENTS.md](PHASE3_REQUIREMENTS.md) に保存しています。
イベント統合と局所時間配置の要件は [PHASE35_REQUIREMENTS.md](PHASE35_REQUIREMENTS.md) に保存しています。
アタック領域保護と帯域別位相リセットの要件は [PHASE36_REQUIREMENTS.md](PHASE36_REQUIREMENTS.md) に保存しています。
ステレオ位相の一貫性に関する要件は [PHASE4_REQUIREMENTS.md](PHASE4_REQUIREMENTS.md) に保存しています。
複数解像度処理の要件は [PHASE5_REQUIREMENTS.md](PHASE5_REQUIREMENTS.md) に保存しています。
継続的な調波ピーク追跡の要件は [PHASE6_REQUIREMENTS.md](PHASE6_REQUIREMENTS.md) に保存しています。

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
./build/phase35_tests results/phase35/artificial
./build/phase36_tests results/phase36/artificial
./build/phase37_tests results/phase37/artificial
./build/phase4_tests
./build/phase5_tests
```

入力: mono/stereo、44.1/48 kHz、PCM int16 または IEEE float32 WAV。出力: IEEE float32 WAV。

既定の FFT は 4096 点、解析ホップは 1024 サンプル。合成ホップは `analysisHop / speed` で、フレーム位置を絶対座標から丸めるため、非整数ホップでも累積丸め誤差を避けます。周期 Hann 窓を解析と合成に適用し、重ね合わせた各サンプルを窓の二乗和で割ります。speed=1.0 は入力をそのまま通す経路です。

`--fft-size`、`--analysis-hop` で変更できます。`--phase-locking on` で Phase 2 のピーク位相固定を使い、`off`（既定）で Phase 1 と同じ処理を使います。`--transient on` で Phase 3 の過渡検出を使います。

`TimeStretchEngine` は構成と処理の窓口、`STFT` は窓と FFT、`PhaseVocoder` は各チャンネルの位相状態、`PhaseLocker` はピーク検出・所有領域・相対位相の固定、`OverlapAdd` は復元と振幅補正を担当します。後続 Phase ではこれらの処理段階を拡張できます。

実録音の Phase 1/2 比較は、`bash scripts/phase2_real_ab.sh mix.wav bass.wav guitar.wav piano.wav vocal.wav drums.wav` で実行できます。0.75x/0.50x の ON/OFF を同じ条件で書き出し、`results/phase2/real/stems/` に一覧と処理時間を記録します。4 素材の旧形式の呼び出しにも対応しています。

Phase 3 は `--transient on` で、オフラインの過渡検出と左右共通タイミングの位相リセットを追加します。`--debug-csv directory` で `transients.csv` にスペクトル変化量、閾値、強度、検出・リセット位置を記録します。実録音の Phase 2/3 比較は `bash scripts/phase3_real_ab.sh mix.wav bass.wav guitar.wav piano.wav vocal.wav drums.wav` で生成できます。

Phase 3.5 は `--transient on --adaptive-time-map on` で有効になります。過渡候補をイベントにまとめ、イベント前後の局所伸縮率を滑らかに 1.0 へ近づけます。イベント位置を元のテンポ上に保ちながら、間の持続区間で時間を補償します。左右でイベントと時間配置を共有します。`--debug-csv directory` で `event_map.csv` にイベント ID、局所伸縮率、合成開始位置を記録します。Mix/Bass の 3 方式比較は `bash scripts/phase35_real_ab.sh mix.wav bass.wav` で再生成できます。測定結果と制約は [Phase 3.5 レポート](results/phase35/REPORT.md) に記載しています。

Phase 3.6 は `--transient on --adaptive-time-map on --selective-reset on` で有効になります。過渡イベントの開始から早い減衰までを保護し、位相リセットをスペクトル上昇の強い bin に絞ります。疎なクリックは入力サンプル位置を使ってイベント時刻を補正します。`--debug-csv directory` の `events.csv` に領域境界と時刻誤差を記録します。Mix/Bass の Phase 2／3.5／3.6 比較は `bash scripts/phase36_real_ab.sh mix.wav bass.wav` で再生成できます。**Phase 3.6 は実験的機能です。Bass のステレオ幅と人工ドラムの 0.50x アタック幅に未解決の退行があるため、既定では無効です。** 数値は [Phase 3.6 レポート](results/phase36/REPORT.md) を参照してください。

Phase 3.7 は `--transient on --adaptive-time-map on --precise-anchoring on` で有効になります。音質処理は Phase 3.5 と同じです。孤立した鋭いイベントだけ、入力サンプルの実際の位置を使って時間配置を補正します。曖昧なイベントは Phase 3.5 と同じフレーム位置のままです。`--selective-reset on` との併用はできません。`--debug-csv directory` の `anchors.csv` に補正判定を記録します。Mix/Bass の比較は `bash scripts/phase37_real_ab.sh mix.wav bass.wav` で再生成できます。検証結果は [Phase 3.7 レポート](results/phase37/REPORT.md) にあります。

Phase 4 は Phase 3.7 の引数に `--stereo-coherence on` を加えて有効になります。左右の合成位相を入力の左右位相差へ向けて補正します。左右の振幅は変えず、共同のピーク領域を使います。`--coherence-strength` と `--low-frequency-coherence` は 0〜1 の強さです。モノラルでは処理しません。既定は OFF です。`--debug-csv directory` の `stereo_coherence.csv` に周波数ごとの補正量を記録します。全長の Mix/Bass 比較は `bash scripts/phase4_real_ab.sh mix.wav bass.wav` で生成し、`bash scripts/phase4_analyze.sh` で測定できます。結果は [Phase 4 レポート](results/phase4/REPORT.md) を参照してください。

Phase 5 の歴史的な3経路構成は `--quality experimental` で再現できます。8192/2048、4096/1024、1024/256 の3つの FFT/解析ホップで処理し、中解像度で決定したイベントと出力時間配置を `TimeMap` で共有します。全長Mix/Bass比較は `bash scripts/phase5_real_ab.sh mix.wav bass.wav`、測定は `bash scripts/phase5_analyze.sh`。男女ボーカルの30秒比較は `bash scripts/phase5_vocal_ab.sh input.wav output_dir label` で行えます。結果は [Phase 5 レポート](results/phase5/REPORT.md) を参照してください。

Phase 5.1 の逐次処理は `--chunked on` で有効になります。既定の書き出し単位は 16384 サンプルで、`--chunk-size 8192..65536` で変更できます。WAV の読み込み、重ね合わせ、周波数分割、書き出しを有限長の作業領域で行います。歴史的な3経路での長さ別メモリ測定は `bash scripts/phase51_memory.sh mix.wav bass.wav metrics.txt` で再実行できます。結果は [Phase 5.1 レポート](results/phase51/REPORT.md) を参照してください。

# Phase 5.2 比較モード

逐次処理の `--ablation a|b|c` で、同じ中解像度の過渡検出と時間配置を使う3構成を比較できます。`--chunked on` と併用します。A は 4096/1024 のみ、B は低 8192/2048 と中 4096/1024 を `mid + LP250(low-mid)` で合成、C は旧 Phase 5.1 の3経路です。現在は `--ablation` を省略して `--multiresolution on` にすると B を選びます。

比較手順と計測結果は [Phase 5.2 レポート](results/phase52/REPORT.md) を参照してください。

# Phase 5.3 品質モード

`--quality normal|high|experimental` を指定できます。Normal は中4096/1024のみ、High は低8192/2048＋中4096/1024で LP250 により合成、Experimental は旧3経路です。`--multiresolution on` の既定は High に変更しました。品質モードを指定しない `--multiresolution off` は Normal、`--multiresolution on` は High です。逐次処理でも全長処理でも同じ品質モードを選べます。比較実験用に `--low-crossover-hz 200|250|300` を指定できますが、既定は250 Hzのままです。[Phase 5.3 レポート](results/phase53/REPORT.md) に回帰・音質・負荷の結果を記録しています。

# Phase 6 部分音ピーク追跡

`--phase-locking on --partial-tracking on` で中4096/1024経路の部分音ピーク追跡を試せます。左右共通のピーク地図とtrack IDを使い、各チャンネルの位相を継続します。低8192/2048経路、過渡処理、TimeMap、クロスオーバーは従来どおりです。既定は OFF です。Vocalの主観AB試聴を含む採用判断が済むまで、High Quality基準はPhase 5.3のまま維持します。[Phase 6 レポート](results/phase6/REPORT.md) に比較結果を記録しています。

# Phase 7 周期的な位相再同期の試作

`--phase-locking on --transient on --adaptive-time-map on --precise-anchoring on --stereo-coherence on --pvsola on --chunked on --quality high` で Mid 経路の PVSOLA 型再同期を試せます。既定は OFF で、Phase 6 の `--partial-tracking on` とは併用しません。既定の再同期間隔は 120 ms、入力探索範囲は ±10 ms、波形相関の下限は 0.65 です。`--pvsola-interval-ms`、`--pvsola-search-ms`、`--pvsola-min-correlation` で変更できます。`--debug-csv directory` は `pvsola_resync.csv` を保存します。試作版の ON 処理は逐次処理専用です。出力時間配置と Low 経路は Phase 5.3 のままです。実 Vocal の指標には悪化もあり、採用・既定化はしていません。[Phase 7 レポート](results/phase7/REPORT.md) に A/B と測定結果を記録しています。
