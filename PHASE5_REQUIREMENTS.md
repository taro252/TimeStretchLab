# Phase 5 — Multi-resolution Time Stretch

Phase 4まで完了した。

Phase 4を現在のベースラインとする。

Phase 5では、

**Multi-resolution STFT / Phase Vocoder**

を実装する。

目的：

単一FFTサイズでは両立しにくい、

- 低域の周波数安定性
- 高域の時間分解能
- transient clarity
- cymbal / consonantのにじみ
- bassの周期的揺れ

を改善する。

Phase 4のStereo Coherence、Phase 3.7のTransient処理とPrecise Anchoringは維持する。

---

## 1. 基本構成

最初は3解像度構成とする。

Low:

FFT = 8192
Hop = 2048

Mid:

FFT = 4096
Hop = 1024

High:

FFT = 1024
Hop = 256

sample rate 44.1 / 48 kHz両対応。

---

## 2. Frequency regions

初期値：

Low:
0〜300 Hz

Mid:
200〜4000 Hz

High:
3000 Hz〜Nyquist

overlapを必ず設ける。

Low→Mid:
200〜300 Hz

Mid→High:
3000〜4000 Hz

hard切替は禁止。

---

## 3. 最初の実装方式

各resolutionで独立したstretched time-domain outputを生成し、

その後frequency-selectiveに合成する。

つまり：

```text
Low engine
    ↓
lowOutput

Mid engine
    ↓
midOutput

High engine
    ↓
highOutput
```

これらをlinear-phase crossoverまたはfrequency-domain weightingで合成する。

単純なIIR crossoverは使用しない。

---

## 4. 重要

3つのengineは、

- 同じglobal time ratio
- 同じTransientEvent list
- 同じAdaptive Time Map
- 同じPrecise Anchor
- 同じStereo Coherence policy

を使用する。

resolutionごとに異なるtimingを作らないこと。

---

## 5. Synthesis position

全resolutionで同じlogical output timelineを使用する。

analysis hopは異なるため、それぞれのframe時刻を共通のinput sample timeへ変換し、

同じtime mapping functionからoutput位置を得る。

resolutionごとに独立した累積誤差を持たせない。

---

## 6. Time Map abstraction

Phase 3.7までの時間配置処理を、

```cpp
TimeMap
```

のような共通オブジェクトとして扱える構造にする。

概念：

```cpp
double outputPositionForInputSample(
    double inputSample
) const;
```

各resolutionはこれを使用する。

---

## 7. Low engine

Low engineの目的：

- bass fundamental stability
- kick low-end stability
- low-frequency phase wobble低減

FFT 8192を使用する。

ただし長い窓によるtransient smearを高域へ持ち込まない。

Low band以外の出力は最終合成で抑制する。

---

## 8. Mid engine

現在のPhase 4相当。

FFT 4096
Hop 1024

主に、

- vocal
- guitar
- piano
- midrange harmonic structure

を担当する。

このengineをbaselineとして扱う。

---

## 9. High engine

FFT 1024
Hop 256

目的：

- cymbal
- hi-hat
- pick attack
- consonant
- transient edge

の時間分解能改善。

Phase LockingやStereo Coherenceは有効にするが、

peak detection threshold等は必要ならresolution別に調整可能にする。

---

## 10. Crossover

frequency weightingはsmoothにする。

例：

Low weight:

0〜200Hz:
1

200〜300Hz:
cosine fade

300Hz以上:
0

Mid weight:

200Hz以下:
0

200〜300Hz:
fade in

300〜3000Hz:
1

3000〜4000Hz:
fade out

High weight:

3000Hz以下:
0

3000〜4000Hz:
fade in

4000Hz以上:
1

3つのweight合計が常に1になるよう設計する。

---

## 11. Linear phase

crossover合成で新たな位相歪みを作らない。

推奨：

frequency-domain weighting

または

linear-phase FIR

を使用する。

各bandに異なるgroup delayを作らない。

---

## 12. Stereo

