# High Quality Time Stretch Engine
## C++20 + Apple Accelerate / Phase 1〜5

## 1. プロジェクトの目的

iPhone / iPad / macOS向けの楽器練習用オーディオプレイヤーに搭載する、高音質なTime Stretch EngineをC++で実装する。

最終目標は以下。

- 音程を維持したまま再生速度を変更する
- 主用途は完成済みステレオ楽曲
- 特に 0.50〜1.00x の減速品質を重視する
- 0.40〜1.25xを実用範囲とする
- 0.50〜0.80xで既存の高品質商用タイムストレッチ製品に可能な限り近い音質を目指す
- AVAudioUnitTimePitchより明確に高い音質を目標とする
- 将来的にリアルタイムストリーミングへ移行可能な設計にする
- DSPコアはSwiftに依存させない
- FFT等の低レベル処理にはApple Accelerate/vDSPを使用する
- C++20で実装する

本Phaseではリアルタイム再生は実装しない。

最初に、

    input.wav
        ↓
    TimeStretchEngine
        ↓
    output.wav

というオフライン処理プログラムを完成させる。

音質を確立してからiOSプレイヤーへ統合する。

---

# 2. 最重要設計原則

以下を必ず守ること。

1. UIコードを作らない。
2. AVAudioEngineをまだ使用しない。
3. 最初からリアルタイム制約を課さない。
4. 音質をCPU使用率より優先する。
5. アルゴリズムの各段階をON/OFFできるようにする。
6. パラメータをハードコードしすぎない。
7. 入力ファイルと処理結果を簡単に比較できるCLIを作る。
8. 各Phaseをgit commit可能な独立状態にする。
9. DSPコードにヒープアロケーションを乱発しない。
10. 将来リアルタイム化できるよう、処理状態をクラス内部に保持する。
11. Rubber Band等のGPL実装をコピーしない。
12. 特定ライブラリのコードを翻案・移植しない。
13. 公開されたDSP理論を基に独自実装する。

---

# 3. 今回実装するPhase

以下を順番に実装する。

Phase 1:
基本STFT Phase Vocoder

Phase 2:
瞬時周波数推定と正確なPhase Propagation

Phase 3:
Peak-based Phase Locking

Phase 4:
Transient Detection + Phase Reset

Phase 5:
Multi-resolution Processing

Phase 5終了時点で、実際の楽曲を0.5xまで落として実用的な品質になることを目標とする。

---

# 4. 対象フォーマット

初期実装では入力条件を限定する。

必須:

- WAV
- PCM float32 または PCM int16
- 44.1 kHz
- 48 kHz
- mono
- stereo

DSP内部表現:

    float

チャンネル形式:

    planar float

つまり、

    float* left
    float* right

または、

    std::vector<float> channel[2]

として処理する。

内部DSPをinterleaved前提にしない。

---

# 5. ディレクトリ構成

以下を基本とする。

    TimeStretch/
    ├── CMakeLists.txt
    ├── README.md
    ├── src/
    │   ├── main.cpp
    │   │
    │   ├── audio/
    │   │   ├── WavReader.h
    │   │   ├── WavReader.cpp
    │   │   ├── WavWriter.h
    │   │   └── WavWriter.cpp
    │   │
    │   ├── dsp/
    │   │   ├── TimeStretchEngine.h
    │   │   ├── TimeStretchEngine.cpp
    │   │   ├── STFT.h
    │   │   ├── STFT.cpp
    │   │   ├── FFTAccelerate.h
    │   │   ├── FFTAccelerate.cpp
    │   │   ├── PhaseVocoder.h
    │   │   ├── PhaseVocoder.cpp
    │   │   ├── PhaseLocker.h
    │   │   ├── PhaseLocker.cpp
    │   │   ├── TransientDetector.h
    │   │   ├── TransientDetector.cpp
    │   │   ├── MultiResolutionProcessor.h
    │   │   ├── MultiResolutionProcessor.cpp
    │   │   ├── OverlapAdd.h
    │   │   ├── OverlapAdd.cpp
    │   │   └── MathUtils.h
    │   │
    │   └── debug/
    │       ├── CsvLogger.h
    │       └── CsvLogger.cpp
    │
    └── tests/
        ├── TestSignals.cpp
        ├── PhaseVocoderTests.cpp
        ├── TransientTests.cpp
        └── AudioRegressionTests.cpp

