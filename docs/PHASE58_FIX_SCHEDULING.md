# Phase 58 Fix：実時間worker設計

## 採用範囲

Phase58の独立した検証経路に、明示指定の `--worker=workgroup --resident-input=on` を追加した。製品の公開API・既定経路・Merodoa・動的速度変更は変更しない。通常pthread方式も比較対象として残す。

実時間化の対象はReady後の再生中DSP供給である。解析は通常のUTILITY worker、入力同一性監視も通常workerで行う。初期準備・FIFO先行生成は通常優先度であり、起動前の非実行まで解消する設計ではない。

## スケジューリング

独立した非同期音声生成workerとして `AudioWorkIntervalCreate` で専用Audio Workgroupを作る。装置callbackと異なる周期で先行生成するので、装置の作業グループへ単に参加させる構成は採らない。

公開Mach APIの `THREAD_TIME_CONSTRAINT_POLICY` を設定し、実際のpolicyとpriorityを検査してからグループへ参加する。周期・制約は2,048 / 入力sample rate秒（48kHzで42.667ms）、計算予算はその90%、preemptible=true。FIFOの容量・先行量・生成ブロック・ゲインは従来どおりである。

通常所有者が `setRealtimeRendering(true)` を呼び、workerの昇格または生成完了を確認してからAVAudioEngineを開始する。callbackはこの操作に関与しない。workerはブロック間の待機中も再生中の実時間policyを保ち、通常優先度での再開遅延を残さない。各advanceの開始・完了を作業区間APIに通知する。周期予算はOSの無条件保証ではなく、独自の区間期限超過と実音声のFIFO・callback期限を別々に記録する。

待機には作成済みMachセマフォで2msのタイムアウトを指定する。実際の再開遅延はOSスケジューリングにも依存するため、2msの厳密な実行保証とはしない。解析・制御からの通知を1件へ集約し、音声callbackから通知しない。Snapshotが新しくならない場合やFIFOが満杯の場合だけ待ち、DSP計算を省略しない。

## 入力・メモリ・Snapshot

元入力の同一性を固定する非公開一時FDへの複製は維持する。上限512MiB、全内容SHA照合、選択元のinode等の監視も維持する。追加構成ではそのWAVバイト列を読み取り専用でmapし、通常所有者がmlockを完了する。floatのNaN/Infも昇格前に検査する。失敗時は準備失敗として拒否し、実時間worker上のpreadへ黙って戻さない。

WavStreamReaderは常駐バイト列から既存と同じRIFF解析・キャッシュ・PCM変換を行う。DSPのSTFT・位相・OLA・FIR・出力サンプル数の算術は変更していない。入力以外の全プロセスメモリをmlockしたわけではなく、Cライブラリ内部の全確保を計測したとも主張しない。

Snapshotは通常解析側が最大3つの共有所有権を保持する。DSPは世代タグと保護スロットを使用して読み取り専用ポインタを借用し、共有参照数を増減させない。新Snapshot供給によって古い参照が不要になってから保護先を切り替える。取得は最大4試行で、失敗時は次のループへ進む。所有権破棄は通常解析側へ残す。共有所有方式と借用方式の混在は拒否する。

Sink所有関数・DSPバッファ・診断領域を昇格前に確保する。診断領域は容量確保だけで済ませず、通常workerで全要素を初期化し、実際のページサイズごとにvolatileアクセスしてから記録件数を0へ戻す。通常経路にあったブロックごとの所有関数作成、Snapshot取得mutex、元ファイル検証を実時間区間から除く。これらは実時間化の必要条件であり、観測した長い位相停止の直接原因だったとは主張しない。

このページ初期化は追加のOS証拠に基づく。候補V2の最初の詳細計測では、detailObserverの記録書込みにZero Fillが37件あり、合計約132µsだった。C++ newが0でも初回ページアクセスは残ることを確認した。V3では同条件の3セッション・117個の実時間DSPブロックでフォルト0を確認した。これを過去の約200ms停止の原因と混同しない。全プロセスメモリの永久常駐を保証する修正ではない。

## 寿命・終了・例外

Pauseではcallbackを停止・静止させてから降格し、Resumeは再昇格を確認する。EOS・Stop・キャンセル・例外の全経路で区間終了、グループ離脱、通常policy復元を実行し、DSPエンジンやSnapshotを破棄する前に完了する。終了時のpolicy1復元を検査する。pthread QoS分類が元の25へ完全復元されることは保証せず、再使用しないworkerを終了する。

通常のキャンセルはエンジンのcancel状態で扱い、実時間区間で例外生成を通常制御として使用しない。破られた不変条件などの例外は降格してから通常側へエラーを伝える。昇格・参加・区間・復元・待機APIのエラーを記録し、有効な実時間成功として扱わない。

## 計測

block/detail/offを明示指定できる。worker記録65,536、詳細イベント262,144、スレッド標本65,536を上限とし、超過を記録する。計測中の無制限ログ出力は行わず、join後にCSVを出力する。長尺の標本上限到達後は未保存区間があり、全期間の優先度を連続観測したとはしない。

C++ new各入口を検証実行体で計測する。初期化分と昇格中の全寿命を分ける。callbackで測る確保も従来どおりC++が対象であり、Objective-C/C内部の全確保を意味しない。オフラインPCM一致試験は修正構成のデータ経路を通すが実時間昇格しない。実際のpolicy検証は実機試験で行う。

## 不採用方式と公式資料

QoSの再設定だけ、LatencyCritical活動指定、FIFO拡大、低品質PCM、callbackでの待機は採用しない。標準方式＋入力常駐のみも比較し、スケジューリング修正との寄与を区別する。

- [Apple：非同期実時間スレッドをAudio Workgroupに追加](https://developer.apple.com/documentation/audiotoolbox/adding-asynchronous-real-time-threads-to-audio-workgroups)
- [Apple：Audio Workgroupの考え方](https://developer.apple.com/documentation/audiotoolbox/understanding-audio-workgroups)
- [Apple：Instrumentsで音声性能を分析](https://developer.apple.com/documentation/audiotoolbox/analyzing-audio-performance-with-instruments)
- [Apple：Machスケジューラ](https://developer.apple.com/library/archive/documentation/Darwin/Conceptual/KernelProgramming/scheduler/scheduler.html)

実際のヘッダー・APIの使用可否は本機macOS 26.6.2 / Xcode 27 SDKでも確認した。他OS・他装置・Sandboxのmlockや一時FD制限は今回の実機測定から保証しない。

## 次Phaseの製品課題

一時複製は選択元の変更とDSP読取りを分離するため維持した。入力サイズ分の一時ストレージに加え、修正構成では同サイズの常駐入力を必要とする。Stop→Playでも新セッションを準備する。今回の増分経路はPhase54完成解析キャッシュを共有していない。

将来、内容SHA・解析版・品質構成・全161速度の契約をキーとした完成解析の再利用、読み取り専用FDの入力不変性保証、寿命を共有する常駐リソースを検討できる。アクセス権と同一性を保証できない状態で複製を省略しない。製品Sandboxでの一時領域・常駐上限・複数セッション合算予算、停止後のFD解放と原本アクセス権の寿命は別途設計する。
