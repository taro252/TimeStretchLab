# Phase 4 — Stereo Phase Coherence

Phase 3.7まで完了した。

Phase 3.7を現在のベースラインとする。

Phase 3.6 selective resetはexperimental / default OFFのまま維持する。

Phase 4では、

**Stereo Phase Coherence**

を実装する。

目的：

Time Stretch中にL/Rを独立Phase Vocoderとして処理することで発生する、

- stereo image widening
- center image blur
- low-frequency L/R phase drift
- phantom center instability

を改善する。

まだ以下には進まない。

- Multi-resolution
- Pitch Shift
- Real-time streaming
- Swift integration

---

# 1. 最重要原則

L/Rを完全に同一phaseへ揃えてmono化してはいけない。

目的は、

L phase = R phase

ではない。

元入力に存在する、

inter-channel phase difference

を可能な限り維持すること。

---

# 2. Mid / Side analysis

Stereo入力について各analysis frameで、

```cpp
Mid  = 0.5 * (L + R);
Side = 0.5 * (L - R);
```

を解析可能にする。

ただし最初からM/S信号そのものをstretchしてL/Rへ戻す方式には固定しない。

まず診断情報として利用する。

---

# 3. Inter-channel Phase Difference

各FFT binについて、

```cpp
phaseL[k]
phaseR[k]
```

から、

```cpp
ipd[k] =
    wrap(
        phaseR[k] - phaseL[k]
    );
```

を計算する。

IPD = Inter-channel Phase Difference。

この値が元のstereo positionを構成する重要な情報になる。

---

# 4. Reference / Anchor Channel

各binについてreference phaseを決める。

単純に常にLをreferenceにしない。

候補：

```cpp
if (magL >= magR)
    reference = L;
else
    reference = R;
```

またはcombined peak mapを利用する。

重要なのは弱いchannelのnoise phaseをanchorにしないこと。

---

# 5. Coherent Synthesis

reference channelについては通常のPhase 3.7処理：

- instantaneous frequency
- phase propagation
- transient handling
- peak phase locking

を行う。

もう片方のchannelは、

```text
reference synthesis phase
+
input inter-channel phase difference
```

を基準に再構築する。

概念：

```cpp
thetaOther =
    wrap(
        thetaReference
        + ipd
    );
```

ただし全binへ100%適用するとstereo effectを壊す可能性があるため、coherence strengthを導入する。

---

# 6. Coherence Strength

各binについて、

```cpp
coherenceWeight[k]
```

を0〜1で計算する。

例：

- L/R両方で強いtonal component → 高weight
- 片側だけ強い成分 → 低weight
- noise / ambience / reverb → 低weight

候補：

```cpp
balance =
    2 * min(magL, magR)
    /
    (magL + magR + epsilon);
```

balanceは、

両channel同程度:
    ≈1

片側dominant:
    ≈0

となる。

これをcoherenceWeightの基礎にする。

---

# 7. Low-frequency coherence

低域ではstereo phase driftの影響が特に大きいため、coherenceを強める。

初期案：

0〜150 Hz:
    coherence強め

150〜500 Hz:
    smooth transition

500 Hz以上:
    signal-derived weight中心

ただし完全mono化は禁止。

入力IPDを保持するので、

元々stereo low-endの場合はその差を残す。

---

# 8. Phase blending

独立Phase Vocoderで得たphase：

```cpp
independentPhase
```

coherent target：

```cpp
coherentPhase
```

をcomplex unit vectorで補間する。

```cpp
z =
    (1 - weight) * exp(j * independentPhase)
    +
    weight * exp(j * coherentPhase);

finalPhase = arg(z);
```

angleの直接線形補間は禁止。

---

# 9. Input IPD smoothing

binごとのIPDがnoiseによって激しく動かないよう、

必要ならfrequency方向に軽いsmoothingを入れる。

ただし、

- binaural cues
- stereo ambience
- deliberate phase effects

を壊さないよう弱くする。

初版では3〜5 bin程度のweighted smoothingまで。

---

# 10. Peak-based shared regions

Phase 2のPeak Phase LockingをStereo向けに拡張する。

可能ならL/R別peak mapではなく、

combined magnitude：

```cpp
combined =
    sqrt(
        magL * magL
        +
        magR * magR
    );
```

からshared peak mapを生成する。

左右で同じpeak region境界を使用する。

これにより左右の異なるpeak assignmentによるimage blurを減らす。

---

# 11. Transient handling

Phase 3.7のshared transient event timingを維持する。

Transient時にもStereo Coherence処理を適用する。

ただしPhase 3.5の全bin resetを変更しない。

Phase 4ではtransientアルゴリズム自体を再設計しない。

