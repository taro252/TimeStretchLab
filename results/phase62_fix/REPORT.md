# Phase62 Fix 実装・検証報告

一般公開／Merodoa既定採用はNO-GO。現在周期の途中の動的速度応答は未実装。未達仕様を削除せず、固定再利用、同期、安全停止、周期長の修正と分けて判定する。

開始点は `main@d25433c88a1bae83b89168a26f1c6c9d8053a644`、開始差分なし。親コミットへ戻さず、Merodoaの `c52fde5c06a56fe7acf74617bb90583dfdb9dcf1` と作業ツリーを維持した。今回コミット／Push／履歴書換え／LFS移行は行わない。旧成果 `results/phase62` と `build/phase62/run_01` を維持する。

## 修正した原因と実装

1. Pauseの状態観測とinactive公開の間にcallbackがStartedへ進める競合を、要求／応答の原子同期へ変更した。通常側ゲートで実renderを駆動し、末尾1／64フレームだけの部分混合を再現した。未開始は予約を保持、開始済みは完了してから静止する。
2. span内部の短い読出しを外側の完了位置に含めたため、安全用0が数え落とされた。512要求・100受領・412paddingを再現し、旧／新入力missing、必要入力の出力影響の和集合、安全停止paddingを分けた。Clear継続の検出漏れと元の失敗理由の消失も修正した。
3. functional_passだけの抽出と成功件数の固定記述を廃止した。事前台帳、全件状態、CTest実XML、PCM実測行、全ビット比較、非有限値拒否、ソース／実行体／入力／oracleのSHAを関連付ける。途中変更、0件、欠落、古い出力を成功としない。
4. 同一区間・同速度は永続worker、不変Map、完全Exact状態または最大96000出力フレームの短区間RAWを再利用する。毎周のA以前再合成、thread/join、FFT plan作成を廃止した。長区間は有限FIFO16384で流し、全曲PCMは保持しない。追加24MiBも予約へ含め、稼働DSP最大2、予約1GiBを維持した。
5. 入力100ms以上・確定出力周期512以上とし、最大4096callback内の複数境界を固定容量32spanで処理する。論理epochとDSP所有者を分離した。
6. 自動反復の時間的重畳L−Nを廃止し、局所smoothstep補正で周期Lを保つ。RAWと窓外を維持し、独立RAW＋独立数式と照合する。ゲイン0.5は維持する。ClearだけはBから通常継続する別の既存5ms混合契約である。
7. 短区間のB完全状態と未公開PCMを保存し、同速度Clearで曲頭prefixの再合成を避ける。条件不一致は通常Exact準備へ戻す。
8. 永続する自己反復の有効PCMを残し、未開始の置換用ArmedをLatest-Winsで再準備できるようにした。clearPendingの理由付き速度受付APIも追加した。現在周期の途中の速度変更は未実装であり、Bでの適用のままである。
9. Clear受付時に有効な自己反復を止めていた追加不具合を修正した。継続PCMが準備できてから、末尾加工が未確定の安全なBへ接続する。待機中の実周回は数え、Clear接続は数えない。試験がClear失敗を見逃していた経路も閉じ、解除後の状態と全診断を必須にした。
10. 全spanとcallback全体、Mach／source／deviceの時計、速度要求IDなどを固定容量で保持する。異常前後の記録コピーもcallback期限の計測に含める。旧時計異常の原因は未確定。

主な変更は `ProgressiveMacPlaybackEngine.{h,mm}`、`ProgressiveLoopContract.h`、`Phase58RealtimePipeline.{h,cpp}`、`Phase57ProgressiveSynthesis.{h,cpp}`、`Phase62LoopBoundary.h`。Phase14にはカーソルを進めない読出し、FFTには作成回数計測だけを追加し、既存音声変換の数式は変更しない。再現・再利用・完全保存点・周期の実render試験、Sandboxホスト、事前台帳と独立時計／品質集計を追加した。

