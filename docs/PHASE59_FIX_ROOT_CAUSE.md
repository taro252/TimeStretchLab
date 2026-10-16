# Phase 59 Fix 原因調査

基準は `190fbcd1ad9f6cf2e98eccf7d0f3d4cb2dd5e05b`。保存済みの失敗を後続の成功で取り消さない。PCMは音声サンプル列、FIFOは生成順に渡す有限バッファ、Mach時刻はmacOSの音声処理と照合する時計を指す。

## A. 最初のcallbackの時計

旧Phase59 V7のsampleTime 0→1192（要求512、余分680）は保持した。固定済みPhase58 Fix、V7、Phase59最終版、起動診断版を各20回、計80回比較した際は全て正常だった。その後、動的要求を持たない固定速度0.50倍・Float32 stereo 48kHzの診断版で **0→1436、余分924フレーム/19.25ms** を再現した。装置72、48kHz、512フレーム、timestamp flags=7だった。

失敗時の最初のcallbackは6.417µs、次は3.458µs。FIFOは16384→15872で不足0、PCM完全一致、作業期限超過0だった。実際の呼出し開始間隔28.88msと、timestampのレンダー時刻差29.917msを混同しない。AVAudioEngine開始復帰から最初のcallbackまでは8.482msで、正常試行の範囲と重なる。

この症状に速度変更は必要な条件ではない。入力と装置がともに48kHzだったため、44.1→48kHz変換だけではこの再現を説明できない。HAL内部の実際の処理や物理出力の欠落は、当該失敗では未観測である。起動時に正当な不連続が許されるとするAppleの契約も確認できなかった。**原因は未特定、時計の修正完了とは判定しない。**

診断版には構築・接続・形式確定・prepare・Ready・昇格・start要求/復帰の共通Mach時刻、最初のcallback、出力AudioUnitの前後通知を追加した。追加の最初32回の入口記録は、activeになる前のSourceNode呼出しも対象にする。これらは初回2回の除外やepochの付け替えには使わない。

証拠: `results/phase59_fix/CLOCK_REPRODUCTION.json`、`startup_before/`、`build/phase59_fix_artifacts/fixed_probe_clock_repro`、`output_notify_smoke/`。AppleのSourceNodeヘッダー契約は `APPLE_SOURCE_CONTRACT.json` に記録した。

## B. 固定180秒・2倍速の計算時間

PCM16 stereo 44.1kHz、CPU競合2、生成2048を維持した。変更前12試行では期限超過を再現しなかったが、CPU競合なしでも実時間区間が約46.35msまで伸びた。これは周期約46.44msに近い。過去の49.541/48.877msという失敗は有効な証拠として保持する。

段階計測では位相処理を、共有ピーク検出、各チャンネルの位相更新、Stereo補正に分けた。Candidateの指定窓では、位相処理の約83%が位相更新、約14%がStereo補正だった。ブロックの処理フレーム数とCPU時間の相関は約0.924だった。一方、ピーク総数だけが大きいほどCPUが増える関係は、この試行では見られなかった。相関だけを因果の証明にはしない。

コード上の重複を確認し、次を修正した。

- `Phase35PhaseVocoder` が最初のループで求めたFloat32の振幅・位相を、共有ピークへの位相固定でも再利用する。位相の累積・固定の更新順は維持する。
- `Phase35StereoPhaseCoherence` は同じピーク所有者の17ビン近傍を周囲のビンごとに再計算していた。同じ入力を参照している間だけ、直前の所有者の結果を再利用する。近傍の加算順、精度、重みの更新順は維持する。
- 入出力の記憶領域が重なる場合は、途中の書込みが入力へ影響するため、従来の計算を維持する。

位相更新部品の交互5反復ではCPUが約8〜10%短縮した。180秒の同条件2試行では、Stereo細分CPUがCandidateで28.655→23.467ms、Baselineで31.241→24.615msに減った。これは指定窓内の合計であり、1ブロックの最大時間ではない。