---

# 12. Phase 3.7 Precise Anchoring

そのまま維持する。

Stereo Phase Coherenceによってevent位置を変更しない。

---

# 13. Config

追加例：

```cpp
bool enableStereoCoherence = false;

float stereoCoherenceStrength = 1.0f;
```

可能ならdebug用に、

```cpp
float lowFrequencyCoherenceStrength;
```

も設定可能にする。

---

# 14. Mono input

Mono入力ではPhase 4処理を完全bypassする。

Phase 3.7と同一出力であること。

---

# 15. Stereo identity test

入力：

L = sine
R = same sine

完全mono stereo。

処理後も、

L ≈ R

を維持する。

Side energy ≈ 0。

---

# 16. Known phase difference test

例：

L:
440 Hz, phase 0

R:
440 Hz, phase +45 degrees

処理：

0.75
0.50

出力IPDが入力45度に近いこと。

Phase 3.7とPhase 4を比較する。

---

# 17. Amplitude-panned test

L amplitude = 1.0
R amplitude = 0.5

phaseは同一。

処理後、

L/R amplitude ratio

を維持する。

Phase Coherenceによってpan positionを中央へ寄せないこと。

---

# 18. Stereo decorrelated noise

左右独立white noise。

この素材を無理にcoherentにしてはいけない。

Side energyを大きく失わないこと。

coherenceWeightが低くなることを確認する。

---

# 19. Stereo reverb test

同じdry signal + L/R異なるreverb成分。

center dry signalは安定させる。

Side ambienceは過度にmono化しない。

---

# 20. Bass real test

最重要の一つ。

Input
Phase 3.7
Phase 4

について、

0.75
0.50

で：

- L/R correlation
- Mid RMS
- Side RMS
- Side/Mid ratio
- low-frequency IPD error

を比較。

入力Bass:

Side/Mid ≈ 0.105

Phase 3.7:

0.75 ≈ 0.129
0.50 ≈ 0.151

Phase 4では入力値へさらに近付くことを目標とする。

Phase 3.6のようなSide/Mid ≈1は絶対に許容しない。

---

# 21. Mix real test

Input
Phase 3.7
Phase 4

について比較。

特に、

- vocal center
- kick center
- snare center
- bass center
- stereo ambience

を確認。

Side/Mid ratioが入力から過度に増加しないこと。

---

# 22. New metric — IPD error

入力と出力について、対応するtonal binのIPD差を測定する。

```cpp
error =
    wrap(
        outputIPD - inputIPD
    );
```

magnitude-weighted RMS errorを計算。

全bin同等ではなく、強いbinへ重みを付ける。

---

# 23. New metric — ILD

Inter-channel Level Differenceも測定する。

```cpp
ILD =
    20 * log10(
        (magL + eps)
        /
        (magR + eps)
    );
```

Input vs OutputのILD errorを測る。

目的：

Phase Coherenceによってpan positionを壊していないことを確認する。

---

# 24. Stereo success criteria

Phase 4は以下を目標とする。

Bass:

- Side/Midが入力へ近付く
- L/R correlationが入力へ近付く
- pitch stabilityを悪化させない

Mix:

- Side/Midの過剰増大を抑える
- center imageを改善
- ambienceを完全mono化しない

Artificial:

- known IPD維持
- ILD維持
- decorrelated noiseをmono化しない

---

# 25. Regression

Stereo Coherence OFF：

Phase 3.7と最大sample difference = 0。

Mono：

Phase 3.7と同一。

既存Phase 1〜3.7テストをすべて維持。

---

# 26. Debug CSV

必要なら、

```text
frame
bin
magL
magR
inputIPD
independentOutputIPD
finalOutputIPD
coherenceWeight
ILD
```

を出力可能にする。

通常処理では無効。

---

# 27. Performance

音質優先。

ただしprocess frame内で不要なallocationをしない。

L/Rを別々に完全処理した後に巨大な追加FFTを行う構造は避ける。

既存STFT結果を可能な限り共有する。

---

# 28. AB files

最低、

Bass:
Phase 3.7 / Phase 4
0.75 / 0.50

Mix:
Phase 3.7 / Phase 4
0.75 / 0.50

を同一gainで生成。

---

# 29. 報告内容

- Stereo Coherence設計
- shared peak map方式
- coherenceWeight式
- low frequency weighting
- phase blending式
- IPD test結果
- ILD test結果
- Bass Side/Mid
- Bass correlation
- Mix Side/Mid
- IPD weighted RMS error
- decorrelated noise test
- CPU processing time
- AB試聴で確認すべき点
- 残るartifact

Phase 4完了後は停止する。

まだMulti-resolutionへ進まない。