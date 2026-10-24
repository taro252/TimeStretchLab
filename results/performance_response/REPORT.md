# 性能・応答改善の実装・検証

今回の評価を確定した。checkpointの失敗は試験条件・参照構成を正して閉鎖した。
CPU悪化を示したhash既定OFFは取り下げ、08もmono1倍の固定n6すべて増加のため性能採用しない。
09とprobe10も棄却した。**性能一式の局所完了はINCOMPLETE**。閉鎖済み機能回帰・公開・
Merodoa既定採用の判定を分け、未承認を有効化していない。

## 対象と識別

基準commitは`5674bd982d98caacaa3e87cdeae5bfc0b01c66ef`、基準ソース台帳SHA-256は
`2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392`。
作業branchは`codex/performance-response`、HEADは上の基準commitのまま。
今回の修正は未commitで、HEADだけを修正版の識別に使わない。

保存済み有界timer候補05の全ソース台帳SHA-256:
`0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e`。
保存場所は`build/performance_response_20261023_01/`（以下B）。
`build_timer_candidate_05/BUILD.json`と`timer_source_05/SOURCE.json`は768ファイルを対応付け、
`timer_archive_05/ARCHIVE.json`は43実行体・10archive・1dylibを保存する。
native共通clientのリンク依存はそのうち9archiveとheap probe dylibである。
影響する追加7targetは`build_d3_regressions_02/BUILD.json`へ分けた（1種重複）。
各buildの前後ソース台帳一致を要求し、失敗したbuildから実行体を採用していない。

現在の候補08の全ソース台帳SHA-256は
`b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94`。
05との差は`ProgressiveMacPlaybackEngine.h`の内部stage hash既定値をONへ戻した1ファイルだけ。
`B/build_native_default_08/BUILD.json`は同じRelease構成の49targetを新しくビルドしPASS。
05のnative性能・応答値を08の測定へ付け替えない。以下の05の値は設定OFFの履歴として残す。

実測環境はMacBookAir10,1／Apple M1／16GiB／macOS 26.6.2 (25G83)、arm64、
Xcode 27のApple clang 21／SDK 27／C++20。主比較はRelease `-O3 -DNDEBUG`。
内蔵装置72、実出力48kHz／512f。各runに実際の装置値・OS・実行体SHA・flagsを保存する。
Debug `-g`（O0、NDEBUGなし）は機能・PCM比較を分離し、RT承認へ転記しない。
実音声、build、重い試験、profilerは直列。CPU率は1core=100%、
`100*(user+system秒)/wall秒`。p95は`(N-1)*.95`の線形補間。

Merodoaは`c6ed9251fe6e6bb518039aa03332794dd72cea0c`、依存は
`f4f0e6187a643d9442216df87c04353eda4934e5`のまま。本体・gitlink・既定engine・承認SHAは変更しない。

## 修正した挙動と設計

- 位相合成の重複polar、左右処理で重複していた入力abs/argだけを共有する。
  alias／低振幅／DC／Nyquist／任意owner／復元時のfallbackと演算順を維持した。
- 内部stage hashを設定可能にした。native既定OFFは全体CPU悪化を実測したため撤回し、
  現在の08では既定ONへ戻した。入力SHA・有限性・最終PCM監査を維持する。
  明示OFFは研究設定で、CPU改善・製品採用を承認していない。
- 確定Mapを不変ページで共有し、解析延長ごとの全Map再生成・履歴再submitを除いた。
  新規要求のPlanは既存Phase39の算術・L1/L2・密度・確定範囲で判断し、
  診断側では旧全履歴方式と全field／全ノードを別に比較する。
- InputLeaseに唯一の解析producerを持たせ、旧epoch停止後も置換先へ解析を供給する。
  通常Exactは必要な補間prefixと既存DSP先読み条件が確定すれば全曲final前に開始する。
  Loop保存点／FastLocal／末尾Nのfinal待ちは維持する。最後の購読者のjoin後にFDを解放する。
