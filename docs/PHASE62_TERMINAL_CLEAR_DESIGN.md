# Phase62：Paused Clear診断の帰属と確定履歴

開始点は独立checkout `/Users/taro252/Docker/TimeStretchLab` のmain@e4a990787f149b546827fd4dcb96b9708b3662f2、clean。F01とD07/D08の過去判定・原本は保持し、今回の履歴修正A1と初回Exact性能A2を別判定にする。新原本は `build/phase62_terminal_initial_20261022_01` に保存する。

## 確定点と診断の所属

Paused Clearは、旧ownerの停止・join後に `available()` を一度読み、実際の置換破棄数を確定する。これは実消費、underrun、ユーザーseek、自然周回へ加算せず、Clear自身の `LoopSnapshot.pausedClearDiscardedFrames/pausedClearInputFrame` に残す。速度要求がないClearにも同じ診断が残る。

要求別 `discardedForPausedClearFrames` を書くには、当該IDが存在し、`clearContinuation=true`、未終端、loopID・inputGeneration・preparationVersionが実際のClear jobと一致していなければならない。製品台帳の `recordPausedClearDiscard()` がこの条件をまとめて判定する。要求IDはjobが選択時に固定したID、世代は停止済み旧owner、準備版はjobのseekVersionを使う。source session/renderEpochは自然な採用で進むため、外部入力変更との混同を避ける。

順序は旧owner stop/join→実数確定→Clear Snapshotと正当な移管要求へ記録→旧epochの同期・退役→ReadyForResumeである。新しい待機・joinをEngine mutex内へ移さない。明示Resume意思がなければ静止位置Cを保つ。終端行を非終端へ戻したり、Clearの全IDを0へ変更したりしない。

## 回帰と旧比較

主試験はMerodoaの指定33ddcb6…に記録された `--audit-immutability` と同等の14 checks。Baseline、48kHz mono/PCM16、6秒人工入力、[0.5,0.6)、初期1.00から、Pause→1.25→Resume前ReadyForResume→明示Resume→Completed→再Pause→Clearを通常APIで行う。Clear直前のネイティブ個別値を所有コピーし、Clear後個別照会、明示履歴、直接close後の独立終了監査と全フィールド比較する。終端キャッシュやClear後の値を前値にしない。

比較版はe4のEngine.mmと共通の新host・台帳helperを組み合わせた隔離版であり、純未改変binaryではない。helperは旧Engineから呼ばれない。実Completed行の非ゼロ破棄数への変異を保存し、13/14後の不変性FAILを要求する。単なるtimeout、装置停止、未消費数0は再現成功にしない。

補助は未終端要求のClear継続移管8 checks、速度要求なしClear5 checks、実製品helperの全4終端・各identity不一致等7 checks。破棄数は固定値を使わず、join済み旧epochの公開済みフレーム数から実RAW受信総数を差し引いて独立照合する。Loopの周期内consumed座標を累積消費数として引かない。

全Accepted IDの一意完全一致、終了監査1回、即時所有コピー、全worker join・退役、全フィールド不変を維持する。callbackには有界な既存RAW観測以外の待機・確保・ログを追加しない。

## 近接書込みの限定監査

`syncLoopSpeeds()`、停止準備、採用、catch、退役後Ready公開と置換は、終端除外または非終端走査内で処理される。`requestClearLoop()`の暫定移管解除は、終端除外のtransferableを通したIDだけを同じEngine mutex内で扱い、外部へ確定値を公開する前に取消の勝敗を解決する。単に個々の行にterminalガードがないことだけで、別の公開後変更があるとは断定しない。今回実Engineで再現した旧owner退役時の破棄数代入を修正対象とする。

共有DSP演算・PCM参照・公開能力フラグは変更しない。終了監査のcontextはEngine破棄完了まで保持し、借用spanを値コピーする。一般公開、Merodoa既定採用、TCC/security scope/bookmark、物理loopback・人の試聴は今回の局所判定に含めない。
