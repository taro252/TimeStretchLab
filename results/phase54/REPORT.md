# Phase 54 — 再生開始の高速化・解析再利用・低ストレージシーク

## 判定

基準コミット: `34b8903ef43e1bae4e518eeb124caaab9db2976f`。変更対象はTimeStretchLabのみ。

- **Part A: 開発版の完成条件を満たす。** 不変な入力過渡音解析を再利用する。Stop/EOS後も解析回数・全ファイルハッシュ読取量が増えず、位相・OLA・FIR・FIFOは新しいセッションとして作る。先行量は削減していない。
- **Part B: 正確性を優先したシークAPIを統合。高速シークは未達。** Candidate/Baseline、原曲座標、非同期Latest-Wins、Playing/Paused/Ready、停止・装置変更キャンセルに対応する。指定位置まで先頭からDSPを再実行するため、深いシークには大きな待ち時間が残る。
- 全曲の伸縮済みPCMディスクキャッシュは追加していない。正式Experimental 3500、Phase30/36プレイヤー、Phase18/19キャッシュ・シーク、TimeMap/L1/L2/safe-densityの品質アルゴリズムは変更していない。
- 一般公開向けの実時間安定性保証ではない。今回の実機合格と、任意の装置・負荷・長いOS停止への保証を区別する。

## 1. 実装と責務

### 解析再利用

`PlaybackAnalysisCache`はPhase13のイベント、検出フレーム、精密アンカーだけを共有する。不変解析の寿命を再生セッションから分離した。速度依存TimeMapと可変合成状態は毎回構築する。既定32MiB・64エントリ、容量変更、使用していない古いデータの削除、使用中leaseの保持、同一ファイルの同時解析共有、保持無効の比較経路を持つ。

初回は開いた通常ファイルの全内容SHA-256と解析前後の同一性を確認する。APFSではdevice/inode/generation、サイズ、mtime/ctime/birthtime、WAV形式、固定解析仕様を索引にする。再利用時は全ファイル再ハッシュを行わない。サイズとmtimeを戻した書換えもctimeで失効する。置換・symlink変更・破損・同時要求をテストした。同一性確認を採用できないAPFS以外では再解析する。

検証したファイル記述子を保持し、ワーカーはその記述子から読む。Darwinの`/dev/fd`を通常のfstreamで開くと読取り位置を共有する問題があったため、専用経路は位置非依存の`pread`にした。通常パスの既存読取りを保ち、PCM回帰で照合する。再生中に内容が変更されればワーカーで失敗にする。入力はセッション中に書き換えないこと。

容量値は解析所有領域の推定で、アロケータ・FD管理・DSP・AVAudioEngineを含むプロセスRSSとは異なる。使用中データより小さく容量を下げた瞬間は、解放まで設定値を超えることがある。新規データを保持できなくても、そのセッションの解析leaseで動作する。

公開Configuration/RenderResultはPhase53の集約初期化の先頭項目を維持し、互換テストを追加した。既存の空verificationHooks指定が誤って解析再利用OFFへ解釈されないよう、新しい設定は末尾へ追加する。既存測定はこの配置修正前の同じ名前付き設定/合成処理で取得し、最終バイナリは配置修正後に全CTest・Goldenと実機の追加回帰を行う。

### シーク

`seekToInputSeconds/frame()`は受付IDを返す。TimeMapで原曲位置を出力位置へ対応付け、新しい初期速度で頭から合成し、指定出力位置まで捨てる。`inputSeconds / speed`は位置計算に使用しない。新区間は最新の有効な要求速度を初期速度にし、旧速度履歴をコピーしない。準備中に速度が変われば再計画する。

旧再生を継続しながら別ワーカーで新FIFOを準備する。部分ブロックを値を変えず詰め直し、16,384フレームの先行蓄積を維持してから引き渡す。コールバックは公開された区間ポインターを1回だけ読み、旧所有領域はコールバックの静止点を確認してから制御側で破棄する。共有所有権の増減、ファイルI/O、DSP、確保、mutexをコールバックへ追加していない。

