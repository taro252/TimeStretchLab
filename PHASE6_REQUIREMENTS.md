# Phase 6 — Spectral Peak Tracking / Partial Phase Continuity

現在のHigh Quality baselineはPhase 5.3 High：

Low:
8192 / 2048

Mid:
4096 / 1024

高1024経路なし。

Phase Locking、Transient Event、Adaptive TimeMap、Precise Anchoring、Stereo Coherence、Streaming処理は維持する。

Phase 6の目的は、

**ボーカル等の持続的な調波信号に残る watery / phasy artifact を減らすこと**

である。

今回はまだ、

- WSOLA
- PSOLA
- PVSOLA
- Pitch Shift
- Swift integration
- Real-time playback

は実装しない。

---

## 1. 現在の問題

現在のPeak Phase Lockingは各frameごとにspectral peakを独立検出し、そのframe内で周辺binをpeakへロックしている。

しかし、

frame t の peak k

と

frame t+1 の peak k+1

が同じ物理的なpartialであっても、継続的なidentityを持っていない。

これにより、

- peak owner switching
- phase anchor switching
- subtle modulation
- chorus-like artifact
- watery vocal texture

が発生する可能性がある。

---

## 2. PartialTracker

新しく、

PartialTracker.h
PartialTracker.cpp

を作成する。

各spectral peakへ一意のtrack IDを割り当てる。

例：

```cpp
struct TrackedPeak {
    int trackId;
    int bin;
    float interpolatedBin;
    float magnitude;
    float frequencyHz;
    double analysisPhase;
    double synthesisPhase;
    int age;
    int missedFrames;
};
```

---

## 3. Frame-to-frame matching

前frameのpeakと現在frameのpeakをmatchingする。

基本cost：

```text
frequency distance
+
magnitude change penalty
```

最初はgreedy matchingでもよい。

ただし1つのpeakを複数trackへ割り当てない。

---

## 4. Maximum frequency movement

同じpartialとして扱う最大変化量を設定する。

固定binだけではsample rate / FFT size依存になるため、

Hzまたはcentsを使用する。

初期候補：

±80 cents

または

±1.5 FFT bins

程度。

両方のうち厳しい方を使用してもよい。

---

## 5. Magnitude continuity

frequencyだけでなくmagnitude変化もmatching costへ入れる。

急激に振幅が変わった場合は別partialの可能性を高くする。

log magnitude differenceを使用する。

---

## 6. Birth / Death

新peak：

既存trackに一致しなければ新trackを作る。

消失peak：

すぐ削除せず、

missedFrames <= 2

程度まで保持する。

短時間のpeak dropoutでtrack IDが毎回変わらないようにする。

---

## 7. Track phase state

重要。

各track自身に、

```cpp
trackedSynthesisPhase
```

を持たせる。

peak bin indexが、

37 → 38 → 38 → 39

と移動しても、

同じtrackなら同じphase accumulatorを継続する。

---

## 8. Instantaneous frequency

tracked peakについて、現在のinstantaneous frequency推定を使用する。

ただしphase accumulatorはbinではなくtrackに紐付ける。

概念：

```cpp
track.phase +=
    estimatedAngularFrequency
    * synthesisHop;
```

peak binが移動したからphase stateを新規開始しない。

---

## 9. Peak migration

peakがbinを跨いだ場合も、

previous analysis phaseについて適切に処理する。

単純に旧bin phaseと新bin phaseを直接比較して誤ったresidualを作らない。

interpolated peak frequency / tracked frequencyを利用して連続性を保つ。

必要ならpeakのsub-bin周波数をphase propagationの中心として使用する。

---

## 10. Region ownership

各frameのownerPeak mapは現在の方式を利用してよい。

ただしowner peakがTrackedPeakを持つ場合、

周辺binはそのtracked synthesis phaseをanchorとしてphase lockする。

---

## 11. Track-aware identity phase locking

従来：

```text
synthPhase[ownerBin]
+
analysis relative phase
```

Phase 6：

```text
trackedPeak.synthesisPhase
+
analysis relative phase
```

とする。

これによりowner peakが隣接binへ移動してもanchor phaseを維持する。

---

## 12. Track reassignment smoothing

track IDが切り替わったbin regionについて、