クラスを巨大化させないこと。

TimeStretchEngineは全処理を直接実装せず、各DSPコンポーネントを統括するFacadeにする。

---

# 6. Public API

最低限以下を用意する。

```cpp
namespace ts {

struct StretchConfig {
    double sampleRate = 44100.0;
    int channels = 2;

    double timeRatio = 1.0;

    bool enablePhaseLocking = true;
    bool enableTransientHandling = true;
    bool enableMultiResolution = true;

    int fftSize = 4096;
    int analysisHop = 1024;

    float transientThreshold = 1.5f;
};

class TimeStretchEngine {
public:
    explicit TimeStretchEngine(const StretchConfig& config);

    void reset();

    void setTimeRatio(double ratio);

    std::vector<std::vector<float>>
    processOffline(
        const std::vector<std::vector<float>>& input
    );
};

}
```

timeRatioの定義は、

    output duration / input duration

とする。

したがって、

通常速度:

    timeRatio = 1.0

75%速度:

    timeRatio = 1 / 0.75
              = 1.333333

50%速度:

    timeRatio = 2.0

40%速度:

    timeRatio = 2.5

CLI上では利用者にはspeedを指定させてもよい。

例:

    --speed 0.5

内部で、

    timeRatio = 1.0 / speed

に変換する。

---

# 7. CLI仕様

以下を実装する。

```bash
./timestretch \
    input.wav \
    output.wav \
    --speed 0.50
```

追加オプション:

```bash
--fft-size 4096
--analysis-hop 1024

--phase-locking on
--transient on
--multiresolution on

--debug-csv ./debug/
```

比較用presetも用意する。

```bash
--quality draft
--quality normal
--quality high
--quality extreme
```

ただしPhase 1〜5ではhighを基準とする。

---

# 8. Phase 1 — STFT Phase Vocoder

## 8.1 FFT

Apple Accelerate/vDSPを使用する。

FFT abstractionとして、

```cpp
class FFTAccelerate {
public:
    explicit FFTAccelerate(size_t fftSize);

    void forward(
        const float* timeDomain,
        std::complex<float>* spectrum
    );

    void inverse(
        const std::complex<float>* spectrum,
        float* timeDomain
    );

private:
    size_t fftSize_;
};
```

のようなAPIを作る。

Accelerate固有型を他クラスへ漏らさない。

---

# 9. FFTサイズ

最初の標準値:

    FFT size = 4096

44.1kHzの場合、

    4096 / 44100
    ≈ 92.9 ms

48kHzの場合、

    4096 / 48000
    ≈ 85.3 ms

これは音楽全体を扱うPhase Vocoderの初期値として使う。

最終的にはmulti-resolution処理で複数サイズを使用する。

---

# 10. Window

最初はHann windowを使用する。

Analysis:

    xw[n] = x[n] * w[n]

Synthesisにも対応する窓を使用する。

Overlap Add後のレベル変動を防止するため、window normalizationを必ず実装する。

単純にIFFT結果を加算するだけではいけない。

各サンプル位置について、

    normalization[n] += w[n] * w[n]

を蓄積し、

最終的に

    output[n] /= normalization[n]

とする方式でもよい。

0除算を防止するため、

    epsilon = 1e-8

程度を使用する。

---

# 11. Hop Size

初期値:

    N = 4096
    Ha = 1024

つまり75% overlap。

Analysis hop:

    Ha = N / 4

Synthesis hop:

    Hs = Ha * timeRatio

ただしHsが整数でない場合があるため、単純な整数丸めによる累積時間誤差を発生させない。

doubleのsynthesis position accumulatorを持つ。

例:

```cpp
double synthesisPosition = 0.0;

synthesisPosition += analysisHop * timeRatio;
```