## 最終検証の記録

最終固定ソースSHAは `80e9c59efd5910183a6ac90d346c65dfc10f499ab16eba657fb54c705162e3d9`。ソースにCMakeLists.txt、src、tests、scriptsを含む。最終Release／Debugは `build/phase62_fix/run_01/final_v9/{release,debug}（同じ製品コードのfinal_v8ビルドへリンク）`。品質スクリプトだけがF8から変わった。Mixは44.1kHz、Bass／Drums／Guitar／Vocal／Sineは48kHzであり、全既存素材を44.1kHzとする仮定では一部100msが91.875msになった。実WAVのレートを読み、入力A/B・秒数を事前台帳へ記録し、キャプチャのレートとの一致も検査するように修正した。

F8のCMake／製品／C++試験は最終版と同一で、完了済み7スイートが品質スクリプトを使用しないことと、100実行体のSHA不変を明示監査した。旧結果のソースSHAはF8のまま維持し、F9へ自動的に付け替えない。品質と残りのスイートをF9の台帳へ分ける。主試験終了後、Sandboxアプリだけは記録したcodesignで署名を付け直した。最終監査で他99実行体は同じSHA、署名1件はSIGNATURE.jsonの実行時SHAと一致した。以前の100件不変監査の時点と、署名後を区別する。最終実測件数と失敗理由は後段に記す。

## 未達と次の実装

- 長い現在周期を待たない速度反映：Phase59の完全状態を保った生成フロンティアでの受渡し、確定FIFOを維持する交換、動的MapからのB確定、次周期準備を実装する。L1/L2、Latest-Wins、safe-densityを同じ適用履歴の独立動的参照で検証する。単なるフラグ変更では代替しない。
- 異速度境界の独立DSP付き最終キャプチャは未実施。固定全速度RAW、実機の操作監査、同速度の独立加工一致をこの項目の代替合格にしない。
- B直前の手動seekで、通常進入混合より短い残量の一般対応は未承認。入力座標だけで成功保証せず、Bを跨ぐ進入の分割／自己反復との整合を追加検証する。
- 時計異常の保存は最初の1窓33件＋末尾256callback。全異常の全面保存は保証しない。旧44.1→48のhost/sample各1件の根本原因は、反復成功だけで解消扱いにしない。
- 試聴、音響ループバック、Merodoa実アプリのTCC拒否／期限切れbookmarkは未承認・未実施。既存実曲ピアノ素材を追加検証するが、楽器の収録方法は独立確認していない。具体手順は引継ぎ資料を参照する。
- 既存Fast Local長尺78/1080件失敗、既存DSP期限、stereo Ready p95 200ms未達を、固定Exact RAWの合格で解消扱いにしない。

## 証拠、容量、復元

大容量入力、WAV、RAW、trace、実行体、ソースアーカイブ、全台帳はGit管理外の `build/phase62_fix/run_01` に保存する。旧失敗試行も保持する。中断したfinal_v1〜v7は最終版の合格へ付け替えず、INTERRUPTION.jsonとINCOMPLETEを残す。最終SUMMARY、SOURCE_MANIFEST、ARTIFACT_MANIFEST、PROVENANCEに、SHA、場所、コマンド、ビルド条件と復元方法を記録する。

<!-- FINAL_MEASURED_TABLES -->

## 最終実測結果
実機はApple M1 MacBookAir10,1・16GiB、最終ビルドはarm64。主行列の実出力は内蔵装置ID72・48kHz・512フレーム。入力レートの網羅と実装置レートの網羅を区別する。CTestの件数は実XML、以下の台帳件数は実際の期待ケースと終了結果から集計した。

