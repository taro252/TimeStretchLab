# Phase 55：段階的過渡音解析と高速再生開始の実現性検証

## 最終判定

**B：条件付きで成立する可能性を確認。製品採用は保留する。**

閉じたイベントまでの解析・TimeMapと、そこから十分に切り戻したPCMは、今回の限定範囲で全曲解析方式と完全一致した。固定秒数の部分解析を仮のEOSとして再生する方式は、TimeMapもPCMも不一致となった。後続の候補でイベントが連鎖する長さや、次の確定peakまでの距離に上限がないため、任意の楽曲で固定時間内の開始を保証できない。

このBは**依存関係と独立したprefix試験の実現性判定**である。状態を継続する増分解析・増分合成が全曲PCMを最後まで生成して一致した、という判定ではない。長尺全PCM、速度変更を含む段階解析、実時間での解析とDSPの競合は未検証。Aの採用条件には達していない。

製品のPlaybackEngine、Phase54公開API、Merodoa契約、Experimental 3500、L1/L2、安全密度、位相、OLA/FIR、ゲイン、FIFO/先行量を変更していない。既存Golden・過去results・基準ソースの保持は別途監査する。

## 1. 作業開始時の確認

- ブランチ`main`、HEADとPhase54完成SHAは`039592e59cc1a525b495e38d3cedeb6c050792b1`。開始時の`git status --short`は空。
- Phase53品質契約、`docs/APP_INTEGRATION_HANDOFF.md`、`docs/PHASE54_SEEK_API.md`、Phase53/54 REPORTを確認。`phase53-handoff`は`233c773bbc77e5824c36134915f68d6d3a0d581e`に固定。
- Phase54の既存合格は決定論的CTest75/75、アプリraw Golden25/25。これらはPhase55の増分経路の合格ではない。
- Phase54の実時間CTestは**1/2、不合格1件を保持**。`phase44_quality_gate`の起床遅刻最大42.1952ms、提示期限逸脱5回/2,560フレーム、`CALLBACK_TIMING=FAIL`、`SIMULATION_VALIDITY=INVALID`。不足0でも合格へ変えない。
- 高負荷/長いOS停止、装置変更の広い網羅、host/sample時刻不連続、約1.4〜1.6秒等の速度反映遅延、iOS未検証、深いシークの再構築待ちを引き継ぐ。
- macOS arm64、Release、`-O3 -DNDEBUG`、既存build/CTest構成。実験対象は新しい専用実行ファイルと専用テストであり、既存ライブラリへ新しい処理をリンクしていない。

## 2. 依存関係の結論

詳細は[解析依存関係](../../docs/PHASE55_ANALYSIS_DEPENDENCIES.md)にまとめた。

1. 検出の特徴列は有限のFFT窓と直前状態、閾値は過去12フレーム、検出は次の1フレーム、reset位置はlookbackを含む未来2フレームに依存する。
2. イベント統合の12フレームは直近endからの間隔である。候補が続けば同じeventのpeak/end/strengthは任意に長く変わる。12フレームの固定先読みだけでは過去eventを一律に確定できない。
3. イベントが閉じ、そのpeak周囲の入力窓が揃えば精密アンカーは局所的に確定する。
4. TimeMapの伸張側・圧縮側はいずれも**次のイベントまでの区間全体**で保護の補償を配分する。次peakとアンカーが未確定なら、解析済みの区間の先頭からホップが変わり得る。全入力長から目標出力長が分かっても、この依存は消えない。
5. 確定mapよりさらに手前まで合成の窓・位相・OLA・FIRが参照する。map一致とPCM公開可能範囲は同じではない。
6. 現行`TransientDetector::finalize()`は一度だけ呼ぶ設計で、複数回呼ぶと古いtrueが残る反例を確認した。既存関数をそのまま増分APIとして使えない。既存一回解析に修正は加えていない。

専用の分類器入力反例では、等しい全配列長・等しい過去の特徴で未来の最初のpeakだけを変えるとmapのnode1が変わる。最初の閉じた区間は一致しても、次の未閉鎖区間は変わる。イベント連鎖は16/128/4,096フレームで確認した。