各frameの出力開始位置を適切に決定する。

後のリアルタイム版では別設計になる可能性がある。

---

# 12. Phase 2 — Instantaneous Frequency

単純にFFT binの位相をコピーしてはいけない。

bin kの中心角周波数:

    omega_k = 2πk / N

Analysis frame間で期待される位相進行:

    expected =
        omega_k * Ha

前フレームとの実位相差:

    delta =
        phi_current[k]
        - phi_previous[k]
        - expected

これを

    [-π, +π]

へwrapする。

```cpp
inline float wrapPhase(float x) {
    while (x > M_PI) x -= 2.0f * M_PI;
    while (x < -M_PI) x += 2.0f * M_PI;
    return x;
}
```

ただし性能上、最終的にはwhileを使わない高速実装にしてよい。

True angular frequency:

    trueOmega =
        omega_k
        + delta / Ha

Synthesis phase:

    synthesisPhase[k] +=
        trueOmega * Hs

出力complex spectrum:

    Y[k] =
        magnitude[k]
        * exp(j * synthesisPhase[k])

---

# 13. DC / Nyquist

DC binとNyquist binは通常binと同じphase処理を行わない。

特殊ケースとして安全に処理する。

NaNを絶対に発生させない。

---

# 14. Phase 3 — Peak-based Phase Locking

Phase Vocoder特有の

- smeared sound
- hollow sound
- chorus感
- 金属感

を軽減する。

各analysis frameのmagnitude spectrumからlocal spectral peaksを検出する。

peak候補:

    mag[k] > mag[k-1]
    &&
    mag[k] >= mag[k+1]

さらに微小ノイズpeakを除外する。

例:

    mag[k] > localNoiseFloor * threshold

固定絶対値thresholdだけにはしない。

---

# 15. Peak Region

各peakを中心として、そのpeakが支配するbin領域を決める。

最初は単純に、

隣接peakとの中間点をregion boundaryとする。

例:

    peak A = bin 20
    peak B = bin 30

なら、

    bins 0〜25 → A
    bins 26〜... → B

のように所属を決める。

---

# 16. Identity Phase Locking

peak bin pについて通常のphase propagationを行い、

    synthPhase[p]

を求める。

peak周辺bin kについては、

analysis phase difference:

    relativePhase =
        analysisPhase[k]
        - analysisPhase[p]

を保存し、

    synthPhase[k] =
        synthPhase[p]
        + relativePhase

として再構成する。

つまりpeakのphaseへ周辺binをロックする。

この処理をON/OFFできるようにする。

```cpp
config.enablePhaseLocking
```

---

# 17. Peak補間

Phase 3の後半では、可能ならpeak周波数位置を整数binだけで判断しない。

magnitude spectrumの

    k-1
    k
    k+1

を利用してparabolic interpolationを行う。

log magnitude上で補間すること。

概念:

    alpha = log(M[k-1])
    beta  = log(M[k])
    gamma = log(M[k+1])

    p = 0.5 *
        (alpha - gamma)
        /
        (alpha - 2*beta + gamma)

peak location:

    k + p

これによって低周波のfrequency estimation精度を上げる。

---

# 18. Phase 4 — Transient Detection

このPhaseは非常に重要。

通常Phase Vocoderではドラムなどのtransientが時間方向に引き延ばされ、アタックがぼやける。

transientを検出し、そのタイミングではphase continuityを意図的にresetする。

---

# 19. Spectral Flux

基本transient detectorとしてSpectral Fluxを実装する。

normalized magnitude:

    M_t[k]

前frame:

    M_{t-1}[k]

positive spectral flux:

    flux =
        Σ max(
            M_t[k] - M_{t-1}[k],
            0
        )

低周波だけの変動に引っ張られすぎないよう必要ならlog magnitudeを使用する。

候補:

    L[k] = log(1 + c * M[k])

---

# 20. Adaptive Threshold

固定thresholdではなく履歴からadaptive thresholdを計算する。

直近、

    8〜16 frames

程度のflux履歴を保存する。

