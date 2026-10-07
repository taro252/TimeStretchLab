# Phase 2 — Peak-based Phase Locking

Phase 1の全テストが成功しました。

ここから音質改善フェーズへ進みます。

現在のPhaseVocoderにはすでに以下が実装されています。

- STFT
- Hann analysis/synthesis window
- OLA normalization
- instantaneous frequency estimation
- phase unwrapping
- synthesis phase propagation
- fractional synthesis hop対応
- low-energy bin phase state reset

これらは壊さないでください。

今回は **Peak-based Phase Lockingのみ** を追加してください。

まだ以下は実装しないでください。

- Transient Detection
- Transient Phase Reset
- Adaptive Time Mapping
- Multi-resolution
- Stereo coherenceの高度な処理
- Pitch Shift
- Real-time streaming
- Swift/iOS統合

---

# 1. 目的

通常のbin-independent Phase Vocoderでは、各FFT binが独立してphase propagationされるため、

- ボーカルが水っぽくなる
- コード楽器がぼやける
- 音像が広がる
- ベースの芯が弱くなる
- sustained toneがchorus的になる

といったphase incoherence artifactが発生する。

Phase 2ではspectral peakをanchorとして、その周辺binのphase relationshipを維持する。

目標は、

「Phase 1よりも音の芯と定位が明瞭になること」

である。

特に、

- vocal
- bass
- guitar
- piano

を重点評価する。

---

# 2. 実装方針

Identity Phase Locking系の方式を実装する。

各analysis frameについて、

1. magnitude spectrum計算
2. spectral peak検出
3. peak支配領域の決定
4. peak binは従来通りinstantaneous frequencyからphase propagation
5. peak周囲binはpeakとのanalysis phase relationshipを保持
6. synthesis spectrum生成

という順序とする。

---

# 3. クラス分離

PhaseVocoder.cppへすべて書き込まない。

新しく、

```cpp
PhaseLocker.h
PhaseLocker.cpp
```

を作成する。

最低限、

```cpp
class PhaseLocker {
public:
    explicit PhaseLocker(std::size_t fftSize);

    void reset();

    void analyzePeaks(
        const std::complex<float>* spectrum,
        std::size_t binCount
    );

    const std::vector<int>& peakBins() const;
    const std::vector<int>& ownerPeak() const;
};
```

程度の責務分離を行う。

設計上より適切ならAPIは変更して構わない。

ただし、

- peak detection
- peak region assignment
- phase locking

のロジックがテスト可能な構造になること。

---

# 4. PhaseVocoderとの関係

PhaseVocoderには現在、

```cpp
previousPhase_
synthesisPhase_
initialized_
```

が存在する。

これらを利用したinstantaneous frequency処理は残す。

Phase LockingをOFFにした場合は、現在のPhase 1と同一の処理結果になること。

これは必須。

```cpp
config.enablePhaseLocking = false
```

の場合、

Phase 1との差が数値上ほぼゼロになることをテストする。

---

# 5. Magnitude Spectrum

各binについて、

```cpp
magnitude[k] = abs(spectrum[k]);
phase[k] = atan2(imag, real);
```

を計算する。

毎frame dynamic allocationしない。

PhaseLocker内部に必要bufferを事前allocateする。

---

# 6. Spectral Peak Detection

まず単純なlocal maximumを候補とする。

bin kについて、

```cpp
magnitude[k] > magnitude[k - 1]
&&
magnitude[k] >= magnitude[k + 1]
```

をpeak候補とする。

DCとNyquistはpeak detectorから除外する。

---

# 7. Noise Peak除去

全local maximumをpeak扱いすると、微小noise binまでanchorになり品質が不安定になる。

そのため相対thresholdを導入する。

固定絶対値thresholdだけにはしない。

最初の実装では、

```cpp
frameMaxMagnitude
```

に対する相対値を使用してよい。

例:

```cpp
peakMagnitude >= frameMaxMagnitude * 0.001
```

つまり約 -60 dB。

この値は定数として分離し、後から変更可能にする。

例:

```cpp
constexpr float kPeakRelativeThreshold = 0.001f;
```

ただしsilent frameではpeakを0個として安全に処理する。

---

# 8. Peak Region Assignment

検出されたpeakを周波数順に並べる。

隣り合うpeak、

```text
p1
p2
```

について、その中間binをboundaryとする。

例えば、

```text
peak = 20
peak = 30
```

なら、

```text
20のregion:
... ～ 25

30のregion:
26 ～ ...
```

のようにする。

各binについて、

