# Phase 9C — Tonal Residual Recovery

## 判定

残差を連続値の調性重みで二分し、調性側を分析位相継続、雑音側だけを固定シードのランダム位相で伸長する独立プロトタイプを作成した。Phase 9A と Phase 5.3 のコード・出力は変更していない。**測定上は純母音のランダム位相化対象を大きく減らせたが、Phase 9C の音質採否は未判定**。Phase 5.3より水っぽさが少なく、かつPhase 9Aよりノイズ感が少ないかは、末尾のLUFS一致A/B/Cを実際に試聴する必要がある。Hybrid、Swift、リアルタイム処理は実装していない。

## 分離と合成

`TonalResidualEngine` は既存の Phase 9A の primary sinusoidal 分解と track list を使い、元残差を4096点Hann窓・512 sample hopで再解析する。残差の各周波数成分に対し、局所ピークの鋭さ、局所スペクトル平坦度、入力の倍音列から推定したF0への近さ、隣接フレーム間の振幅安定性から0〜1の調性重みを作る。非常に平坦度の低いフレームは、F0推定に依存せず調性側へ寄せる。重みは常に0と1の間で、二値マスクは使用しない。

元残差の複素スペクトルに `weight` と `1-weight` を掛け、逆FFTと窓二乗正規化で元時刻の調性・雑音残差も書き出す。伸長時は調性成分の分析位相差を追跡し、雑音成分にのみ Phase 9A と同じ固定シードの xorshift32 位相を使う。両成分に共通ゲインを掛け、成分の相対バランスと A+B+C の一致を保持する。primary tracker は変更していない。現在は Phase 9A の診断結果も一度生成するため、計算量は最適化していない。

## 人工母音

RMSは元入力のRMSに対する比。エネルギー比はこの値の二乗であり、成分間の相関があるため単純な総和にはならない。倍音エネルギー比は8192点FFT、80〜8000 Hz、既知F0整数倍±12 Hzで測定した。下表は両速度の平均。

| 信号・成分 | RMS / 入力 | 倍音エネルギー比 | スペクトル平坦度 |
|---|---:|---:|---:|
| Pure primary sinusoidal（伸長後） | 0.995 | — | — |
| Pure tonal residual（元時刻） | 0.1097 | 0.9769 | 極小 |
| Pure noise residual（元時刻） | **0.0161** | 0.6140 | 極小 |
| Pure tonal residual（伸長後） | 0.1123 | 0.9901 | 極小 |
| Pure noise residual（伸長後） | **0.0062** | 0.2745 | 約0.00002 |
| Breathy tonal residual（元時刻） | 0.0917 | 0.8849 | 0.0194 |
| Breathy noise residual（元時刻） | 0.2690 | 0.1316 | 0.5150 |
| Breathy tonal residual（伸長後） | 0.1560 | 0.9056 | 0.0103 |
| Breathy noise residual（伸長後） | 0.1901 | 0.1370 | 0.4297 |

Pure primary のRMS比は0.04987/0.05010 ≈ 0.995。Pure noise の元時刻エネルギーは入力の約**0.026%**で、伸長後は約**0.0038%**。Phase 9Bで元残差の97.7%が倍音近傍だったのに対し、Phase 9Cではその大半を tonal residual 側に割り当てた。ただし Pure noise の相対的な倍音比率は61.4%あり、絶対量が小さいことと「単独試聴でpitchが聞こえない」ことは別である。`components/pure_vowel_050/noise_output.wav`で確認する。Breathy では、noise inputの倍音比率13.2%、平坦度0.515となり、息成分を概ね雑音側へ残した。

全16組のprimary/tonal/noiseそれぞれのRMSと入力に対するエネルギー比は`component_energy.csv`に保存した。

## 実 Vocal の残差指標

Female/Male各3区間、両速度の平均。倍音エネルギー比のF0は入力からの倍音列推定なので、無声区間や誤推定で揺れる。`harmonic_variation_std` は各フレームの倍音帯エネルギー比の標準偏差で、独立した聴感評価ではない。