## 3. 独立実験の方法と範囲

`phase55_analysis_probe`は同じ入力の先頭WAVを順に伸ばし、**既存Phase13解析をそれぞれ最初から実行**する。検出器、アンカー、補償、合成アルゴリズムを複製していない。全曲参照と部分WAVの入力サンプルを先にビット照合する。増分状態を引き継ぐ処理速度の試験ではない。

比較対象は次のとおり。

- 検出の全フィールド：double/floatはビット比較、flagは完全比較。構造体のpaddingは比較しない。
- 非EOS時の検出確定prefixは保守的に`active−2`フレーム。
- `active > event.endFrame+12`を満たすeventだけを閉鎖済みとして、全フィールドとアンカー全フィールドを照合。
- 閉鎖済みpeakまでのmap nodeを整数完全比較。未来eventの保護重みがそこへ遡らないことをコードでも確認。
- PCMは実際の既存PlaybackEngineをCandidate/Baselineで別々に初期化し、FIFO不足を待って消費する。raw float32をサンプルごとのビット比較とinterleaved順のSHA-256で照合する。
- PCMの切り戻しは`max(0, map[closedPeak]−16384)`。これは保守的な**比較用crop**で、製品用の最小先読み・一般的な合成境界の証明ではない。0フレームcropの空SHAはPCM一致件数に含めない。
- 最後のEOF snapshotは全入力を別に解析・合成する同一性対照。これだけで、途中で公開した全PCMの正当性を証明したとは扱わない。

### 検証マトリクス

| 群 | 入力 | 境界 | 速度・preset | 実施した比較 |
| --- | --- | --- | --- | --- |
| short | 4秒、PCM16/Float32 × Mono/Stereo × 44.1/48kHzの8形式。持続音と強い過渡音、境界付近の複数アタック、EOS直前インパルス | 1.5/2.5/3.5秒とEOF | 全7速度 × Candidate/Baseline | 解析・map・PCM・SHA |
| special | 4秒、Float32 Mono 48kHz。無音、単発インパルス、持続音と遠い後続アタックの3素材 | 同上 | 全7速度 × Candidate/Baseline | 解析・map・PCM・SHA |
| long | 3分の過渡音素材と5分の持続音素材、全8形式 | 1.5/5.125秒、曲の半分+0.031秒、EOS−0.020秒、EOF | 全7速度。固定mapはpreset共通 | 解析・map。**PCMは未実施** |

全7速度は0.40/0.50/0.75/1.00/1.25/1.50/2.00。長尺は4秒の人工パターンを反復した入力で、自然な3分・5分の楽曲ではない。specialの形式範囲を全8形式へ一般化しない。

### 実測結果

- 27入力、124個の解析snapshot。全フィールド比較と閉鎖済みmapのassertionはすべて成功。速度/preset重複を除くmap比較は868件。
- shortは448件のPCM比較。非EOSの336件すべてで、**非空の確定cropがビット/SHA一致**。
- specialは168件のPCM比較。非EOSの非空cropは48件で全件一致。無音等の空cropを成功件数に加えていない。
- 合計**384件の非空・非EOS cropが完全一致**。全曲末尾の同一性対照は154件で、PCMフレーム数・全サンプル・SHAが一致した。
- naiveな部分WAV全出力は、非EOS462件中414件で共通出力範囲のPCMが不一致。shortだけなら336/336不一致。残り48件の一致を、任意素材の保証にしない。
- longは560行の速度別snapshot比較を完了。非EOS448件中324件で、閉鎖境界より先のnaive mapが変化した。これは長尺の全PCM一致件数ではない。
- 最初の検出/イベント/アンカー差の添字、mapの入力位置・両出力位置、最初のPCM差の出力フレーム/チャンネル間並び順のサンプル添字、比較範囲SHAを各`rows.jsonl`に保存。添字は0始まり、−1はその比較範囲に差がないという意味。

