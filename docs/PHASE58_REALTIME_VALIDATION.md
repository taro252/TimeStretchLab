# Phase 58：実機・固定速度検証の読み方

## 測定環境

macOS 26.6.2（25G83）、arm64、Xcode 27.0（27A266a）、Apple Clang 21.0.0。ハードウェアはMacBookAir10,1、Apple M1、8コア、メモリ16GiB（`hardware.json`）。ReleaseとDebugは別ビルド領域で保存する。実機はMacBook Air内蔵スピーカー、device ID 72、48kHz、2ch、512フレーム、ゲイン0.5。各summaryに装置条件を保存する。44.1kHz入力では装置への変換前のraw PCMを比較する。

通常SandboxではCoreAudio装置が取得できなかったため、ホストの実機アクセスで検証した。空の装置一覧を実機測定結果として扱わない。OS・コンパイラー・装置の保存値は`results/phase58/*environment*`、`os.txt`、`xcode.txt`、`compiler.txt`を参照する。

重いビルド・DSP全量試験・ネイティブ再生を同時に実行しない。検証スクリプトも入力・preset・速度の各ケースを直列に実行する。負荷試験の指定した競合スレッドだけを例外とする。

## 正確性と供給期限

決定論的FIFO試験は消費側がPCMを待つ。worker分離、SPSC受渡し、全出力長、全Float32の生ビットとSHA-256を検証するが、実時間供給の成功件数には含めない。

実機検証器は全参照PCMを開始前に読み込み、callbackで取得した全サンプルのuint32ビットを比較する。参照はPhase57以前のPhase36実装をリンクした独立バイナリ。製品式の固定出力長参照と、従来Phase57のmap終端参照を区別する。

FIFO不足では装置への不足領域を無音にし、論理PCM消費位置は実際に受け取った分だけ進める。このためraw PCMが末尾まで完全一致しても、装置側の再生に無音が挿入される場合がある。PCM一致とFIFO不足0の両方が必要である。正常な末尾のcallback残り領域と、再生途中の不足を別に数える。

## callbackの計測

開始・終了時刻、hostTime/sampleTime/flags、要求/有効要求/受信フレーム、論理出力位置、FIFO先行量を事前確保した記録へ書く。処理最大・p95/p99、期限超過、HAL提示期限、時刻・形式異常、記録落ちを出力する。既存Phase46HostClockの判定を流用し、閾値を緩めない。

グローバルC++ new/new[]とaligned/sized/nothrowの組合せを覆い、callbackスレッド内だけをTLSで計数する。これはC++演算子による確保の検出であり、あらゆるC mallocやOS内部確保を観測したものではない。callback自身にObjective-C同期呼出し・ファイルI/O・mutex・DSP・shared_ptr操作を置かない。従来起動測定器の確保数は未計測としてfalse/nullを保存する。

`measurement_valid`には時刻・HALの成立も含まれる。時刻/HAL異常のある実行を集計から除去してPASSにしてはならない。すべての実行を残し、PCM、供給、callback期限、時刻、測定欠損を個別に評価する。機能未実装や実機操作未実施はfalse/未検証であり0件成功ではない。

worker.csvには各公開ブロックの経過・CPU時間とWAV/FFT/位相/OLA/FIRの段階時間を保存する。公開間隔は背圧・Pauseも含むため、その最大値だけでDSP停止原因を決めない。解析作業CPU、監視込み解析thread CPU、advance作業CPU、合成thread全CPUも区別する。無効化した段階プロファイルは未計測である。

初期版のraw summaryで`analysis_done=false`の場合、`analysis_cpu_s`とsnapshot統計の0は完了時統計の初期値であり未計測。集計ではnull/対象外とし、解析完了した件数nだけで統計を作る。監視込み解析thread CPUとprocess CPUは停止までの実測であり、残りの全解析費用を含まない。起動用の約1秒再生を、全曲CPU量の比較とは扱わない。

修正版の診断JSONは`analysis_cpu_measured=false`/`analysis_storage_measured=false`とnullを直接出力する。初期raw記録の0は上記の通り解釈し、原記録を改変しない。

## 保存する検証範囲

| 保存先 | 範囲 |
| --- | --- |
| `pcm58_short` | 全8形式、過渡境界/持続/連鎖、代表7速度、両preset、3チャンク |
| `pcm58_all_speeds` | 全8形式、161固定速度、両preset、2チャンク |
| `pcm58_long` | 3分境界・5分連鎖、代表7速度、両preset、2チャンク |
| `native_gate_product_final` | 全8形式の境界素材0.40/1.00/2.00倍、30秒MIX代表7速度、両preset、実機EOSまで |
| `startup_final` | 30秒/3分/5分MIX、0.50倍、両preset、各5回の従来/新経路Cold・Stop→Play |
| `lifecycle_load_final` | Pause/Resume、EOS→新規Play、装置変更を模した停止、30秒MIXの9速度を各3秒・2競合thread/128MiB、無音/持続/連続attack/連鎖 |
| `native_long_final` | 3分境界Candidate0.40/Baseline2.00、5分連鎖Candidate2.00/Baseline1.00、実機EOSまで |
| `notification_lifecycle_final` | 通知所有権だけを修正したバイナリで通知停止/Pause/Resume/EOS再開を再試験 |
| `reproduce_*` | 通常負荷で不足したケースの独立再実行・段階計測 |
| `ready_stress` | 同期修正後の短尺EOS反復1,000回、PCMとReady通知遅れを別々に判定 |
| `startup_after_ready_fix` | 最終同期修正版の起動比較30組を再実施 |
| `reproduce_after_ready_fix` | 最終版の通常負荷不足条件を20回追加で再試験 |

