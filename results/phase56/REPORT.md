# Phase 56：継続状態を持つ増分解析と完全一致検証

## 判定

**A：解析と要求した固定速度TimeMapについて完全成立。Phase 57の増分DSP合成検証へ進める。**

入力を追加して状態を引き継ぎ、確定済み検出フレーム、閉鎖event、精密anchor、TimeMapを順に公開する内部実験エンジンを実装した。**全161速度対応の最終Release実行ファイルで78入力×7チャンク条件＝546セッション、中間の公開データと真のEOS後の全解析結果が固定参照とビット一致**した。各セッションで**0.40〜2.00倍を0.01刻みの全161速度**を検証し、固定mapの最終全node比較は**87,906件**。チャンクごとに先頭から全解析を再実行していない。

このAはPhase56の範囲に限る。PCM継続合成、位相/OLA/FIRの部分解析接続、実時間DSP競合、再生中の速度変更、製品PlaybackEngine/Merodoaへの統合、PCM開始時間の短縮は未実装・未証明である。Phase55のBやPhase54の保存済み実時間FAILを上書きしていない。

## 1. 基準・保護・独立参照

- 開始時：`main`、HEAD `14d30be6a7a2dc164eead5a5d747c60fba806b49`、作業ツリーはクリーン。Phase55の依存関係/設計/REPORT/VERDICTと、Phase53/54の品質・Golden・引継ぎ契約を確認した。
- 既存のPhase13、STFT、TransientDetector、EventMap、アンカー、Phase37/39、再生API、位相・OLA・FIR、L1/L2/safe-density、ゲインを変更していない。新しいlibraryは実験実行ファイル/テストだけがリンクする。
- 実装前に既存ライブラリで参照実行ファイルをビルドし、`build/phase56_frozen/reference`へ固定した。SHA-256：`d60cc4b6bcd30e94fcb6931122f71d50c62a669447151b3277a4ea9e2c4a4aa4`。バイナリSHAは`frozen_reference_sha256.txt`にも保存。
- 参照データは各フィールドのIEEE生ビット、整数、flagを明示的に並べ、構造体paddingや十進文字列へ依存しない。参照ファイルSHA、入力SHA、oracle/checkerのバイナリSHAを各ケースの`reference_manifest.json`に保存する。
- 161速度への拡張前に、未変更の既存ライブラリだけで全161速度を生成する`build/phase56_frozen/reference_percent`を固定した。SHA-256：`8a7a7ee9e2f9760b79682feab5c08fe794de00512eb4163e1d9d79abe2d8dd2a`。直列化v2は版と速度整数表を追加。性能用2入力で共通7列と全解析フィールドを旧v1形式へ復元し、実装前の旧バイナリと生バイト一致（`percent_frozen_equivalence/summary.json`）。追加154列の算術も未変更Phase39のまま。変更後の新旧コード同士だけを正解の根拠にしていない。
- 最終監査：既存追跡ファイル **6,770/6,770一致**、既存Golden WAVファイル全体SHA **30/30一致**、`phase53-handoff`タグも固定値のまま（`protected_percent_final.json`）。既存CMakeには新規target/testの追加だけを行った。

## 2. 実装と変更ファイル

| ファイル | 役割 |
| --- | --- |
| `src/prototype/Phase56ProgressiveAnalysis.h/.cpp` | 増分STFT、分類、event閉鎖、暫定/確定anchor、MapPrefixBuilder、session API |
| `src/prototype/Phase56ImmutableSeries.h` | 不変ページと索引、共有snapshot、所有容量・コピー量の計数と上限 |
| `src/prototype/Phase56PinnedWav.h` | FD保持・同一性確認・有限サイズread・失敗伝達の実験用入力adapter |
| `src/prototype/Phase56ReferenceData.h` / `Phase56Reference.cpp` | 既存一回解析の固定参照、全フィールドの直列化、性能用oracle |
| `src/prototype/Phase56Check.cpp` | 中間・最終・保持snapshotのビット比較、処理回数、全結果SHA、進行/時間/コピー量のCSV |
| `tests/Phase56Tests.cpp` / `Phase56FixedModes.cpp` / `Phase56Smoke.py` | 状態・異常系・並行読取・preset・固定参照smoke |
| `scripts/phase56_*.py` | 素材/チャンク行列、性能、識別コスト、資産監査、最終集計 |
| `CMakeLists.txt` | 新規実験library/executableと専用CTestの追加 |

