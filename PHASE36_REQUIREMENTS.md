# Phase 3.6 — Attack Region Preservation + Selective Phase Reset

Phase 3.5の結果：

- Transient event consolidationは成功
- Synthetic Drumは1 attack = 1 eventになった
- Impulse / Clickは大幅に改善
- 0.50x Synthetic DrumはPhase 2よりまだattack widthが長い
- Click interval最大誤差は12.4 ms
- Bassの左右相関がPhase 3/3.5で非常に高くなった
- 全bin Phase Resetによるroughness / low-frequency discontinuityの可能性が残る

今回はMulti-resolutionへ進まず、Phase 3.5を改善する。

目的：

1. PeakだけでなくAttack Region全体を保護する
2. 全bin Phase Resetをやめ、Transient-sensitiveな選択的resetへ変更する
3. タイミング誤差を減らす
4. Stereo imageを不必要にmono方向へ寄せない

---

## 1. Attack Region

TransientEventへ以下を追加する。

```cpp
struct TransientEvent {
    size_t onsetFrame;
    size_t peakFrame;
    size_t attackEndFrame;
    size_t endFrame;

    float strength;
};
```

peakFrameだけでなく、

onsetFrame
attackEndFrame

を推定する。

---

## 2. onsetFrame

spectral fluxがbaselineから明確に立ち上がり始めたframeをonset候補とする。

peakFrameから単純に固定N frame戻すだけでなく、

flux slope

も利用する。

例：

peakFrameから後方探索し、

fluxが

threshold以下

または

peak fluxの20〜30%以下

になった位置をonset候補とする。

最大探索範囲を設定する。

例：

4 frames。

---

## 3. attackEndFrame

peak後について、

energy envelopeおよびspectral fluxが落ち着くまでをAttack Regionとする。

例：

- flux < peakFlux * 0.2
- frame energyの急激な増加が終了
- 最大4〜6 frame

などを組み合わせる。

固定値だけにせず、eventごとに可変とする。

---

## 4. Protected Attack Region

Adaptive Time Mappingでは、

event peakの一点だけではなく、

onsetFrame ～ attackEndFrame

を保護する。

このregion内のlocal time ratioを1.0付近に維持する。

ただし境界はsmooth transitionにする。

---

## 5. Local Ratio envelope

例：

globalRatio = 2.0の場合、

通常：

2.0

pre-onset transition：

2.0
1.7
1.3

attack region：

1.0～1.1

post-attack transition：

1.2
1.5
1.8
2.0

とする。

Hard switchは禁止。

---

## 6. 重要：ImpulseとDrumで異なるregion長を使う

Impulseのように極端に短い信号はattack regionも短くする。

DrumやPianoのようにattack + early decayを持つ信号では長くする。

Event strength / energy decayから自動決定する。

Impulseテストだけに最適化しないこと。

---

# 7. Phase Resetをband-selectiveに変更

現在の全有効bin resetをやめる。

Transientの強い周波数binのみ強くresetする。

各binについて、

```cpp
spectralRise[k] =
    max(
        currentMagnitude[k] - previousMagnitude[k],
        0
    );
```

を求める。

---

## 8. Reset Strength per Bin

各binについて、

```cpp
resetStrength[k]
```

を0〜1で計算する。

例えば、

```text
強いspectral onset
    → 1.0

定常成分
    → 0.0
```

とする。

frame全体のtransient strengthとbinごとのspectral riseを組み合わせる。

---

## 9. Soft Phase Reset

phaseをbinary resetしない。

通常propagation phase：

```text
propagatedPhase
```

analysis phase：

```text
analysisPhase
```

をcomplex unit vectorで補間する。

概念：

```cpp
z =
    (1 - resetStrength) * exp(j * propagatedPhase)
    +
    resetStrength * exp(j * analysisPhase);

newPhase = arg(z);
```

phase angleそのものを線形補間しないこと。

---

## 10. Low Frequency Protection

低域についてはresetを弱める。

初期案：

0～120 Hz:
最大resetStrengthを0.2程度

120～250 Hz:
smooth transition

250 Hz以上:
通常resetStrength

これは固定hard crossoverではなくsmooth weightingにする。

目的：

- bass fundamental stability
- kick low-end continuity
- pitch wobble低減

---

## 11. Peak Phase Lockingとの順序

処理順：

1. normal phase propagation
2. selective soft phase reset
3. internal synthesis phase state更新
4. Peak-based Phase Locking
5. output spectrum生成

とする。

内部phase stateと実際の出力phaseを一致させる。

---

# 12. Stereo

L/RのTransientEventとAdaptive Time Mapは共有する。

ただしresetStrengthを完全にL/R同値にしない。

各channelのspectral riseを使う。

ただし極端に異なるreset timingは禁止。

event timingは共有する。

---

## 13. Stereo preservation test

元入力、Phase 2、Phase 3.5、Phase 3.6について、

以下を計測する。

- L/R Pearson correlation
- Mid energy
- Side energy
- Side/Mid energy ratio

特にSide/Mid ratioを追加する。

Correlationだけを品質指標にしない。

---

## 14. Stereo成功条件

Phase 3.6によってBass correlationが1.0へ近付くこと自体を成功条件にしない。

元音源にSide成分が存在する場合、

Side/Mid ratioが過度に低下しないこと。

入力と処理後のStereo widthの変化を報告する。

---

# 15. Click Timing精度

現在0.50x click interval最大誤差 = 12.4 ms。

これを改善する。

Adaptive mapping後のtransient event peakについて、

ideal synthesis position

と

actual synthesis position

の誤差を計測する。

目標：

最大 3 ms以下

できれば1 ms前後。

---

## 16. Event anchoring

各TransientEventのpeakについて、

global time mapping上の理想位置をanchorとして維持する。

局所ratio補償は、

anchor間のnon-transient frames

へ分散する。

Transient peak位置を補償処理で動かさない。

---

# 17. Synthetic Drum

最重要テスト。

Phase 2
Phase 3.5
Phase 3.6

比較。

0.75x
0.50x

測定：

- onset位置
- attack width
- peak position
- peak amplitude
- pre-echo
- post-echo

0.50xでPhase 2よりattack widthが短くなることを目標とする。

---

# 18. Bass

特に評価：

- fundamental pitch stability
- attack clarity
- low-frequency discontinuity
- flutter
- Side/Mid ratio

---

# 19. Full Mix

0.75x
0.50x

Phase 2
Phase 3.5
Phase 3.6

を生成する。

同一区間
同一gain

で比較。

---

# 20. Event Count

現在Mix 約290秒で844 event。

Phase 3.6ではevent数自体を目標値へ合わせない。

ただし、

events per second

を報告する。

さらにイベント間隔histogramも出力する。

50ms未満
100ms未満
200ms未満

などの近接event数を報告する。

過剰検出の判断材料とする。

---

# 21. Regression

Phase 3.6 OFF：

Phase 3.5と完全一致すること。

Phase 3.5 OFF：

Phase 3と一致。

Transient OFF：

Phase 2と一致。

既存Phase 1～3.5 testを壊さない。

---

# 22. 報告

以下を報告する。

- attack region detection方式
- onsetFrame推定方法
- attackEndFrame推定方法
- local ratio envelope
- selective reset formula
- low-frequency protection curve
- Synthetic Drum attack width
- Click timing最大誤差
- event count
- event interval distribution
- Bass pitch stability
- L/R correlation
- Mid energy
- Side energy
- Side/Mid ratio
- Phase 2 / Phase 3.5 / Phase 3.6 AB結果
- CPU processing time
- 残るartifact

まだMulti-resolution / Advanced Stereo Coherenceへ進まない。