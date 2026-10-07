# Phase 3 — Transient Detection + Phase Reset

Phase 2まで完了し、75%再生ではPhase Lockingによる改善が確認できた。

一方で以下がまだ残っている。

- アタックのブレ
- アタックの時間方向のにじみ
- 音像のにじみ
- スネア、キック、ピッキング等の輪郭の弱さ

Phase 3ではこれらを改善するため、

**Transient Detection + transient-synchronized Phase Reset**

を実装する。

今回はまだ以下は実装しない。

- Multi-resolution
- Adaptive Local Time Mapping
- transient区間だけstretch ratio=1にする処理
- transient / tonal separation
- advanced stereo coherence
- pitch shift
- real-time streaming
- Swift integration

---

# 1. 基本方針

Phase 2までの処理：

    STFT
      ↓
    instantaneous frequency
      ↓
    phase propagation
      ↓
    Peak-based Phase Locking
      ↓
    IFFT

Phase 3：

    STFT
      ↓
    Transient Detector
      ↓
    transient?
       ├─ NO
       │   ↓
       │ normal phase propagation
       │ + Peak Locking
       │
       └─ YES
           ↓
         Phase Reset
           ↓
         Peak Locking
           ↓
         IFFT

とする。

---

# 2. 新しいクラス

以下を追加する。

    TransientDetector.h
    TransientDetector.cpp

責務：

- magnitude history保持
- spectral flux計算
- adaptive threshold計算
- transient strength計算
- transient state / cooldown管理

PhaseVocoderへ直接大量のtransient detectorコードを書かない。

---

# 3. 最初のDetector

Phase 3初期版では、

**positive spectral flux**

を使用する。

各binについて、

    current[k]
    previous[k]

から、

    diff =
        current[k]
        -
        previous[k]

正の増加分だけを使用する。

    flux =
        Σ max(diff, 0)

ただしlinear magnitudeそのものより、

    logMagnitude =
        log(1 + gain * magnitude)

を使えるようにする。

初期値：

    gain = 10

または実際のスケールに応じて調整する。

---

# 4. Magnitude normalization

入力levelに依存しすぎないようにする。

frame energyまたはmagnitude sumで正規化する。

候補：

    fluxNormalized =
        flux /
        (sum(currentMagnitude) + epsilon)

あるいは、

log magnitudeを使う場合は履歴baselineによる相対評価を優先してよい。

重要なのは、

小さい音のスネア

と

大きい音のスネア

の両方をある程度検出できること。

---

# 5. Adaptive Threshold

固定thresholdだけで判定しない。

直近のflux履歴を保存する。

初期値：

    historyFrames = 12

baseline：

    median(history)

を使用する。

必要なら、

    MAD
    median absolute deviation

も利用してよい。

初期判定候補：

    threshold =
        median
        +
        sensitivity * MAD

例：

    sensitivity = 3.0

MADがほぼ0の場合用に最低thresholdを持たせる。

---

# 6. spectral fluxの単純倍率方式も比較可能にする

実装を複雑にしすぎないため、

以下2方式を切り替えられる構造にしてもよい。

Mode A:

    flux >
        median * multiplier

Mode B:

    flux >
        median
        + sensitivity * MAD

最初の既定値はMAD方式を推奨。

---

# 7. Transient Strength

transientをbinaryだけで扱わず、

    transientStrength

を0〜1で計算する。

例えば、

    strength =
        clamp(
            (flux - threshold)
            /
            (threshold * range),
            0,
            1
        )

rangeは調整可能。

ただしPhase 3初版では、

    transientStrength >= X

でbinary phase resetしてよい。

後のsoft reset用にstrengthを保持する。

---

# 8. Cooldown / Minimum Distance

同じattackを複数frameでtransient判定しない。

48kHz、

    analysis hop = 1024

の場合1frameは約21.3ms。

minimum transient distance：

    30〜50ms

程度を初期値とする。