設計は[増分解析仕様](../../docs/PHASE56_INCREMENTAL_ANALYSIS.md)、Phase57の契約は[DSP引継ぎ](../../docs/PHASE56_DSP_HANDOFF.md)。

内部APIは`appendInput(generation, offset, planarPCM, count)`、`advanceAnalysis()`、`getSnapshot()`、`finishInput(generation)`、`cancel()`、`failInput(generation,error)`、`statistics()`。1 producerと複数snapshot readerを想定する。終了commit直前のcancelを再現するテストhookも用意し、通常は使用しない。

世代、受信サンプル数、特徴量数、検出確定数、閉鎖event/anchor数、map公開node数、正常EOS/cancel/errorを分けた。型上は共有所有権付きの読み取り専用snapshotだけを渡す。速度は100万倍の整数で指定する。既定の全161速度に加え、必要な速度だけを要求できる。空の速度列なら解析だけ。要求順を保持し、未要求の速度取得は例外。範囲外・重複・同時161列超過は初期化時に拒否する。mapが既存でも成立しない速度のために、解析自体を使えなくしない。

## 3. 継続状態と不変性

STFTは4,096/1,024の絶対格子、左右2,048padding、前回logスペクトルとenergyを保持する。既存pushMagnitudesを利用し、旧finalizeは増分中に一度も呼ばない。閾値・局所最大・cooldown・lookbackの算術を実験用分類器で同じ順に実装した。未来のresetで変わり得る末尾は公開しない。

イベントは既存の4/12フレームとenergyの規則を継続する。open eventは連鎖長で強制閉鎖しない。新しい非統合候補、または直近endから12フレームの候補確定、または真のEOSで閉じる。peakが動くたび、揃っている3,072サンプル窓で既存Locatorを呼び、閉じるまで暫定anchorを保持する。PCM ringは1chあたり8,192サンプルで、長い連鎖の古いpeakのためにPCM全体を残さない。

TimeMapは閉じたpeakの間だけ計算する。伸張側のdouble累積位置を持ち越し、圧縮側の区間始点/終点の丸め直しを維持する。将来eventの左肩が既確定区間に入らないことを距離条件で確認した。末尾区間はEOSまで確定しない。全546セッションでFFT回数が参照フレーム数と等しく、map区間の処理数も参照node数−1と等しいことを実行時に検査した。

snapshotは64要素ページと深さ16の不変索引を共有し、変更ページと索引経路だけを複製する。既定64MiBの所有容量上限を設け、古いsnapshotを保持し続けた場合も無制限に増やさない。上限超過時は事前確保した失敗snapshotを公開する。内部特徴列・座標列は曲長に比例し、既定入力上限は48kHz換算10分。これはeventの長さ上限ではなく、明示的な資源予算である。

## 4. 完全一致行列

主たる最終証拠は**`percent_exact/`**。当初の7速度で通った`exact_release_final/`と`performance_final/`、`REPORT_SEVEN_SPEEDS.md`、`VERDICT_SEVEN_SPEEDS.json`は当時の範囲の証拠として保持する。旧7速度の結果や前段試行を最終件数へ重複加算しない。

| 素材群 | 入力数 | 内容 |
| --- | ---: | --- |
| 短尺全8形式 | 48 | PCM16/Float32 × Mono/Stereo × 44.1/48kHz。各形式で無音、単発、連続impulse、持続音、境界アタック/EOSアタック、event連鎖の6素材。各4秒 |
| 空/極短 | 8 | Float32 Mono 48kHz、0/1/17/1,023/1,024/2,047/2,048/2,049サンプル |
| 長尺全8形式 | 16 | 各形式で3分の過渡音素材、5分の持続音素材。4秒の人工パターン反復であり自然な別楽曲ではない |
| 長いPCM連鎖 | 1 | Float32 Mono 48kHz、5分、4,096サンプル間隔のimpulse。既存参照で約14,066特徴量フレーム・1イベント |
| 既存実音源 | 5 | MIX/Drums/Vocal/Bass/Guitarの既存10秒抜粋。自然な3分/5分の楽曲ではない |

各入力を1/7/8/32/128 Mid相当（1,024/7,168/8,192/32,768/131,072サンプル）、5,003サンプル、不規則列`1,3071,17,8193,1023,131071,7,5003,65535`で処理した。hopに揃わない境界と短い最終チャンクを含む。