実験プログラムの終了コード0/PASSは「設定した確定領域は不変で、不一致も保存できた」という検証工程の成功を表す。naive方式のPCM正確性をPASSに変換するものではない。

## 4. 具体的な不一致

Float32 Mono 48kHz、4秒の持続音、1.5秒までの部分解析。既存event/anchorは一致し、検出結果は先頭67フレームまで一致するが、その後のmap補償は未確定。

| 速度 | 最初に違うmap node / 入力サンプル | 部分map / 全曲mapの出力位置 | 最初に違うPCM出力フレーム |
| --- | --- | --- | --- |
| 0.50 | 10 / 10,240 | 18,504 / 18,503 | 13,312 |
| 1.00 | 共通nodeに差なし | 同じ | 65,693 |
| 2.00 | 11 / 11,264 | 7,116 / 7,117 | 1,024 |

0.50/2.00では、閉じた最初のeventより後の区間が、部分WAVの仮末尾と全曲の後続eventで異なる補償になる。FIR/窓の未来参照により、PCM差はmap差の出力位置より前から現れ得る。等倍でも部分末尾の窓・合成終了状態は本来の続きと異なる。この結果は、解析時間の長さやmapの一致だけでPCMを公開できないことを示す。

証拠：`special/sustained_3_1_48000_4/rows.jsonl`。例えば0.50の共通範囲SHAは全曲`28a52b16a46114e4b8b1710c957bba9a2bab4dd69f9e74ad2eec1b24564b8945`、部分`c1c5004235c910334588e2554fd16f9397fb7cf0a128d2f923e3d4c477c0f4d1`。サンプル1個の差も不合格として保存した。

## 5. 全曲解析A/Bの起動性能

macOS arm64 Release、同一の290秒PCM16 Stereo 44.1kHz入力、0.50倍速。入力は既存10秒MIXを0.25倍してPCM16へ量子化・反復した別fixture。無clipping、元音源は変更していない。Merodoaで測定した自然音源そのものではなく、過去の800.79/657.53msとの同一音源比較ではない。レシピとSHAは`input/manifest.json`。

Aは既存prepare→playの同期呼出し、Bは**同じ処理を`std::async`で包み、同じ再生可能条件まで待つ**。各preset・方式を5プロセスで測定し、各プロセスの初回（解析cache Cold）と再準備（Warm）を保存した。合計40件、順序を交互にした。ほかのDSP検証は同時実行していない。OSファイルcacheはpurgeしておらず、ColdはOS Coldを意味しない。

「再生可能」は既定FIFO先行量を満たして`play()`が戻る時点。実機callbackでも物理可聴時刻でもない。

| preset / 解析cache | A 中央値 / 最大 / 母標準偏差 ms | B 中央値 / 最大 / 母標準偏差 ms |
| --- | --- | --- |
| Candidate Cold | 744.730 / 766.454 / 11.393 | 738.612 / 744.326 / 3.279 |
| Candidate Warm | 38.656 / 39.756 / 0.476 | 38.608 / 38.940 / 0.149 |
| Baseline Cold | 738.480 / 752.986 / 8.905 | 737.151 / 738.483 / 2.218 |
| Baseline Warm | 32.214 / 33.967 / 0.766 | 32.054 / 32.575 / 0.243 |

BのCold受付応答中央値はCandidate0.013ms、Baseline0.011msだが、実際に再生可能になるまでは約738ms待つ。全曲解析の依存が消えたとはしない。数msの差から一般的な開始高速化・統計的有意差を主張しない。

Candidate Coldの内訳中央値：A prepare704.932ms、解析679.398ms、prefill39.001ms。B prepare699.636ms、解析673.500ms、prefill38.899ms。親子区間の中央値は加算可能とは限らず、重複する段計測も加算しない。