新しい有効シークは古い準備をReplaced、Stop/route変更はCancelledにする。最新の不正要求をRejectedにしても、古い有効要求の完了で最新snapshotを上書きしない。履歴128件とactiveId/pendingIdを公開する。準備完了は可聴完了ではない。旧区間の不足を隠さないlifetimeカウンターと、旧区間の公開PCM範囲/SHA/plans（最大16件）を保持する。

## 2. 条件・再現性

Release、arm64、`-O3 -DNDEBUG`。環境と実行バイナリSHAは `environment.json`（配置互換修正前の実測）と `environment_final.json`（最終ビルド）、入力SHAは `input_manifest.json` / `mono_input_manifest.json`。

- MIX 44.1kHz、他4素材48kHz、元のステレオ素材を30/180/300秒へ繰り返した試験入力。**自然な3分・5分の別楽曲ではない。** 元音源は変更していない。
- 44.1/48kHz × Mono/Stereoは人工信号の全サンプル試験で検証。実機MonoはMIX/Drumsの片チャンネルを3秒抽出した別入力で検証。
- Candidate: FIFO/先行/生成=16,384/16,384/2,048、L1/L2有効。Baseline: 16,384/12,288/2,048、L1/L2無効。同じ合成コア、継承QoS。
- 実機: default device ID 72、装置48kHz・512フレーム。SourceNodeは48kHz入力512、44.1kHz入力471フレームの実測。装置名の列挙はsandbox内で取得できず、数値IDを保存した。
- 高負荷は8本のCPU競合プロセス。実機と、待ちながらFIFOを読むオフライン正確性試験は別判定。
- WAVはGit対象外。入力再生成は `scripts/phase54_inputs.py` で元音源のfloat32 PCMを繰り返し、指定フレーム数に切り出す。`source_manifest.json`の元音源SHAを検証し、再生成レシピ15/15のSHAが一致した（`input_recipe_check.log`）。公開不可の元音源をリポジトリへ追加しない。

## 3. Part A — 起動時間

### 同一MIX 30秒・0.50倍速

旧ライブラリを変更前に独立バイナリへ固定し、同じ入力・最適化設定で呼出し全体を計測した。`baseline/`は変更前の初回測定、`startup_native_final/`は凍結バイナリと更新後を連続測定したもの。単回測定であり統計的な保証ではない。Coldは当該プロセスに解析キャッシュがない状態で、OSのファイルキャッシュを冷却した試験ではない。

| macOS呼出し | 旧版 | 更新後 |
| --- | ---: | ---: |
| Cold prepare | 225.95 ms | 180.27 ms |
| Ready→Play | 47.11 ms | 58.73 ms |
| Stop→Play | 142.42 ms | 63.21 ms |

Stop→Playは約79.20ms（55.6%）短縮。一方Ready→Playはこの試行で遅く、すべての段階が改善したとはしない。Coldには初回全ハッシュ・解析が残る。

更新後の実機Cold prepare内: core prepare76.68ms、全ハッシュ等の識別5.48ms、入力解析70.96ms、pipeline生成0.075ms。AV構築103.51ms。Ready→Play内は先行蓄積45.73ms、TimeMap0.065ms、ワーカー初期化3.84ms、AV起動12.92ms。Stop→Playは解析0（hit）、識別2.13ms、先行蓄積40.20ms、AV再構築17.39ms、AV起動3.28ms。

更新後Play受付→最初の有効PCMコールバックはCold63.01ms、Stop後72.79ms。これはコールバック到達の推定で、音響ループバックによる可聴時刻ではない。旧バイナリは同じ粒度の全内部段別時刻・最初のcallback相対時刻を保存しておらず、変更前の各段の完全な加算比較は未実施。空欄を0実測に置き換えない。