phaseを突然切り替えない。

必要なら1〜2frameでcomplex phase interpolationする。

ただし最初から複雑にしすぎない。

まずtrack continuityだけを実装し、artifactが出る場合に追加する。

---

## 13. Transient interaction

Transient eventではPhase 3.5のreset policyを維持する。

ただし明確なtransient後は、

partial tracksを再初期化してよい。

古いtrack phaseを新しいattackへ持ち越さない。

---

## 14. Vocal-focused tracking

Mid 4096 pathでPhase 6を重点適用する。

Low 8192 pathでは初版では現行Phase Lockingを維持してもよい。

まずVocal問題を分離する。

---

## 15. Optional frequency range

初版ではPartial Trackingを例えば、

150 Hz ～ 6 kHz

程度に限定してもよい。

理由：

- vocal fundamentals/harmonicsを主対象
- very low frequencyはLow path
- noisy high frequenciesを無理にtrackしない

境界はsmoothにする必要はない。
これはphase tracking適用範囲でありaudio crossoverではない。

---

## 16. Noise rejection

tonalityの低いpeakをpartial trackしない。

Phase 4で使用しているtonality推定等を再利用してよい。

noise / breath / sibilanceを無理にsinusoidal partialとして追跡しない。

---

## 17. Test — moving sine

400 → 500 Hz

slow glide。

track IDが基本的に1つのまま継続すること。

peak binが変わってもphase continuityを維持する。

---

## 18. Test — vibrato sine

440 Hz

±20 cents vibrato

5〜7 Hz程度。

Phase 5.3 vs Phase 6。

出力で、

- frequency modulation depth
- unwanted amplitude modulation
- phase discontinuity

を比較。

本来のvibratoを消してはいけない。

---

## 19. Test — harmonic stack

F0 = 120 Hz

2F0 ... 12F0

各partialに軽いvibratoを加える。

track IDの継続率を測定する。

---

## 20. Synthetic vocal

F0 + harmonic spectrum + slowly moving formant envelope

を生成。

Phase 5.3 / Phase 6

0.75
0.50

比較。

評価：

- amplitude modulation
- spectral centroid modulation
- harmonic phase stability
- track continuity

---

## 21. Real vocal

Female Vocal
Male Vocal

0.75
0.50

Phase 5.3 High
Phase 6

を同一gainで生成。

重点試聴：

- watery sound
- chorus effect
-母音の輪郭
- sustained vowel
- vibrato
-子音
- center image

---

## 22. Metrics

新規：

track continuity ratio

```text
total matched peak frames
/
total trackable peak frames
```

average track lifetime

track switches per second

peak phase discontinuity

を測定。

---

## 23. Modulation metric

持続母音区間について、

各harmonic magnitudeのframe間変動

と

spectral envelopeのframe間変動

をPhase 5.3 / Phase 6で比較する。

waterinessの代理指標として使用する。

---

## 24. Stereo

Stereo Coherenceは維持する。

L/Rごとに完全別のtrack matchingを行ってstereo imageを壊さない。

可能ならcombined peak map上でtrack IDを共有し、

各channelのphaseはPhase 4 policyで再構築する。

---

## 25. Regression

Phase 6 OFF：

Phase 5.3 Highと最大sample difference = 0。

Bass、Mix、Vocalの既存metricsを悪化させない。

---

## 26. Performance

毎frameで動的allocationしない。

track poolを事前確保する。

最大track数をbin count以内に制限。

---

## 27. Success criteria

Phase 6採用条件：

- sustained Vocalでwatery / chorus artifactが聴感で減る
- vibratoを不自然に平坦化しない
- consonantを悪化させない
- center imageを悪化させない
- Bass / Mix regressionなし
- CPU増加が合理的範囲

数値だけで採用しない。

主観AB試聴を必須とする。

---

## 28. Report

以下を報告：

- matching algorithm
- frequency tolerance
- magnitude cost
- track lifetime
- average track count
- continuity ratio
- track switches/sec
- synthetic vocal modulation metrics
- female/male Vocal metrics
- stereo metrics
- CPU
- Phase 5.3 vs Phase 6のAB試聴確認ポイント
- 残るartifact

Phase 6完了後は停止。

まだWSOLA/PVSOLAには進まない。