| 検証 | 結果 | 意味 |
|---|---|---|
| Release／Debug CTest | 33/33 ／ 33/33 | Phase59動的PCM、Phase60寿命、Phase61同期・seek・退役を含む既存回帰 |
| 固定独立RAW | Exact896/896、Golden25/25 | 全ビット比較、非有限値は別に拒否 |
| 有界RAW96 | 有限96/96＋再利用96/96 | 既存条件を維持 |
| 全161速度×2方式 | 有限322/322＋再利用322/322 | 48kHz Stereo Float32。全入力形式の総当たりではない |
| Release主行列 | 53条件・530周、機能／RAW／周期／実時間すべて通過 | Clear後の診断も含む |
| 100ms実機 | 48条件×10周＋独立時計48件 | 6代表速度×4形式×2方式、最大callbackは別のオフライン行列でも照合 |
| 長いA実機 | 12条件×100周 | 同一300秒素材、A=0/30/270秒、100/500ms、2倍、2方式 |
| 長期実機 | 100周／1000周、Release／Debugとも通過 | 1000周を4100境界オフラインで代替しない |
| 基本長区間 | 2秒の.4/1/2倍、10秒／30秒の2倍 | 実機5条件、各4周。全曲は主行列にも含む |
| オフライン境界 | 8形式×24条件＋4100境界 | callback64/128/512/4096、有限履歴。実時間の承認ではない |
| 品質キャプチャ | 176/176、RAW／加工数式／finite一致 | 176条件の入力A/B・レートも一致。主観音質の承認ではない |
| 既存実曲ピアノ | 16/16 | 30秒48kHz Stereo Float32の既存素材。楽器の収録方法は独立未確認 |
| Pause／供給不足 | 実renderの末尾1／64フレーム競合、512要求100受領412padding等を通過 | 製品callbackに待機やテストバリアを追加しない |

### 全スイートの台帳
PASSはそのケースに宣言した検査の成功であり、音質・公開・時計異常0など全ゲートの一括承認ではない。たとえば時計再計算のPASSは、記録と独立再計算の一致を示す。

最終F9実行ドライバーは20件中PASS13／FAIL2／NOT_RUN5／INCOMPLETE0。F8で完了した7件は別の元ソース台帳を保ち、依存関係と実行体不変の監査で適用した。ドライバーの状態は子スイート全体の状態であり、機能とRTは下位の別ゲートで確認する。

| F9ドライバー全件 | 状態 | 未実施理由／失敗理由 |
|---|---|---|
| dependency_audit | PASS |  |
| release_controls | PASS |  |
| release_long | PASS |  |
| release_step1 | PASS |  |
| release_offline | PASS |  |
| release_short | PASS |  |
| release_longA | PASS |  |
| release_clock | PASS |  |
| release_deadline | PASS |  |
| release_quality | PASS |  |
| debug_native | FAIL |  |
| debug_controls | FAIL |  |
| debug_long | PASS |  |
| release_cli | PASS |  |
| current_cycle_dynamic_speed | NOT_RUN | 動的Mapとbounded B確定の統合が未実装。フラグ変更だけでは代替しない |
| different_speed_independent_capture | NOT_RUN | 異速度境界の独立DSP付き最終キャプチャ試験は未実装 |
| subjective_listening | NOT_RUN | ユーザーの試聴承認なし |
| acoustic_loopback | NOT_RUN | 物理的音響ループバック測定装置を使用していない |
| merodoa_tcc_bookmark | NOT_RUN | Merodoa本体変更は対象外。実アプリのTCC拒否・期限切れbookmark未実施 |
| dependency_audit_after_main | PASS |  |