例:

    baseline =
        median(previousFlux)

transient condition:

    flux >
        baseline * transientThreshold

初期値:

    transientThreshold = 1.5

必要に応じて平均値ではなくmedianを使う。

外れ値の影響を抑えるためである。

---

# 21. Transient判定のヒステリシス

transientを1frameだけ単純検出すると不安定になる可能性がある。

以下を検討する。

- onset candidate
- attack state
- release state

minimum intervalも設定する。

例:

    minimumTransientDistance
        = 20〜30 ms

同じスネアのアタックを複数回検出しないこと。

---

# 22. Phase Reset

transient frameでは通常のphase propagationを弱める。

最初の実装では、

    synthesisPhase[k]
        = analysisPhase[k]

を基本とする。

ただし全binを完全resetすると音色が不安定になる可能性がある。

そのためPhase 4後半で、

    transient strength

を0〜1へ正規化し、

    propagatedPhase

と

    resetPhase

を補間する方法を試せるようにする。

位相そのものを線形補間するとwrap問題があるため、complex unit vectorとして補間すること。

---

# 23. Transient時のPhase Lock

transient frameではPeak-based Phase Lockingを通常frameより強く適用してよい。

最初は、

    transient detected
        ↓
    phase reset
        ↓
    peak locking

という順番で試す。

AB比較できるようにする。

---

# 24. Transient Preservation

重要:

transientそのものをtimeRatio倍に間延びさせない方向を目指す。

Phase 4ではまずphase resetまで実装する。

次Phase以降で、

    transient region
        ↓
    near-unity local stretch

    sustain region
        ↓
    compensate with stronger stretch

というadaptive time mappingへ発展させられるよう設計しておく。

ただしPhase 1〜5の完成条件には必須としない。

---

# 25. Stereo Processing

L/Rを完全独立した別エンジンとして扱わない。

transient detectionは原則として共通化する。

transient analysis signal:

    M = 0.5 * (L + R)

または、

    magnitudeCombined[k]
        = sqrt(
            Lmag[k]^2
            + Rmag[k]^2
        )

を用いる。

peak detectionについても可能な限り共通peak mapを使う。

Phase propagationそのものは各チャンネルで行ってよいが、

- transient position
- spectral peak regions
- phase reset timing

はL/Rで共有する。

これによりステレオ像が左右に揺れるのを減らす。

---

# 26. Phase 5 — Multi-resolution

単一FFTサイズでは、

- bass
- vocal
- drums
- cymbals

を同時に最適化できない。

低音ではfrequency resolutionが重要。

transientではtime resolutionが重要。

そのため複数解析解像度を組み合わせる。

---

# 27. 初期Multi-resolution構成

3band構成を試す。

Low:

    FFT = 8192
    hop = 2048

Mid:

    FFT = 4096
    hop = 1024

High / transient:

    FFT = 1024
    hop = 256

ただしsample rateに応じて調整可能にする。

---

# 28. 周波数帯

初期cross-over:

Low:

    0〜300 Hz

Mid:

    200〜4000 Hz

High:

    3000 Hz〜Nyquist

overlap領域を設ける。

ハードなbin切り替えは禁止。

必ずcrossfadeする。

例えば、

Low → Mid:

    200〜300 Hz

Mid → High:

    3000〜4000 Hz

を滑らかにブレンドする。

---

# 29. Multi-resolutionの実装戦略

Phase 5初期版では、

各resolutionで完全なtime-domain outputを生成する。

    Low engine
        ↓
    lowOutput

    Mid engine
        ↓
    midOutput

    High engine
        ↓
    highOutput

その後、適切なfrequency-domain crossover / FIR filter等で統合する方式を採用してよい。

ただし単純なtime-domain IIR filterで位相関係を壊さないこと。

可能ならlinear-phase FIRまたはfrequency-domain weightingを利用する。

---

# 30. 別案

実装上より安定する場合は、

一つのSTFT frame内で複数解像度を解析し、

frequency regionごとに対応するresolutionのphase/frequency informationを採用してもよい。

