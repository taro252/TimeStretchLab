# Phase 9D — Track Stability Diagnostic

## 結論

Phase 9Cのprimary trackerと音質処理は変更していない。Female/Male各3区間の0.50x出力から、track出入りが多い箇所と安定した有声箇所を選び、**54組の600 ms比較WAV**を作成した。客観測定では、track出入りが多いほどPhase 9C単独の倍音振幅変動は大きい傾向がある。しかし**同じ箇所のPhase 5.3との差分**では、その関連は弱く、Phase 9C固有の可聴artifactの因果関係は確認できていない。したがってmissed-frame allowance、周波数許容幅、birth minimum ageはいずれも変更していない。Phase 9Cは現時点の有力なVocal処理候補として維持する。

ユーザーのPhase 9C試聴評価は「Phase 5.3よりwatery感が明確に少なく、Phase 9Aのnoise感はPhase 5.3との差が分からない程度まで改善」。本診断はその評価を維持し、残るflutter/robotic/timbre instabilityがtrack出入りに集中するかを調べる。**今回の局所クリップはまだ人間の試聴判定を受けていない。**

## 箇所の選択

48 kHz・0.50xの出力時間軸を50 ms窓に区切った。各窓に、trackの最初の検出をbirth、最後の検出をdeathとして数えた。寿命60 ms未満のtrackはbirth窓のshort-track countへ加えた。寿命は最初から最後の検出中心までに分析hop 512 sampleを足したもの。`window_metrics.csv`には全窓のbirth/death/short count、active tracks、音量、スペクトル指標を記録する。

高密度箇所は、十分な音量とprimary成分を持つ有声窓から、birth+death+shortの合計が大きい順に選択。対照は同じ有声条件で合計が少ない順に選んだ。比較箇所の中心間隔は最低650 ms。Female 3区間とMale 2/3は**高密度5＋対照5**。Male 1は有声部分が出力の約4秒に集中するため、独立した**高密度2＋対照2**。合計27＋27箇所。各中心の前後300 msを切り出した。

| 選択群 | 50 msあたりのbirth+death+short中央値 |
|---|---:|
| 高密度 27箇所 | 22 |
| 対照 27箇所 | 0 |

個々のbirth、death、short countと時刻、元ファイルへのリンクは`selected_regions.csv`。対照は音量を揃えた同一フレーズではないため、自然な発声内容の差が残る。Phase 5.3との差分指標を併用して、この交絡を減らしている。

## 客観指標と相関

各50 ms中心の前後50 ms（計100 ms）で、Phase 9CおよびPhase 5.3の波形を2048点FFTで複数回解析した。倍音振幅変動は、元入力の推定F0の整数倍近傍の振幅をフレームごとに追い、そのdB標準偏差の中央値。スペクトル包絡変動は、周波数方向に平滑化した対数スペクトルから全体ゲインを引き、隣接フレームの形状差を測った。`harmonic_variation_delta_db`と`envelope_variation_delta`はそれぞれ **Phase 9C − Phase 5.3**。全窓と有声窓に分け、track churnとのPearson/Spearman相関を`correlations.csv`に保存した。

下表は有声窓でのSpearman順位相関。相関は因果関係を示さない。Male 1は有声窓が76個で、他区間より推定が不安定。

| 区間 | 有声窓数 | churn × Phase 9C倍音変動 | churn × 倍音変動差 | churn × Phase 9C包絡変動 | churn × 包絡変動差 |
|---|---:|---:|---:|---:|---:|
| Female 1 | 254 | +0.40 | -0.04 | +0.15 | -0.07 |
| Female 2 | 239 | +0.24 | +0.01 | +0.19 | -0.14 |
| Female 3 | 394 | +0.51 | +0.04 | +0.22 | -0.07 |
| Male 1 | 76 | +0.14 | -0.08 | +0.08 | +0.08 |
| Male 2 | 325 | +0.37 | -0.09 | +0.32 | -0.23 |
| Male 3 | 388 | +0.11 | -0.01 | +0.09 | +0.02 |

倍音振幅変動の絶対値は高密度箇所で上がることが多い。一方、Phase 9CとPhase 5.3の差分相関は倍音で**-0.09〜+0.04**、包絡で**-0.23〜+0.08**。発声変化そのものがtrack出入りと同時に起きている可能性が高く、これだけではPhase 9C固有のflutterやrobotic音を特定できない。なお、この指標は可聴artifactを直接測るものではない。

## 聴感比較ファイル

`clips/<区間>/<highまたはcontrol>_<順位>/` に以下を保存した。

- `phase53.wav`: Phase 5.3（LUFS一致）
- `combined.wav`: Phase 9C（LUFS一致）
- `primary.wav`: Phase 9C primary only
- `primary_tonal.wav`: Phase 9C primary + tonal residual

Phase 9Cの成分ファイルには`combined.wav`と同じゲインを適用し、成分間バランスを保った。すべて600 ms、同じ出力位置、同じWAV形式。54組のPhase 5.3/9Cペアは**最大LUFS差0.07 LU**、サンプルピーク最大0.85、NaN/Infなし。ゲインと実測LUFSは`selected_regions.csv`。

`blind/<区間>/<highまたはcontrol>_<順位>/A.wav`と`B.wav`は方式名を隠した同一音声。割り当ては固定シードでランダム化し、対応表を**別ファイル**`blind_key.csv`に保存した。対応表は試聴結果を記録した後に開く。`blind_listening_sheet.csv`には各箇所3回分の記入欄を設けた。同じ箇所を数回聴き、好みだけでなくflutter、robotic modulation、buzz、roughness、急な音色変化、母音の安定性を記録する。

0.50xの男女各3区間の**全長版**Phase 5.3/9CはPhase 9Cの`matched_lufs/`にあり、ペア差は最大0.03 LU。局所クリップで違和感が見つかった場合は全長版の文脈でも確認する。

## 採否

短命trackが約55%あること自体は、変更の理由にしない。高密度箇所だけでPhase 9Cに繰り返し聞こえるartifactがあり、対照では目立たず、Phase 5.3との差でも確認できた場合に限って、missed-frame allowance等を**1項目ずつ**試す。現時点ではその聴感証拠がないため、A=currentのみを保持しB/C/D実験は未実施。誤ったpartial接続によるpitch glideやharmonic swappingの危険を避けた。

もし盲検試聴でPhase 9C固有の実用上気になるartifactがなければ、Vocal prototypeはPhase 9Cで固定し、この系統をこれ以上複雑にしない。Phase 5.3への統合設計は今回行っていない。

## 再現と検証

`scripts/phase9d_diagnostic.py`で生成。`--correlations-only`は既存の窓指標から相関を、`--sheet-only`は試聴記録シートを再生成する。54組の長さ・有限性・peak・LUFS差、盲検ファイルと対応表のバイト一致を検査済み。Phase 9C/Phase 5.3のDSPコード、CMake、既存テストは変更していない。