frame換算で、

    2 frames

程度。

つまり一度transientを検出したら、

    cooldownFrames = 2

程度は新規triggerを抑制する。

ただしflux history自体は更新する。

---

# 9. Look-ahead

オフライン処理なので、1〜2frame程度のlook-aheadを使用してよい。

重要。

transient detectorがattack発生後のframeで反応すると、

attack前半がすでにPhase Vocoderでsmearされてしまう。

そのため、

    candidate frame
    ↓
    local maximum確認
    ↓
    transient位置を1 frame前へ補正

などを検討する。

初版では、

    detectedFrame - 1

をphase reset位置候補として試せるようにする。

ただし負のframeは禁止。

DAFxの研究でも、onset位置の遅れがtransient smearingにつながることが指摘されている。

---

# 10. オフラインPre-analysis

今回のPhaseではリアルタイム制約がないため、

**可能ならtransient detectionを事前解析として行う。**

推奨構成：

    Pass 1:
        全frameのspectral flux計算

    Pass 2:
        adaptive threshold
        local maximum
        transient frame決定

    Pass 3:
        time stretch

これにより、

- look-ahead
- local maximum判定
- onset位置補正

をきれいに実装できる。

将来リアルタイム版では別方式に変更する。

---

# 11. Transient Frame判定

単純に、

    flux > threshold

だけではなく、

可能なら局所最大条件を追加する。

例：

    flux[t] > threshold[t]
    &&
    flux[t] >= flux[t-1]
    &&
    flux[t] > flux[t+1]

これによりattackのピーク位置にresetを集中させる。

---

# 12. Phase Reset基本方式

transient frameでは、

通常の、

    synthesisPhase +=
        trueFrequency * synthesisHop

をそのまま使用しない。

最初の実装では、

    synthesisPhase[k]
        =
    analysisPhase[k]

とする。

ただし対象は、

- DC除外
- Nyquist除外
- magnitude threshold以上

とする。

---

# 13. Reset後の状態

非常に重要。

phase resetしたframeでは、

    synthesisPhase_[k]
        =
    analysisPhase[k]

だけでなく、

    previousPhase_[k]
        =
    analysisPhase[k]

    initialized_[k]
        =
    true

として内部状態も整合させる。

「実際に出したphase」と「内部phase state」を必ず一致させる。

---

# 14. Peak Lockingとの順番

Transient frameでは、

1. analysis phase取得
2. phase reset
3. transient anchor phase決定
4. Peak-based Phase Locking
5. output生成

の順番とする。

つまり、

    reset
      ↓
    phase locking

とする。

Phase Lockingによってtransient内の局所的なphase coherenceを保つ。

---

# 15. 非Transient frame

従来のPhase 2処理を完全に維持する。

つまり、

    instantaneous frequency
    phase propagation
    phase locking

を使用する。

Phase 3 OFF時にはPhase 2と同一出力になること。

---

# 16. Config

StretchConfigへ追加。

例：

```cpp
bool enableTransientHandling = false;

float transientSensitivity = 3.0f;

int transientHistoryFrames = 12;

int transientCooldownFrames = 2;

int transientLookbackFrames = 1;
```

名称は適切なら変更してよい。

---

# 17. 重要：全bin resetの問題を評価する

初版では全有効bin resetで構わない。

ただし必ずAB評価する。

全bin resetにより、

- bass discontinuity
- low-frequency thump
- stereo instability
- click
- pitch wobble

が出る可能性がある。

問題が出た場合は、

**すぐ複雑な処理を追加せず報告する。**

後でband-selective reset / peak-selective resetを検討する。

---

# 18. Stereo transient detection

Stereo入力ではtransient positionを左右別々に検出しない。

共通detectorを使う。

analysis magnitude：

    combined[k]
        =
    sqrt(
        magL[k]^2
        +
        magR[k]^2
    )

または同等のenergy-based combined magnitude。

これからtransient位置を1つ決める。

