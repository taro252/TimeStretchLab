# Phase 3.5 — Transient Event Consolidation + Adaptive Time Mapping

Phase 3の検証結果から、単純なTransient Detection + Phase Resetだけではattack preservationが不十分であることが分かった。

重要な結果：

- 単独Impulse / Click TrainではPhase 2と波形が同一
- Synthetic Drumでは1回のattackに3回transient detectionされた
- attack widthがPhase 2よりわずかに広がった
- 実音源ではstereo correlationの改善が見られた
- Phase 3 OFF時はPhase 2と完全一致している

したがってPhase 3のコードを捨てず、次は

1. transient detectionを「frame detection」から「onset event detection」へ改善
2. transient周辺でlocal stretch ratioを1.0へ近づけるAdaptive Time Mapping

を実装する。

まだ以下には進まないこと。

- Multi-resolution
- Advanced Stereo Coherence
- Pitch Shift
- Real-time Streaming
- Swift integration

---

## 1. 最重要目標

50%再生でもattack自体を単純に2倍へ引き延ばさない。

例えば、

通常：

50 ms attack
→
100 ms

ではなく、

目標：

50 ms attack
→
50〜60 ms程度

とする。

その分、attack後のsustain区間をより強くstretchして、曲全体として指定time ratioを維持する。

---

## 2. TransientをframeではなくEventとして扱う

現在はspectral fluxがthresholdを超えたframeをtransientとしている。

これを、

TransientEvent

としてグループ化する。

例：

```cpp
struct TransientEvent {
    std::size_t onsetFrame;
    std::size_t peakFrame;
    std::size_t endFrame;

    float strength;
};
```

---

## 3. Event Formation

thresholdを超えた連続または近接frameを同じeventへまとめる。

単純な固定2-frame cooldownだけに依存しない。

event開始：

fluxがthresholdを上回る

event継続：

fluxが高い、または短いgapの後に再上昇する

event終了：

fluxがbaseline付近まで十分戻る

---

## 4. Minimum Event Distance

1つのdrum hitが複数eventにならないようにする。

初期値として、

minimum event distance = 60〜100 ms

程度を試す。

例えば48kHz / hop 1024の場合、

1 frame ≈ 21.3 ms

なので、

3〜5 frames

程度。

ただし単純に無視するだけではなく、近接eventは強い方へmergeする。

---

## 5. Peak Picking

各event内では、

spectral flux最大frame

を1つだけpeakFrameとして採用する。

Phase Resetは基本的にこのpeakFrameに対してのみ行う。

同じattackに何度もphase resetしない。

---

## 6. Pre-onset位置

Attackがsmearする前にtime mappingを変更する必要がある。

peakFrameだけでなく、

peakFrameの1〜2frame前

からTransient Regionとして扱う。

初期値：

preRollFrames = 1

postRollFrames = 2

程度から開始する。

---

# 7. Adaptive Time Mapping

現在：

```cpp
start =
    round(
        frameIndex * synthesisHop
    );
```

で全frameを一定time ratioで配置している。

これを変更する。

各analysis frameに対して、

```cpp
localRatio[frame]
```

を計算する。

通常：

```text
localRatio = globalTimeRatio
```

Transient region：

```text
localRatio ≈ 1.0
```

とする。

---

## 8. Hard switchingは禁止

例えば、

```text
2.0
2.0
2.0
1.0
1.0
1.0
2.0
2.0
```

と急に変更するとtiming discontinuityを起こす。

必ずsmooth envelopeを使う。

例：

```text
2.0
1.8
1.4
1.1
1.0
1.1
1.4
1.8
2.0
```

のようにする。

Raised cosine等のsmooth curveを使用してよい。

---

# 9. Global Duration Conservation

最重要。

local stretchを変更しても最終出力長は、

```text
inputLength * globalTimeRatio
```

を維持する。

Transient regionで節約したstretch量を、non-transient regionへ再配分する。

例えばglobal ratio = 2.0で、

Transient regionを1.1

とした場合、

残りのsustain区間では、

2.0より少し大きなratio

を使用して補償する。

---

## 10. Ratio Distribution

全frameについてまず、

```cpp
weight[frame]
```

を作ってよい。

