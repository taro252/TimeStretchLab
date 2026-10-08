# Phase 7 — PVSOLA Prototype

Phase 6 Partial Trackingはexperimentalとして残すが、既定OFFを維持する。

理由：

- 実Vocalで聴感上の改善が確認できない
- 持続母音の変動指標も改善していない
- track寿命が短い
- watery / phasy artifactの改善につながっていない

Phase 7では、Phase 5.3 Highをベースに、

**PVSOLA-style periodic phase resynchronization**

を実装する。

目的：

ボーカルの持続母音に残る、

- watery
- phasy
- reverberant
- distant
- chorus-like

artifactを減らす。

---

## 1. 基本方針

通常処理はPhase 5.3 Highのまま。

つまり：

Low:
8192 / 2048

Mid:
4096 / 1024

+

- transient handling
- adaptive time mapping
- precise anchoring
- peak phase locking
- stereo coherence
- streaming

を維持する。

PVSOLAはまずMid pathだけに適用する。

---

## 2. Periodic resynchronization

一定間隔ごとにMid Phase Vocoderのphaseを入力信号へ再同期する。

通常：

analysis frame
→ phase propagation
→ phase locking
→ synthesis

Phase 7：

analysis frame
→ phase propagation
→ phase locking
→ ...

一定期間後：

WSOLA-style alignment
→ original analysis phaseを使う
→ phase state reset
→ 通常phase propagationへ戻る

---

## 3. Resync interval

固定1フレームごとにはresetしない。

初期値候補：

80 ms
120 ms
160 ms

の3条件を比較する。

48 kHz / hop 1024なら、

約4 / 6 / 8 analysis frames

程度。

まず120 msをdefault prototypeとする。

---

## 4. Resyncをtransientでは行わない

Phase 3系のtransient handlingとは別。

PVSOLA resyncは、

**持続的・tonal・voicedな区間**

でのみ行う。

明確なTransientEvent周辺では抑制する。

transient前後：

±2〜3 frames

ではPVSOLA resyncしない。

---

## 5. Tonality gate

全区間で周期resetするとpolyphonic mixやnoiseでartifactが出る可能性がある。

まずMid pathのtonalityを判定する。

例えば：

- spectral peak concentration
- harmonicity
- spectral flatness

を使用。

初版では既存Phase 4/6のtonality情報を再利用してよい。

tonalityが一定値以上のときだけresync候補にする。

---

## 6. WSOLA-style alignment

単純に予定されたanalysis frameをそのままresetしない。

現在output overlap部分と、入力側候補frameのwaveform similarityを計算する。

予定入力位置の周辺を検索する。

例：

search range:

±10 ms

または

±15 ms

程度。

normalized cross-correlationを使用する。

---

## 7. Search signal

初版ではMid-band waveformまたはfull-band inputを使ってよい。

ただしLow bassやhigh noiseに引っ張られにくくするため、

可能なら150 Hz〜6 kHz程度のband-limited correlationを試す。

新しい巨大FFT処理は不要。

簡単なFIRでもよい。

---

## 8. Correlation

候補offsetごとに、

normalized cross correlation

を計算する。

概念：

corr =
    dot(a,b)
    /
    sqrt(
        dot(a,a) * dot(b,b) + eps
    )

最大corrになるoffsetを採用する。

---

## 9. Minimum correlation

曖昧な場合はresyncしない。

例：

minimum correlation = 0.65

程度から開始。

最大相関がthreshold未満なら、

通常Phase Vocoderを継続する。

---

## 10. Phase reset

resync frameでは、

Mid pathについて：

synthesisPhase[k] = analysisPhase[k]

previousPhase[k] = analysisPhase[k]

initialized[k] = true

とする。

その後Peak Phase Lockingを適用する。

内部phase stateと出力phaseを一致させる。

---

## 11. Important — synthesis timing

WSOLA alignmentのために入力frame位置をずらしても、

global TimeMapのoutput timingを壊さない。

変更するのは、

「どの入力frameをphase reset sourceとして使うか」

であり、

