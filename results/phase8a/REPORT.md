# Phase 8A — Pure WSOLA Vocal Benchmark

## 判定

独立した時間領域 WSOLA を実装し、Phase 5.3 High の既存出力と同じ区間の A/B 音源を作成した。**「声の watery/phasy 感が明確に減る」という成功条件は、聴感試験をまだ行えていないため未判定。** 数値上、WSOLA の左右関係は概ね安定する一方、孤立 Vocal の倍音バランスのフレーム間変動は Phase 5.3 より大きい。Phase 8B には進まない。

## 実装

- `WSOLAEngine` は PhaseVocoder を呼ばず、入力を mono/stereo の平面 float 配列として処理する。将来リングバッファ化できるよう、grain の選択と重ね合わせをエンジン内に分離した。今回は offline 処理で、入力・重ね合わせの加算配列・重み配列・最終出力を全長保持する。このため RSS は音源長に応じて増える。
- 基準設定: 対称 Hann 2048 samples、出力 hop 512、入力 hop `512/timeRatio` を double で累積、検索 ±512 samples。検索はまず16 sample刻み、最高候補の周囲を1 sample刻みで再探索する。候補評価は重なり部分の正規化相互相関。Stereo では `(L+R)/2` で1つの位置を選び、両チャンネルへ同じ位置を適用する。
- 入力信号に対称 Hann を掛けて重ね、出力では重なった **窓の和** で各 sample を割る。分析窓を別途掛けていないため、窓二乗ではなく窓の和を使う。出力長は `round(inputSamples*timeRatio)`。
- `wsola_stretch` CLI は `--speed`, `--window`, `--hop`, `--search`, `--debug-csv` を受け付ける。CSV 列は grainIndex、予定入力 sample、採用入力 sample、offset、最大相関、出力 sample、検索実施フラグ。
- Phase 5.3 の DSP ファイル、設定、実行経路は変更していない。Phase 6 Partial Tracking と Phase 7 PVSOLA は OFF の既存出力を参照した。

## 検証結果

- `cmake --build build -j8`: 成功。`ctest --test-dir build --output-on-failure`: **15/15 成功**。
- 440 Hz 正弦波: 0.75x は 439.999 Hz、0.50x は 440.001 Hz（C++ unit test のゼロ交差推定）。2048-sample 短時間 RMS の変動係数は両速度で約 0.003。1.0x・検索0の再構成最大誤差は `5.96e-8`。
- 全20出力で期待長との差は **0 samples**、NaN/Inf は **0**。無音 mono/stereo はゼロのまま。既知の Stereo 比率0.8も全 sample で誤差 `1e-6` 未満。
- 440 Hz ±20 cents、6 Hz の人工ビブラート: 出力の変動速度は 0.75x で WSOLA/Phase 5.3 とも **4.448 Hz**（理論4.5 Hz）、0.50x で **3.050/2.949 Hz**（理論3.0 Hz）。窓付き推定の深さは入力12.27 cents、0.75x の WSOLA/Phase 5.3 が14.77/13.91、0.50x が16.68/15.58 cents。窓の平滑化により絶対値は設定した20 centsより小さく出るため、相対比較に使う。

### Vocal 検索統計・処理費用

各値は女性または男性の3区間（各10秒）の平均。CPU列は WSOLA の処理本体時間、RSS はプロセス最大常駐メモリ。Phase 5.3 の CPU 約1.04〜1.10秒、RSS 約13.8 MiB は Phase 7 の同一区間の測定で、入出力計測範囲が異なるので速度比を厳密に読まない。

| Vocal | speed | 平均相関 | 相関10%点 | 平均絶対offset | offset95%点 | WSOLA処理秒 | WSOLA RSS MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| Female | 0.75 | 0.921 | 0.748 | 314 | 504 | 0.085 | 27.3 |
| Female | 0.50 | 0.871 | 0.630 | 316 | 506 | 0.127 | 33.5 |
| Male | 0.75 | 0.949 | 0.827 | 281 | 503 | 0.080 | 27.3 |
| Male | 0.50 | 0.913 | 0.755 | 282 | 501 | 0.118 | 33.5 |

offset の95%点が ±512 の検索限界に近い。これだけで範囲を広げる判断はできない。

### Stereo 指標

3区間平均。Side/Mid は左右差成分の RMS を中央成分の RMS で割った値。ILD は左右の音量差、IPD は左右の位相差の測定値。いずれも小さいだけで音質優位とは言えない。

