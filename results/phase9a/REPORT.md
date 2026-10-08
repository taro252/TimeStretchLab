# Phase 9A — Sinusoidal + Residual Vocal Prototype

## 結論

Phase 5.3 High を変更せず、独立したモノラル Vocal 用の正弦波＋残差エンジンを実装した。**Phase 9A の音質優位は確認できていない。Phase 5.3 への統合は行わない。** 1.0x の再合成は数値上ほぼ元音声に一致するが、純粋な人工母音の伸長でも倍音変動が Phase 5.3 より明確に減っていない。実 Vocal の残差には調性成分が残り、追跡が短いトラックも多い。聴感判定は A/B WAV の試聴が必要である。

## 構造と分析

- 独立クラス `SinusoidalResidualEngine`。既存 PhaseVocoder や WSOLA は内部で使用しない。入力はモノラル float。出力は厳密に `round(inputSamples*timeRatio)`。
- STFT は Apple Accelerate の FFT 4096、分析 hop 512、周期 Hann。各フレームの局所最大から対数振幅の放物線補間で bin 内位置を求め、周波数・振幅・窓中心の位相を推定する。70〜6500 Hz、フレーム最大の1.2%以上、周辺に対する鋭さ2.2倍以上、最大64ピーク。
- 前フレームの周波数傾向と振幅連続性でピークを track に割り当てる。2フレームまでの欠落を許容する。追跡した周波数・振幅を時間方向に線形補間し、誕生／消滅時に短い fade を掛ける。
- 正弦波は IFFT で戻さず、`A[n] cos(phi[n])` の時間領域発振器で直接合成する。各 track の位相は sample ごとに連続積分する。隣接分析時刻の位相差から**その区間の周波数を補正**するが、分析フレーム境界で発振器位相をリセットしない。時間軸だけを `timeRatio` 倍し、周波数値を倍率変更しない。
- 入力時刻に正弦波を再合成し、`residual = input - sinusoidal` を sample 単位で作る。追跡ピーク周辺に0〜1の滑らかな調性マスクを持つ。残差 STFT の振幅を出力時刻へ線形補間し、残差の調性漏れをマスクで抑えた後、各出力フレームに再現可能なランダム位相を与えて IFFT＋Hann二乗和正規化で重ね合わせる。これは初版の noise-like residual synthesis であり、WSOLA は使わない。
- 1.0x は分離した正弦波と残差を加算する。元入力と残差の差から正弦波を作るため、**1.0x の一致は時間伸長時の音質を保証しない**。成分単体の残差量とスペクトルも別途測定した。
- 将来の transient 成分を追加できるよう正弦波入力・残差入力・各伸長出力を独立した結果として返す。今回は全長バッファ方式の offline prototype。

## ビルド・回帰

`cmake --build build -j8` 成功。`ctest --test-dir build --output-on-failure` は **16/16 成功**。新規 unit test は1.0x再構成、0.75/0.50の厳密長、440 Hz 発振器のピッチ維持、ビブラート track の継続、NaN/Inf を検査した。16組の A/B 出力で期待長との差は **0 samples**、NaN/Inf なし。

### 1.0x 再構成

全8素材の最大絶対誤差は `5.96e-8` 以下、RMS誤差は `1.80e-9` 以下、FFT振幅の相対誤差は `5.96e-9` 以下。これは float 丸め程度で、1.0x 加算出力に可聴な着色を生む大きさではない。詳細は `unity_metrics.csv`。

| 入力 | 平均 active tracks | 中央 track 寿命 | births/s = deaths/s | 正弦波エネルギー / 入力 | 残差 RMS / 入力 |
|---|---:|---:|---:|---:|---:|
| Pure vowel | 19.0 | 6.016 s | 3.2 | 0.991 | 0.113 |
| Breathy vowel | 32.8 | 0.064 s | 190.7 | 0.913 | 0.300 |
| Female 1/2/3 平均 | 19.9 | 約0.050 s | 152.9 | 0.811 | 0.385 |
| Male 1/2/3 平均 | 20.8 | 約0.050 s | 172.5 | 0.855 | 0.339 |

「正弦波エネルギー / 入力」は合成正弦波のエネルギー比であり、直交射影による厳密な説明率ではない。残差 RMS と併せて解釈する。

### 残差の性質

`diagnostics/{pure_vowel,breathy_vowel,female_1,male_1}_100/` に正弦波・残差の WAV、track CSV、平均スペクトル CSV を保存した。flatness はスペクトルが平らなほど1に近い。top10 は上位10周波数 bin のパワー比で、大きいほど調性が強い。