曲全体の出力durationは維持する。

---

## 12. Smooth resync

hard resetでclickが出る場合に備えて、

soft resync modeも実装可能にする。

例：

2 framesかけて、

current propagated phase
→ input analysis phase

へcomplex unit-vector interpolationする。

ただし最初はhard resetを試し、

必要な場合だけsoft modeを使う。

---

## 13. Stereo

StereoではL/R別々のoffsetを選ばない。

correlation search位置は共有する。

候補offsetはMidまたはL+R energyから決定。

左右とも同じanalysis positionでresetする。

各channelのanalysis phaseは各channel自身の値を使う。

その後Phase 4 Stereo Coherenceを適用する。

---

## 14. Low path

Low 8192 pathには初版ではPVSOLA resetを入れない。

Bass安定性を壊さないため。

Mid 4096 pathだけで評価する。

---

## 15. Test — sustained vowel synthetic

F0 + harmonic stack + formant envelope。

Phase 5.3
Phase 7

比較。

0.75
0.50

特に0.50を重視。

---

## 16. Test — real Female Vocal

持続母音の多い区間を最低3箇所選ぶ。

Phase 5.3
Phase 7

AB。

---

## 17. Test — real Male Vocal

同様。

特に、

- sustained vowel
- vibrato
- breathy vowel

を含む区間。

---

## 18. Negative tests

以下でartifactが増えないこと：

- snare
- cymbal
- distorted guitar
- dense full mix
- noise
- reverb tail

---

## 19. Resync diagnostics

CSV：

frame
inputSample
scheduledResync
resyncApplied
searchOffsetSamples
correlation
tonality
transientSuppressed

を保存する。

---

## 20. Metrics

最低以下：

resync count/sec

平均search offset

平均correlation

resync skip rate

transient周辺のresync数

を報告。

---

## 21. Vocal modulation metrics

Phase 6で使用した、

- harmonic magnitude frame variation
- spectral envelope frame variation
- centroid variation

も再計測する。

ただし採用判断は聴感優先。

---

## 22. Click / discontinuity detection

resync位置の前後について、

sample derivative
short-term RMS
spectral discontinuity

を測定。

resetに由来するclickを検出する。

---

## 23. Interval study

以下を比較：

80 ms
120 ms
160 ms

必要なら240 msも追加。

期待：

短すぎる
→ rough / reset artifact

長すぎる
→ watery artifactが戻る

最適点を探す。

---

## 24. Search range study

±5 ms
±10 ms
±15 ms

を比較してよい。

ただし全組合せを大量探索しすぎない。

まず：

120 ms interval
±10 ms

を基準にする。

---

## 25. AB output

Female Vocal:
Phase 5.3 / Phase 7
0.75 / 0.50

Male Vocal:
Phase 5.3 / Phase 7
0.75 / 0.50

Mix:
Phase 5.3 / Phase 7
0.75 / 0.50

同一区間・同一gain。

---

## 26. Success criteria

Phase 7採用条件：

- Vocal watery/phasy感が聴感で明確に減る
- vowel presenceが改善する
- vibratoを壊さない
- transient clickを増やさない
- stereo centerを壊さない
- Bass stabilityを壊さない
- dense Mixでroughnessを増やさない

数値だけで採用しない。

---

## 27. Regression

PVSOLA OFF：

Phase 5.3 Highと完全一致。

Phase 6 Partial TrackingはOFFで比較。

---

## 28. CPU / memory

Phase 5.3 streaming構造を維持。

correlation search用bufferを事前確保。

frame loopでallocationしない。

iPhone候補なので過剰な検索量は避ける。

---

## 29. Report

以下を報告：

- resync interval
- search range
- correlation threshold
- tonality gate
- resync count/sec
- average correlation
- average search offset
- skipped resets
- vocal modulation metrics
- stereo metrics
- click/discontinuity metrics
- CPU/RSS
- Phase 5.3 vs Phase 7 ABで確認すべき点
- 残るartifact

Phase 7完了後は停止。

Pitch Shift、Swift、real-time playbackには進まない。