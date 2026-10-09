# Phase 9B — Loudness-Matched Diagnostic & Residual Analysis

## 判定

Phase 9A の既定出力は**全16組で Phase 9A 保存済み WAV とバイト単位で一致**した。Phase 5.3 と Phase 9A の元出力は変更していない。音量差は実 Vocal で約0.4〜0.6 LU あり、試聴への影響はあり得る。ただし元の Phase 9A は小さい側であり、残差の調性漏れと短命トラックは音量調整では解消しない。**ノイジーさの最有力候補は、ランダム位相の残差再合成と頻繁なトラック出入り。どちらが聴感上の主因かは、以下の音量一致済み成分 A/B の試聴待ち。** Phase 5.3 への統合・Hybrid 実装は行っていない。

## 音量一致 A/B

FFmpeg `loudnorm` の測定値 `input_i` を integrated LUFS として使用した。各同一区間・同一速度ペアについて、RMS 一致版と integrated LUFS 一致版を**別々に**作成した。両者の小さい方へ定数ゲインで合わせ、必要なペアでは再生時のピーク歪みを避けるため、**両側を同じ量**だけ追加で下げた。最終サンプルピークは全て0.85以下。元の DSP WAV はそのまま。

- 16組の LUFS 一致版で最大差 **0.05 LU**（目標0.1 LU以内）。
- RMS 一致版で最大差 **`4.69e-7 dB`**。RMS一致だけでは、一部 Male Vocal の integrated LUFS 差が平均約0.13〜0.17 LU残るため、聴感比較には LUFS 一致版を優先する。
- `loudness.csv` は各元ファイルの RMS・ピーク・LUFS、適用ゲイン、安全のための共通ゲイン、一致後の測定値を記録する。`matched_pairs.csv` が全 A/B パスとペア差を記録する。

| 入力 | speed | Phase 5.3 元LUFS | Phase 9A 元LUFS | Phase 5.3 適用ゲイン | Phase 9A 適用ゲイン |
|---|---:|---:|---:|---:|---:|
| Female 3区間平均 | 0.75 | -12.77 | -13.40 | -1.73 dB | -1.10 dB |
| Female 3区間平均 | 0.50 | -12.48 | -13.08 | -2.07 dB | -1.48 dB |
| Male 3区間平均 | 0.75 | -24.35 | -24.85 | -0.50 dB | 0.00 dB |
| Male 3区間平均 | 0.50 | -24.31 | -24.70 | -0.40 dB | -0.02 dB |

表の適用ゲインにはピーク余裕確保のための共通減衰も含む。Female の元サンプルピークは Phase 5.3 側で平均1.01〜1.04に達していた。

代表 A/B（0.50x、LUFS 一致版）：

| 区間 | Phase 5.3 | Phase 9A |
|---|---|---|
| Female 2 | `matched/lufs/female_2_050_phase53.wav` | `matched/lufs/female_2_050_phase9a.wav` |
| Male 2 | `matched/lufs/male_2_050_phase53.wav` | `matched/lufs/male_2_050_phase9a.wav` |
| Pure vowel | `matched/lufs/pure_vowel_050_phase53.wav` | `matched/lufs/pure_vowel_050_phase9a.wav` |
| Breathy vowel | `matched/lufs/breathy_vowel_050_phase53.wav` | `matched/lufs/breathy_vowel_050_phase9a.wav` |

## A/B/C/D/E 成分

`components/<区間>_<速度>/` に次を保存した。全16組に存在する。

- A `sinusoidal_output.wav`: 伸長した正弦波成分だけ。
- B `residual_output.wav`: 既定のランダム位相で伸長した残差だけ。
- C `combined.wav`: A+B。Phase 9A の保存済み元出力とバイト一致。
- D `sinusoidal_input.wav`: 元入力時刻の正弦波分析再合成。
- E `residual_input.wav`: 元入力から D を引いた残差。
- `tracks.csv`: track ID、分析中心時刻、周波数、振幅、分析位相。大量の診断データなので Git 管理対象外、ローカルに保存。

実 Vocal で B の RMS は A の約**17〜18%**。音色を変え得る量であり、B に母音 pitch・buzz・金属的な音が聞こえるかを先に確認する。A では flutter、robotic な音、声の距離、track 出入り時の不連続を確認する。A と B が個別に自然で C だけ悪い場合はバランスやマスキングを疑う。

## 残差の調性漏れ

`residual_tonality.csv` では、8192点 Hann FFT の80〜8000 Hzの残差パワーに対し、F0 の整数倍±12 Hzに入るパワーを合計した。人工母音は既知 F0、実 Vocal は入力音の倍音列から F0 を推定した。実 Vocal の比率は F0 推定誤差と無声区間の影響を受ける。flatness は1に近いほどノイズ状、top10 は上位10 binへのパワー集中率。