Candidate Coldの開始→最初のオフラインpullまでのプロセスCPU中央値はA0.744134秒、B0.739235秒。解析所有容量とcache residentは全40件579,995bytes、Warm解析は0秒・hit・analysis_runs=1を維持した。Cold Peak RSS中央値はA18,628,608bytes、B18,644,992bytes、Cold worker最大処理時間中央値はA12.492ms、B12.337ms。最大・母標準偏差も`performance/summary.json`に保存。

不足フレーム・書込拒否は40件とも0。ただし先行蓄積後に512フレームを一度だけ読む開始試験であり、全曲の実時間供給試験ではない。RSSはそのプロセスの最大値で、WarmにはColdの履歴が含まれる。

全曲解析完了はprepare戻り時刻で「この時刻までに完了」を観測した。内部の解析だけのwall/CPUと内容識別時間も保存した。最初のPCM生成の正確な瞬間、実機の最初の有効callback、物理可聴遅延、callback deadline missはこの測定では**未測定（null）**。オフラインpullの値で代用しない。

C/Dの正しい製品相当の開始時間は未測定。仮EOSで速く始められても、PCMが不一致なら高速化の成功とはしない。

### 解析領域とコスト

既存`phase54_startup_probe`のprepare-only経路を使い、別プロセス各5回で追加測定した。上のA/B測定・Golden・CTestとは競合させていない。

| 領域・入力 | 解析wall中央値 ms | 解析スレッドCPU中央値 ms | 解析所有容量 bytes |
| --- | ---: | ---: | ---: |
| 1.5秒・Float32 Stereo 44.1kHzの人工素材 | 4.4393 | 4.4393 | 3,915 |
| 2.5秒・同素材 | 6.2100 | 6.1989 | 5,835 |
| 3.5秒・同素材 | 8.6520 | 8.6522 | 7,595 |
| 4.0秒・同素材 | 9.8125 | 9.8127 | 8,515 |
| 290秒・上記性能用PCM16 MIX反復 | 680.3038 | 679.7313 | 579,995 |

prepare全体のwall/プロセスCPU、Peak RSS、各値の最大・母標準偏差も`analysis_cost/raw.json` / `summary.json`へ保存した。Peak RSS中央値は約9.98〜10.40MBで、合成を開始しないプロセス全体の値。所有容量はcache用データ等の推定を含み、RSSとは異なる。

**短い解析領域の解析自体は短いが、その領域すべてのPCMが確定するとは限らない。** 表は別々のprefixの全解析であり、増分状態のチャンクサイズ別性能ではない。実験のように追加のたび先頭から再解析すれば総CPU量が増えるため、その方式を実用性能の根拠にしない。

## 6. ビルド・回帰・資産監査

Releaseの全ターゲットをビルドした（`build_all.log`）。決定論的CTestは**77/77成功、443.31秒**（`ctest_deterministic.log`）。Phase54のcache/160条件seek PCM、L1/L2、EOS、旧来の合成・計測回帰と新規2試験を含む。アプリコアの**Golden25/25はraw float32 PCMのフレーム数・SHA一致**（`golden/summary.json`）。既存WAVファイル全体の一致監査とは分けて扱う。

最後にイベント連鎖の反例入力を0〜1内のfluxにしても成立することを確認し、専用targetを再ビルド後、Phase55の2試験を再実行して2/2成功（`ctest_phase55_final.log`、1.31秒）。DSPや合否基準の変更ではない。

開始後の読取り専用監査は、Phase54 HEADで追跡済みの既存ファイル（意図した追加だけを行うCMakeを除く）**6,516/6,516一致**、既存Goldenファイル全体SHA **30/30一致**。これはアプリコアのGolden25件PCM再生成照合とは別の監査である。

全工程後の最終監査も**6,516/6,516・Golden30/30一致**（`protected_final.json`）。既存のソース、テスト、文書、過去results、Golden、handoffタグを維持した。新規実験コードと実行バイナリのSHA-256、コンパイラー、Release/arm64/最適化設定は`environment.json`、範囲別の集計と未保証flagは`VERDICT.json`へ保存した。