CPU競合と128MiBの保持は有界な人工負荷であり、OS全体のメモリ逼迫を検証したものではない。長尺実機は上表の4条件であり、全形式×全速度の長尺実時間保証ではない。機能停止のため、動的変更を伴う負荷・ライフサイクルは未実施。物理デバイス/サンプルレート切替も未実施で、`route`モードは安全停止の模擬だけである。

起動/固定行列/負荷/長尺の160セッションは保存した測定版の実行。装置通知と破棄の競合への所有権修正後、8セッションのライフサイクル再試験を別バイナリで行う。両版のSHAと結果を分ける。通知修正はcallback・DSP・FIFOの算術を変えない。

固定行列の途中でReady通知の取りこぼしを発見した。準備完了約17〜39msに対し、検証プロセスが約60秒待つ例を23件保存した。経過時間は連続する参照/FIFOログのファイル時刻差による推定。状態更新と待機を同じmutexで保護し、修正版では`ready_wait_s`/`ready_return_s`/`ready_notification_lag_s`を直接計測する。通知の修正前行列を`*_before_ready_fix`へ保持し、最終行列へ合算しない。以後の8件のライフサイクル、起動30組、通常不足20回はこの同期修正・通知所有権修正を含む版で実施する。

## 失敗を残す

`native_product`の境界PCM16 Stereo 48kHz・2.00倍・Candidateで不足2048フレームが発生した。同じ入力の`reproduce_fifo`は新経路9/10成功・旧固定製品5/5成功。`reproduce_stages`では19/20成功。入力の非公開複製と監視分離後も`reproduce_private_input`で19/20成功、不足10,240フレームが残った。最終行列で成功するケースが増えても、この未解決事象を取り消さない。

非公開入力版の失敗では、位相処理区間の経過約201.7msに対しCPU約23.3ms。解析は最初のcallback前に完了していた。元入力検証・解析競合だけが原因とは言えない。OSによる非実行と内部待ちの内訳は未測定である。通常pthreadのQoSだけで供給期限は保証できていない。

初期の`native_gate_v2`はBaselineの蓄積上限修正前、`native_gate_final`はPhase57のmap終端長契約である。中断記録・適用範囲を保存するが、最終の製品互換成功件数には合算しない。

Phase54の過去の実時間FAIL（phase44、最大起床遅れ42.1952ms、期限5件/2560フレーム）は削除しない。今回も同じCTest条件・閾値で実行し、結果を別に保存する。故障注入を検出したテストの成功を、実機の通常再生成功とは解釈しない。

今回の既存実時間CTestは2/2成功した。一方、従来製品の実機smokeはCandidateが計測FAIL、BaselineがPASS。Candidateもraw PCM・FIFO不足・処理期限は正常だったが、epoch 1のcallback 2でhost進行誤差12,069,728ns、sample進行誤差532フレームがあった。`legacy_native_candidate_clock_analysis.json`へ既存基準による再計算を保存した。バイナリは開始時と同一で、原因は未特定。SRC初期動作などを断定せず、判定条件を緩めない。

## 起動時刻

新経路は音源受付相当のコンストラクター開始を原点とし、検証・内容識別/複製・解析開始・最初の閉鎖event公開・確定map公開・最初の生成/公開・既定先行量到達・AV構築・Play要求・AV開始・最初の有効callback・解析完了を保存する。event/map時刻はworkerがsnapshotを公開できた時刻である。

Mach時刻とsteady時刻は前後計測の中点で接続し、不確かさ1ms以下を起動計測の成立条件とする。従来側は既存計測を用いる。複数回の中央値・最大値・母標準偏差は`statistics.json`。新旧のPlay要求位置はReady成立後なので、受付→callbackとPlay→callbackの両方を比較する。

`play_requested_s`はAVAudioEngine開始APIの呼出し直前、`audio_started_s`は正常復帰時刻。最初のcallbackがAPI復帰前に動く場合もあり、この順序だけで時刻異常とは判定しない。従来側もPlay呼出し前と復帰を分ける。

最初の有効callbackはスピーカーの可聴開始時刻ではない。物理ループバック測定は行っていない。

Coldは新規プロセス・解析キャッシュmissであり、OSのファイルキャッシュ消去はしていない。独立参照を生成後、各回で従来A→新経路Bの順に実行した。装置起動やOSキャッシュに対する順序の影響は独立評価していない。
