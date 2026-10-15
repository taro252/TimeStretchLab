# Phase 56：継続状態を持つ増分解析と完全一致検証

## 判定

**A：解析と要求した固定速度TimeMapについて完全成立。Phase 57の増分DSP合成検証へ進める。**

入力を追加して状態を引き継ぎ、確定済み検出フレーム、閉鎖event、精密anchor、TimeMapを順に公開する内部実験エンジンを実装した。**最終Release実行ファイルで78入力×7チャンク条件＝546セッション、中間の公開データと真のEOS後の全解析結果が固定参照とビット一致**した。各セッションで7速度を検証し、固定mapの最終全node比較は3,822件。チャンクごとに先頭から全解析を再実行していない。

このAはPhase56の範囲に限る。PCM継続合成、位相/OLA/FIRの部分解析接続、実時間DSP競合、再生中の速度変更、製品PlaybackEngine/Merodoaへの統合、PCM開始時間の短縮は未実装・未証明である。Phase55のBやPhase54の保存済み実時間FAILを上書きしていない。

## 1. 基準・保護・独立参照

- 開始時：`main`、HEAD `14d30be6a7a2dc164eead5a5d747c60fba806b49`、作業ツリーはクリーン。Phase55の依存関係/設計/REPORT/VERDICTと、Phase53/54の品質・Golden・引継ぎ契約を確認した。
- 既存のPhase13、STFT、TransientDetector、EventMap、アンカー、Phase37/39、再生API、位相・OLA・FIR、L1/L2/safe-density、ゲインを変更していない。新しいlibraryは実験実行ファイル/テストだけがリンクする。
- 実装前に既存ライブラリで参照実行ファイルをビルドし、`build/phase56_frozen/reference`へ固定した。SHA-256：`d60cc4b6bcd30e94fcb6931122f71d50c62a669447151b3277a4ea9e2c4a4aa4`。バイナリSHAは`frozen_reference_sha256.txt`にも保存。
- 参照データは各フィールドのIEEE生ビット、整数、flagを明示的に並べ、構造体paddingや十進文字列へ依存しない。参照ファイルSHA、入力SHA、oracle/checkerのバイナリSHAを各ケースの`reference_manifest.json`に保存する。
- 性能用には解析＋7mapの時間を追加計測する参照バイナリを別に固定した。元の実装前バイナリとの全解析・全map直列化SHAは性能用2入力とも一致（`frozen_equivalence/summary.json`）。変更後同士だけの比較を正解の根拠にしていない。
- 最終監査：既存追跡ファイル **6,770/6,770一致**、既存Golden WAVファイル全体SHA **30/30一致**、`phase53-handoff`タグも固定値のまま（`protected_final.json`）。既存CMakeには新規target/testの追加だけを行った。

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

世代、受信サンプル数、特徴量数、検出確定数、閉鎖event/anchor数、map公開node数、正常EOS/cancel/errorを分けた。型上は共有所有権付きの読み取り専用snapshotだけを渡す。必要な7速度をbit maskで選べる。mask=0は解析だけで、mapが既存でも成立しない速度のために、解析自体を使えなくしない。

## 3. 継続状態と不変性

STFTは4,096/1,024の絶対格子、左右2,048padding、前回logスペクトルとenergyを保持する。既存pushMagnitudesを利用し、旧finalizeは増分中に一度も呼ばない。閾値・局所最大・cooldown・lookbackの算術を実験用分類器で同じ順に実装した。未来のresetで変わり得る末尾は公開しない。

イベントは既存の4/12フレームとenergyの規則を継続する。open eventは連鎖長で強制閉鎖しない。新しい非統合候補、または直近endから12フレームの候補確定、または真のEOSで閉じる。peakが動くたび、揃っている3,072サンプル窓で既存Locatorを呼び、閉じるまで暫定anchorを保持する。PCM ringは1chあたり8,192サンプルで、長い連鎖の古いpeakのためにPCM全体を残さない。

TimeMapは閉じたpeakの間だけ計算する。伸張側のdouble累積位置を持ち越し、圧縮側の区間始点/終点の丸め直しを維持する。将来eventの左肩が既確定区間に入らないことを距離条件で確認した。末尾区間はEOSまで確定しない。全546セッションでFFT回数が参照フレーム数と等しく、map区間の処理数も参照node数−1と等しいことを実行時に検査した。

snapshotは64要素ページと深さ16の不変索引を共有し、変更ページと索引経路だけを複製する。既定64MiBの所有容量上限を設け、古いsnapshotを保持し続けた場合も無制限に増やさない。上限超過時は事前確保した失敗snapshotを公開する。内部特徴列・座標列は曲長に比例し、既定入力上限は48kHz換算10分。これはeventの長さ上限ではなく、明示的な資源予算である。