| 入力 | 残差 RMS比 | 入力 flatness | 残差 flatness | 入力 top10 | 残差 top10 |
|---|---:|---:|---:|---:|---:|
| Pure vowel | 0.113 | ≈0 | `3.1e-7` | 0.771 | 0.644 |
| Breathy vowel | 0.300 | 0.024 | 0.456 | 0.750 | 0.210 |
| Female 1 | 0.328 | 0.00044 | 0.0030 | 0.884 | 0.753 |
| Male 1 | 0.315 | 0.096 | 0.144 | 0.545 | 0.436 |

Breathy vowel の残差はノイズらしいが、Pure vowel と Female 1 の残差には明確な調性漏れがある。伸長時は追跡ピーク周辺のマスクで抑えるが、残差のランダム位相化によるざらつきが残る可能性がある。

### 人工母音 A/B

元信号は F0 165 Hz、±16 cents・5.5 Hz のビブラート、時間変化するフォルマント、19倍音。Breathy 版は振幅0.015の再現可能な雑音を追加。数値は 0.75/0.50 の順に記載。

| 入力・指標 | Phase 5.3 | Phase 9A |
|---|---:|---:|
| Pure F0 中央値 | 165.076 / 165.041 Hz | 165.061 / 165.046 Hz |
| Pure 倍音変動 RMS | 0.914 / 0.750 dB | 1.002 / 0.763 dB |
| Pure スペクトル包絡変動 | 0.01796 / 0.01519 | 0.01876 / 0.01655 |
| Breathy 倍音変動 RMS | 1.168 / 1.200 dB | 1.315 / 1.259 dB |

基本周波数は保つが、倍音変動では Phase 9A の明確な改善がない。純母音でもランダム位相化した残差の微量ノイズと track の補間差が残り、仕様の「純母音で大幅改善」という期待を数値では満たしていない。これらの指標は watery 感を直接測れない。

### 実 Vocal A/B と性能

Phase 7/8A の女性・男性各3区間を同じモノラル入力へ変換し、同じ入力ゲインで Phase 5.3 High と Phase 9A を処理した。以下は各3区間平均。処理時間は Phase 5.3 の CLI CPU値と Phase 9A の処理本体時間で計測範囲が異なるため、厳密な速度比ではない。

| Vocal | speed | Phase 5.3 倍音変動 | Phase 9A 倍音変動 | Phase 9A処理秒 | Phase 9A RSS MiB | Phase 5.3 RSS MiB |
|---|---:|---:|---:|---:|---:|---:|
| Female | 0.75 | 8.55 | 10.36 dB | 0.49 | 52.8 | 11.4 |
| Female | 0.50 | 8.32 | 10.70 dB | 0.63 | 61.3 | 11.5 |
| Male | 0.75 | 5.49 | 6.86 dB | 0.49 | 52.8 | 11.5 |
| Male | 0.50 | 5.13 | 7.52 dB | 0.63 | 61.3 | 11.4 |

Phase 9A の出力 RMS は入力比で Female 約0.91、Male 約0.94。Phase 5.3 は Female 約0.98、Male 約0.97〜0.98。出力に追加の音量正規化を行っていないため、試聴時には約0.3〜0.6 dBの音量差に注意する。数値だけで「近い声」「watery が少ない」とは判定しない。

## 試聴・判断

`manifest.csv` に全16組の WAV パスを列挙した。特に持続母音、声の距離、watery/phasy 感、息・歯擦音の粗さ、track 出入りに伴う robotic な揺れを比較する。代表例:

| 入力 | speed | Phase 5.3 | Phase 9A |
|---|---:|---|---|
| Pure vowel | 0.50 | `pure_vowel_050_phase53.wav` | `pure_vowel_050_phase9a.wav` |
| Breathy vowel | 0.50 | `breathy_vowel_050_phase53.wav` | `breathy_vowel_050_phase9a.wav` |
| Female 2 | 0.50 | `female_2_050_phase53.wav` | `female_2_050_phase9a.wav` |
| Male 2 | 0.50 | `male_2_050_phase53.wav` | `male_2_050_phase9a.wav` |

**聴感上の優劣は未評価。** 現在の追跡寿命の短さと残差の調性漏れから、robotic な音、倍音の揺れ、ノイズ化した息や歯擦音が候補となる。明確な改善が試聴で確認されるまで Phase 5.3 は基準のまま維持する。Phase 9A で停止し、Hybrid・Mix・Bass・Drums・Swift・リアルタイム再生には進まない。

再現には `scripts/phase9a_generate.py --stage unity`、1.0x 検証後 `--stage stretch`、`scripts/phase9a_analyze.py` を使う。数値詳細は `unity_metrics.csv`、`residual_metrics.csv`、`synthetic_metrics.csv`、`vocal_modulation.csv`、`output_metrics.csv`。