親子計測は重複する。metadataは識別の一部、TimeMapはワーカー初期化の一部、prefillのCPUは待機する制御スレッドのCPU。値を足して全体時間としない。

### 75条件とライフサイクル

`startup_matrix_final/`: 5素材 × 30/180/300秒 × 0.40/0.50/1.00/1.50/2.00 = **75/75完走**。Cold後のStop→Playで全条件analysis_runs=1のまま、cache hitとなる。各段のwall/実行スレッドCPU、プロセスCPU、RSSを保存した。

例: 5分Drums・0.50はCold prepare808.31ms、Stop→Play42.84ms、解析所有容量641,195bytes。3分MIX・0.50はCold461.82ms、Stop→Play37.80ms、375,035bytes。30秒MIXは61,595bytes。これらは異なる処理範囲の時間で、同一Cold処理を42.84msで終えたという意味ではない。

`startup_lifecycle_final/`にはCold/Ready/already Playing/Stop/EOS/異なる初期速度/別曲/元曲へ戻る比較を保存。別曲の初回は解析し、元曲へ戻るとhitになる。別曲分以外の全ハッシュは増えない。同測定はシーク性能試験と一部並行しており、主たる単独実機比較とは区別する。

## 4. Part B — PCM・遅延・高速化方式

人工信号の44.1/48kHz × Mono/Stereo × 5速度 × 2preset × 先頭/中央/末尾付近/終端で **160条件の全サンプル一致**。さらにキャッシュ無効の4形式でも独立参照suffixのSHA一致を確認する。読取り64〜4,096フレーム、C++ callback確保0、入力終端と正確なEOSを検証する。この消費側は不足を待つため、実時間安定性の証拠には使用しない。

独立参照はPhase35のフレーム配列合成。対象の初期速度・TimeMap・密度履歴で先頭から生成し、同じ出力位置以降を照合する。比較のために全曲WAVを保存せず、サンプルsinkへハッシュする。従来のWAV出力経路は既定のまま残る。

CPU側の限定試験 `seek_performance_final/` は **32ケース・36回の準備と公開PCM比較が成功**。同じ箇所への再シーク3回、キャッシュ無効、Baselineを含む。36回すべて独立参照の該当公開範囲のSHAが一致した。全suffixは別の160条件で全サンプル比較している。

30秒入力の原曲15秒への移動、5素材各1回の準備時間:

| 初期速度 | 中央値 | p95/最大（5件） |
| --- | ---: | ---: |
| 0.4 | 4.491秒 | 4.984秒 |
| 0.5 | 2.375秒 | 2.533秒 |
| 1.0 | 2.076秒 | 2.171秒 |
| 1.5 | 2.237秒 | 2.295秒 |
| 2.0 | 2.228秒 | 2.321秒 |

p95はnearest-rank、通常中央値は中央2値の平均（偶数の場合）。ここではn=5なのでp95=最大となる。OS待ちを含む単回の限定測定で、一般的な応答保証ではない。

| Drums・90%位置 | 0.40倍速 | 2.00倍速 |
| --- | ---: | ---: |
| 3分入力・162秒 | 51.375秒 | 26.753秒 |
| 5分入力・270秒 | 101.796秒 | 42.760秒 |

同じMIX位置・0.40の3回再シークは5.268/5.264/5.077秒、Baseline Drums・0.50は2.744/2.854/2.735秒。解析hitでも合成状態を再構築するため、繰り返すだけで瞬時にはならない。キャッシュ無効のDrums・0.40は5.381秒、analysis_runs=2（prepare+seek）、ハッシュ読取23,040,088bytes。キャッシュありでは解析・ハッシュが1回のまま。CPUとRSSは各CSVに保存し、長尺0.40の準備CPUは約102.4秒だった。RSSは検証プロセス全体の最大値で、繰り返し時の過去の独立参照処理を含み得る。