## 4. 完全一致行列

主たる最終証拠は`exact_release_final/`。前段の`short/long/*_final/exact_final/exact_verified`は開発中の独立した試行として保持し、最終件数へ重複加算しない。

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
- 0.40/0.50/0.75/1.00/1.25/1.50/2.00の全公開nodeを整数完全比較。Candidate L2/Baseline Cの初期固定mapが同じことも専用CTestで確認。
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

同じ入力でも解析自体は既存Phase13に一致し、mapMask=0と0.50だけの選択を別途検証した。成立しない速度を黙って近似mapへ置き換えたり、使わない速度の失敗を解析全体の新しい必須制約にしたりしていない。

同一入力の解析を自動的に1 flightへまとめる仕組みは追加していない。複数要求は別session/世代/容量を持ち、独立に一致することを検証した。多数sessionの総CPU・総メモリ予算は次Phaseの管理側の責務となる。

## 6. 性能：Release単独実行

最終測定は`performance_final/`。macOS arm64、Release、`-O3 -DNDEBUG`。旧全曲解析＋7固定mapをA、増分解析＋7map＋snapshotをBとし、同一入力・各条件5回。2入力×7チャンク×5＝70増分実行、全曲側10実行を保存した。他のDSP検証とは競合させていない。プロセスは各回新規で、OSファイルcacheはpurgeせず、OS Coldではない。

「開始」は解析呼出し/Session構築の開始。Bにはチャンク読取とFD同一性検査、copy/publicationも含む。ベンチでは中間の全フィールド照合や保持snapshot再検査を時間外にし、終了後に最終全結果のビット・SHA一致を検査する。比較用参照配列を事前に読む検証プログラムのRSSであり、libraryだけのRSSではない。

### 290秒MIX反復・PCM16 Stereo 44.1kHz

既存10秒MIXをPhase55のレシピで反復・PCM16化した入力。同じ入力SHAを使用した。Aの解析＋7mapの中央値はwall **758.771ms**、スレッドCPU **758.024ms**。

| 入力チャンク | B総wall中央値 ms | B総CPU中央値 ms | A比CPU増減 | 最初の確定event/map区間 ms | 累積snapshotコピー MB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 Mid | 1,671.650 | 1,192.683 | +57.34% | 3.624 | 63.321 |
| 7 Mid | 860.559 | 646.049 | −14.77% | 2.176 | 23.942 |
| 8 Mid | 827.345 | 635.342 | −16.18% | 2.212 | 22.993 |
| 32 Mid | 600.929 | 554.272 | −26.88% | 1.924 | 10.252 |
| 128 Mid | 552.467 | 538.766 | −28.92% | 6.028 | 4.515 |
| 不規則 | 628.206 | 562.716 | −25.77% | 7.565 | 7.091 |
| 5,003 sample | 987.962 | 692.085 | −8.70% | 2.531 | 27.059 |

小チャンクではsnapshot公開とFD検査回数が増える。CPUが少なくてもwallが短くならない条件があり、最初の確定区間の通知粒度と総処理コストを分けて選ぶ必要がある。最大値・母標準偏差も`statistics.json`へ保存した。5回の限定測定であり、一般的な期限保証や統計的な有意差を主張しない。

snapshot計数Peakは約1.459〜1.462MB、プロセスPeak RSS中央値は約13.89〜15.81MB（A約10.13MB）。累積コピー63MBは同時占有量ではない。ringへの受信PCMコピーは各条件102,312,000bytesで一定。コピー計数はring転送、snapshot本体/ページ/索引の推定であり、FFT内部やstd::vector再配置まで含む全プロセスのコピー量ではない。

### 5分のevent連鎖

Aはwall **428.106ms**、CPU **427.112ms**。Bの128 Midはwall **337.380ms**、CPU **323.995ms**。1 Midはwall **1,579.368ms**、CPU **1,033.940ms**。

全チャンク条件で、最初の確定eventと非空map区間が得られたのは**EOSの最終処理完了時**。解析中にmap境界を無理に進めず、入力14,400,000フレーム全体が閉鎖待ちとなることを記録した。確定区間が必ず早期に得られるという保証は成立しない。各chunkの処理wall/CPU、確定境界、コピー差分、EOS処理行をCSVへ保存した。

### 全内容識別の別コスト

既存Phase54のprepare-onlyを同じ290秒入力で5回測定した（`identity_cost/`）。全内容SHA-256等の識別wall中央値 **24.904ms**、最大25.270ms、母標準偏差0.157ms。解析wall中央値664.946ms、prepare全体690.058ms。これは上の「解析＋7map」と処理範囲が異なるため、同じ列として比較しない。