| 主スイート | PASS | FAIL | NOT_RUN | INCOMPLETE |
|---|---|---|---|---|
| debug_controls | 13 | 2 | 0 | 0 |
| debug_ctest | 4 | 0 | 0 | 0 |
| debug_long | 7 | 0 | 0 | 0 |
| debug_native | 104 | 5 | 0 | 0 |
| release_clock | 43 | 0 | 0 | 0 |
| release_controls | 15 | 0 | 0 | 0 |
| release_ctest | 4 | 0 | 0 | 0 |
| release_deadline | 7 | 0 | 0 | 0 |
| release_exact | 4 | 0 | 0 | 0 |
| release_golden | 4 | 0 | 0 | 0 |
| release_long | 7 | 0 | 0 | 0 |
| release_longA | 27 | 0 | 0 | 0 |
| release_native | 109 | 0 | 0 | 0 |
| release_offline | 12 | 0 | 0 | 0 |
| release_pcm | 291 | 0 | 0 | 0 |
| release_pcm161 | 969 | 0 | 0 | 0 |
| release_quality | 532 | 0 | 0 | 0 |
| release_short | 99 | 0 | 0 | 0 |
| release_step1 | 8 | 0 | 0 | 0 |

| 追加スイート | PASS | FAIL | NOT_RUN | INCOMPLETE |
|---|---|---|---|---|
| deep_independent | 16 | 0 | 0 | 0 |
| deep_long_seed | 7 | 0 | 0 | 0 |
| exact_finite | 113 | 0 | 0 | 0 |
| paired_1000 | 2 | 2 | 0 | 0 |
| sandbox_evidence | 6 | 0 | 0 | 0 |
| waveform_analysis | 176 | 1 | 0 | 0 |
| post_clear_clock | 194 | 0 | 0 | 0 |
| fd_lifetime | 4 | 0 | 0 | 0 |
| listening_pack | 44 | 0 | 0 | 0 |
| piano_quality | 44 | 0 | 0 | 0 |
| piano_waveform | 16 | 1 | 0 | 0 |
| piano_listening_pack | 4 | 0 | 0 | 0 |
| clock_startup_extended | 303 | 0 | 0 | 0 |
| preserved_clock_audit | 1 | 0 | 0 | 0 |
| inside_seek | 15 | 0 | 0 | 0 |
| boundary_methods | 192 | 1 | 0 | 0 |
| figure_repair | 3 | 0 | 0 | 0 |

`waveform_analysis`／`piano_waveform`／`boundary_methods` の元の図生成失敗は、描画用matplotlibが未導入だったためで、元の失敗台帳を保持した。数値176／16／192条件を成功として残し、図だけを専用依存フォルダと新しい `figure_repair` 台帳で再生成した。音声試験や失敗したRT試験を再実行して成功へ置き換えていない。

### 再利用、初回準備、CPUとメモリ
旧版と新版の制御した直列1000周比較は、同一入力SHA `7ec3f2aa3c2e746643d24cfbda653bdde6eaedc9dd82be6a9ca7159372fe26ce`、A=17/B=24017、2倍、Candidate、Release arm64、装置ID72・48kHz・512で行った。旧版は約152.75秒で「次周期PCM不足またはcallback上限超過」により安全停止し、結果JSONを生成しなかった。新版は1000周を完走した。双方の装置設定は前後一致したが、旧版の完走CPU値がないため、制御した比較のCPU改善率は算出できない。診断文だけでは不足と上限超過のどちらか、またスケジューラ等の根因までは特定できない。

| 走行 | CPU秒 | 経過秒 | CPU使用率 | 準備回数 | 周期契約 |
|---|---|---|---|---|---|
| 旧・初回保存の成功1000周 | 80.675300 | 244.439000 | 33.004% | 1002 | L−N |
| 新・最終主試験1000周 | 11.796548 | 247.751151 | 4.761% | 1 | L |
| 新・制御した直列比較1000周 | 10.992456 | 247.759712 | 4.437% | 1 | L |

各走行n=1。旧・初回保存の成功は同じ記録上の入力・範囲・速度・rate/bufferだが、装置IDの前後トレースがないため厳密な対照走行とは区別する。CPU使用率は全プロセスCPU秒÷経過秒×100（1コア=100%）。通常増分再生CPUと旧版の段階別CPUは未測定であり、差のすべてを再合成削減へ因果帰属しない。