| 方式 | 今回の実装・結論 |
| --- | --- |
| 先頭から再計算 | 正確性フォールバックとして実装。深い位置では遅い |
| 入力解析再利用 | 実装。シークごとの全曲解析・ハッシュを省く |
| DSP状態チェックポイント | 未実装。各解像度の位相所有領域/位相距離、OLA未確定信号と重み、FIR履歴・畳み込み境界、TimeMap・次フレームを一体で保存する必要がある |
| 必要区間だけ合成 | 未実装。履歴なしで任意位置から位相を開始すると厳密な参照一致を保証できない |
| 小容量PCMメモリキャッシュ | 未実装。短いPCM窓だけではその後の可変DSP状態を再開できない。導入にはチェックポイントとの組合せが必要 |
| 全曲PCMディスクキャッシュ | 不採用。Phase18/19は保持し、このAPIの既定へ接続しない |

### CPU・メモリ中心の方式比較（設計評価）

現行Phase36の配列容量を読み取り専用で調査した。ステレオの3解像度出力ringは65,536×2×4×3=1.50MiB、OLA信号/重みは(8,192+4,096+1,024)×4×2ch×2配列×4=0.8125MiB、2系統FIRの蓄積ringは16,384×2ch×2×4=0.25MiB。**1状態の保存下限は2.5625MiB**で、位相・前回振幅・ステレオ状態・索引・可変密度履歴などは別。これはコピー容量の設計下限で、復元済み実機のRSSではない。Phase17の旧推定値を今回の実測へ流用していない。

5分入力・0.40倍速を10秒出力間隔で全域保持するなら約75状態、上記ringだけで約192MiBになる。チェックポイント数を8などへ制限すればメモリは抑えられるが、未処理の未来位置の初回シークを高速化できず、間隔も広がる。入力SHA・速度6桁・preset・固定TimeMap・密度履歴・実装/環境をキーとし、速度変更履歴を持つ状態を「新しい固定初期速度」の参照へ誤適用しない設計が必要。

32MiBのPCM窓は48kHzステレオfloatで約87.4秒出力に相当する。しかし窓の先へ続けるためのDSP状態がないため、PCM窓だけでは一般的なシーク再開にならない。チェックポイントと短いPCM窓を組み合わせる案は次段階。頭から再計算する現行方式は、取得済みの解析だけを再利用し追加ディスク容量0で厳密一致するが、合成のCPU量は移動位置に比例する。このトレードオフを今回は隠さず公開する。

終端ちょうどのシークでも現行フォールバックはワーカーが先頭からの処理を終了してEOSを確定するため、出力サンプルが0の新区間でEnded通知を待つ時間が残る。途中のStop/新しいシークでキャンセル可能。これは高速化の未達事項であり、即時EOSの保証とはしない。

旧区間が準備中にEOSへ達した場合、新区間の完成まで無音待ちになり得る。高負荷の同時再構築も追加CPUを要する。今回の結果で「瞬時にどこへでも移動できる」とはしない。準備120秒の制限、連打での再試行、失敗理由をアプリUIへ表示する。

## 5. 実機ライフサイクルと試聴

`native_short_final/`7/7、`native_long_final/`3/3、`native_mono_final/`2/2。**12実行の音声/計測/参照PCM/保存CSVがPASS**。11実行はEOS、1実行は模擬装置変更による安全停止（EOS成功ではない）。

短尺は5素材、Candidate/Baseline、連続シーク・置換、pause中のseek→resume、seek後の速度変更、Stop→Playを実行。長尺は3分MIXと5分Drumsの中央シーク→EOS、3分Drums高CPU競合の全曲EOS。最後の高負荷試験は速度2.00固定で、**高負荷下の全速度・深いシーク網羅ではない**。MIX/Drumsの長尺シーク実測は準備約13.25/23.86秒で、待ち時間を隠していない。