ただしPhase 5では過度に複雑化しない。

まず音質比較可能な実装を優先する。

---

# 31. Multi-resolutionで特に確認するポイント

ベース:

- 周期的な揺れが減るか
- 音程が安定するか
- E弦など40〜100Hz付近が明瞭か

Kick:

- attackがぼやけないか

Snare:

- 二重アタックにならないか

Hi-hat / Cymbal:

- phasiness
- metallic noise
- granular感

Vocal:

- chorus感
- watery sound
- metallic sound

を重点評価する。

---

# 32. Normalization

Time stretch後に勝手にピークノーマライズしない。

入力と出力で知覚上の音量差が極端にならないようOverlap Add normalizationのみ行う。

テスト時にnormalizeしてしまうと処理の問題を隠すため禁止。

クリップした場合は検出してログ出力する。

---

# 33. Numerical Safety

以下を徹底する。

- NaNチェック
- Infチェック
- denormal対策
- division by zero対策
- silence input対策

silenceに対して、

    phase = atan2(0,0)

等を無条件に繰り返さない。

非常に小さいmagnitudeについてはphase trackingから除外可能にする。

例:

    magnitude < 1e-7

---

# 34. Memory

frameごとに以下をnew/deleteしない。

事前allocateする。

- FFT input
- FFT output
- magnitude
- phase
- previous phase
- synthesis phase
- peak map
- window
- OLA buffer
- normalization buffer

Realtime化を想定し、

process loop内のallocationを極力ゼロにする。

---

# 35. Debug Data

以下をCSVへ出力可能にする。

frameごとに、

    frameIndex
    inputTime
    outputTime
    spectralFlux
    transientDetected
    peakCount

特定binについて、

    magnitude
    analysisPhase
    trueFrequency
    synthesisPhase

もdebug optionで出せるようにする。

通常時は無効。

---

# 36. Test Signals

実音源だけでは原因解析できないため、人工信号テストを作る。

最低限:

### Sine

    440 Hz
    5 sec

50%速度にしても周波数が、

    440 Hz

付近に維持されること。

---

### Low sine

    55 Hz
    110 Hz

bass stabilityを見る。

---

### Impulse

単一impulse。

transientが極端に広がらないか確認する。

---

### Click Train

    120 BPM

一定間隔のclickを生成。

50%速度ならclick間隔がおよそ2倍になること。

click本体のattack幅が必要以上に2倍にならないこと。

---

### Chirp

20 Hz〜20 kHz frequency sweep。

不連続やaliasingを見る。

---

### Two Tone

    440 Hz
    +
    660 Hz

phase/frequency trackingを確認。

---

### Stereo

L:

    440 Hz

R:

    440 Hz phase shifted

ステレオ関係が破綻しないこと。

---

# 37. 実楽曲の評価セット

最低5種類用意する。

A:
ロック / ポップス完成音源

B:
ベースが強い音源

C:
男性または女性ボーカル中心

D:
アコースティックギター / ピアノ

E:
ドラムが強い音源

可能なら無圧縮WAVを使用する。

---

# 38. 評価速度

必ず以下を生成する。

    1.00x
    0.85x
    0.75x
    0.65x
    0.50x
    0.40x

特に、

    0.75
    0.50

を重点評価する。

---

# 39. AB比較

同一音源について、

    original
    custom
    AVAudioUnitTimePitch
    Signalsmith Stretch

等を比較できるようにする。

ただし、他製品の実装コードをコピーしない。

比較対象は音質ベンチマークとしてのみ使用する。

---

# 40. ABテスト時の注意

比較音源間で、

- sample rate
- bit depth
- output length
- loudness

をなるべく一致させる。

ファイル名だけでどのエンジンかわからないblind test用scriptを作ってもよい。

例:

    test_A.wav
    test_B.wav
    test_C.wav

対応表を別ファイルへ保存する。

---

# 41. 自動テスト

以下をunit test化する。

## Duration

speed 0.5なら、

    output duration
        ≈ input duration * 2

許容誤差:

    < 1 analysis hop

