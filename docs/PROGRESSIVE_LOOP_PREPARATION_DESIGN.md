# AB入口の有界な先行準備（契約3）

これはcold Exactを局所位相へ変更する方式ではない。利用者がA/Bを確定した後に明示要求し、既存の0→Aまたは厳密互換P→AのExact仕事をクリック前へ移す。未訪問・保存点なし・先行準備なしのON時間は別に測る。目標は採用台帳の1000ms/250msを維持する。

## 状態と所有権

`Pending → Preparing → Ready`。Readyは準備ownerのstop/join/破棄後にだけ公開する。保存するのは既存の完全固定A保存点1件で、解析identity、入力lease、Preset、速度、全固定TimeMap、A/B・各出力座標が一致する場合だけ使う。位相・左右履歴・OLA・FIR・未公開PCMの既存コピー/互換性検査を緩めない。

旧通常ownerが第1スロットを保持し、先行準備は既存seek直列workerの第2スロットを使う。RAWを公開せず、A直前の既存生成フロンティアで不変保存点を作って終了する。最大2実行owner/2保存点、既存24MiB予約内。完了後は追加実行ownerも周期的なDSP仕事もない。FIFO・callback参照・可聴PCM・消費位置・周回を変更しない。

## 受付と失効

Loop無効かつClearなし、通常owner、Ready/Playing/Pausedに限定する。入力世代・session・epochをすべて指定する。ユーザーseek/停止中速度準備/Loop処理/採用開始済み境界がある場合はResourceBusyで拒否し、自動無限再送しない。要求は最大1件の最新意図、履歴4096件/engineで有界。実行中の置換はCancelling→join→Replacedを経て次を開始する。明示seek/速度変更/Pause/Stop/入力変更/route/closeは取消する。workerが必要なlockを保持してjoinしない。

入力leaseと解析は最後のworker退役まで保持する。入力異常、期限、保存点上限では旧音声を保持し、Failedとして返す。Readyは音声適用のCompletedではない。終端の準備記録は書換えず、保存点が現在も有効かは別のsnapshot.availableで示す。

## ONとの接続

同じ入力・A/B・Preset・速度のReady準備があれば、ReturnToAが既存の厳密A保存点を採用できる。ONがPreparingより早ければ先行版を取消/退役して通常の明示Loop要求を優先する。部分prefixを暗黙に互換保存点と見なさない。未完了準備の残待ちは高速化PASSにしない。既存のrequestLoopRangeを準備APIとして早送信しない。

## 計測

準備受付、実行開始、保存点準備、join後Readyを記録し、coldDiscardedFrames、P、CPU/wallを保存する。先行準備CPU、ON→初回A PCM、HAL推定、物理出音を分ける。cancel/replacement/pause/stop/曲変更/close、旧PCM不変、A独立Exact、owner/checkpointピークを新実行体で検査する。
