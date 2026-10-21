# 停止中の速度変更：検証記録

## 版と実行環境

- 開始 SHA：`406a1fde0b130bbe5ae3ce7a1666cce696db9c99`。main、開始時差分なし。
- 検証対象：この SHA に本件の未コミット差分を加えたソース。HEAD そのものの結果ではない。
- macOS 26.6.2 / 25G83、Darwin arm64、Apple clang 21.0.0 / SDK 27.0、Release、`-O3 -DNDEBUG -std=c++20 -arch arm64`。
- 入力は 3 秒の時刻識別可能なチャープ・非周期インパルス・変化する振幅を持つ PCM16 WAV。44.1kHz mono と48kHz stereo、それぞれ Candidate/Baseline の4条件。短い初回 Ready は2049入力フレーム。
- 実音声は AVAudioEngine/AVAudioSourceNode、Audio Workgroup に参加する実 DSP と実 FIFO を使用する。RAW PCM は固定出力ゲイン0.5と装置側変換の前で観測する。
- 装置は既定出力、48kHz / 512フレーム。最終 Phase62 ネイティブ記録の device_rate/device_buffer に記録した。音響出力時刻は測定していない。

最終判定は PASS（下記の試験範囲）。ソース内容の SHA-256 は `7caa096f33f1a69349e9903c88a7c2bb226e3066ca45ce80c24279ded97c142c`。これはGitコミットではなく、[SOURCE_MANIFEST](../results/paused_speed_change/SOURCE_MANIFEST.json) のソース・試験コード・レシピの内容識別子である。実行コマンドは [COMMANDS](../results/paused_speed_change/COMMANDS.json)、行ごとの比較は [PCM_RESULTS](../results/paused_speed_change/PCM_RESULTS.json)、独立参照は [REFERENCE_MANIFEST](../results/paused_speed_change/REFERENCE_MANIFEST.json) を参照する。

## 完了した確認

| 項目 | 結果 | 条件 |
| --- | --- | --- |
| 全161速度の個別準備・再開 | PASS 644/644 | 4条件それぞれで全値のReadyForResumeを待ち、再開先頭2048フレーム以上を独立RAWと完全一致 |
| 停止中の競合・短い初回Ready | PASS 76/76 | 19種類×4条件。Latest-Wins、A→B→A、再開待ち取消、seek前後、stop、新入力、close、装置変更、失敗、上限4096、EOF、短い末尾等 |
| 原因照合 | PASS | 採用88d5247…と開始406a1fd…、CAUSE_AUDIT.json |
| 通常workerでの準備 | PASS | 元解析未完了、満杯の旧FIFO、DSP完了かつ13フレーム残る末尾、空EOF、取消8回×2 preset |
| 既存関連 CTest | PASS 12/12 | phase59_request_control、Phase60契約、Phase61契約・同期・チェックポイント・安全性、Phase62共通部 |
| 既存Exact独立参照 | PASS 96/96 | 4条件×4速度×先頭/中間/EOF×Standard/Workgroup。全suffixをbit単位照合、checkpoint使用32件 |
| Golden25 | PASS 25/25 | Goldenを読み取り専用で照合。更新なし |
| 速度境界の往復 | PASS 156/156 | 13要求の順序×3反復×4条件、0.40↔2.00、0.49↔0.50、1.00近辺 |
| 再生中操作とpause | PASS 12/12 | Pending/Submitted/Appliedをそれぞれ観測後pause、最新停止速度のRAW一致。さらに後続の再生中速度変更→pause→seekでも過去操作を復活させない |
| 準備中・準備後資源 | PASS 4/4 | FD 6→6、スレッド15→17。停止後FD4/スレッド13の開始値へ復帰 |
| Loop制御互換 | PASS 4/4 | KeepPositionをArmed後にReadyからPlay、境界速度変更中のPaused/resume、解除準備中のPaused/resume |
| 既存Phase60ネイティブ | PASS 2/2 | adapter/lifecycle。Readyの速度履歴照合を新APIへ変更し、Phase59操作を捏造していないことも確認 |
| 既存Phase62ネイティブ | PASS 2/2 | 最新ライブラリへ再リンク後、Candidate/Baseline各10周期、controls、入力・混合・callback資源監査 |

## 独立参照と停止位置