新版主1000周はMap構築1、worker生成2、準備1、warm FFT plan生成0、warm prefix破棄0。cold prefix CPU 0.024171秒、初回DSP CPU 0.071064秒、warm生成・コピー・FIFO書込み合計CPU 0.331706秒。warmは先読み分を含む処理合計で、各周のcallback時間ではない。RSSは51,789,824→16,465,920バイト、観測peak 51,806,208バイト。
100周間隔10区間のCPU使用率は平均4.684%、中央値4.674%、p95 5.063%、最大5.075%。これは1周ごとの分布ではない。全プロセスのスレッド観測値は[16, 14, 12, 12, 12, 12, 12, 14, 12, 12, 13]で周回に比例した増加は見られない。DSP生成カウンタの2と、OS／試験スレッドを含む総数を区別する。

| A／区間／方式（2倍） | 初回Ready ms | cold prefix CPU秒 | warm合計CPU秒 | 準備済み再利用周期数 | warm prefix破棄 |
|---|---|---|---|---|---|
| A0_0.1s_baseline | 951.760 | 0.024272 | 0.005793 | 107 | 0 |
| A0_0.1s_candidate | 964.291 | 0.024105 | 0.006229 | 109 | 0 |
| A0_0.5s_baseline | 789.979 | 0.024321 | 0.034605 | 101 | 0 |
| A0_0.5s_candidate | 918.146 | 0.024507 | 0.036027 | 101 | 0 |
| A270_0.1s_baseline | 29838.121 | 28.920271 | 0.008573 | 105 | 0 |
| A270_0.1s_candidate | 29723.057 | 28.995410 | 0.008629 | 107 | 0 |
| A270_0.5s_baseline | 29797.382 | 28.992545 | 0.035527 | 101 | 0 |
| A270_0.5s_candidate | 29980.357 | 29.030174 | 0.035043 | 101 | 0 |
| A30_0.1s_baseline | 4106.337 | 3.262670 | 0.008205 | 105 | 0 |
| A30_0.1s_candidate | 3993.709 | 3.266677 | 0.008508 | 107 | 0 |
| A30_0.5s_baseline | 4031.230 | 3.268437 | 0.034906 | 101 | 0 |
| A30_0.5s_candidate | 4115.523 | 3.260112 | 0.035214 | 101 | 0 |

全12条件で準備1、Map1、worker2。coldはAが後半ほど長く、A270秒のReadyは約30秒であり200ms以内を約束しない。warmはA以前の全prefix再合成を繰り返さず、部分ブロック上限内の復元か短区間RAWコピーを使う。再利用周期数は有限FIFOの先読みを含み、可聴周回100とは異なる。長いAの10秒区間は短区間RAW上限を超える条件でも独立RAWとB継続を照合した。

### 時計とDebugの残る失敗
最終固定Release主行列・長期・短区間・長いA・Clear後の診断ではDSP／callback期限、host／sample診断、HAL窓、不足／padding、Workgroup、callback確保／解放は0。故障注入の意図した停止はこの正常系0判定へ混ぜない。

- normal_44100_to_48000_100: fresh start 100/100、host=0、sample=0、callback期限=0、DSP期限=0。
- normal_44100_to_44100_100: fresh start 100/100、host=0、sample=0、callback期限=0、DSP期限=0。
- normal_48000_to_48000_100: fresh start 100/100、host=0、sample=0、callback期限=0、DSP期限=0。

装置の物理レートは各試験後に元の48kHzへ復元した。旧異常と途中F5の48→48異常は保持し、独立再計算でもcadence／sample各1。F5の最初の2callbackではsource sampleTimeが0→1120、要求512に対して余分608フレーム、host差23.333ms。rawは連続し、render／clock epochは不変、論理出力1024<確定周期11877で最初のBより前だった。SRCだけが原因と断定できない。末尾履歴に最初に残った境界を真の初回Bとは呼ばない。追加300回が0でも旧異常の根本原因は未解決である。