全546セッションで次を確認した。

- 新しく公開する検出フレームの全double/floatフィールドを生ビット比較し、flagも完全比較。
- 閉鎖eventのonset/peak/attackEnd/end/strength、anchorのframe/offset/absolute/crest/confidenceを完全比較。
- **0.40, 0.41, …, 1.00, 1.01, …, 2.00の全161速度**の全公開nodeを整数完全比較。Candidate L2/Baseline Cの初期固定mapが同じことも専用CTestで確認。
- 途中のsnapshotを保持し、解析継続後に保持した全フィールドを再比較。後から変更されないことを確認。
- 各append後はisFinal=false。真のEOS後に入力数、active数、検出数、event/anchor数、全node数と全結果SHAを照合。
- **中間だけ、最終だけの成功では合格にしない。** Releaseでも比較関数は動作し、NDEBUGで検証を無効にしていない。

不一致は**0件**。構造体paddingは比較対象にせず、許容誤差・Golden差替え・基準緩和は導入していない。エラー時にはfield、0始まりindex、actual/referenceのビット値をstderrへ出す。

## 5. 安全性・既存で成立しない入力

専用CTestでは以下を検証した。

- 16/128/4,096/16,384フレームの候補連鎖を途中で閉じない。
- 次のfluxで暫定局所最大が覆るケース、実EOSの最後の局所最大。
- 解析中の別スレッドcancel、EOS直前のcancel、完了commit直前のcancel、完了済みEOSへのcancel。
- 世代違い、offsetの隙間、不正サンプル、受信後の一時入力不足、未完成データの破棄。
- producerと別スレッドのsnapshot reader、同一入力の2つのFD/2解析要求の同時実行、古いsnapshot保持。
- 解析中のファイル置換・切詰め・権限失効・読取り失敗。FDと選択パスの同一性を前後確認。
- 所有容量不足と、readerが多数snapshotを保持する場合の容量不足。失敗/cancelを正常EOSにしない。

既存Phase37の失敗も保持した。単発impulseを入力3,001サンプル目に置く例では、peak=1の精密offset=1,977が2.00の最初の圧縮アンカーを負位置へ動かし、既存バイナリは`No monotonic high-speed event interval`で拒否する（`rejections/`）。増分側も要求した速度でこの条件を拒否し、計算途中のnodeを公開しない。

同じ入力でも解析自体は既存Phase13に一致し、空の要求速度列と0.50だけの選択を別途検証した。成立しない速度を黙って近似mapへ置き換えたり、使わない速度の失敗を解析全体の新しい必須制約にしたりしていない。

同一入力の解析を自動的に1 flightへまとめる仕組みは追加していない。複数要求は別session/世代/容量を持ち、独立に一致することを検証した。多数sessionの総CPU・総メモリ予算は次Phaseの管理側の責務となる。

## 6. 性能：全161速度、Release単独実行

最終測定は`percent_performance/`。macOS arm64、Release、`-O3 -DNDEBUG`。旧全曲解析＋161固定mapをA、増分解析＋161map＋snapshotをBとし、同一入力・各条件5回。2入力×7チャンク×5＝70増分実行、全曲側10実行を保存した。全体回帰テスト完了後に単独実行し、他のDSP検証と競合させていない。各回新規プロセス、OSファイルcacheはpurgeしていない。

開始は解析呼出し/Session構築の開始。Bにはチャンク読取とFD同一性確認、copy/publication、計測行の蓄積も含む。中間の全フィールド照合と保持snapshot再検査は時間外にし、終了後に最終全結果のビット・SHAを検査する。A/Bとも結果直列化とSHA計算は時間外。BのRSSには事前に読み込む比較用参照配列も含まれるため、ライブラリだけのRSSではない。

### 290秒MIX反復・PCM16 Stereo 44.1kHz

Aの解析＋161mapはwall中央値 **1,029.828ms**、スレッドCPU中央値 **1,026.253ms**、Peak RSS中央値28.131MB。

既存10秒MIXをPhase55のレシピで反復・PCM16化した入力で、自然な290秒の別楽曲ではない。