| 同じ診断条件、CPU競合2 | 修正前RT最大CPU | 修正後RT最大CPU |
|---|---:|---:|
| Candidate | 28.996ms | 27.117ms |
| Baseline | 28.365ms | 27.722ms |

両方とも全PCM一致、FIFO不足0、作業期限超過0、実時間C++ new 0だった。処理時間は試行間でも変動している。過去の49msの当該区間について、コア・周波数・OS状態まで含む完全な因果は証明できていない。

WAV/FFT/位相/IFFT・OLA/FIRの集約CPU・Wall、実際の区間開始/終了/期限、解像度別のフレーム・ピーク・reset数を保存した。IFFTとOLA、位相累積と位相固定・resetの個別時間、TimeMap補間など全関数の時間を独立に測定したわけではない。個別未計測を0として扱わない。

証拠: `PHASE_BEFORE_ANALYSIS.json`、`PHASE_AFTER_ANALYSIS.json`、`VOCODER_BENCH_*.json`、`phase_before_v2/`、`phase_after/`。元の最大Wall位置と実際の期限判定点を同一視しない。診断版の `intervals.csv` は元の判定に使ったMach ticksを保存する。

## C. 従来製品のFIFO不足

旧Phase59の記録は、Phase59以前の固定実行体によるCandidate smokeの1319フレーム不足である。今回も同じ保存実行体で、Baseline smokeの **8208フレーム不足** を再現した。PCMと時刻診断は合格したが、供給失敗として不合格である。

今回の不足はsession1/epoch1、callback114〜120と125〜135、最初のcallbackから約1.205〜1.429秒だった。0.5/0.6/0.7秒の連続シーク後であり、過去のsession2/epoch2・callback270〜272とは異なる。旧版、Phase59時点の製品実行体、診断版の計12比較に、製品経路の180秒・CPU0/2・両presetの4件を加え、15/16合格だった。

**Phase59以前の実行体で供給停止が存在することは確認した。停止の正確な原因は未特定。** シーク構築とのCPU競合、公開遅延、優先度、キャッシュ・ページングのどれかを、この旧失敗のOS証拠なしに断定しない。旧callbackとseekログは時計の起点が異なり、較正なしに直接引き算しない。

診断版には、通常側の有界な公開位置標本、操作の開始/終了Mach時刻、既存worker profileの停止後書出しを追加した。最初の診断版は共有ヘッダー変更後の再構築対象不整合で失敗したため中断し、関連全ターゲットの再構築と短尺一致を確認してからやり直した。その準備失敗も保持した。

次の旧製品専用Fixでは、シーク準備中に現在の供給workerへ残るCPU時間、公開間隔、FIFO残量を同じ時計で測り、準備処理の取消・同時実行・優先度を調べる必要がある。今回、旧製品の制御方式を大きく変更していない。

証拠: `LEGACY_FAILURE_REVIEW.json`、`legacy_before_v2/`、`MEASUREMENT_PREPARATION_FAILURES.json`。新経路の成功件数で旧製品の失敗を相殺しない。

## D. EOS再始動

Releaseの周期付き排出は2入力でEOS→次のPlayまで完了し、作業期限超過0だった。通常優先度へ戻してからの機能試験も合格した。高速排出は完了したものの、期限超過13/20件、最大非CPU約0.571秒を記録した。Debugの周期付きは完了したが期限超過16/33件、高速排出は不合格、通常優先度の機能試験は合格した。

高速排出の長い非CPU区間では、アプリがdemoteを呼ぶ前に、OS標本がpolicy2・優先度97からpolicy1・優先度0へ変化した。6秒のOSトレースでも、例としてWall278.656msのうちCPU23.702ms、Preempted約254.986ms、優先度Background 0を観測した。実行可能なthreadが実行権を待っていた証拠であり、DSP計算だけが279msかかったという意味ではない。

Appleは、要求量を超えてブロックせず計算を続ける実時間threadが通常優先度へ下げられ得ると説明している。[Mach Scheduling and Thread Interfaces](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/scheduler/scheduler.html)。今回の高速排出と整合するが、カーネル内部の安全策フラグを直接取得したわけではない。**過去の4.8秒停止を同じ原因と証明したとはしない。**

