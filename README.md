# TimeStretchLab

音程を保った速度変更を研究する、macOS向けC++20のデジタル音声処理（DSP）・再生エンジンです。Apple Accelerateによる音声合成、オフラインWAV生成、AVAudioEngineによる実機再生を扱います。DSP内部はチャンネルごとに分けたfloat32サンプルを使用します。

## 現在の開発状況：Phase 54

同一音源のトランジェント解析をメモリ上で再利用し、Stop→Play/EOS→Playの全曲再解析を省きます。Candidate/Baselineの0.40〜2.00倍速へ原曲座標の非同期シークAPIを追加しました。位相・OLA・FIRを先頭から正確に再構築し、全曲の伸縮済みPCMをディスクへキャッシュしません。深いシークの待ち時間と高負荷の制限は残ります。

利用方法は [Phase 54 API](docs/PHASE54_SEEK_API.md)、実測と回帰は [Phase 54 REPORT](results/phase54/REPORT.md)。アプリ本体 **Merodoa** は別リポジトリで、[引き継ぎ仕様](docs/APP_INTEGRATION_HANDOFF.md) に従ってsubmoduleを新しい完成SHAへ更新します。`phase53-handoff` タグは既存233c773の切戻し先として維持します。前段の [Phase 53](results/phase53/REPORT.md) と [検証修正](results/phase53_post_handoff/REPORT.md) の結果も保持しています。

## Phase 52で統合した再生エンジン

**0.40〜2.00倍速の開発版再生エンジンを、アプリから使えるライブラリ/APIとして統合しました。** 再生、速度変更、一時停止・再開、停止・再起動、EOS（音源末尾までの排出）、出力装置変更時の安全停止に対応します。GUIはまだありません。

音質の基準は **Phase 5.3 Experimental 3500 Hz** です。凍結済みオフラインDSP、既存Golden（品質回帰用の参照WAV）、Phase 30/36のプレイヤー、Phase 18/19のキャッシュ・シークは保持しています。Candidateは開発版の暫定標準であり、一般公開向けの実時間安定性を保証したものではありません。

| 設定 | Candidate（開発版の暫定標準） | Baseline（比較・切戻し用） |
| --- | --- | --- |
| 速度範囲 | 0.40〜2.00、小数6桁 | 同左 |
| 共通合成コア | Experimental 3500、Phase 37高速方式B、Phase 42 safe-density | 同左 |
| TimeMap（入力と出力の時間対応） | Phase 40方式C + Phase 50 L1 + Phase 51 L2 | Phase 40方式C、L1/L2無効 |
| FIFO容量 / 先行上限 / 生成ブロック | 16,384 / 16,384 / 2,048フレーム | 16,384 / 12,288 / 2,048フレーム |
| ワーカー優先度（QoS） | 継承 | 継承 |
| 変更中の速度要求 | 最新1件を保持し、古い保留要求を置換 | 同左 |

FIFOは未再生音声を先入れ先出しするバッファです。L1は変更禁止境界の精密化、L2は安全区間での出力時間に基づくランプ進捗、safe-densityは窓重みと将来の合成ホップに基づく解析密度の安全判定です。0.40以上0.50未満では半解析ホップを使い、通常密度へ戻す時点も安全条件で判断します。1.00倍速も位相ボコーダーで合成し、入力をそのまま通すunity bypassとは区別します。

詳しい結果は [Phase 52 REPORT](results/phase52/REPORT.md)、API・状態遷移・アプリへのリンク方法は [再生エンジンAPI](docs/PHASE52_PLAYBACK_API.md) を参照してください。

## ビルドと通常の回帰テスト

必要な環境はmacOS、C++20とObjective-C++に対応するAppleの開発ツール、CMake 3.21以上、検証スクリプト用のPython 3です。現在のビルドはApple Accelerate、AVFoundation、Foundation、CoreAudioを使用します。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j 3
ctest --test-dir build --output-on-failure
```

通常のCTestはDSP・PCM・TimeMap・状態管理・障害検出の回帰を対象とします。OSのスレッド起床時刻に依存する期限試験は、次の明示的なスイートで実行します。他のDSP試験や実機再生と同時実行しないでください。

```sh
cmake -S . -B build -DTIMESTRETCH_ENABLE_REALTIME_TESTS=ON
ctest --test-dir build -L realtime --output-on-failure
cmake -S . -B build -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
```

`phase44_quality_gate` と `phase45_deadline_integrity` の名前・閾値・FAIL/INVALID判定は維持しています。模擬消費側が大きく遅刻した試験は実時間PASSにしません。音声供給、時刻計測、PCM一致の判定も別々に扱います。

## macOSでの再生と速度操作

自分の入力WAVを用意して実行します。入力はmono/stereo、44.1/48 kHz、PCM int16またはIEEE float32です。セッション中にファイルを変更・差し替えないでください。

```sh
# Candidateで0.50倍速の有音再生。保存先は試行ごとに新しくする。
./build/playback_demo input.wav results/playback_demo/run_001 candidate 0.50