| 入力チャンク | B総wall中央値 ms | B総CPU中央値 ms | A比CPU増減 | 最初の確定event / map ms | snapshot Peak MB | 累積snapshotコピー MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 Mid | 2,233.030 | 1,648.907 | +60.67% | 6.498 / 6.498 | 20.106 | 350.321 |
| 7 Mid | 1,152.900 | 1,022.036 | -0.41% | 2.751 / 2.751 | 20.106 | 260.554 |
| 8 Mid | 1,145.110 | 987.839 | -3.74% | 2.986 / 2.986 | 20.106 | 255.772 |
| 32 Mid | 771.079 | 716.551 | -30.18% | 2.104 / 2.104 | 20.106 | 131.803 |
| 128 Mid | 648.866 | 636.671 | -37.96% | 7.030 / 7.030 | 20.106 | 65.076 |
| 不規則 | 773.491 | 695.016 | -32.28% | 8.306 / 8.306 | 20.106 | 90.024 |
| 5,003 sample | 1,544.190 | 1,220.671 | +18.94% | 3.417 / 3.417 | 20.106 | 270.910 |

BのプロセスPeak RSS中央値は条件により84.328〜86.229MB。MBは10⁶bytes。累積コピー量は同時占有量ではない。

### 5分のイベント連鎖・Float32 Mono 48kHz

Aの解析＋161mapはwall中央値 **529.624ms**、スレッドCPU中央値 **523.211ms**、Peak RSS中央値27.705MB。

| 入力チャンク | B総wall中央値 ms | B総CPU中央値 ms | A比CPU増減 | 最初の確定event / map ms | snapshot Peak MB | 累積snapshotコピー MB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 Mid | 1,752.987 | 1,437.576 | +174.76% | 1,752.987 / 1,752.987 | 22.424 | 160.437 |
| 7 Mid | 669.825 | 562.204 | +7.45% | 669.825 / 669.825 | 22.424 | 64.074 |
| 8 Mid | 692.043 | 542.083 | +3.61% | 692.043 / 692.043 | 22.424 | 62.159 |
| 32 Mid | 497.058 | 444.421 | -15.06% | 497.058 / 497.058 | 22.424 | 51.552 |
| 128 Mid | 468.393 | 456.180 | -12.81% | 468.393 / 468.393 | 22.424 | 48.896 |
| 不規則 | 494.930 | 427.340 | -18.32% | 494.930 / 494.930 | 22.424 | 52.203 |
| 5,003 sample | 809.745 | 583.181 | +11.46% | 809.745 / 809.745 | 22.424 | 71.025 |

BのプロセスPeak RSS中央値は条件により74.826〜75.907MB。MBは10⁶bytes。累積コピー量は同時占有量ではない。

全チャンク条件で最初の確定eventと非空map区間が得られるのは**EOSの最終処理完了時**。入力14,400,000フレーム全体が閉鎖待ちとなり、固定時間内の開始保証は成立しない。

最大値・母標準偏差も`percent_performance/statistics.json`に保存した。各チャンクの処理wall/CPU、進行境界、累積コピーと差分、EOS処理行はCSVにある。5回の限定測定であり、一般的な期限保証や統計的な有意差を主張しない。コピー計数はring転送、snapshot本体/ページ/索引の推定で、FFT内部やvector再配置まで含む全プロセスのコピー量ではない。

全161列を持つsnapshotは7列より大きく、公開と保持の費用が増える。検証では全161速度を同時構築した。製品が現在・次の要求速度だけを使う構成は同時列数を減らせるが、速度列の追加・変更と解析共有の管理はPhase57以降で設計する。小チャンクほど通知粒度は細かくなる一方、FD確認・snapshot公開の回数が増える。

### 全内容識別の別コスト

速度数に依存しない既存Phase54のprepare-only測定（`identity_cost/`、同じ290秒入力・5回）は保持した。全内容SHA-256等の識別wall中央値 **24.904ms**、最大25.270ms、母標準偏差0.157ms。解析wall中央値664.946ms、prepare全体690.058ms。これは上の解析＋161mapと処理範囲が異なるため同じ列として比較しない。

**確定mapを早期に得られた時刻から、PCM開始時間や可聴遅延の改善は判断しない。** 製品では全内容識別、DSP初期化、十分な確定領域、位相/OLA/FIRの先読み、既定FIFO先行蓄積、実機callbackが別に必要である。

## 7. ビルド・回帰