- 同一identityの準備途中ONは済んだprefix仕事を保持し、完全A状態の完成・旧owner退役後に
  successorへ引き継ぐ。準備IDとLoop IDを別に保存し、終端行を新しい要求へ書き換えない。
  Pauseの静止を優先し、移管後の明示Resume意思は準備と必要な退役の完了まで保持する。
- 入力copy/hash／Float32検査へ取消・受付からの期限を伝える。途中例外ではRAIIで
  FD／mapping／lock／予約を回収する。OSのmlock呼出自体の即時中断は保証しない。
- seek時刻の周期監視を現在targetの1indexと一度のラッチへ変え、4096件の明示履歴と
  終了監査を維持する。長いscheduled Requested境界待ちだけを1msの有界timerにし、
  Started／通常seekは従来待機を保つ。callbackへ通知・確保・mutex・I/Oを追加しない。

既存のFIFO 16,384、短周期RAW 96,000/program、owner／checkpoint各2、予約1GiB、
161速度、Preset、ゲイン、Exact／Golden／3dB基準、期限を変更していない。
リングの剰余演算置換、近似演算、100% bypass、FastLocalへの暗黙変更、
無制限cache、未測定のhandshake lock解除は採用していない。

詳細は[設計](../../docs/PERFORMANCE_RESPONSE_DESIGN.md)、
[調査](../../docs/PERFORMANCE_RESPONSE_AUDIT.md)、
[検証手順](../../docs/PERFORMANCE_RESPONSE_VALIDATION.md)を参照。

## checkpoint失敗の解消

[専用記録](CHECKPOINT_RESOLUTION.md)を参照。追加mono16秒は旧版・候補とも
NoSafeIntervalとなる負例だった。元mix／stereoのApplied肯定試験は維持し、
異速度Map拒否・拒否後の状態不変・Duplicate・独立RAW全suffix・別操作の固定Exact復旧を
3つの固定IDで追加した。Releaseでは3/3、肯定2/2が通過した。
clone suffix計3,039,232fと新速度全1,920,000fを独立固定RAWへ全bit比較した。
この下位層の明示復旧を公開seekの別ID回収や自動Exact切替の証拠にはしていない。

Debug肯定2fixtureと計画52・設定20は通過。Release O3参照をDebug O0へ与えた追加試行は
PCM bit差でFAILとして保存し、保存済み独立Debug oracleで別runへ同構成再検査した。
追加3/3ケースは全bit／count／有限性が一致し、checkpoint状態破損は再現しなかった。
凍結Debug binary SHAは`4ee8f3d61cab5aa7d8b39cb148525d7d81a65061efdfe3ce50d4cdc66f637f3f`。
Debug成功をRelease RTへ転記せず、元のO3対O0失敗も保持した。

## 完了済みの影響回帰

実施ソースを各行の元記録へ保持し、変更のない実行体・依存の対応を
`B/FINAL05_REUSE_AUDIT.{json,md}`で確認した。旧native性能をtimer05で再測定した値とはしない。
新規実行の件数と限定再利用を足して架空の総PASS件数を作らない。
**下表は過去の各sourceで実施した履歴であり、08一括PASSではない。**
08への限定再利用は`evidence/NATIVE08_REUSE_AUDIT.json`の`reuse_eligible=true`行だけ。
`planner72`はNOT_TRANSFERRED、D3の群も監査対象外で、05のnative時間・RTは継承しない。