Debug主行列は53条件すべて機能／RAW／周期通過、RTは48条件通過・5条件失敗。DSP期限超過は48kHz Stereo PCM16 Baseline2倍1、music1秒1、music2秒1、music10秒21、全曲10で最終累積34件。操作試験では同Stereo PCM16のCandidate／Baseline各1で2件。Clear前の値を最終累積へ二重加算しない。host／sample、callback期限、不足／padding等は0。Debug長期100／1000周は別に通過したが、この失敗を取り消さない。旧x86_64 Debug全曲121件も別の履歴である。

### 音量、位相、アタックと比較資料
固定RAW、窓外、独立数式の一致と、音楽的な良さを分離する。各品質ケースの10／25／100msは検証済み定常周期を前後へ延長した窓であり、短い周期の物理録音ではない。出力ゲインは0.5。

| 窓 | RMS変化最小 dB | 最大 dB | 数値チャンネル窓数 |
|---|---|---|---|
| 10 | -3.919149 | 13.138103 | 320 |
| 25 | -1.745622 | 11.598755 | 320 |
| 100 | -0.378277 | 10.558765 | 320 |

ピークはゲイン0.5適用後0.706309199、意図しない0フレーム0。最大+13.138103dBは100ms・0.40倍のimpulse_train両方式で、10ms窓のRAW RMS約0.00717588→加工後約0.03256718。周期維持の補正が局所エネルギーを増すため、無音量変化を保証できない。旧−5.548〜+1.084dBとは数式・評価窓が違い、直接の改善値にしない。

1秒文脈のFFTは1Hz間隔で、20–200／200–4000／4000–Nyquist帯域、55Hz／437.3Hzの左右位相、左右RMS・相関、境界差分・傾き、20msの局所差分を保存した。短い5ms FFTだけで低音を承認していない。192条件で、現行補正と周期Lを保ち両端を0にするスカラー減衰案を比較した。減衰案は2つの既存端点を意図して0へ加工するもので、追加無音ではないがアタック・音量低下の危険があり、製品には未実装。比較の技術PASSを採用承認としない。

| 素材・速度・方式 | 10ms現行 dB | 10ms減衰案 dB | 100ms現行 dB | 100ms減衰案 dB |
|---|---|---|---|---|
| impulse_train_100ms_400000_candidate | 13.138 | -8.337 | 10.559 | -2.610 |
| bass_long_1000000_baseline | -3.563 | -4.512 | -0.332 | -0.386 |
| low_sustain_long_400000_candidate | 0.876 | -2.464 | 0.075 | -0.150 |
| stereo_phase_100ms_2000000_candidate | 0.035 | -4.343 | 0.007 | -0.588 |
| drums_long_2000000_candidate | -1.823 | -7.145 | -0.002 | -0.005 |
| piano_real_long_2000000_candidate | -0.006 | -5.140 | -0.000 | -0.187 |

上表は左チャンネルのRAW比。減衰案は現行の増幅を抑える一方、局所音量を下げる。RMS差だけでクリック、位相、アタック、定位を承認せず、採用判断は別に行う。

試聴用には44条件のRAW／現行加工、実曲ピアノ4条件、方式比較6条件のRAW／現行／減衰案を、それぞれ同ゲイン0.5・最低10秒で保存した。短区間はビット照合済み定常周期の反復。注目点は低音の脈動、左右定位、インパルス／打楽器／ピアノのアタック、境界の音量、拍の周期。実際の試聴と音響ループバックは未実施。

比較図は `build/phase62_fix/run_01/final_v9/figure_repair/{waveform_analysis,piano_waveform,boundary_methods}/`、WAVと全数値は元の各スイートにある。描画依存のバージョンはPLOT_DEPENDENCIES.jsonに記録する。