配置互換修正後の最終Releaseバイナリでも、MIXのsmokeを追加1/1成功（`native_release_final_mix/`、`native_release_review.json`）。連続シーク・pause/resume・Stop→Play・EOS、閉じた区間と最終区間の参照PCM、CSV行数/通番/有限値を再確認した。12件の元測定とこの追加測定のバイナリSHAは別に保持し、未実施条件を埋めるために旧結果を流用しない。

元の全12実行で不足フレーム0、書込み拒否0、callback期限超過0、callback C++確保0。長尺callback最大はMIX0.027958ms、Drums5分0.031708ms、高負荷Drums0.046833ms。長尺再生中RSSは約60.3〜71.3MiB（独立参照生成前に計測）。高負荷の製品保証、malloc/Objective-Cランタイム全体の確保0、物理装置切替の完走を証明するものではない。

大きなworker_max_wallには、指定位置まで公開せずに合成する再構築の時間も含まれる。通常の2,048フレーム供給が13〜24秒停止したという解釈はしない。旧ワーカーの供給と新ワーカーの準備を区別する。

ユーザーは最初のMIX実機試験に「違和感なし」と回答。意図した約1.5〜1.8秒のpauseを含む。これは他の全素材・全フェード長の最終主観合格へ一般化しない。

### フェードの分離

raw/FIFOは無加工。再生段gain0.5と線形fade-in0/64/128/256を別に適用する。暫定既定64は旧研究の知見を引き継ぐが、シーク位置ちょうどのアタックは弱まる可能性がある。固定ゲイン、同じ原曲位置の短い比較を `audition/` に保存する。

`audition/manifest.json`の8ファイルは有限値・ピーク1.0未満、全方式固定gain0.5。最初の256フレームのエネルギー比（フェードなし=1）は次のとおり。

| フェード | Drums | MIX |
| --- | ---: | ---: |
| 0 | 1.000 | 1.000 |
| 64 | 0.800 | 0.831 |
| 128 | 0.587 | 0.584 |
| 256 | 0.230 | 0.264 |

Drumsのこの位置では64で先頭256サンプル内の最大ピークは維持されたが、エネルギーは約20%低下。256では約77%低下する。アタックが境界の最初のサンプルに一致すれば、全ての非0フェードでそのサンプルは0になる。この数値だけで聴感の優劣を決めない。MIXは原曲4.0秒、Drumsは3.77秒を新位置とした例で、全アタックの統計ではない。


試聴: `fade_0.wav`→64→128→256を同じ音量で比較する。先頭0.2秒は旧位置の末尾、そこから新位置へ移る。Drumsの最初のピーク、クリック、余韻、MIXの定位を確認する。原曲の異なる位置へジャンプするため、波形の連続を期待する比較ではない。追加のMIX/Drums比較案内に対し、ユーザーは「64フレームで問題なし」と回答した。再生段の暫定既定64を維持する。全位置・全素材の保証や、128/256の個別音質評価へは一般化しない。

## 6. 回帰・監査