---

## Pitch

440Hz入力を0.5x処理。

出力dominant frequency:

    440Hz ± 1Hz

を目標。

---

## Silence

全ゼロ入力。

出力:

- NaNなし
- Infなし
- 大きなノイズなし

---

## Unity

speed = 1.0

入力と出力が可能な限り近いこと。

完全bit-identicalは要求しないが、

Phase Vocoderを経由した結果として異常なphase alterationがないこと。

可能ならspeed=1.0ではDSP bypassも用意する。

---

# 42. Performance Measurement

各処理で、

    processing time / audio duration

を記録する。

例:

    60 sec audio
    process time 4.2 sec

Realtime factor:

    4.2 / 60
    = 0.07

Phase 1〜5では、

    realtime factor < 1.0

であればまず合格。

音質をCPUより優先する。

iPhone最適化は後で行う。

---

# 43. Quality Presetの初期値

### Draft

    FFT 2048
    Phase locking OFF
    transient ON
    multiresolution OFF

### Normal

    FFT 4096
    phase locking ON
    transient ON
    multiresolution OFF

### High

    FFT 4096
    phase locking ON
    transient ON
    multiresolution ON

### Extreme

Phase 5終了後に設計する。

最初はHighを主要ターゲットとする。

---

# 44. 実装順序

この順序を厳守する。

## Step 1

WAV reader/writer。

input.wavを読み、そのままoutput.wavへ書いてbit depth変換が正常か確認。

## Step 2

FFT wrapper。

sine waveをFFT → IFFTし、再構成できることを確認。

## Step 3

STFT + OLA。

timeRatio=1.0で正常に再構成。

## Step 4

basic phase vocoder。

0.75 / 0.5でdurationとpitchを確認。

## Step 5

instantaneous frequency correction。

## Step 6

peak detector。

CSVでpeak位置を確認。

## Step 7

phase locking。

ON/OFF比較ファイルを生成。

## Step 8

spectral flux transient detector。

click/drumで検出位置をCSV確認。

## Step 9

phase reset。

ON/OFF比較。

## Step 10

stereo shared analysis。

## Step 11

multi-resolution。

## Step 12

quality presets。

---

# 45. 各Phase終了時の成果物

必ず以下を生成する。

例えばPhase 3なら、

    results/
    └── phase3/
        ├── rock_075.wav
        ├── rock_050.wav
        ├── bass_075.wav
        ├── bass_050.wav
        ├── drums_075.wav
        ├── drums_050.wav
        └── metrics.txt

Phaseごとの比較を削除しない。

---

# 46. PhaseごとのGit運用

最低限以下のcommitを分ける。

    Phase 1 basic STFT
    Phase 2 instantaneous frequency
    Phase 3 phase locking
    Phase 4 transient handling
    Phase 5 multi resolution

途中で音質が悪化した場合にbisectできる状態を保つ。

---

# 47. コメント

DSPコードでは、

「何をしているか」

だけでなく、

「なぜ必要なのか」

をコメントする。

悪い例:

```cpp
phase += delta;
```

だけ。

良い例:

```cpp
// Accumulate synthesis phase using the estimated
// instantaneous frequency instead of the FFT-bin
// center frequency. This prevents pitch drift when
// a sinusoidal component falls between FFT bins.
phase += trueOmega * synthesisHop;
```

---

# 48. 最適化について

最初からNEON intrinsicsを直接書かない。

まずAccelerate/vDSPを使用する。

最適化優先順位:

1. correctness
2. audio quality
3. architecture
4. profiling
5. performance optimization

とする。

推測で最適化しない。

---

# 49. Accelerate

FFT、windowing、vector operation等についてApple Accelerateを積極的に利用する。

ただしDSPアルゴリズムそのものをAccelerate依存にしない。

理想:

    PhaseVocoder
        ↓
    FFT interface
        ↓
    FFTAccelerate

将来他プラットフォームへ移植する場合、

    FFTAccelerate

だけを交換できる設計にする。

---

# 50. 将来のPhase 6以降を考慮

