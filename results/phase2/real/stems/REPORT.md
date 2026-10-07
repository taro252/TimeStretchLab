# 6 素材の Phase 1 / Phase 2 AB 比較

入力は `/Users/taro252/Downloads/` の `mix.wav`、`bass.wav`、`guitar.wav`、`piano.wav`、`vocal.wav`、`drums.wav` です。各入力に 0.75x・0.50x、位相固定 OFF（Phase 1）・ON（Phase 2）を適用し、合計 24 個の float32 WAV を生成しました。`manifest.csv` は対応表、`processing_metrics.txt` は処理時間、`metrics.txt` は全入力・出力を読み直した数値です。入力に対する自動ゲイン調整やピーク正規化は行っていません。

## 結果

全 24 出力で長さは期待サンプル数と一致し、NaN/Inf はありませんでした。入力と出力の左右実効振幅比はおおむね近い一方、**左右の波形相関は位相固定 ON で大きく低下**しました。以下は 1 秒単位の左右相関の中央値です。

| 素材 | 入力 | 0.75x OFF | 0.75x ON | 0.50x OFF | 0.50x ON |
| --- | ---: | ---: | ---: | ---: | ---: |
| Mix | 0.913 | 0.001 | -0.019 | 0.800 | -0.007 |
| Bass | 0.998 | 0.037 | 0.068 | 0.884 | 0.033 |
| Guitar | 0.901 | -0.025 | 0.065 | 0.754 | -0.096 |
| Piano | 0.778 | 0.016 | -0.032 | 0.476 | -0.005 |
| Vocal | 0.917 | -0.002 | -0.005 | 0.212 | 0.000 |
| Drums | 0.975 | 0.000 | 0.050 | 0.449 | 0.016 |

ON は OFF より全体実効振幅が入力に近い傾向です。例として Bass の 0.75x は入力 0.1221、OFF 0.0865、ON 0.1211 です。しかし中央の定位を保つという観点では、これらの数値から Phase 2 ON を改善とは判断できません。0.75x OFF にも強い左右相関低下があり、Phase 1 にも課題があります。チャンネルごとの独立位相処理が関係する可能性がありますが、原因の確定や修正はこの比較作業には含めていません。

float32 WAV は 1.0 を超える値も保持しますが、そのようなサンプルは再生環境によってクリップする可能性があります。ピーク超過数と各素材の詳しい数値は `metrics.txt` を参照してください。処理時間はこの Mac で OFF が平均約 7.16 秒、ON が平均約 8.91 秒／ファイルでした（入力長は素材ごとに異なります）。

## 試聴用セット

`audition/` に各原曲 60～90 秒と対応する 0.75x の 40 秒、0.50x の 60 秒を収めました。全 30 ファイルへ**同じ固定ゲイン 0.4**を適用し、各ファイル別のピーク正規化はしていません。最大ピークは 0.765、1.0 超えと NaN/Inf はありません。`audition/metrics.txt` に各ファイルの値があります。

| 素材 | 原曲 | 0.75x OFF / ON | 0.50x OFF / ON |
| --- | --- | --- | --- |
| Mix | [原曲](audition/mix_original.wav) | [OFF](audition/mix_075_off.wav) / [ON](audition/mix_075_on.wav) | [OFF](audition/mix_050_off.wav) / [ON](audition/mix_050_on.wav) |
| Bass | [原曲](audition/bass_original.wav) | [OFF](audition/bass_075_off.wav) / [ON](audition/bass_075_on.wav) | [OFF](audition/bass_050_off.wav) / [ON](audition/bass_050_on.wav) |
| Guitar | [原曲](audition/guitar_original.wav) | [OFF](audition/guitar_075_off.wav) / [ON](audition/guitar_075_on.wav) | [OFF](audition/guitar_050_off.wav) / [ON](audition/guitar_050_on.wav) |
| Piano | [原曲](audition/piano_original.wav) | [OFF](audition/piano_075_off.wav) / [ON](audition/piano_075_on.wav) | [OFF](audition/piano_050_off.wav) / [ON](audition/piano_050_on.wav) |
| Vocal | [原曲](audition/vocal_original.wav) | [OFF](audition/vocal_075_off.wav) / [ON](audition/vocal_075_on.wav) | [OFF](audition/vocal_050_off.wav) / [ON](audition/vocal_050_on.wav) |
| Drums | [原曲](audition/drums_original.wav) | [OFF](audition/drums_075_off.wav) / [ON](audition/drums_075_on.wav) | [OFF](audition/drums_050_off.wav) / [ON](audition/drums_050_on.wav) |

試聴で確認する点は Bass の芯と揺れ、Vocal の水っぽさと中央定位、Guitar/Piano の和音と余韻、Mix の音像、Drums のアタックです。聴感上の結論は、実際に各ペアを再生して判断する必要があります。現時点の数値では ON のステレオ定位が品質上の大きな問題です。Transient Detection や Multi-resolution は実装していません。