左右チャンネルは同じframeでphase resetする。

これはstereo image安定のため重要。

---

# 19. Phase reset自体はchannel別

Transient positionは共有する。

ただしanalysis phaseは、

    phaseL[k]
    phaseR[k]

それぞれ異なるので、

reset phaseは各channel自身のanalysis phaseを使用する。

つまり、

    same transient timing

だが、

    independent channel analysis phase

を用いる。

---

# 20. Artificial Test — Impulse

単一impulse。

Phase 2とPhase 3を比較。

speed：

    0.75
    0.50

評価：

- attack width
- pre-echo
- post-echo
- peak amplitude
- transient position

Phase 3でattackが明瞭になること。

---

# 21. Click Train

120 BPM click train。

speed 0.5。

期待：

    interval × 2

ただし各click自体が単純に2倍の時間幅に引き延ばされないこと。

Phase 2 vs Phase 3でwaveform比較する。

---

# 22. Synthetic Drum Transient

以下のような信号を作る。

    short noise burst
    +
    decaying 100Hz sine

kick / snareに近いtransientを模擬する。

Phase 2 / Phase 3比較。

---

# 23. Tonal-only Test

440Hz sine。

Phase 3 ONでも、transient false positiveにより不要なphase resetが頻発してはいけない。

steady sineでは、

    transient count ≈ 0

を目標にする。

---

# 24. Slow amplitude modulation

ゆっくり音量変化するsineを使う。

単なるcrescendoをtransientとして大量検出しないこと。

---

# 25. Guitar/Piano attack test

可能なら実音源で、

単音ギターpluck
ピアノ単音

を使う。

確認：

- attack clarity
- sustain stability
- pitch stability

Phase Resetでattackは改善するが、sustainがPhase 2より悪化してはいけない。

---

# 26. Full Mix AB

最重要。

同じ曲について、

    Phase 2
    Phase 3

を生成。

speed：

    0.75
    0.50

比較項目：

- kick attack
- snare attack
- bass attack
- pick attack
- vocal consonants
- cymbal smear
- stereo center
- overall sharpness

---

# 27. Debug CSV

最低限：

    frameIndex
    spectralFlux
    threshold
    transientStrength
    transientDetected
    resetApplied

を出力できるようにする。

Stereoの場合：

    shared transient decision

であることがわかるようにする。

---

# 28. Waveform debug

Impulse / Clickについて、

入力と出力のattack周辺をCSV等へ出力できるようにしてよい。

例えば、

    -50ms
    ～
    +150ms

を比較する。

---

# 29. Regression

Phase 3 OFF時、

Phase 2との出力差が実質ゼロであること。

Phase 1 / Phase 2のunit testもすべて通すこと。

---

# 30. Expected Result

Phase 3で主に改善したいのは、

- attack smear
- drum blur
- pick blur
- consonant blur

である。

今回、

- bassの低周波安定性
- extreme slow speed
- cymbalの完全な自然さ

まで完全解決する必要はない。

それらは後続Multi-resolution等で扱う。

---

# 31. 重要：過剰resetを避ける

Phase resetが多すぎると、

- roughness
- flutter
- pitch instability
- stereo instability

が増える。

「transientを見逃さない」より、

**明確なattackだけをresetする**

方向から開始する。

false positiveを少なくする。

---

# 32. 完了報告

以下を報告する。

1. TransientDetector設計
2. flux計算式
3. threshold方式
4. history size
5. cooldown
6. look-ahead / lookback処理
7. stereo transient共有方式
8. phase reset方式
9. transient count
10. impulse test
11. click test
12. tonal test
13. Phase 2 vs Phase 3 0.75x
14. Phase 2 vs Phase 3 0.50x
15. CPU performance
16. false positive / false negativeとして気付いたケース
17. 現在残っているartifact

今回もここで止める。

Multi-resolutionやAdaptive Time Mappingにはまだ進まない。