参照は `scripts/phase61_freeze_reference.py` で、Phase57より前の DSP ソース `ec087019626d9ff0d9f157245729b74ddb6847d7` の Phase36 を先にリンクした別プログラムから生成する。旧 Phase13 の全入力解析と Phase39 の固定速度マップを用い、停止中準備の実装やその出力を参照には使用しない。参照ソース・コンパイル/リンクコマンド・実行物の SHA-256 は oracle manifest に記録する。

各速度で ReadyForResume まで待つ。旧 epoch にいる間は consumed が凍結値と同じこと、新 epoch は consumed==outputStartFrame のままであることを確認し、実際に再開して最初の2048フレーム以上を独立 RAW とmemcmpで完全一致させる。epoch/session/inputGeneration、連続output offset、出力spanの非混合、missing無しも確認する。中間位置は整数マップの境界とずれる入力中央+17を用いる。先頭ケースは実再生→pauseの実消費カーソルから開始する。停止中速度準備によるユーザーseek履歴増加は認めない。

EOFは既存の正常終端を許容する。短い初回ReadyではdspDone=trueを確認後、75%→125%を無消費で準備し、再生された全PCMを短い独立参照と完全一致させる。

## コマンドと証拠の保存

主な再現コマンド（保存先は毎回新しく作る）：

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --target paused_speed_native_tests paused_speed_pipeline_tests paused_speed_boundary_tests paused_speed_loop_tests phase61_seek_reference phase61_seek_check phase54_core_probe phase60_adapter_tests phase60_lifecycle_tests phase62_native_tests -j 4
python3 scripts/phase61_freeze_reference.py --build build --output build/paused_speed_oracle_NEW
python3 -B scripts/verify_paused_speed.py --build build --oracle build/paused_speed_oracle_NEW/phase61_frozen_reference --output build/paused_speed_full_NEW --full
python3 -B scripts/verify_paused_speed_controls.py --build build --fixtures build/paused_speed_full_NEW --output build/paused_controls_NEW
python3 -B scripts/verify_paused_speed_regression.py --build build --fixtures build/paused_speed_full_NEW --oracle build/paused_speed_oracle_NEW/phase61_frozen_reference --output build/paused_exact_NEW
python3 -B tests/Phase61Golden.py --probe build/phase54_core_probe --output build/paused_golden_NEW
```

実際の全引数・順序・終了値は各 evidence directory の commands.json と、最終 COMMANDS.json に記録する。

採用する証拠は `build/paused_speed_full_final`、`build/paused_controls_final` の先頭18コマンド、再リンクした `build/paused_phase62_final` の2コマンド、`build/paused_exact_regression_final`、`build/paused_speed_golden_final`、`build/paused_regression_final_v2.log`。controls_final内の旧Phase62実行物の2件は参考のみとし、最終合格には再リンク後の2件を使用する。

制限環境では音声装置を取得できなかったため、ネイティブ試験は装置アクセス可能な権限で実行した。最初の拒否を実機合格と扱わない。入力、独立参照RAW、過去の途中結果は削除しない。Gitへ入れるのは小さいmanifest・集計・レシピ・文書だけである。実測の再開頭部は停止後のメモリ上でmemcmpし、頭部RAWファイル自体は保存していない。PCM_RESULTSのspan SHAは比較した独立参照部分のハッシュであり、別途保存した実測ファイルのハッシュと偽ってはいない。

## 実時間・資源の読み方

4条件とも161件、反復1回ずつ。速度境界の別試験は13要求の順序を各条件3反復した。

| 条件 | 準備時間 中央値 / p95 / 最大 (ms) | 再開要求→最初の有効PCM 中央値 / p95 / 最大 (ms) |
| --- | --- | --- |
| 44.1kHz mono Baseline | 98.8 / 161.1 / 166.2 | 14.9 / 16.8 / 17.8 |
| 44.1kHz mono Candidate | 106.5 / 166.4 / 200.9 | 14.8 / 17.0 / 34.3 |
| 48kHz stereo Baseline | 218.1 / 370.2 / 388.0 | 14.9 / 36.8 / 39.1 |
| 48kHz stereo Candidate | 230.7 / 382.0 / 391.0 | 14.8 / 37.4 / 39.4 |

acceptedNs→readyNs は停止準備時間。resume/play呼出し→観測先epochの最初の有効RAW PCMは別の単調時計で測る。後者はcallbackへの到達でありスピーカーからの音響出力時刻ではない。品質は要求速度値やsineの周波数だけで判定しない。

準備中の追加スレッドは2本以内、共有InputLeaseのFD増加なしを確認した。300msの準備後待機でepoch・archive数・consumedが増えず、CPU消費は4条件で約7.4〜10.0ms、stopは約2.4〜3.2msだった。これらは3秒の入力に対する測定であり一般的な応答時間上限ではない。既存の入力同一性監視・制御監視の待機は残る。全速度試験の最大RSSは69,861,376バイトだった。最終の既存Phase62検証では両presetともcallback内C++ new/malloc/free、missing、worker/callback期限超過、host/sample/HALエラー、Workgroupエラーは0だった。

## 制限・未検証・統合時の要件

- 物理的な出力装置の抜差し・交換は未検証。今回はsimulateDeviceChangeForTestと同じ安全停止経路による旧世代完了の破棄を検証した。
- 音響出力時刻、聴感による総合音質、長尺曲におけるExact準備時間の全条件は未検証。FastLocalの既存の品質制限、Phase62の公開NO-GOを維持する。
- 途中実行 full_01〜03 は取消・検証スクリプトの未生成参照処理の修正・最終ソース統一のための予備記録。最終合格件数へ混ぜない。成功済みの独立参照だけを入力SHAとoracle SHA確認後に再利用する。
- C++ snapshot追加とresumeの受付契約をMerodoaへ接続する必要がある。詳細は[引継ぎ](PAUSED_SPEED_CHANGE_HANDOFF.md)。本体・submoduleは変更していない。
- 統合時には同内容を確定した完全SHAとこの証拠の対応を記録する。埋込み timeStretchLabSha は開始HEADなので、未コミットソースの識別にはSOURCE_MANIFESTとバイナリSHAを用いる。
- コミット・Push・履歴書換え・Golden更新・既存大容量証拠削除・LFS移行は実施していない。


## 2026-10 動的Loop修正の追記

今回の追加実装と新binaryによる検証は [動的Loop設計](PHASE62_DYNAMIC_LOOP_DESIGN.md)、[検証手順](PHASE62_DYNAMIC_LOOP_VALIDATION.md)、[専用REPORT](../results/phase62_dynamic_loop/REPORT.md) を参照する。この文書の旧成功件数を今回へ付け替えず、従来の未解決記録も維持する。

長い非cache Loopは既存producerの完全状態を保持してPhase59の合法な未来へ速度を適用し、採用Mapで現在Bを再確定する。次の固定A→Bは第2所有者で先に準備し、commit後は必要な境界版を保持する。短い既確定区間等の延期理由はLoopSnapshot.speedDeferReasonへ記録する。Clearは明示的な固定Exact継続であり、動的位相履歴のB以後の連続ではない。

Paused新速度は停止後の実位置CからExact再準備し、旧producerの退役完了後にStoppedSpeedState::ReadyForResumeを公開する。要求ID・inputGeneration・Loop・cycle・preparationVersion・位置を照合し、可聴Completedと区別する。Resume/Playの意思、再Pause取消、旧FIFO破棄の専用監査を使う。B直前の進入混合はBで分割し、丸めでR=0の場合も架空のPCMを追加しない。

Merodoaへ渡す側はReadyをResume前に観測し、古いcontext/準備版を再使用しない。LoopSnapshotのdynamicSpeedRequestIDとdynamicOperationID、mapVersion、dynamicCycle、dynamicOutputEndで外部要求と実計画を対応付ける。speedPreparationFailed/speedFailureRequestIDは有効な旧出力を保持した準備失敗を示す。同じ速度の再要求も失敗後は再試行できる。公開初期値、seek公開承認、currentCycleSpeedChangesの一般承認は専用REPORTの未実施ゲートが閉じるまで変更しない。Merodoa本体・UI・submoduleは今回変更しない。

## c4bdbb44以後

[残件REPORT](../results/phase62_finish/REPORT.md) の外部台帳試験は実4096受付境界、拒否理由、開始済み履歴、再開意思を検査する。追加の `phase62_paused_clear_native` は両Presetで初回ReturnToAの採用前/開始後Clear、旧commit＋Preparing→Clear、手動seek置換、Ready→Clear、開始成功済み未PCM→Clearの12条件・24checksを検査する。旧成功件数を新規件数へ付け替えず、同じ最終ソースのmanifest/SHAを参照する。