- 全161速度対応のRelease全targetビルド成功。全体の決定論的CTest **80/80、474.22秒**（`ctest_percent_deterministic.log`）。既存77項目＋Phase56新規3項目。7速度時の旧79/79ログも保持。
- 全161速度対応のDebugビルド成功。Phase13＋新規3試験 **4/4、5.50秒**（`ctest_percent_debug_final.log`）。同じDebug構成の既存一回解析を参照とし、Release/Debugの構成間一致試験とは区別する。
- 専用試験では全161速度のCandidate L2/Baseline C初期map、解析専用、選択速度・非昇順指定、非単調map拒否、キャンセルcommit境界も確認。
- 従来の製品再生経路のGolden **25/25**：raw float32 PCM SHA・フレーム数一致。既存製品ソースは今回も未変更であり、新方式によるPCM合成試験ではない。保存済みGoldenファイルSHAも30/30一致。
- Phase54の実時間FAILは監査対象として保持。Phase56では新しい解析/DSP競合や実機試験を実施しておらず、今回の解析成功で過去の実時間不合格をPASSへ変更していない。

初期ビルドでは、この環境のlibc++で未対応のatomic共有ポインターを対応するshared_ptr原子操作へ変更し、Darwinのsize_t/uint64_t型差を修正した。161速度追加時の直列化データ省略初期化の警告も明示的な空列初期化で解消した。Release検証実行ファイルは警告修正前後でSHAが同一（`warning_cleanup_binary.json`）。失敗・警告ログは保持し、数値差を許容して通したケースはない。

## 8. 残るリスクとPhase 57への条件

今回の範囲では確定境界の未解決依存はなく、継続状態による解析・固定mapの基盤としてPhase57へ進める。次を引き継ぐ。

- 全161速度を直接計算し、速度間の補間はしない。小数6桁の固定速度指定も受け付け、0.666667の一致と、2.00/0.41/0.99/1.01/0.40の非昇順指定を専用試験で確認した。全小数6桁の網羅ではない。session開始後の速度列追加・変更や速度履歴mapの構築は未実装。
- 完成SnapshotをPhase54 cacheやPhase13の非公開データへ変換する機能は未接続。部分結果を完成cacheへ登録しない。全内容SHA・入力世代・FD寿命契約を維持する。
- snapshotの所有容量は有界だが、小チャンクのCPU/copy増加、同時session全体の予算、保持し過ぎるreaderへのエラー処理が必要。
- 分類器とmap算術は既存参照を保持した独立実験実装で、将来の二重保守には固定参照と全フィールド照合の継続が必要。
- 任意の長さの連鎖・無候補区間で確定mapが停滞する。固定時間内の開始を保証しない。
- PCMの公開境界はmap確定境界より手前になる。Phase55の切り戻し値を一般的な証明に使わない。
- 位相・OLA・FIRを1インスタンスのまま続ける全PCMのビット一致、速度変更、CPU競合、callback期限、物理可聴遅延、製品接続は未実施。
- 他OS/CPU/最適化や自然な長尺楽曲の広い網羅は未保証。

Phase57は固定速度・オフラインで、同じDSP状態へ確定解析を補給し、全8形式・全161速度・複数チャンク・長尺・EOSの全PCMを既存全曲方式と比較するところから始める。内部契約は[DSP引継ぎ](../../docs/PHASE56_DSP_HANDOFF.md)。製品経路への接続は、その後の正確性・実時間試験を通してから判断する。

## 9. 再実行

出力先は新規を使う。生成入力WAV、参照バイナリ/直列化データはGit対象外の既存ルールを使い、入力SHA・参照SHAとレシピを保存する。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j 3
ctest --test-dir build -L deterministic --output-on-failure -j 2
python3 -B scripts/phase56_study.py --suite short --output results/phase56/short_new
python3 -B scripts/phase56_study.py --suite long --output results/phase56/long_new
python3 -B scripts/phase56_study.py --suite natural --output results/phase56/natural_new
python3 -B scripts/phase56_study.py --suite performance --reference build/phase56_frozen/reference_percent --output results/phase56/performance_new
python3 -B scripts/phase56_audit.py --output results/phase56/protected_new.json
```

既定の`build/phase56_frozen/reference_percent`は全161速度拡張前に、未変更の旧ライブラリへリンクして固定したoracleを使う。新しい環境では同じ保護ソースから`phase56_reference`を構築し、固定先へ保存してSHAを記録する。旧7速度oracleも保持し、共通列の抽出一致を確認する。最終集計は`phase56_summary.py`が実際の参照ファイル・バイナリSHAまで検査して行う。