### Sandboxと寿命の範囲
実際に署名したTimeStretchLab専用App SandboxでNSOpenPanelから1つの入力WAVと専用出力フォルダだけを選択し、選択入力をscope中に一度デコード、100ms100周×2方式と13故障処理を実行した。全所有者停止後にscopeを終了し、許可外パスが実際に拒否されることを確認した。別の非Sandbox試験では2所有者が入力親の破棄後も参照を保持し、両方式1000周期後もFD2、最後の所有者破棄後FD0を確認した。非SandboxのFD結果をMerodoaのTCC／bookmarkの代替にしない。

## 9ゲートとStep3
| 番号／ゲート | 判断 | 成立範囲と未達 |
|---|---|---|
| 1 固定・動的PCM | NO-GO | 固定PCMはGO、Phase59既存回帰はPASS。Phase62現在周期内の動的Mapと同一要求履歴の独立PCM照合は未実装 |
| 2 境界・周期長 | 未検証 | 固定同速度のLと累積ΣLはGO。異速度境界の独立最終キャプチャは未実施 |
| 3 操作・同期・寿命 | NO-GO | Pause競合、供給不足、Clear、FD、検証済み中点seekはGO。B直前手動seekの一般対応は未承認 |
| 4 100ms・長いA・速度応答 | NO-GO | 固定100ms・複数境界・A270秒再利用はGO。長い現在周期を待たない速度応答が未実装 |
| 5 Release実時間 | NO-GO | 最終固定主行列・長期・短区間・長いAの観測はGO。保存した開始時host/sample不連続の根本原因未確定。再現0の走行で消さない |
| 6 Debug機能・実時間 | NO-GO | CTest33/33、主行列53機能・RAW・周期はGO。最終Debug主行列DSP期限超過34件、操作試験2件。旧x86_64全曲121件とも区別 |
| 7 主観音質・実音響 | 未検証 | RAW・加工数式・非有限値・比較用WAVと波形を技術検証。試聴・物理ループバックなし。RMS最大+13.14dBを音質承認にしない |
| 8 Sandbox・TCC・bookmark・FD・実アプリ | 未検証 | TimeStretchLab実Sandbox・scope・範囲外拒否・FD寿命はGO。Merodoaの実TCC拒否・期限切れbookmark・実アプリ統合は未実施 |
| 9 一般公開・Merodoa既定採用 | NO-GO | 。上記未達があるため既定フラグ維持。Step3は明示opt-in研究接続と検証済み固定条件のみ |

Merodoa Step3は専用直列キュー、値だけのsnapshot、scope寿命、理由付き拒否、診断表示を確認する明示opt-in研究ブリッジと、上記の固定速度・検証済み位置／形式／装置条件まで進められる。Merodoa本体はこの依頼では変更していない。一般公開、200ms監視の既定置換、Capabilities.seekの有効化は進めない。`allowExperimentalLoops=false`、`publicLoopApproved=false`、`Capabilities.seek=false`を維持する。

次はPHASE62_FIX_LOOP_REUSE.md末尾の生成フロンティア引継ぎを実装し、Phase59同一要求・適用履歴の動的独立参照、L1/L2、動的MapのBと次周期を最大2DSPで照合する。異速度境界の独立キャプチャ、B直前手動seek一般化、時計異常の起動経路調査、Debugの処理期限調整、試聴／物理録音、実アプリTCC拒否／stale bookmarkはそれぞれ別の未達項目として残す。

最終の容量／Git／旧証拠／Merodoa不変更の検査はFINAL_CHECKS.json、全変更ファイルとSHAはCHANGED_FILES.json、全大容量原本のSHA索引はARTIFACT_MANIFEST.jsonから辿れる。ステージ済み検査と、全未ステージ追跡ファイル・未追跡候補の50,000,000バイト境界検査を分ける。コミット・Pushはこの依頼に含めず実施しない。