| 入力・成分 | RMS/入力 | 倍音比 | 平坦度 | harmonic variation |
|---|---:|---:|---:|---:|
| Female tonal input | 0.2407 | 0.6722 | 0.0009 | 0.2239 |
| Female noise input | 0.2212 | 0.1541 | 0.0275 | 0.1421 |
| Female tonal output | 0.3473 | 0.6735 | 0.0005 | 0.2703 |
| Female noise output | 0.1506 | 0.1758 | 0.0221 | 0.1370 |
| Male tonal input | 0.1638 | 0.5638 | 0.0150 | 0.2540 |
| Male noise input | 0.2304 | 0.1172 | 0.0581 | 0.0999 |
| Male tonal output | 0.2642 | 0.5590 | 0.0086 | 0.2838 |
| Male noise output | 0.1661 | 0.1254 | 0.0495 | 0.1093 |

全区間・全成分のRMS、倍音比、平坦度、top-10 bin power ratio、harmonic variationは`residual_metrics.csv`。primary trackの生死・寿命分布は`component_manifest.csv`、`track_lifetimes.csv`と`components/*/tracks.csv`。trackerは不変で、60 ms未満のtrack割合（Female約55.2%、Male約54.9%）も不変である。Phase 9Cはtrack由来のflutterを解消したとは言えない。

## 3方式の音量一致

各同一区間・同一速度について Phase 5.3 / 9A / 9C の integrated LUFS をFFmpeg `loudnorm`で測定し、最も小さい側へ**試聴コピーだけ**を定数ゲインで合わせた。必要なときは3本すべてに同じ追加減衰を掛け、最終サンプルピークを0.85以下にした。元DSP WAVは無変更。全16組の3方式内最大LUFS差は**0.06 LU**で、目標0.1 LU以内。各ファイルの元RMS・peak・LUFS、適用ゲイン、一致後の値は`loudness.csv`、試聴パスは`matched_triples.csv`。

| 入力 | speed | Phase 5.3 元LUFS | Phase 9A 元LUFS | Phase 9C 元LUFS |
|---|---:|---:|---:|---:|
| Female 3区間平均 | 0.75 | -12.77 | -13.40 | -12.66 |
| Female 3区間平均 | 0.50 | -12.48 | -13.08 | -12.52 |
| Male 3区間平均 | 0.75 | -24.35 | -24.85 | -24.46 |
| Male 3区間平均 | 0.50 | -24.31 | -24.70 | -24.29 |

代表0.50x A/B/C：`matched_lufs/female_2_050_phase53.wav`、`female_2_050_phase9a.wav`、`female_2_050_phase9c.wav`。男性は同じ名前規則で`male_2_050_*`。各実Vocal区間の`components/<区間>_<速度>/`には A `primary.wav`、B `tonal_output.wav`、C `noise_output.wav`、D `primary_and_tonal.wav`、E `combined.wav`を保存した。元時刻の`tonal_input.wav`と`noise_input.wav`もある。

## 試聴で判定する点

1. LUFS一致3方式で、Phase 9CがPhase 9Aよりgraininess/雑音感を減らし、Phase 5.3よりwaterinessが少ないか。
2. `noise_output.wav`に純母音の明確なpitchが残るか。Breathy の`noise_output.wav`が自然な息として聞こえるか。
3. `tonal_output.wav`にbuzz、metallic ringing、位相の不自然な揺れが増えていないか。
4. `primary_and_tonal.wav`と`combined.wav`を比べ、雑音成分を足したときの声の距離や粗さが変わるか。
5. primary trackerの短命trackによるrobotic/flutterがそのまま残るか。

これらの聴感結果が未取得なので、成功条件の「Phase 9Aより明確にノイズが減り、Phase 5.3より水っぽさが少ない」は**未確認**。成立しなければ Sinusoidal + Residual 路線を停止する判断が必要。

## 検証

`cmake --build build -j8`成功。`ctest --test-dir build --output-on-failure`で全17件成功。Phase 9C単体テストは長さ、NaN/Inf、無音、成分和、固定シード再現性、Phase 9Aの反復一致を確認。Phase 9Aの実ファイルとのバイト比較も実施。生成: `scripts/phase9c_generate.py`。
