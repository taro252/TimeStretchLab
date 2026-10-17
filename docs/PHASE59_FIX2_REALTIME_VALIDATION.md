# Phase 59 Fix 2：実時間検証と観測限界

## 変更の範囲

独立SourceNode再現器、raw時計/FIFO cursor、退役セッションworker履歴、Workgroup寿命ticks、診断配列の準備時write-touch、解析の欠測集計を追加した。時計不連続と旧供給停止の因果が未確定なので、DSP演算・速度変更・実時間policyを推測で修正していない。

Experimental3500、0.40〜2.00の1%刻み161速度、Phase39の50ms遷移、Latest-Wins、L1/L2/Phase50/Phase42 safe-density、STFT/位相/過渡音/OLA/FIR、出力長・Float32生ビット・順序・gain0.5を維持。Phase59 Fixで最適化された6ソースは同じSHA。FIFO容量16384、先行Candidate16384/Baseline12288、生成2048も同じである。

最終候補は`build/phase59_fix2_artifacts/final`に固定した。`FINAL_CANDIDATE.json`に実行体、ライブラリ、ビルド入力SHAを保存し、品質開始/終了と実機開始/終了に照合する。元の固定参照とGoldenは変更しない。

## 回帰の実行条件

PCMの独立比較は並列実行するが、性能評価には使わない。全品質検査後、音声実機試験を直列実行する。Nativeに品質合成・ビルド・トレース解析を意図的に重ねない。システム上の他のユーザープロセスは勝手に終了しない。

必須の動的1140、隣接遷移640（1140の内数）、固定Phase58の6216、Phase57の51344を別集計する。全PCMの長さ・Float32生ビット・順序・SHAを変更前の独立参照と照合する。全161速度を扱うが、161²の全初期/目標ペアを網羅したとは呼ばない。Phase56解析・Phase54 cache/seek・Phase39/42/50/51・所有権/EOS/Cancelは既存回帰を維持した。

Release deterministic CTest93/93、Debug関連18/18、Golden25/25、ThreadSanitizer2件、Address/UndefinedSanitizer4件、容量ガードと時計解析6件を実行。全件のコマンド・終了値・ログは`checks_final`に保存する。Debugの全既存CTestを実行したとは表現しない。最終の完了状態・追加試験は[REPORT](../results/phase59_fix2/REPORT.md)を参照。

## 実時間workerとOS

Workgroup生成、policy適用、join、leave、通常policy復元をraw Mach ticksで追加記録した。[Apple Workgroupの契約](https://developer.apple.com/documentation/audiotoolbox/understanding-audio-workgroups)に照らし、同じ周期の締切を持つworkerの寿命管理と、実際のOS状態を区別する。appが数えたjoin/leave正常だけで全OS期限内を保証しない。

要求なし動的トレースでは、28/28実時間合成区間と113/113 callback本体をOS記録と照合できた。合成区間に重なるVM観測は0。worker全寿命のVMイベントは別にあり、準備中・昇格中・復元後を混ぜて「実時間フォルト」と数えない。`REALTIME_WORKER_TRACE.json`に分母と詳細payloadを保存する。

製品の旧通常workerは新経路のWorkgroup workerとは異なる。旧製品で優先度やOS状態が欠測なら、新経路の28区間の結果で補わない。観測できた短尺から全161速度・全190実機・全EOSのOSフォルト0へ拡張しない。

## EOS再始動

装置周期に従う実機EOS40件と、Release/Debugの通常・周期付き・高速排出の合成EOS試験を分ける。高速排出は実際の10.667ms/512周期より速く供給を消費するため、実機と同じ負荷条件ではない。タイムアウトや期限の値を増やしてPASSにしない。各sessionの昇格/参加/離脱/復元・interval数・Wall/CPUとMach ticksを保存する。

過去の約4.8秒非CPU時間、通常policy復元前のOS降格、Debugストレスの長待機は保護した。過去の観測ではpolicy2/97→1/0がapp復元より前に現れ、最悪278.656msの区間にCPU23.702ms / Preempted254.986msがあった。Machの過大実行に対する降格と整合する可能性はあるが、4.8秒全体の因果は証明されていない。今回の追加成功だけで解決扱いにしない。

今回の6モード12セッションはEOS完了・世代分離・join/leave/restoreが成立し、実時間C++ newは0。期限は以下のとおりで、機能成功と区別する。normalは要求判断後、排出前にアプリが通常policyへ戻す対照である。

|ビルド/排出|期限超過|実時間interval最大|離脱前にpolicy2以外を観測した標本|
|---|---:|---:|---:|
|Release 周期付き|0|30.049ms|0|
|Release 高速|6|253.443ms|1316|
|Release 通常policy|0|実時間blockなし|0|
|Debug 周期付き|44|74.676ms|0|
|Debug 高速|172|532.335ms|7860|
|Debug 通常policy|0|実時間blockなし|0|

`lifetime.csv`のMach括弧とpipeline時刻から、幅210〜461nsの共通時刻変換区間を求めた。取得成功標本がjoin後・leave前に全て収まる場合だけ数えた。高速排出では昇格直後の2/97と異なる1/0を観測したが、連続したOS状態や降格理由は未取得。高速の最悪非CPU残差はRelease232.512ms、Debug456.166msだった。Debug周期付きの期限超過は、この記録ではCPU時間が大部分を占める。全blockの最大Wallには昇格前の準備も含まれるため、その値を実時間期限超過数と同一視しない。`EOS_FINAL_SCHEDULER_REVIEW.json`参照。

## 実時間メモリ

PhaseLocker/位相Scratch/FFT・Accelerate/診断・captureを区別して調べる。新診断版ではcallback記録/capture配列へ昇格前にvolatile write-touchした。これは初回の未割当ページを減らす準備であり、後の圧縮・再ページインを禁止しない。登録したメモリ領域の範囲はCSVに明示した。Accelerate内部と全DSP scratchの全割当領域を網羅したものではない。

以前のPhaseLocker Zero Fill 5.708µsは具体的な所有領域を確定できていない。途中のDecompress Memoryも観測したが、異常の長待機全体を説明していない。全領域mlockは適用していない。callback内のnew0はmalloc/OS/圧縮復帰まで全て否定する値ではない。

## 証拠の保存と容量

大きなWAV/Float32/trace/XML/固定実行体はGit対象外の`build/phase59_fix2_artifacts`に保存する。元のPhase59/59Fix/Golden/固定参照はSHAで照合する。manifestにサイズ、SHA、絶対保存場所、生成コマンドと復元方法を記録する。trace上限は実測で見直し、取得回数の改訂も履歴を残した。未取得窓を正常に補うための再取得は行わない。

新規blobは50,000,000バイト未満。既存pre-commit/pre-pushを維持し、提案全ファイルは一時index/object storeで検査して実indexを変更しない。Push広告refは実際のPush前に別途検査が必要である。履歴変更・LFS移行・重要証拠削除は行わない。今回はコミット/Pushしない。

## Gate判定

品質完全一致と実時間安全性を別に判定する。初回時計、途中過負荷、旧供給停止、全OS観測、物理音声連続性の未確認を残したまま総合PASSにはしない。Phase60、Gate3、Merodoa統合には進まない。