# 同じ合成コアのBaselineで比較する。
./build/playback_demo input.wav results/playback_demo/run_002 baseline 0.50
```

速度変更・pause/resumeを試す場合は、十分な長さの入力（例：20秒以上）と次の `actions.csv` を用意します。

```csv
seconds,action,value
1,speed,2.00
3,speed,0.40
5,pause,0
5.25,resume,0
```

```sh
./build/playback_demo input.wav results/playback_demo/run_003 candidate 0.40 --actions actions.csv
```

操作時刻は再生開始からの壁時計時間で、pause中も進みます。この例は5.00〜5.25秒に意図的な一時停止を含みます。速度変更中は実行中の計画を維持し、最新の保留要求だけを置換するLatest-Wins制御を使います。安全区間不足によるRejectedも結果へ記録します。

再生ゲインは共通0.5で、AVAudioEngineのmixerに適用します。無加工のDSPサンプルへ焼き込みません。`--silent` は出力ゲイン0、`--offline` は固定速度の非実時間WAV生成です（`--actions`との併用は不可）。CLIは結果を `summary.txt`、操作・計画・コールバック等のCSVへ保存し、保存済みsummaryを上書きしません。

## アプリ向けAPIと実時間処理

| ライブラリ | 役割 |
| --- | --- |
| `playback_engine` / `PlaybackEngine` | C++の再生ライフサイクル、速度要求、状態・位置・診断、FIFO消費 |
| `macos_playback_engine` / `MacPlaybackEngine` | AVAudioEngine、出力装置、再生ゲイン、安全停止を扱うアダプター |

`prepare(input, config)`、`play()`、`pause()`、`resume()`、`stop()`、`setSpeed(speed)` を公開します。`getStateSnapshot()`、`getCurrentPlaybackPosition()`、`getPlaybackDiagnostics()` で状態・位置・不足を取得できます。要求速度、適用済み目標速度、実行中の変更、保留要求を別々に公開し、計画適用を即時の可聴変化とは扱いません。

Candidate/Baselineは型付きの `Configuration::candidate()` / `baseline()` で選びます。アプリ経路は研究CLIの環境変数へ依存しません。方式の切替はstop後のprepareで行います。利用例とCMakeのリンク設定は [API文書](docs/PHASE52_PLAYBACK_API.md) にあります。

ファイル解析・DSPワーカー・オーディオ出力は分離しています。音声コールバックは事前確保FIFOの読取り、不足分のゼロ埋め、事前確保領域への軽量計測だけを行い、DSP・ファイルI/O・動的確保・ブロッキングmutex・TimeMap計画・ログ書込みを行いません。制御APIはアプリの制御・作業キューから呼んでください。診断OFFでもアンダーラン（供給不足）の件数とフレーム数は保持します。

pause/resumeは未再生FIFOとDSP状態を保持して継続します。stop/EOS後のplayは最新要求速度で先頭から再初期化します。出力装置変更では安全停止し、ユーザー操作で形式を再取得します。**停止位置からの再開・シークは、この新APIでは未対応です。**

## 検証結果と残る制限

Phase 52の実装コミット `65a8759` に記録した結果です。条件と失敗試行を含む詳細は [REPORT](results/phase52/REPORT.md) にあります。

- Golden 25/25バイト一致、独立固定速度mono/stereo参照12/12一致。
- 最終の通常CTest 70/70成功、別のOS期限スイート2/2成功。
- 通常実機試行62件中61件で音声・計測・PCM照合PASS。旧停止試行1件は部分PCMハッシュ未計測でPASSに含めません。
- 高CPU負荷のMIX・Drums各3分入力はEOS、PCM一致、供給不足0、コールバック期限超過0。各1回で、入力は既存短区間の反復です。
- 故意の450msワーカー停止2件では各5,120フレームの不足を検出し、音声FAILとしました。
- 最終EOSガード試行は機能確認成功・不足0でしたが、起動時host/sample時刻不連続で計測FAILです。原因は未特定です。

新アダプターの5/10分試験、物理出力装置の変更、広範な高負荷反復は未実施です。OSによる長いワーカー停止への耐性は保証していません。0.40→2.00の適用開始座標の推定提示遅延はMIX約1.63秒、Drums約1.40秒で、操作応答は継続課題です。音響ループバックによる可聴時刻の実測ではありません。

0.40倍速の多少の水っぽさは既知の制限として保持します。0.25倍速は将来の研究対象です。シーク・キャッシュとの新API接続、Swift/Objective-C用UIブリッジ、iOS/iPadOSアダプターは未実装です。

## 音質基準・Golden・保管

[正式音質基準](PHASE12_QUALITY_BASELINE.md) はLow 8192/2048、Mid 4096/1024、High 1024/256、LP250/LP3500、位相ロック・過渡音処理・適応TimeMap・精密アンカー・ステレオ整合ONです。新エンジンでは低速側の解析密度と高速側のTimeMapを研究成果に従って切り替えます。

Phase 12の0.50/0.75倍速10本とPhase 28の0.60/0.70/0.80倍速15本を、厳密回帰の25本として維持しています。Phase 12には別途1.00倍速のunity bypass参照もあります。入力・出力SHA-256と条件は [Phase 12 manifest](results/phase12/golden/manifest.csv)、[Phase 28 manifest](results/phase28/golden/manifest.csv) を参照してください。

WAVと著作権上公開できない入力音源はGit対象外です。リポジトリでは仕様・生成スクリプト・ハッシュ付きmanifest・検証結果を管理します。私有音源がない環境では [音源保管設計](PHASE12_ARTIFACT_CUSTODY.md) に従って入力・環境を復元してください。[Phase 13の保管レポート](results/phase13/CUSTODY_REPORT.md) にPhase 12の暗号化二次保管・USBからの復元試験を記録しています。

```sh
# ローカルの凍結入力・Goldenが必要。欠損をPASS扱いしない。
python3 -B scripts/phase52_validate.py golden
python3 -B scripts/phase52_validate.py audit
```

## 研究履歴と既存オフラインCLI

以下は各段階の研究機能と再現手順です。既存CLIの既定値は互換性のため維持しており、開発版Candidateの選択とは別です。Experimental 3500の凍結オフライン基準を生成するには、品質モードに加えて採用済み機能を明示します。

```sh
./build/timestretch input.wav output.wav --speed 0.50 \
  --quality experimental --low-crossover-hz 250 --high-crossover-hz 3500 \
  --phase-locking on --transient on --adaptive-time-map on \
  --precise-anchoring on --stereo-coherence on \
  --chunked on --chunk-size 16384