| 検査 | 期待／実施・結果 | 範囲・限界 |
|---|---|---|
| 固定全161速度・2Preset・8形式・hash設定／chunk | 10,304／10,304 PASS | bfa実行。同じ共有DSP／同じ実行体を対応付け |
| Exact／Golden | 896／896、25／25 PASS | c230実行。凍結参照の全bit／count |
| 固定Loop・有限RAW・reuse | 各322／322 PASS | 161×2Preset、3集合計966jobs |
| 動的全速度 | 640／640遷移 PASS | 独立planner／Map／採用計画DSP、全161速度を実適用 |
| 動的形式・chunk | 32／32 PASS | 8形式、公開途上の確定範囲・延期を含む |
| C1の単体／旧新費用対照 | 52／52項目、72／72program PASS | 全144決定・72Map一致。計画CPUでありRT/PCMとは別 |
| C2標準／Workgroup経路 | 各48／48program、384／384項目 PASS | 各24全suffixを凍結RAW照合。offlineでRTではない |
| C2未開始置換・独立固定参照 | 8／8program・64項目、12／12参照 PASS | 最終producer凍結、旧stop後の寿命 |
| 入力取消・期限・異常 | 12／12program・110項目 PASS | c230。新しい応答時間目標を捏造しない |
| 全履歴監視／独立最終監査 | 30／30program・300項目 PASS | 履歴0/1/100/1000/4095、31,206全field監査行 |
| 通常速度全epoch監査 | 4／4program・56項目 PASS | bfa。Accepted ID終端と凍結後不変性 |
| timer05関連回帰 | 12／12driver PASS | 準備40/320、Paused選択51（内包140）、Clear・連打・F01・独立境界PCM等。選択外はNOT_RUN |
| 起動／長時間高負荷代表 | 起動20／20、180秒素材の2倍・競合2の両Preset PASS | 実再生wall約90秒。bfa実行。timer05の一般RTを旧実行から承認しない |
| FastLocal既知品質 | 102完了、24 PASS／78 FAIL | 26固有条件×3＋24対照。全1080件の再実施ではない |