| 入力（平均） | 元残差 RMS / 入力 | 元残差の倍音エネルギー比 | ランダム位相・伸長残差の比 | 元残差 flatness | ランダム位相・伸長残差 flatness |
|---|---:|---:|---:|---:|---:|
| Pure vowel | 0.113 | **0.977** | 0.479〜0.502 | `2.6e-7` | 約`1.2e-5` |
| Breathy vowel | 0.300 | 0.435 | 0.177〜0.182 | 0.445 | 0.392〜0.418 |
| Female 3区間平均 | 0.385 | 0.432 | 0.135〜0.138 | 0.017 | 0.030〜0.033 |
| Male 3区間平均 | 0.339 | 0.276 | 0.105〜0.106 | 0.054 | 0.063〜0.067 |

**Pure vowel は雑音を加えていないのに、元残差の約97.7%のエネルギーが倍音近傍にある。** 残差 RMS 自体は入力の11.3%で、伸長後ランダム位相残差は入力の約1.1% RMSまで下がるが、分離は完全ではない。Breathy vowel の元残差は flatness 0.445で、息成分に近い。一方 Female Vocal の元残差は flatness 0.017、上位10 binのパワー比は平均0.485で、単なる息だけではない。細部は `residual_tonality.csv` と A/B/C/D/E WAV で確認できる。

## Track 寿命と出入り

同じ入力の0.50x track CSVから数えた。寿命は最初〜最後の検出中心時刻に1 hopを足した値。

| 3区間合計 | <30 ms | 30〜60 ms | 60〜120 ms | 120〜250 ms | >250 ms | births/s = deaths/s（区間平均） |
|---|---:|---:|---:|---:|---:|---:|
| Female 4586 tracks | 31.3% | 23.9% | 21.1% | 14.4% | 9.2% | 152.9 |
| Male 5174 tracks | 31.3% | 23.6% | 23.9% | 13.4% | 7.9% | 172.5 |

**60 ms未満が Female 約55.2%、Male 約54.9%**。`track_lifetimes.csv` に区間別の実数を保存した。最も出入りが密集する時刻の前後50 msを各区間・birth/death別に切り出し、`birth_death/` に A/B/C の短い WAV を保存した。`birth_death_clips.csv` は時刻と近傍イベント数、`birth_death_metrics.csv` は局所 RMS と波形差分を記録する。選択した12箇所では、正弦波成分の RMS ジャンプ絶対値の中央値は birth 0.72 dB、death 1.72 dB。これは声の自然な変化も含み、flutter の聴感判定にはならない。

## ランダム位相 vs 分析位相継続

`--residual-phase analysis` を**診断専用**として追加した。残差スペクトルの分析フレーム間位相差から bin ごとの周波数を推定し、出力フレームへ位相を累積する。正弦波 track と元残差はランダム位相版と同一。既定は従来の `random` で、保存済み Phase 9A 出力と16/16でバイト一致。同一入力のランダム版を2回処理した unit test も完全一致した。

Pure/Breathy vowel と Female 1/Male 1 の両速度に、`phase_variants/` の分析位相版を作った。比較の音量差を除くため、`phase_compare/` に**残差単独の RMS 一致版**と**合成音の LUFS 一致版**も作った。残差 RMS 差は最大 `2.7e-7 dB`、合成音 LUFS 差は最大0.01 LU。パスと適用ゲインは `phase_compare.csv`。

0.50x Pure vowel では伸長残差の倍音比率がランダム位相 **0.479**、分析位相 **0.937**。Female 1 ではランダム位相版の残差が分析位相版よりスペクトルが平らになる傾向がある。分析位相へ替えると調性が残りやすいため、「ざらつきが減るが buzz が増える」可能性もある。**Bでノイズ感が減るかどうかは試聴して初めて判定できる。**

## 原因切り分けの現状

1. **音量差だけが主因とは考えにくい。** Phase 9A は元々小さい側であり、成分検査でも純母音の調性漏れと実 Vocal の短い track が存在する。ただし音量一致後に聴感がどれだけ変わるかは未判定。
2. **第一候補はランダム位相で再合成する残差の質。** 実 Vocal では元残差がノイズだけではなく、その成分をフレームごとにランダム位相化している。残差単独の random/analysis を RMS 一致で聴き比べる。
3. **第二候補は track 出入り。** 約55%が60 ms未満で、Aの短い切り出しで flutter/robotic な変化を確認する。
4. A と B が単独で自然なのに C で悪化する場合のみ、成分バランスやマスキングを疑う。

**主観試聴は未実施なので、上記は測定結果からの暫定順位である。** 結果にかかわらず、この Phase では Phase 5.3 へ統合しない。

試聴時の判定順序は、(1) `matched/lufs/` で音量差の影響、(2) `phase_compare/residual_rms/` で位相方式の影響、(3) `birth_death/` の A と C で track 出入り、(4) `components/` の A/B/C で成分の相互作用とする。音量一致だけで差が消えれば Case A、残差だけ粗ければ Case B、正弦波だけ揺れれば Case C、単独成分は自然で合成時だけ悪ければ Case D に対応する。

再現: `scripts/phase9b_loudness.py`、`scripts/phase9b_components.py`、`scripts/phase9b_residual_metrics.py`、`scripts/phase9b_phase_compare.py`、`scripts/phase9b_birth_death_metrics.py`。`cmake --build build -j8` 成功、`ctest --test-dir build --output-on-failure` は16/16成功。