今回の独立実時間CTestは**2/2成功、58.19秒**（`ctest_realtime.log`）。`phase44_quality_gate`17.08秒、`phase45_deadline_integrity`41.09秒。閾値は変更せず、ほかのDSP検証と競合させず実行し、構成を`TIMESTRETCH_ENABLE_REALTIME_TESTS=OFF`へ戻した。この1回の既存経路の結果は、Phase54の保存済みFAILを取り消さず、未実装の段階解析workerの供給性能も保証しない。

初期の専用targetビルドはCMake再構成前にtarget名を指定したため失敗し、再構成後に成功した。初期の反例テストは、保護中の特定の1nodeに不一致を期待して失敗し、未確定区間で実際に差が生じる最初のnodeを調べる試験へ修正した。両方のログを保持し、音質やPCMの許容誤差を導入していない。

## 7. 安全性・未検証事項

設計上の競合・失敗処理とAPI案は[設計](../../docs/PHASE55_PROGRESSIVE_ANALYSIS_DESIGN.md)に記載する。Stop、Pause/Resume、入力置換、媒体権限、同一入力の並行解析、別曲、cache失効、失敗、EOS、メモリ不足、CPU競合を検討した。新しい段階解析workerを動かしてこれらを合格させたという意味ではない。

未実施・未保証：

- 真の持続状態による増分STFT/検出/アンカー/TimeMap、単一DSPインスタンスへの解析補給。
- 3分・5分の全出力PCM比較、自然な長尺楽曲での網羅、special全8形式。
- 段階解析中の速度変更、L1/L2/safe-densityの世代更新、シーク、Stop/Pause/Resume/入力切替/失敗注入。
- 解析がDSPに追いつく実時間保証、高CPU負荷・メモリ不足・権限失効の段階解析試験。
- 段階解析での実機callback到達、deadline、物理可聴遅延。
- OSファイルcacheのCold試験。他OS/CPU/最適化設定でのビット一致。

既存経路の回帰合格を新方式の未実施範囲へ流用しない。過去の実時間FAILも今回のprefix成功で合格へ変更しない。

## 8. 次Phaseの推奨

まず曲選択時に既存の全曲prepareを専用作業キューで先読みし、再生要求より前に完了させるアプリ案を推奨する。要求後に別スレッドへ移すだけでは同じ待ちが残る。全曲解析そのものの読取/FFT/閾値/アンカーの内訳を測り、演算順を保持する高速化も並行候補とする。

本当の段階解析は、固定速度の内部実験APIから進める。特徴列・検出・event・map・PCMの確定境界を分離し、全曲参照に対する全フィールドと全PCMの完全一致を先に通す。その後に状態を継続する合成、長尺、速度変更、実時間・失敗条件を検証する。公開`prepareAsync`/`preloadAnalysis`案の採用は、それらを満たした後とする。現在のprepareの成功条件やMerodoa引継ぎAPIは変えない。

## 9. 再実行

保存先は毎回新規にする。入力と比較用WAVはgit対象外で、既存入力・Goldenを上書きしない。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j 3
ctest --test-dir build -L deterministic --output-on-failure -j 2
python3 -B scripts/phase55_study.py --suite short --output results/phase55/short_new
python3 -B scripts/phase55_study.py --suite special --output results/phase55/special_new
python3 -B scripts/phase55_study.py --suite long --output results/phase55/long_new
python3 -B scripts/phase55_study.py --suite performance --binary build/phase55_startup_study --input results/phase55/input/mix_290_pcm16.wav --output results/phase55/performance_new
python3 -B scripts/phase55_analysis_cost.py --output results/phase55/analysis_cost_new
python3 -B scripts/phase54_golden.py --output results/phase55/golden_new
python3 -B scripts/phase55_audit.py --output results/phase55/protected_new.json
```

`phase55_performance_input.py`は`results/phase55/input`が存在すれば拒否する初回用レシピ。既存入力がある通常再試験で繰り返さない。`phase55_summarize.py`は上記の標準保存先から範囲を集計し、長尺PCM・速度変更・実時間の未検証flagをfalseのまま保存する。