各resolutionでPhase 4 Stereo Coherenceを使用する。

ただしLow engineではcoherenceをやや強めてもよい。

High engineではambienceを壊さないよう、coherence weightingを現状Phase 4以下にしてよい。

最初はPhase 4と同じ設定で開始する。

---

## 13. Transient

TransientEventは共有する。

High engineだけ独自に別transient eventを検出しない。

Phase 3.7で決定したevent timingを共通使用する。

---

## 14. Important regression

Multi-resolution OFF：

Phase 4と最大sample difference = 0。

Mono input：

正常。

Stereo:

Phase 4のIPD/ILD改善を大きく失わない。

---

## 15. Test — Low sine

以下：

55 Hz
82.41 Hz
110 Hz

speed:

0.75
0.50
0.40

Phase 4 vs Phase 5比較。

評価：

- dominant frequency
- frequency modulation
- amplitude modulation
- periodic beating

---

## 16. Test — Bass harmonic signal

110Hz基音＋高調波。

Phase 4 vs Phase 5。

特に0.50xで、

- fundamental stability
- harmonic alignment
- watery sound

を評価。

---

## 17. Test — Impulse / click

High resolutionによって、

Phase 4よりattackを悪化させないこと。

測定：

- 10→90% rise time
- peak position
- pre-echo
- post-echo

以前の「10%以上の総サンプル数」だけをattack指標にしない。

---

## 18. New transient metrics

最低限：

- rise time
- time to peak
- -3 dB decay time
- -10 dB decay time
- pre-echo energy
- first 20ms energy

を計測する。

---

## 19. Cymbal / noise burst

short noise burstを使用。

Phase 4 vs Phase 5。

評価：

- smear
- metallic ringing
- granular modulation
- attack timing

High engineの改善対象。

---

## 20. Vocal test

男性・女性ボーカル。

確認：

- consonant clarity
- watery artifact
- formant blur
- center image

Phase 4より悪化させない。

---

## 21. Bass real test

Input
Phase 4
Phase 5

について：

- pitch stability
- Side/Mid
- correlation
- IPD RMS
- ILD RMS
- low-frequency modulation

を比較。

---

## 22. Mix real test

Input
Phase 4
Phase 5

0.75
0.50

で比較。

特に：

- bass
- kick
- snare
- vocal center
- hi-hat
- cymbal
- guitar attack
- reverb width

を試聴する。

---

## 23. New metric — spectral modulation

一定sineやbass sustainについて、

frameごとのdominant frequencyとmagnitudeを追跡する。

frequency standard deviation
magnitude standard deviation

をPhase 4 / 5で比較。

---

## 24. CPU

Phase 5は重くなってよい。

まず音質優先。

ただし3engineすべてで不要なallocationを行わない。

FFT setupは再利用する。

---

## 25. Memory

8192 / 4096 / 1024の各bufferは事前allocate。

frame loopでvector生成しない。

---

## 26. Preset

Phase 5完成後、

High quality:

Multi-resolution ON

Normal:

Multi-resolution OFF

のようなquality presetを作れる構造にする。

今回はpreset UIは不要。

---

## 27. 完了条件

Phase 5は以下を目標とする。

Low:

0.50x Bassの低域揺れがPhase 4より減る。

High:

cymbal / attack smearがPhase 4より減る。

Stereo:

Phase 4のStereo Coherence改善を維持。

Timing:

Phase 3.7のprecise anchoringを維持。

Duration:

期待sample数と一致。

NaN/Infなし。

---

## 28. 報告内容

- Multi-resolution architecture
- TimeMap共有方法
- 3 FFT size / hop
- crossover方式
- band weighting
- Phase 4 regression
- sine modulation metrics
- Bass pitch metrics
- transient metrics
- cymbal test
- stereo metrics
- processing time
- memory usage
- Phase 4 / Phase 5 ABで確認すべき点
- 残るartifact

Phase 5完了後は停止する。

Pitch Shift / Real-time / Swift integrationにはまだ進まない。