**数msで確定mapを取得できたことを、PCM開始時間や可聴遅延の改善とは報告しない。** 製品では全内容識別、DSP初期化、十分な確定領域、位相/OLA/FIRの先読み、既定FIFO先行蓄積、実機callbackが別に必要である。

## 7. ビルド・回帰

- Release全targetビルド成功。全体の決定論的CTest **79/79、430.13秒**（`ctest_deterministic.log`）。既存77項目と当時の新規2項目を含む。
- 追加preset試験、選択map/解析専用モード、非単調map拒否、cancelのcommit境界を含む最終専用CTest **3/3、2.48秒**（`ctest_terminal_final.log`）。全体79項目と重複する2件を除き、独立項目数は既存77＋Phase56新規3＝80。後段の新規実装の更新は、最終専用試験と最終546セッションで再確認した。
- Debugビルド成功。最終のPhase13＋新規3試験 **4/4、4.47秒**（`ctest_debug_terminal_final.log`）。同じDebug構成の既存一回解析をoracleとした。Releaseとの構成間一致試験とは区別する。
- 従来の製品再生経路のGolden **25/25**：raw float32 PCM SHA・フレーム数一致。新方式によるPCM合成試験ではない。
- Phase54の実時間FAILは監査対象として保持。Phase56では新しい解析/DSP競合や実機試験を実施しておらず、従来の実時間不合格を今回の解析成功でPASSへ変えていない。

初期コンパイルでは、この環境のlibc++で`atomic<shared_ptr>`が未対応だったため、対応するshared_ptr原子操作のfree functionへ変更した。また、Darwinのsize_tとuint64_tの型差に起因する検証プログラムのコンパイルエラーを修正した。ログは保持。数値不一致を許容して通したケースはない。

## 8. 残るリスクとPhase 57への条件

今回の範囲では確定境界の未解決依存はなく、継続状態による解析・固定mapの基盤としてPhase57へ進める。次を引き継ぐ。

- 現在の実験用mapは列挙した7速度を選ぶ。任意の小数6桁速度や動的変更のAPIは未実装。補間で近似せず、同じ補償計算を拡張して検証する。
- 完成SnapshotをPhase54 cacheやPhase13の非公開データへ変換する機能は未接続。部分結果を完成cacheへ登録しない。全内容SHA・入力世代・FD寿命契約を維持する。
- snapshotの所有容量は有界だが、小チャンクのCPU/copy増加、同時session全体の予算、保持し過ぎるreaderへのエラー処理が必要。
- 分類器とmap算術は既存参照を保持した独立実験実装で、将来の二重保守には固定参照と全フィールド照合の継続が必要。
- 任意の長さの連鎖・無候補区間で確定mapが停滞する。固定時間内の開始を保証しない。
- PCMの公開境界はmap確定境界より手前になる。Phase55の切り戻し値を一般的な証明に使わない。
- 位相・OLA・FIRを1インスタンスのまま続ける全PCMのビット一致、速度変更、CPU競合、callback期限、物理可聴遅延、製品接続は未実施。
- 他OS/CPU/最適化や自然な長尺楽曲の広い網羅は未保証。

Phase57は固定速度・オフラインで、同じDSP状態へ確定解析を補給し、全8形式・全7速度・複数チャンク・長尺・EOSの全PCMを既存全曲方式と比較するところから始める。内部契約は[DSP引継ぎ](../../docs/PHASE56_DSP_HANDOFF.md)。製品経路への接続は、その後の正確性・実時間試験を通してから判断する。

## 9. 再実行

出力先は新規を使う。生成入力WAV、参照バイナリ/直列化データはGit対象外の既存ルールを使い、入力SHA・参照SHAとレシピを保存する。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j 3
ctest --test-dir build -L deterministic --output-on-failure -j 2
python3 -B scripts/phase56_study.py --suite short --output results/phase56/short_new
python3 -B scripts/phase56_study.py --suite long --output results/phase56/long_new
python3 -B scripts/phase56_study.py --suite natural --output results/phase56/natural_new
python3 -B scripts/phase56_study.py --suite performance --reference build/phase56_frozen/reference_scope --output results/phase56/performance_new
python3 -B scripts/phase56_audit.py --output results/phase56/protected_new.json
```

`build/phase56_frozen/reference`は実装前に保存したoracleを使う。新しい環境で再構築する場合も、基準SHAの保護ソースを用い、その一致を確認する。性能用oracleの追加計測は元バイナリとの参照SHA一致を先に通す。最終集計は`phase56_summary.py`が実際の参照ファイル・バイナリSHAまで検査して行う。