Transient：

```text
weight ≈ 0
```

Sustain：

```text
weight ≈ 1
```

として、

最終的なlocalRatioを、

全frameのsynthesis hop総和が目標出力時間と一致するよう正規化する。

---

# 11. 制約

localRatioに安全範囲を設ける。

例えばglobal ratio 2.0なら、

Transient：

```text
1.0〜1.2
```

Sustain compensation：

必要に応じて2.0より上

ただし極端な値は避ける。

初期上限：

```text
globalRatio * 1.5
```

程度。

---

# 12. synthesis position

従来の、

```cpp
frameIndex * synthesisHop
```

は使えなくなる。

double accumulatorを使用する。

例：

```cpp
double synthesisPosition = 0.0;

for each frame {
    start =
        llround(synthesisPosition);

    synthesisPosition +=
        analysisHop * localRatio[frame];
}
```

ただし最終duration誤差が蓄積しない設計にする。

---

# 13. Phase propagation

PhaseVocoderへ渡すsynthesis hopも、

実際のframe start位置差、

```cpp
start - previousStart
```

を使用する。

現在の設計思想を維持する。

---

# 14. Phase Reset

Eventにつき原則1回だけresetする。

reset frame：

TransientEventのpeakFrameまたはonset位置補正後のframe。

Phase Reset後、

synthesisPhase
previousPhase
initialized

を整合させる。

Peak Phase Lockingはその後に適用する。

---

# 15. Stereo

Transient event listとlocal time mapは左右で完全に共有する。

L/Rで異なるsynthesis frame placementは禁止。

各channelのanalysis phaseだけは個別。

---

# 16. Test 1 — Single Impulse

Phase 2
Phase 3
Phase 3.5

を比較。

speed:

0.75
0.50

測定：

- attack width
- peak position
- peak amplitude
- pre-echo
- post-echo

Phase 3.5では50%時でもattack widthがPhase 2より明確に狭くなることを目標とする。

---

# 17. Test 2 — Click Train

120 BPM。

speed 0.50。

クリック間隔は2倍になる。

ただしclick自身のwidthは可能な限り元入力に近く保つ。

重要：

「click interval」はstretchするが
「click attack width」はstretchしすぎない。

---

# 18. Test 3 — Synthetic Drum

Phase 3で1attackあたり3transient検出されたテストを再利用する。

Phase 3.5では、

1 physical attack
≈
1 TransientEvent

になること。

Event countを報告する。

---

# 19. Test 4 — Sustained Sine

steady sineにTransientEventを発生させない。

Adaptive Time Mapによってpitch modulationが増えないこと。

---

# 20. Test 5 — Bass

特に確認：

- onset click
- low-frequency discontinuity
- pitch wobble

Transient preservationのためにbass sustainを壊さないこと。

---

# 21. Full Mix

0.75
0.50

について、

Phase 2
Phase 3
Phase 3.5

の3種類を生成する。

同一gainで比較。

---

# 22. 必ず保存するDebug情報

CSV：

```text
frameIndex
flux
threshold
eventId
eventStrength
isTransientRegion
localTimeRatio
synthesisStart
```

---

# 23. 可視化用データ

Synthetic Drumについて、

```text
input waveform
Phase 2
Phase 3
Phase 3.5
```

のattack周辺±150ms程度をCSV出力する。

---

# 24. 成功条件

Phase 3.5は以下を目標とする。

Synthetic Drum:

- 1 attack ≈ 1 event
- 0.50xでもattack widthがPhase 3より短い
- 余計なclickなし

Real Mix:

- attackがPhase 2より明瞭
- Phase 3よりroughnessが増えない
- pitch wobbleが増えない
- stereo imageが不安定にならない

Duration:

最終sample数はglobal targetと一致。

---

# 25. 重要

Adaptive Time Mappingは「音源全体のテンポを変える」のではない。

短時間スケールでstretch量を再配分するだけ。

全曲の平均time ratioは指定値を厳密に維持する。

---

# 26. ここで停止

Phase 3.5完成後、

- test results
- attack-width comparison
- event counts
- Phase 2/3/3.5 AB audio

を確認する。

Stereo CoherenceやMulti-resolutionにはまだ進まない。