Phase 1〜5のコードは将来以下へ拡張できるようにする。

Phase 6:
より高度なStereo Coherence

Phase 7:
Adaptive Time Mapping / transient preservation

Phase 8:
Pitch Shift

Phase 9:
Streaming API

Phase 10:
iOS real-time integration

Phase 11:
Swift / Objective-C++ wrapper

Phase 12:
A-B loop / seek / speed automation

このため、

processOffline()内部へすべての処理ロジックを書かない。

内部処理は将来的に、

```cpp
pushInput(...)
process(...)
available()
retrieve(...)
```

方式へ移行可能にする。

---

# 51. 今回やってはいけないこと

以下は禁止。

- SoundTouchをラップしただけの実装
- AVAudioUnitTimePitchへ処理を丸投げ
- Rubber Bandコードのコピー
- GPLコードのコピー
- ffmpeg atempoへ丸投げ
- phase vocoderを数十行書いて「完成」とする
- transient detectorなしで完成扱い
- stereo L/Rを完全独立処理
- 0.9xだけ試して品質評価
- testなし
- WAV結果を出さず数値だけ評価
- FFTサイズ4096固定で終了
- 処理ごとに大量allocation
- audio loop内部の不要なlogging

---

# 52. Phase 5完成条件

以下を満たしたらPhase 1〜5完了とする。

技術条件:

- WAV stereo 44.1/48kHz正常処理
- 0.40〜1.25x対応
- pitch維持
- duration正常
- NaN/Infなし
- unity正常
- transient detector動作
- phase locking動作
- multi-resolution動作
- stereo共有解析あり

音質条件:

### 0.75x

- ボーカルに強いmetallic artifactがない
- ベースの周期的な揺れが小さい
- kick/snare attackが明瞭
- stereo centerが大きく揺れない
- cymbalが極端にgranularにならない

### 0.50x

多少artifactが出るのは許容するが、

- 楽器練習に十分使える
- ベース音程を聞き取れる
- ボーカルの音程を聞き取れる
- drum attack位置を判断できる
- AVAudioUnitTimePitchより主観的に改善している

ことを目標とする。

---

# 53. Codexの作業方法

一度にPhase 5まで実装しないこと。

最初はPhase 1のみ実装する。

各Phase終了後、

1. build
2. unit test
3. artificial signal test
4. WAV generation
5. metrics
6. 問題点の報告

を行う。

既存Phaseを壊さず次へ進む。

---

# 54. 最初にCodexが実装する範囲

まず以下だけを実装する。

### Phase 1

- CMake project
- WAV reader/writer
- FFTAccelerate
- Hann window
- STFT
- Overlap Add
- basic Phase Vocoder
- CLI
- sine test
- impulse test
- duration test
- 1.0 / 0.75 / 0.50 speed output

この時点では、

- peak phase locking
- transient detection
- multi-resolution

はまだ実装しない。

ただし後から追加可能なinterfaceを用意しておく。

---

# 55. Phase 1実装後に報告する内容

実装終了時、以下を必ず報告する。

1. 作成したファイル一覧
2. アーキテクチャ
3. FFT APIの選択理由
4. FFT size
5. analysis hop
6. synthesis hopの計算方法
7. window normalization方法
8. phase propagation式
9. unit test結果
10. 0.5x処理時間
11. 判明している音質上の問題
12. Phase 2で改善すべき項目

コードを書いただけで終了しない。

---

# 56. 最終的な設計思想

このプロジェクトは単に、

「音を遅く再生できる」

ことを目的としない。

目標は、

「0.5〜0.8xまで速度を落としても、ベース、ギター、ボーカル、ドラムを耳で追いやすく、楽器練習に使える音質」

である。

そのため、

    CPU efficiency

より、

    transient integrity
    pitch stability
    stereo coherence
    low-frequency stability
    reduction of phase-vocoder artifacts

を優先する。

特に0.5xでの音質を主要benchmarkとする。

Phase 1〜5完了後、実際の比較音源を聴いた結果を基にPhase 6以降のアルゴリズムを決定する。