```

出力は入力と同じサンプルレート・チャンネル数のIEEE float32 WAVです。raw出力にはサンプルピーク1.0超えがあり得るため、試聴用ゲインは別段階で管理します。旧 `timestretch` の速度上限は1.25で、開発版再生APIの0.40〜2.00とは別の制限です。旧オフラインCLIの1.00倍速はunity bypassです。

Phase 13の固定速度ストリーミングとGolden波形照合は [Phase 13レポート](results/phase13/REPORT.md)、凍結時のリアルタイム化設計は [Phase 12計画](PHASE12_REALTIME_PLAN.md) にあります。

プロジェクト初期の設計方針は [DESIGN.md](DESIGN.md) を参照してください。
ピークに基づく位相固定の要件は [PHASE2_REQUIREMENTS.md](PHASE2_REQUIREMENTS.md) に保存しています。
過渡音検出と位相リセットの要件は [PHASE3_REQUIREMENTS.md](PHASE3_REQUIREMENTS.md) に保存しています。
イベント統合と局所時間配置の要件は [PHASE35_REQUIREMENTS.md](PHASE35_REQUIREMENTS.md) に保存しています。
アタック領域保護と帯域別位相リセットの要件は [PHASE36_REQUIREMENTS.md](PHASE36_REQUIREMENTS.md) に保存しています。
ステレオ位相の一貫性に関する要件は [PHASE4_REQUIREMENTS.md](PHASE4_REQUIREMENTS.md) に保存しています。
複数解像度処理の要件は [PHASE5_REQUIREMENTS.md](PHASE5_REQUIREMENTS.md) に保存しています。
継続的な調波ピーク追跡の要件は [PHASE6_REQUIREMENTS.md](PHASE6_REQUIREMENTS.md) に保存しています。

初期の評価CLIは次のコマンドで実行できます。個別の成果物は対応するPhaseのレポートを参照してください。

```sh
./build/timestretch input.wav output.wav --speed 0.5
./build/phase1_tests results/phase1
./build/phase1_validation
./build/phase2_tests results/phase1 results/phase2
./build/phase3_tests results/phase2 results/phase3/artificial
./build/phase35_tests results/phase35/artificial
./build/phase36_tests results/phase36/artificial
./build/phase37_tests results/phase37/artificial
./build/phase4_tests
./build/phase5_tests
```

既定の FFT は 4096 点、解析ホップは 1024 サンプル。合成ホップは `analysisHop / speed` で、フレーム位置を絶対座標から丸めるため、非整数ホップでも累積丸め誤差を避けます。周期 Hann 窓を解析と合成に適用し、重ね合わせた各サンプルを窓の二乗和で割ります。speed=1.0 は入力をそのまま通す経路です。

`--fft-size`、`--analysis-hop` で変更できます。`--phase-locking on` で Phase 2 のピーク位相固定を使い、`off`（既定）で Phase 1 と同じ処理を使います。`--transient on` で Phase 3 の過渡検出を使います。

`TimeStretchEngine` は構成と処理の窓口、`STFT` は窓と FFT、`PhaseVocoder` は各チャンネルの位相状態、`PhaseLocker` はピーク検出・所有領域・相対位相の固定、`OverlapAdd` は復元と振幅補正を担当します。後続 Phase ではこれらの処理段階を拡張できます。

実録音の Phase 1/2 比較は、`bash scripts/phase2_real_ab.sh mix.wav bass.wav guitar.wav piano.wav vocal.wav drums.wav` で実行できます。0.75x/0.50x の ON/OFF を同じ条件で書き出し、`results/phase2/real/stems/` に一覧と処理時間を記録します。4 素材の旧形式の呼び出しにも対応しています。

Phase 3 は `--transient on` で、オフラインの過渡検出と左右共通タイミングの位相リセットを追加します。`--debug-csv directory` で `transients.csv` にスペクトル変化量、閾値、強度、検出・リセット位置を記録します。実録音の Phase 2/3 比較は `bash scripts/phase3_real_ab.sh mix.wav bass.wav guitar.wav piano.wav vocal.wav drums.wav` で生成できます。

Phase 3.5 は `--transient on --adaptive-time-map on` で有効になります。過渡候補をイベントにまとめ、イベント前後の局所伸縮率を滑らかに 1.0 へ近づけます。イベント位置を元のテンポ上に保ちながら、間の持続区間で時間を補償します。左右でイベントと時間配置を共有します。`--debug-csv directory` で `event_map.csv` にイベント ID、局所伸縮率、合成開始位置を記録します。Mix/Bass の 3 方式比較は `bash scripts/phase35_real_ab.sh mix.wav bass.wav` で再生成できます。測定結果と制約は [Phase 3.5 レポート](results/phase35/PHASE3_5_REPORT.md) に記載しています。

Phase 3.6 は `--transient on --adaptive-time-map on --selective-reset on` で有効になります。過渡イベントの開始から早い減衰までを保護し、位相リセットをスペクトル上昇の強い bin に絞ります。疎なクリックは入力サンプル位置を使ってイベント時刻を補正します。`--debug-csv directory` の `events.csv` に領域境界と時刻誤差を記録します。Mix/Bass の Phase 2／3.5／3.6 比較は `bash scripts/phase36_real_ab.sh mix.wav bass.wav` で再生成できます。**Phase 3.6 は実験的機能です。Bass のステレオ幅と人工ドラムの 0.50x アタック幅に未解決の退行があるため、既定では無効です。** 数値は [Phase 3.6 レポート](results/phase36/PHASE3_6_REPORT.md) を参照してください。

Phase 3.7 は `--transient on --adaptive-time-map on --precise-anchoring on` で有効になります。音質処理は Phase 3.5 と同じです。孤立した鋭いイベントだけ、入力サンプルの実際の位置を使って時間配置を補正します。曖昧なイベントは Phase 3.5 と同じフレーム位置のままです。`--selective-reset on` との併用はできません。`--debug-csv directory` の `anchors.csv` に補正判定を記録します。Mix/Bass の比較は `bash scripts/phase37_real_ab.sh mix.wav bass.wav` で再生成できます。検証結果は [Phase 3.7 レポート](results/phase37/PHASE3_7_REPORT.md) にあります。

Phase 4 は Phase 3.7 の引数に `--stereo-coherence on` を加えて有効になります。左右の合成位相を入力の左右位相差へ向けて補正します。左右の振幅は変えず、共同のピーク領域を使います。`--coherence-strength` と `--low-frequency-coherence` は 0〜1 の強さです。モノラルでは処理しません。既定は OFF です。`--debug-csv directory` の `stereo_coherence.csv` に周波数ごとの補正量を記録します。全長の Mix/Bass 比較は `bash scripts/phase4_real_ab.sh mix.wav bass.wav` で生成し、`bash scripts/phase4_analyze.sh` で測定できます。結果は [Phase 4 レポート](results/phase4/REPORT.md) を参照してください。

Phase 5 の歴史的な3経路構成は `--quality experimental` で再現できます。8192/2048、4096/1024、1024/256 の3つの FFT/解析ホップで処理し、中解像度で決定したイベントと出力時間配置を `TimeMap` で共有します。全長Mix/Bass比較は `bash scripts/phase5_real_ab.sh mix.wav bass.wav`、測定は `bash scripts/phase5_analyze.sh`。男女ボーカルの30秒比較は `bash scripts/phase5_vocal_ab.sh input.wav output_dir label` で行えます。結果は [Phase 5 レポート](results/phase5/REPORT.md) を参照してください。

Phase 5.1 の逐次処理は `--chunked on` で有効になります。既定の書き出し単位は 16384 サンプルで、`--chunk-size 8192..65536` で変更できます。WAV の読み込み、重ね合わせ、周波数分割、書き出しを有限長の作業領域で行います。歴史的な3経路での長さ別メモリ測定は `bash scripts/phase51_memory.sh mix.wav bass.wav metrics.txt` で再実行できます。結果は [Phase 5.1 レポート](results/phase51/PHASE5_1_REPORT.md) を参照してください。

### Phase 5.2 比較モード

逐次処理の `--ablation a|b|c` で、同じ中解像度の過渡検出と時間配置を使う3構成を比較できます。`--chunked on` と併用します。A は 4096/1024 のみ、B は低 8192/2048 と中 4096/1024 を `mid + LP250(low-mid)` で合成、C は旧 Phase 5.1 の3経路です。現在は `--ablation` を省略して `--multiresolution on` にすると B を選びます。

比較手順と計測結果は [Phase 5.2 レポート](results/phase52/PHASE5_2_REPORT.md) を参照してください。

### Phase 5.3 品質モード

`--quality normal|high|experimental` を指定できます。Normal は中4096/1024のみ、High は低8192/2048＋中4096/1024で LP250 により合成、Experimental は旧3経路です。`--multiresolution on` の既定は High に変更しました。品質モードを指定しない `--multiresolution off` は Normal、`--multiresolution on` は High です。逐次処理でも全長処理でも同じ品質モードを選べます。比較実験用に `--low-crossover-hz 200|250|300` を指定できますが、既定は250 Hzのままです。[Phase 5.3 レポート](results/phase53/PHASE5_3_REPORT.md) に回帰・音質・負荷の結果を記録しています。

### Phase 6 部分音ピーク追跡

`--phase-locking on --partial-tracking on` で中4096/1024経路の部分音ピーク追跡を試せます。左右共通のピーク地図とtrack IDを使い、各チャンネルの位相を継続します。低8192/2048経路、過渡処理、TimeMap、クロスオーバーは従来どおりです。既定は OFF で、現在の音質基準・Candidateへ統合していません。[Phase 6 レポート](results/phase6/REPORT.md) に比較結果を記録しています。

### Phase 7 周期的な位相再同期の試作

`--phase-locking on --transient on --adaptive-time-map on --precise-anchoring on --stereo-coherence on --pvsola on --chunked on --quality high` で Mid 経路の PVSOLA 型再同期を試せます。既定は OFF で、Phase 6 の `--partial-tracking on` とは併用しません。既定の再同期間隔は 120 ms、入力探索範囲は ±10 ms、波形相関の下限は 0.65 です。`--pvsola-interval-ms`、`--pvsola-search-ms`、`--pvsola-min-correlation` で変更できます。`--debug-csv directory` は `pvsola_resync.csv` を保存します。試作版の ON 処理は逐次処理専用です。出力時間配置と Low 経路は Phase 5.3 のままです。実 Vocal の指標には悪化もあり、採用・既定化はしていません。[Phase 7 レポート](results/phase7/REPORT.md) に A/B と測定結果を記録しています。