- 最終Releaseビルド: `build_release_final.log`。Configuration/RenderResult互換修正後に **決定論的CTest 75/75成功**、373.27秒（`ctest_deterministic_release_final.log`、`release_final_validation.json`）。旧来のPhase29/30/35/36、Mono/Stereo、公開済みPCM、EOS、計測ON/OFF、キャッシュ/シーク等の既存回帰を含む。旧名・判定閾値は変更していない。
- 最終アプリコアで **Golden25/25のraw float32 PCM SHA・フレーム数が一致**（`golden_release_final/summary.json`）。元Golden WAVはファイル全体のSHAも再照合し、変更していない。新しい全曲比較WAVをディスクへ保存していないため、「新しいWAVヘッダーも含むファイル一致」とは呼ばない。
- 保護資産監査: **5574/5574一致**（`protected_assets_release_final.json`）。既存の追跡済みresultsと凍結合成/TimeMap/safe-density等の選択ソースを、基準コミットのGit blobと照合した。`phase53-handoff^{}`は `233c773bbc77e5824c36134915f68d6d3a0d581e` のまま。
- 変更した合成周辺は、Phase13の読取り専用メモリ量getter、Phase35の既定WAV出力を保った参照サンプルsink、Phase36の初期化計測通知、Phase39の準備済み解析の受取り・位置指定・出力破棄/詰め直し。位相伝播・FFT/IFFT・OLA・FIR・L1/L2・safe-densityの判定式/演算順を変更していない。
- 最終ビルド対象のソース指紋は `tested_source_fingerprint.json`（b906b949db4286a96236794029f9fadf5ecf2c5ed8e17c857663ea290a92c4c6）。構成・バイナリSHAは `environment_final.json`。完成コミットはこのREPORTを含むGit履歴で識別する。
- **別枠の実時間CTestは1/2成功、1件不合格**（`ctest_realtime.log`）。`phase44_quality_gate`は最大42.1952msの起床遅刻、5期限/2,560フレームの提示期限逸脱で `CALLBACK_TIMING=FAIL` / `SIMULATION_VALIDITY=INVALID`。不足0・callback処理期限超過0でもPASSへ昇格させない。実消費365,440と提示時間軸368,000の不整合も不合格理由として保持。`phase45_deadline_integrity`は成功した。この旧模擬経路の無効結果を、今回の実機13実行の音声不足に置き換えず、実時間安定性の証明にも使わない。
- `final_validation.json`は最初のフェード生成失敗と実時間CTest不合格を含むため、元の工程全体は非0終了のまま保持した。フェード生成は相対パス処理を修正し、別の `fade_final.log` と8ファイルのmanifestで成功を確認した。元ログや既存の計測FAILを上書きしていない。


保存した初期のコンパイル/読取りエラー、timestamp=0を含んだ古い試行、symlinkのターゲット内容をblobとして比較した最初の監査結果は消していない。最終判定は最終ビルドのログと明示したsummaryに限定する。時刻の順序、元セッションの音声不足、CSV行数・通番・有限値を再確認し、過去のFAILを暗黙にPASSへ上書きしない。

## 7. 再実行・アプリ統合

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j 3
ctest --test-dir build -L deterministic --output-on-failure -j 2
python3 -B scripts/phase54_inputs.py # 既存private入力の再生成レシピSHAを検査（書込みなし）
python3 -B scripts/phase54_golden.py --output results/phase54/golden_new_run
python3 -B scripts/phase54_startup_matrix.py --output results/phase54/startup_new_run
python3 -B scripts/phase54_seek_bench.py --output results/phase54/seek_new_run
python3 -B scripts/phase54_native_batch.py --output results/phase54/native_new_run --suite short
python3 -B scripts/phase54_native_batch.py --output results/phase54/native_long_new_run --suite long
python3 -B scripts/phase54_native_batch.py --output results/phase54/native_mono_new_run --suite mono
# --suite short/monoは有音、longは再生段gain0。すべて実機のコールバックを使う。
```

実時間CTestは従来どおり`TIMESTRETCH_ENABLE_REALTIME_TESTS=ON`で登録し、`ctest --test-dir build -L realtime --output-on-failure`を単独実行する。閾値やINVALID判定は緩めていない。

アプリ向けAPI、スレッド/入力寿命、seekの状態・raw範囲、エラーと制限は [`docs/PHASE54_SEEK_API.md`](../../docs/PHASE54_SEEK_API.md)。利用例は `examples/mac_playback_handoff.cpp`、CMakeターゲット`playback_handoff_example`。Merodoa側のコード変更は行わない。submoduleをレビュー済みの新しい完成SHAへ更新して再ビルドする。`phase53-handoff`は233c773のまま。

次は、現在のAPIを使ったアプリ統合を継続しつつ、厳密なDSP状態チェックポイントの保存単位とメモリ予算を設計する。シーク待ちを短くするために先行量やsafe-densityを削ったり、位相を途中から近似初期化したりしない。