| Vocal | speed | Phase 5.3 Side/Mid | WSOLA Side/Mid | Phase 5.3 L/R相関 | WSOLA L/R相関 | Phase 5.3 ILD dB | WSOLA ILD dB |
|---|---:|---:|---:|---:|---:|---:|---:|
| Female | 0.75 | 0.240 | 0.206 | 0.891 | 0.918 | 1.38 | 1.40 |
| Female | 0.50 | 0.267 | 0.199 | 0.866 | 0.924 | 2.00 | 2.27 |
| Male | 0.75 | 0.361 | 0.329 | 0.738 | 0.771 | 0.90 | 1.14 |
| Male | 0.50 | 0.380 | 0.323 | 0.719 | 0.776 | 1.67 | 1.74 |

Female IPD RMS は Phase 5.3/WSOLA で 0.75x: 30.1/12.3度、0.50x: 41.7/16.7度。Male は 13.9/7.8度、25.6/15.2度。

### Vocal の変動指標

倍音比率のフレーム間変動 RMS（dB）を3区間平均した。大きい値は不自然な揺れの可能性を示すが、水っぽい音の聴感を直接測るものではない。

| Vocal | speed | Phase 5.3 | WSOLA |
|---|---:|---:|---:|
| Female | 0.75 | 8.86 | 9.95 |
| Female | 0.50 | 8.40 | 11.17 |
| Male | 0.75 | 5.56 | 6.36 |
| Male | 0.50 | 5.00 | 7.89 |
| 人工母音 | 0.75 | 4.63 | 5.28 |
| 人工母音 | 0.50 | 4.54 | 8.01 |

### Grain 境界と対照素材

- 境界直前・直後の sample 差の99%点（3区間平均）は Female 0.75/0.50 で 0.111/0.106、Male で 0.015/0.014。周囲16 sample の差分中央値に対する99%点は Vocal で約2.98〜3.31倍。短時間 RMS 変化の95%点は Female 約3.1〜3.3 dB、Male 約4.3〜4.5 dB。声の自然な変化も含むため、これだけでクリックの有無を断定しない。人工ビブラートでは境界差分99%点 0.012、周囲比 1.10、RMS変化95%点 0.46 dB。
- 参考の Mix は15秒、Drums は20秒。0.50x の平均検索相関は Mix 0.827、Drums 0.710、相関10%点は0.473/0.245。Drums の RMS 変化95%点は7.90 dB。倍打ち・フラムは A/B 試聴で確認が必要。
- 少数のパラメータ比較（Female/Male の第2区間、0.50x）では ±256/±512/±768 と窓1536/2048/3072を比較した。±768 は相関を Female 0.852→0.871、Male 0.937→0.943 に上げたが、平均offsetも313→481/514 samplesへ増えた。窓1536 は Female/Male 相関0.882/0.952、窓3072 は0.805/0.907。設定の自動変更はしていない。

## A/B 試聴

音量を揃えず、同一入力・同一速度の WAV を切り替えて確認する。主観差はまだ判定していない。

| 区間 | 0.75x Phase 5.3 | 0.75x WSOLA | 0.50x Phase 5.3 | 0.50x WSOLA |
|---|---|---|---|---|
| Female 1 | `../phase7/female_1_075_off.wav` | `female_1_075_wsola.wav` | `../phase7/female_1_050_off.wav` | `female_1_050_wsola.wav` |
| Female 2 | `../phase7/female_2_075_off.wav` | `female_2_075_wsola.wav` | `../phase7/female_2_050_off.wav` | `female_2_050_wsola.wav` |
| Female 3 | `../phase7/female_3_075_off.wav` | `female_3_075_wsola.wav` | `../phase7/female_3_050_off.wav` | `female_3_050_wsola.wav` |
| Male 1 | `../phase7/male_1_075_off.wav` | `male_1_075_wsola.wav` | `../phase7/male_1_050_off.wav` | `male_1_050_wsola.wav` |
| Male 2 | `../phase7/male_2_075_off.wav` | `male_2_075_wsola.wav` | `../phase7/male_2_050_off.wav` | `male_2_050_wsola.wav` |
| Male 3 | `../phase7/male_3_075_off.wav` | `male_3_075_wsola.wav` | `../phase7/male_3_050_off.wav` | `male_3_050_wsola.wav` |

最優先は持続母音の厚み、watery/phasy 感、コーラス感、声の距離。次にビブラート、子音・歯擦音・息、母音間の移動、声像の位置を確認する。WSOLA で予想される問題は粒の選択が飛ぶことによる倍音比率の揺れ、子音の重複、息やドラムの粗さ。ここでの数値は聴感の代用にならない。

再現用: `scripts/phase8a_generate.py`、`scripts/phase8a_analyze.py`、`scripts/phase8a_parameters.py`。数値詳細は `manifest.csv`、`metrics.csv`、`vibrato_metrics.csv`、`vocal_modulation.csv`、`parameters/manifest.csv`。grain CSV は `diagnostics/` にある。