FIFOにある分だけ排出する周期付き試験は、実際のcallbackの供給検査とは異なる。最終実機のEOS反復と、これらの寿命・ストレス検査は別に判定する。高速排出の失敗を消さず、オフラインで排出する場合は実時間の昇格を外すという契約を明記する。

証拠: `eos_before/`、`EOS_TRACE_OBSERVATIONS.json`、`OS_SCHEDULER_SOURCE_NOTES.json`。トレースはrun0で45/149、run1で20/158区間の全状態を確認できた。残りはUnknownまたは取得範囲外であり、正常とは補完しない。

## E. Zero Fill・ページアクセス

元の `PhaseLocker::analyzePeaks` 内のZero Fill 5.708µsは保持した。ピーク配列はreserveだけで、全容量への初回書込みを終えていなかった。新実装は準備時に全容量を構築し、volatile書込みで触れてからclearし、従来と同じ空配列状態に戻す。実時間中の容量増加を導入しない。

ただし、元のfaultアドレスと配列の割当範囲を対応付ける情報がなく、この配列が元のfaultそのものだったと確定できない。また、事前書込みはOSによる後の圧縮・退避を禁止しない。

修正前の追加起動トレースでは96区間中48区間を全状態で観測でき、その既知区間内にDecompress Memoryを24件観測した。C++ new 0はページフォルト0を意味しない。EOSトレースの既知65区間ではVM faultを観測しなかったが、残る242区間へ一般化しない。過剰なメモリ固定やOS制限変更は行わない。

証拠: `clock_audio_trace/manifest.json` とGit管理外の解析データ、`TRACE_ARCHIVE_*.json`。保存bundleはopen FDなしと全ファイルの復元SHAを確認して圧縮した。一時ktraceは使用中のまま移動・削除していない。

## 最終実機回帰での追加観測

動的実機は189/190、正式な新経路274セッションの不合格は1件だった。最初のnormal Candidate・0.50倍では、元V7と同じ入力SHAでsample0→1160（要求512、余分648/13.5ms）を再現した。callback入口の間隔23.896msとtimestamp差24.167msを区別する。速度要求受付より前に発生し、全PCM一致・不足0・作業期限超過0でも時計は不合格とした。

個別の時計差、不足callback、取得できた期限区間は`results/phase59_fix/FINAL_NATIVE_FAILURES.json`。旧製品最終比較は11/12で、過去の1319と今回修正前の8208フレーム不足を取り消さない。

最終旧Baseline smokeにも234フレーム不足（session4/epoch1/callback179、wanted470/received236/fifo236）を再現した。PCM・時計は合格だった。`FINAL_LEGACY_FAILURES.json`を別保存し、このcallback時点のOS状態をworker全体の最大Wallから推定しない。

長いオフライン回帰後の最初の正式Nativeで起きたという順序も調査候補である。ただし、他アプリも含む装置のidle/稼働状態は取得していない。自分の試験の休止時間を装置の休止と同一視せず、次Fixでは休止時間を制御した旧版/最終版比較とHALの失敗時観測で検証する。

追加の最終trace付き再生のNative判定は不合格。正式274音声セッションとは別記する。最終6秒窓の全状態既知は94/155区間、窓内Unknownは61、窓外・部分区間は1777。既知区間のVM観測は{'Decompress Memory': 3}。全区間のfault 0とはしない。指定した元の最大Wall位置付近の7区間は、窓内0区間で未取得。attachの開始遅延により取得位置は後ろへずれた。

追加試行の時計FAILは起動時ではなく、約85.821秒のcallback8016→8017の518フレームの余分な進みだった。直前のIOProcが遅れ、OSはClient Overloadを1件記録した。Native独自のHAL windowカウンター0とは区別する。Client threadの約11.2ms Blockedとdtsecurityによる起床を観測したが、待機の全因果や計測器の関与は未証明。元の初回時計異常と同原因だとはしない。根拠はPOST_TRACE_CLOCK_VM.json。