```cpp
ownerPeak[k]
```

を持たせる。

ownerPeak[k]には、そのbinを支配するpeak bin番号を格納する。

peakが存在しないframeではPhase 1方式へfallbackする。

---

# 9. Peak BinのPhase

peak bin p自身については現在のPhase Vocoderと同様に、

```text
analysis phase difference
↓
unwrap
↓
instantaneous frequency
↓
synthesis phase accumulation
```

を行う。

つまりpeak binは、

```cpp
synthesisPhase_[p]
```

を通常通り計算する。

---

# 10. Identity Phase Locking

peak pのregionに属するbin kについて、

analysis frame内のrelative phase:

```text
relativePhase =
    analysisPhase[k]
    - analysisPhase[p]
```

を計算する。

その後、

```text
synthesisPhase[k] =
    synthesisPhase[p]
    + relativePhase
```

とする。

必ずphase wrapを適切に扱う。

概念式:

\[
\theta_k =
\theta_p +
wrap(\phi_k-\phi_p)
\]

ここで、

- φ = analysis phase
- θ = synthesis phase
- p = owner peak

である。

---

# 11. 重要: Peak自身を二重処理しない

k == pの場合は、

```cpp
synthesisPhase_[p]
```

をそのまま使用する。

relative phase処理を再適用して数値誤差を増やさない。

---

# 12. previousPhase状態

重要。

Phase Lockingを有効にした場合でも、

```cpp
previousPhase_[k]
```

は全有効binについて更新する。

将来的に、

- peakが移動する
- owner peakが変わる
- phase locking OFFへ切り替える

可能性があるため、analysis phase historyを失わないこと。

ただし低振幅binについてはPhase 1で実装済みのreset処理を維持する。

---

# 13. Peak移動への対応

音楽では、

```text
frame t:
peak bin 37

frame t+1:
peak bin 38
```

のようにpeakが移動する。

Phase 2初期版では高度なpeak trackingはまだ実装しなくてよい。

各frame独立でpeak detection / region assignmentしてよい。

ただし、

peakが1bin移動するたびに大きなphase discontinuityが発生していないかテストする。

大きな問題が見られる場合は、勝手に複雑なpeak trackingを実装せず報告する。

---

# 14. Parabolic Peak Interpolation

Phase 2では、integer bin peak detectionに加えてsub-bin peak estimationも実装する。

peak kについて、

```cpp
a = log(max(magnitude[k - 1], epsilon));
b = log(max(magnitude[k], epsilon));
c = log(max(magnitude[k + 1], epsilon));
```

として、

```cpp
denom = a - 2*b + c;
```

denomが十分大きい場合、

```cpp
offset =
    0.5 * (a - c) / denom;
```

とする。

offsetは安全のため、

```text
-0.5 ～ +0.5
```

へclampする。

sub-bin peak position:

```cpp
peakPosition = k + offset;
```

とする。

---

# 15. Parabolic interpolationの用途

最初は、

- debug表示
- peak frequency推定
- 将来の高度なphase propagation

に利用する。

Phase 2初期実装では、sub-bin peak位置を無理にphase locking region境界へ使用しなくてもよい。

まずinteger owner mapを安定させる。

---

# 16. Silent / Near-Silent Frame

frame全体が非常に小さい場合は、

```text
peak count = 0
```

とする。

その場合、

```text
Phase 1 processing
```

へfallbackする。

NaN / Infを絶対に発生させない。

---

# 17. Stereo

Phase 2ではまだ高度なstereo coherenceは実装しない。

現在と同じく各channel独立処理でよい。

ただし将来、

```text
shared peak map
```

を導入できる設計にする。

PhaseLockerがchannel固有の状態へ強く依存しすぎないようにする。

---

# 18. Debug CSV

Phase 2では以下をCSV出力できるようにする。

frame単位:

```text
frameIndex
peakCount
```

peak単位:

```text
frameIndex
peakBin
interpolatedPeakPosition
peakFrequencyHz
peakMagnitude
```

必要なら特定frameについて、

```text
bin
ownerPeak
magnitude
analysisPhase
synthesisPhase
```

も出力できるようにする。

通常buildでは無効化可能にする。

---

# 19. Artificial Test 1 — Single Off-bin Sine

以下を使用する。

```text
sample rate = 48000
frequency = 437.3 Hz
duration = 10 sec
```

speed:

```text
0.75
0.50
```

Phase Locking ON/OFFで比較する。

単一sineについてphase lockingによって明らかな品質劣化が起きてはいけない。

dominant frequencyも維持する。

