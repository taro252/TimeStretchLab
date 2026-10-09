# Experimental 3500 ゴールデンWAV

## 保存物

`input/`に5種類の既存比較区間をコピーし、`raw/`に速度0.50／0.75／1.00の計15本を保存した。すべてDSP本来の**無加工float WAV**で、音量一致版ではない。全長SHA-256、入力SHA-256、フレーム数、ピーク、RMS、統合LUFS、true peak、実行時間、常駐メモリ、イベント数は [`manifest.csv`](manifest.csv) に記録した。実行条件は [`baseline.json`](baseline.json)、再生成・整合性検証は [`scripts/phase12_golden.py`](../../../scripts/phase12_golden.py)。再生時のクリッピングを避けるため、DSP参照とは別に `audition/` に−18 LUFSを目標とした**固定ゲインのみ**の試聴コピーを置き、適用ゲインと別ハッシュを [`audition_manifest.csv`](audition_manifest.csv) に記録した。

WAVはGit管理外でローカルに保持している。非公開の二次保管と復元試験の条件は [`PHASE12_ARTIFACT_CUSTODY.md`](../../../PHASE12_ARTIFACT_CUSTODY.md) に定めた。2026-10-10に暗号化USBコピーからの復元試験を完了した。検証結果は [Phase 13保管レポート](../../phase13/CUSTODY_REPORT.md) を参照。

| 音源 | 既存区間 | 入力長 | サンプルレート |
| --- | --- | ---: | ---: |
| MIX | Phase 5.3/5.2 real比較の90〜135秒 | 45秒 | 44,100 Hz |
| Vocal（女性） | Phase 5.3/5.2 real比較の90〜135秒 | 45秒 | 48,000 Hz |
| Bass | Phase 5.3/5.2 real比較の90〜135秒 | 45秒 | 48,000 Hz |
| Drums | Phase 10.1 real比較の30〜40秒 | 10秒 | 48,000 Hz |
| Guitar | Phase 10.1 real比較の30〜40秒 | 10秒 | 48,000 Hz |

## 測定結果

表のハッシュは見やすさのため先頭12桁のみ。完全値はmanifestを参照。速度1.00は3解像度処理を通らないunity bypass。

0.50倍の比較用：[MIX raw](raw/mix_050.wav)／[MIX 試聴](audition/mix_050.wav)、[Vocal raw](raw/vocal_050.wav)／[Vocal 試聴](audition/vocal_050.wav)、[Bass raw](raw/bass_050.wav)／[Bass 試聴](audition/bass_050.wav)、[Drums raw](raw/drums_050.wav)／[Drums 試聴](audition/drums_050.wav)、[Guitar raw](raw/guitar_050.wav)／[Guitar 試聴](audition/guitar_050.wav)。0.75倍・1.00倍も同じ命名規則で保存した。

| 音源 | 速度 | 出力フレーム | サンプルピーク | LUFS | SHA-256先頭12桁 | 処理時間 |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| MIX | 0.50 | 3,969,000 | 1.426309 | −10.35 | a729f3764c7a | 7.01秒 |
| MIX | 0.75 | 2,646,000 | 1.365266 | −10.22 | ef1ed78c06df | 6.53秒 |
| MIX | 1.00 | 1,984,500 | 1.000000 | −9.69 | 50b6e4edae59 | 0.10秒 |
| Vocal | 0.50 | 4,320,000 | 0.988933 | −12.33 | 44c33a2e1edb | 7.34秒 |
| Vocal | 0.75 | 2,880,000 | 1.018444 | −12.46 | 109816b81df9 | 6.96秒 |
| Vocal | 1.00 | 2,160,000 | 0.923431 | −12.28 | 56ad66b7a5be | 0.10秒 |
| Bass | 0.50 | 4,320,000 | 0.878249 | −17.23 | 70ba7adafe87 | 6.05秒 |
| Bass | 0.75 | 2,880,000 | 0.973402 | −17.28 | 10558461001d | 5.79秒 |
| Bass | 1.00 | 2,160,000 | 0.989410 | −17.23 | 382955b5e0a3 | 0.12秒 |
| Drums | 0.50 | 960,000 | 1.043968 | −16.41 | 7cd350cee36a | 1.58秒 |
| Drums | 0.75 | 640,000 | 1.051213 | −16.31 | bfa18f2ab42d | 1.52秒 |
| Drums | 1.00 | 480,000 | 1.000000 | −15.33 | d77f30cdc1b8 | 0.02秒 |
| Guitar | 0.50 | 960,000 | 0.839131 | −16.36 | 871653d181b5 | 1.47秒 |
| Guitar | 0.75 | 640,000 | 0.945484 | −16.22 | 0052694fab45 | 1.41秒 |
| Guitar | 1.00 | 480,000 | 0.958374 | −16.01 | 3da0902bd133 | 0.02秒 |

全15本の長さは `round(inputFrames / speed)` に一致し、NaN/Infはなかった。MIX／Vocal／Bassの0.50・0.75倍、計6本は、同じ入力を使った保存済みPhase 5.2 C（現Experimental 3500）と**WAV全体がバイト単位で一致**した。1.00倍の5本はそれぞれ入力との最大サンプル差0だった。`python3 scripts/phase12_golden.py` の再検証は15本と入力5本のハッシュ一致を確認した。

実音源15本では精密アンカーの採用数が0で、この機能を通る波形回帰にはならない。補助参照 [`anchor_click_050.wav`](anchor_click_050.wav) は既存の48 kHz・stereo人工クリック列10秒を0.50倍にした20秒WAVで、19イベントすべてに精密アンカーが適用された。イベント・出力ハッシュ、長さ、ピーク、LUFSは [`anchor_diagnostic.json`](anchor_diagnostic.json) に固定し、[`scripts/phase12_anchor_diagnostic.py`](../../../scripts/phase12_anchor_diagnostic.py) で検証する。これは実音源の聴感評価とは別の機能回帰である。

MIXやDrumsなど、一部raw出力のサンプルピークは1を超える。float WAVのデータはクリップしていないが、一般的な再生系が整数PCMへ変換する際にはクリップし得る。**ゴールデンWAVへリミッターやゲインを適用しない。** `audition/` は聴感比較専用で、DSP回帰判定に用いない。

試聴コピー15本の統合ラウドネスは−18.01〜−17.99 LUFS、最大サンプルピーク0.9055、最大true peak −0.86 dBTP。元rawと異なるハッシュと固定ゲインを [`audition_manifest.csv`](audition_manifest.csv) に明記した。`python3 scripts/phase12_audition.py` で15本の試聴コピーを再検証できる。

0.50倍の45秒素材で処理時間は約6.05〜7.34秒、最大常駐メモリは約17.1 MBだった。これらはMac上のオフラインCLI計測であり、iPhoneのオーディオコールバック期限を保証しない。

`cmake --build build -j8` 成功。`ctest --test-dir build --output-on-failure` は **21/21成功、失敗0件**（152.04秒）。今回DSP本体には変更を加えていない。