固定独立oracleはsource `ec087019626d9ff0d9f157245729b74ddb6847d7`由来、
Release binary SHA `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。
動的は`bb22efcbd27f999e8ffe85bbe3f03e20895be3f2`由来の
`1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818`。
製品変更コードで参照を再リンクしていない。入力・参照・validator・各実行体SHAは
個別EXPECTED、`evidence/CORE_GATES.json`と最終manifestに対応付ける。
`Phase62PcmAudit`単独を独立DSP oracleとは呼ばない。

## 性能の局所差分と不採用案

多イベント・履歴4件のC1計画CPU中央値は300秒で102.208→5.801ms、
600秒で402.406→14.111ms（両Preset／履歴0/4／30/300/600秒、旧新n3の72実行）。
原chain300はEOSまでイベントが閉じず増分負荷を作れなかったため専用対照を使った。
これは計画費用だけの結果で、ABやFastLocal品質素材の代用ではない。

Armed待機のCV案は、待機threadが減っても全体CPU中央値13.653→16.327%へ悪化したため
不採用。全6program/48機能・RT検査のPASSを性能PASSへ変換していない。
mutexを追加しない有界timer候補はbfaとのn3交互比較で全3組の全体CPUが低下した。
中央値は18.199→15.817%、待機threadは2.429→1.011%。
20秒窓、6program/48検査、供給／期限／callback禁止操作は全て通過。
統計的有意差を証明したものではなく、このArmed条件での差分比較である。

手動シーク交互比較は各版120件、計48program/240casesを完了し機能／RTは両版PASS。
Ready合算p95は214.552→189.735ms、first PCM p95は222.705→191.264ms。
2倍Candidateの15件p95は240.812→206.476msで未達、200ms超は9→3件。
全体p95が200ms以内でも、この群を平均して消さず未承認を維持する。
FastLocal品質78FAILは旧102件の全数値・PCM hash・座標・countと同じで新規悪化0、
解消0。最大スペクトル誤差3.593187876dB、座標誤差・欠落・重複は0であり別障害へ言い換えない。

## 最終測定と採用判断

05の定常48と、未判定mono1/2倍の固定追加12は全件完了し、機能/供給/期限はPASS。
ただしmono2倍の追加n3は全3組で全体CPUが増えた。併合n6の平均は
20.243423→20.496426%、中央値は20.244516→20.413788%。05一式をCPU改善として
採用しない。mono1倍の併合平均低下やstereo2倍の改善でこの増加を相殺しない。
分岐特殊化06は下位156項目を通過した後、旧/05/06の固定ローテーション9実行を完了。
全体CPU平均は20.659297/21.291055/21.169721%。06は旧版より全3組で増加したため
不採用とし、変更2ファイルだけを05へ戻した。source05の全台帳一致を確認し、
06実行体・archive・source差分・全失敗/成功値を保存した。改善しない実験のため、
最終採用候補としての広い行列は実行していない。

スレッド診断01は6実行/48項目/RTがPASS。旧/05の全体CPU平均は
20.723485/21.247195%、DSP threadは5.815727/5.966722 CPU秒、待機回数は逆に
12135/12066へ減った。追加診断02も6/48/RT PASSで、既存advance/公開区間のCPUは
5.635579→5.870450秒。区間外を含む残差は増えておらず、待機時間の延長を対策にしない。
旧hashがcompilerによって全面除去されていた仮説は実行体の命令確認で否定した。
分岐をblock先頭へ移す07実験も固定9実行を終了し、平均CPU旧21.027914/05の
21.552131/07の21.711305%。旧r1のみRT=falseで原因未帰属のためRT適格な全n3比較ではない。
07は05比でも2増/1減で改善を示さず、不採用・05の全54保存物とソースへ復元した。
元FAIL、07の肯定checkpoint2件、全9観測、archiveは保持する。

同じ保存05ソース・ライブラリによるhash ON/OFFの固定ローテーションは
`steady_digest_cpu_pairs_01`の9実行/72項目を完了し、機能・RTは全件PASS。
mono48kHz Float32・2倍・Candidate・30秒・各n3の全体CPU平均は
旧20.731785%、05 OFF21.303268%、05 ON20.810076%。OFF→ONは全3組低下し、
平均差は−0.493193ポイントだった。これを根拠に既定OFFを取り下げた。
ON対旧は2増/1減、平均+0.078291ポイントであり、改善を立証したとはしない。
詳細profile OFFの通常設定比較で、入力SHAや最終PCM検査の省略ではない。

mono専用scalar対照`mono_vocoder_bench_01`は54/54測定と9/9事前条件がPASS。
主経路4608組、copy継続144組、copy対主経路288組でビット差・非有限値0。
FFT/全曲PCM/native CPU/RTを承認する試験ではなく、全体CPU比較の代用にしない。

freshは元70完了＋容量拒否2件の新規回収を明示し、全72で機能/RTが通過した。
新たに72実行した件数とはしない。coldは全群1000ms未達、A270 stereo1倍の中央値は
32052.69→27518.29ms。nonfresh36も機能/RTが通過したがearly0/midの待ち目標は未達。
独立AB全108capture監査は別実行で540/540項目PASS。遅延未達とは別の判定である。

warm12とPaused deep6の初回回収では、hostがStop後の保存予約見積値をlive予約と
誤認した資源検査で旧/05とも失敗した。元FAILを保持し、close後の独立engineによる
予約再取得を測定窓外で確認する修正版hostで再検査した。単にassertを削除していない。
修正版final08はwarm12/144、Paused deep6/72、別engineによる無再生の予約再取得18組、
warm独立24capture/120項目すべてPASS。probe前/後の費用を分ける。
AB独立108capture/540項目もPASS。元FAILは保持する。
診断sample2は採取完了、候補RTはPASS・旧RTはFAILで原因未帰属。通常性能へ混ぜない。
各driverの命令・全期待ID・期限・実行結果を保存し、失敗も同じ台帳へ残す。

通常CPU、cold AB、warm、手動操作性、品質、RT、資源、アプリFは別に判定する。
cold未達を先行準備後の成功で閉じず、品質FAILを長いprerollやExactへの暗黙切替で隠さない。
物理出音／試聴／Merodoa実アプリF・TCCは未実施。今回の通常native比較の代用にはしない。

## 最終設定08の新規測定

`steady_pairs_native08`は旧5674／08を同条件で48/48実行し、完全性・供給・期限・
callback禁止操作は全件PASS。stage hash既定ON、詳細profile OFF、30秒窓、
4速度×mono/stereo×旧新×n3である。これはrunnerの機能/RT PASSで、CPU採用PASSではない。

| 条件（Candidate） | 旧の平均CPU % | 08の平均CPU % | 3pairの方向 |
|---|---:|---:|---|
| mono48・0.4倍 | 11.128 | 11.067 | 2増/1減 |
| mono48・0.5倍 | 8.337 | 8.471 | 2増/1減 |
| mono48・1倍 | 12.617 | 12.852 | 全3増 |
| mono48・2倍 | 20.262 | 19.943 | 全3減 |
| stereo44.1・0.4倍 | 19.774 | 19.287 | 全3減 |
| stereo44.1・0.5倍 | 17.167 | 16.447 | 全3減 |
| stereo44.1・1倍 | 20.049 | 20.166 | 2増/1減 |
| stereo44.1・2倍 | 23.509 | 21.322 | 全3減 |

mono1倍の増加を他条件で相殺せず、08全体のCPU採用を保留する。
平均が増えた全3条件（mono0.5／mono1／stereo1）だけを追加前に
`NATIVE08_CPU_FOLLOWUP_PLAN.json`へ固定した。追加r04–06の18実行を一度に限り、
元n3の逆順として、併合n6の旧先/候補先を3:3にする。
元48・追加全結果・併合値を残し、結果が良くなるまでの反復はしない。
`steady_followup_native08_01`の追加18/18実行は供給/期限PASS。
併合n6平均はmono0.5倍8.194100→8.246936%、mono1倍12.408514→12.679873%、
stereo1倍20.189001→19.792662%。mono1倍は6pairすべて増加し、08一式は性能採用しない。
各群は記述統計で、CPU範囲の重なりや装置状態のばらつきがあり、因果的な悪化率・
統計的有意差は主張しない。改善の判定はNOT_DEMONSTRATED、性能一式は不採用とする。
08でさらに好結果が出るまで反復しない。後続09/10の保存08対照を事前固定n6へ足さず、
08の広い後続native行列は未実施のまま保留した。

次の小実験09は、内部hash ONのmono1倍に限定して、Phase57のサンプルごとの
条件分岐をblock単位のprivate templateへ移す。旧07のOFF/mono2失敗を成功へ変更しない。
製品root08を保った独立コピー`digest_on_source_09`のsource SHAは
`d38474d21a0484a7e923009474ab39b65b864fae40d9c1e839ea0199cd96a50f`。
差分はPhase57.cppだけで、入力位置・FIR・加算・生成/公開順・状態/ABIは維持する。
初回CMake構成は付属examples不足でFAIL（実行体登録0）として保持し、補助2ファイルを
全byte/SHA付きで追加後の別buildで3targetがPASSした。旧binaryは流用していない。
新実行体の独立固定RAW checkpoint3caseはPASS。CPU9/9は機能・供給・期限PASSだが、
CPU平均は旧12.750547／08 12.730921／09 12.792931%。09対08は2増/1減、
平均+0.062011ポイントで改善せず不採用。`EXPERIMENT09_REJECTED.json`へ固定し、
広い回帰へは進めない。旧07のOFF/mono2失敗をON/mono1成功へ変更していない。

追加の因果切分けprobe10は、Phase36のstage hash判定とPhase57のFIR hash判定だけを
外したON専用の隔離ソース（SHA `4d9b4a1e0ea4e74a3a969abdb59bfd767ec7641101471102fd9cad35463102bf`）。
全hash・数値演算・状態更新・PCM公開の順序を保つが、OFF設定の契約を実装していないため
**製品採用不可の診断用probe**である。独立固定RAW checkpoint3caseはPASS。
旧／08／10の9/9実行は機能・供給・期限PASS。CPU平均は12.813827／12.873548／
12.992661%。10対08は2減/1増でも平均+0.119113ポイントで改善せず棄却した。
ばらつきの大きいn3からB3を単独原因と確定せず、利益のない追加変更を製品へ入れない。

`native08_reuse_audit_01`は現行08の全768ソース、05/08の保存物、現行49実行体を
再確認しPASS_IDENTITY_AUDIT。これは新しいPCM・RT試験ではない。
`checkpoint_native08_recheck_01`では現行08の実行体を新たに走らせ、保存済み独立RAWを
全SHA確認して3/3ケースPASS。参照の新規生成0、元の肯定・Debug結果は保持する。

## 確定した結果と残る局所ゲート

| 対象 | 実施／期待 | 結果と採用範囲 |
|---|---|---|
| 現行08の通常CPU | 48/48＋固定追加18/18 program | 機能/供給/期限PASS。mono1倍n6全増加のため性能一式はNOT_ADOPTED |
| 現行08のcheckpoint | 3/3 case、新規参照生成0 | PASS。拒否後旧suffix計3,039,232f、新速度1,920,000fの独立RAW全bit/有限性 |
| 隔離09のCPU/小回帰 | CPU9/9、checkpoint3/3 | 機能/RT・PCM PASS、CPU改善なしREJECTED。rootへ未適用 |
| 隔離probe10のCPU/小回帰 | CPU9/9、checkpoint3/3 | 機能/RT・PCM PASS、CPU改善なしREJECTED。ON専用診断で製品採用不可 |
| 05→08同一実行体の監査 | 768 source、54＋6保存物、現行49実行体 | PASS_IDENTITY_AUDIT。新PCM/RT実施件数0 |
| 08のInteractive48/240、cold72、nonfresh36 | 0／各期待数 | NOT_RUN。CPU不採用の08を広い候補行列へ進めない |
| 08のwarm12/144、Paused deep6/72、独立warm24/120・AB108/540 | 0／各期待数 | NOT_RUN。05の成功・遅延を08へ付け替えない |
| 08のD3関連12driver、ABI/iOS9検査 | 0／各期待数 | NOT_RUN。05の結果は保存するが08最終native回帰完了とはしない |
| FastLocal品質・200ms・cold1000ms | 既知品質102件、05の応答を保存 | 品質78FAIL、05の2倍Candidate p95=206.476ms、cold未達を保持。08応答未実施 |
| 無音の実行監督dummy v2 | 4/4 case | 限定PASS。timeout/TERM/INT/inner killpgの回収。製品/RT試験へ加えない |
| 試聴・物理出力・Merodoa実アプリF | 未実施 | NOT_RUN。公開・Merodoa既定・物理音響の承認なし |

監督prototype v1はaudit-token APIが利用できず、child開始前のFAILを保存した。
v2のdummy4件はgroup要求抑制と限定回収だけを確認する。`subprocess.run(timeout)`の
内側`Popen.kill()`による孫残留経路が未対応なので、D3/queueへ接続・採用しない。
通常native比較09/10はnested Python driverを使わず、直接childの終了・回収を確認した。
これら試験側の制約を製品音声の障害や正常RT PASSへ読み替えない。

自動承認レビューは、以前の音声試験と重なる後続起動を低容量時に拒否した。
その時点では起動せず、先行完了・容量確保後に直列で再開した。別のENOSPCによる
レビュー初期化不能も保持する。容量不足や拒否をPASSへ変換していない。
新しい全結果は`SUMMARY.json`、`manifest.json`、`evidence/FINAL_GATES.json`へ対応付ける。
索引の整合性PASSは局所全体GOを意味しない。

## 引継ぎ・証拠管理

契約v4のheader／全archiveを同じ候補から再ビルドする。`ContractV3Tag`名の別名は
ソース互換だけで、旧v3 binaryとの混在はprepareリンクで拒否する。
実効機能・24MiB Loop予約・有限観測の一元化、安定理由コード、4096上限時の
全join／退役／closeで終了監査を回収・確認し、新しいアプリ側engine／prepare UUIDで
再準備する復旧契約を維持する。UUIDはprocess内のengineSerialとは別である。
渡すAPIと状態は[Merodoa HANDOFF](../../docs/PHASE62_MERODOA_HANDOFF.md)と
[v4移行](../../docs/PROGRESSIVE_ADOPTION_API_V3.md)を参照。

大容量RAW・WAV・trace・binaryはB以下のGit管理外。旧証拠の内容は削除しない。
完全SHA確認後のhardlink／APFS共有・圧縮は保存パスと全byteを保ち、別監査へ記録する。
Gitには小さいmanifest、hash、実行レシピ、復元方法だけを置く。
消失編集の復元、初回driver不備、誤fixture、build失敗、品質FAIL、ABI試行失敗等は
`evidence/FAILURE_HISTORY.json`に保存し、後の成功件数で上書きしない。
commit／push／履歴書換え／公開リリースは行わない。