---

# 20. Artificial Test 2 — Harmonic Signal

以下を同時に生成する。

```text
110 Hz
220 Hz
330 Hz
440 Hz
550 Hz
660 Hz
```

振幅は高調波ほど少し小さくする。

例:

```text
110 = 1.0
220 = 0.8
330 = 0.6
440 = 0.5
550 = 0.4
660 = 0.3
```

speed:

```text
0.75
0.50
```

Peak Locking ON/OFFを比較する。

目的:

- harmonic structureが安定するか
- 不自然なbeatが減るか
- spectrumが崩れないか

---

# 21. Artificial Test 3 — Moving Frequency

ゆっくり、

```text
400 Hz → 500 Hz
```

へ変化するsineを作る。

duration:

```text
10 sec
```

これによってpeak binが時間とともに移動する。

Phase Locking ONで、

- crack
- click
- sudden phase jump
- periodic modulation

が発生しないことを確認する。

---

# 22. Artificial Test 4 — Two Nearby Frequencies

例えば、

```text
440 Hz
470 Hz
```

を同時入力する。

2つのpeakが近接した場合にも、

owner regionが安定しているか確認する。

speed:

```text
0.75
0.50
```

---

# 23. Artificial Test 5 — Noise

white noiseを処理する。

Phase Lockingによって、

- tonal ringing
- oscillation
- NaN
- Inf
- 大きなlevel jump

が発生しないこと。

NoiseについてはPhase Lockingによって必ず音質向上する必要はない。

安定性確認が目的。

---

# 24. 実音源AB比較

以下を必ず比較する。

```text
Phase 1
vs
Phase 2
```

同じ入力・同じ速度・同じ出力音量条件にする。

速度:

```text
0.75
0.50
```

最低以下の素材を使う。

### Bass

確認:

- 音の芯
- pitch stability
- 低音の揺れ
- chorus感

### Vocal

確認:

- watery sound
- metallic sound
- voice center
- consonant clarity

### Guitar / Piano

確認:

- chord clarity
- phase smear
- attack後のsustain

### Full Mix

確認:

- stereo image
- center image
- overall definition

---

# 25. 期待する改善

Phase 2によって特に、

```text
sustain成分のまとまり
音像の芯
harmonic structure
```

が改善することを期待する。

一方、

```text
drum transient
kick attack
snare attack
cymbal smear
```

は今回大きく改善しなくてもよい。

これらは次のTransient Processing Phaseで扱う。

---

# 26. Phase LockingのON/OFF

StretchConfigの、

```cpp
enablePhaseLocking
```

を実際に機能させる。

```cpp
enablePhaseLocking = false
```

ならPhase 1アルゴリズム。

```cpp
enablePhaseLocking = true
```

ならPhase 2アルゴリズム。

Phase 2完成後もPhase 1比較を可能にする。

---

# 27. Regression Test

Phase Locking OFF時に、Phase 1の既存テストをすべて通すこと。

最低でも、

- FFT round trip
- STFT/OLA reconstruction
- off-bin sine
- duration
- silence
- threshold re-entry
- stereo

を壊さない。

---

# 28. Performance

Phase 2では音質を優先する。

ただし毎frame、

```cpp
std::vector
```

の生成・破棄を大量に行わない。

必要bufferはconstructor等でallocateする。

processing loop内で不要なheap allocationを行わない。

---

# 29. 実装後の報告

以下を必ず報告する。

1. 変更ファイル一覧
2. PhaseLockerの設計
3. peak detection方式
4. peak threshold
5. peak region assignment方式
6. relative phase lockingの式
7. peak interpolation方式
8. Phase 1 regression test結果
9. Artificial Test結果
10. 0.75x Phase 1/Phase 2比較
11. 0.50x Phase 1/Phase 2比較
12. processing performance
13. 現時点で分かっているartifact
14. 次Phaseで改善すべき点

---

# 30. 重要

Phase 2の目的は、

「コード上Phase Lockingを実装した」

ことではない。

実際の音源で、

Phase 1よりPhase 2の方が、

- harmonic soundがまとまる
- watery artifactが減る
- sustainが明瞭になる

ことを確認する。

もしPhase Locking ONの方が明確に悪い音になる場合は、無理に次Phaseへ進まない。

原因を調査し報告する。

---

# 31. 今回はここで止める

Phase 2完成後、

- ソースコード
- テスト結果
- AB比較結果

を確認してから次Phaseを決定する。

まだTransient Detection、Phase Reset、Multi-resolutionには進まないこと。