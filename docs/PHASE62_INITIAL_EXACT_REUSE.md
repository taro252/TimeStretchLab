# 初回ReturnToA Exact保存状態の再利用（A2）

## 変更前の観測と固定目標

基準e4a990787f149b546827fd4dcb96b9708b3662f2由来のEngineと同一測定hostによる隔離ビルドを使い、300秒・48kHz stereo PCM16人工入力、Baseline 1.00、AB長2秒を直列測定した。各A/条件n=2、受付→A位置合わせ→明示Play後の最初のA RAWまでの中央値はA=0でfresh 0.121秒/re-request 0.092秒、A=30で3.360/3.344秒、A=270で29.653/29.272秒。既存周回ではなく、Clear後にOFF→ABを再要求している。長いAまでの前置Exact合成が支配し、解析・Map計算は主因ではなかった。

最適化前に `build/phase62_terminal_initial_20261022_01/ACCEPTANCE_PLAN_01.json` を固定した。同prepare・同条件の再要求A=30/270で中央値1秒以下かつ変更前の20%以下。互換保存状態がないfresh coldは従来Exactを維持し、変更前の1.20倍+0.25秒以内。A=0は変更前+0.25秒以内。物理出音時間、p95、すべてのfresh要求の高速化は保証しない。

## 所有権と互換条件

選ぶ方式は、既存の初回合成がA直前で作る完全固定Exact保存状態を、同じInputLeaseの一枠に共有参照で保持する方式。追加の実行producerは作らない。通常seek保存点と合わせた既存checkpoint上限2、実行epoch上限2、FIFO 16,384、短区間RAW 96,000出力フレーム、1GiBおよび既存24MiB予約を増やさない。保存状態には位相・左右履歴・OLA・FIR・PCM・全カーソル・固定Mapが含まれる。動的遷移後の稼働DSPを固定保存点としてコピーしない。

キーはInputLease固有の入力世代・resident入力identity・finalAnalysis identity、Preset、速度、入力A/B、Map上の出力A/B/全長、保存位置P。P<=OAかつOA-P<2048とし、履歴なしの固定・最終Mapだけを使う。復元は新epochの通常workerでclone→prepareCheckpointForEpoch→新snapshot/new fixedMapの全ノード照合。PCM先頭位置だけの一致では採用しない。通常手動seekの方式やopt-inは変更しない。C!=AのLoop seekは対象外とし、開始前に任意の初回保存枠も解放する。これにより、現在のLoop保存点と新しいPaused再準備の保存点が2枠を使える。古い初回保存状態を残して3枠目を要求しない。

保存枠は取得時に移動して空け、clone後の一時参照も新A保存点の予約前に解放する。旧ownerがA保存点を保持する場合も新ownerの保存点と合わせて2まで。通常KeepPosition用原点保存点を準備する前には任意の初回保存枠を解放する。leaseのFD/resident入力は保存状態と全epochより長く生存し、close時に全workerをjoinした後で解放する。

## 取消と採用順序

通常createSeek/初回Loop準備の開始時にlease準備版を進める。保存状態の公開は、完了したA保存点、入力世代、準備版、取消状態を確認した通常workerだけが行う。古いworkerは新しい準備版へ保存状態を再公開できない。Clearは不変の互換状態を保持できる。速度・範囲・Preset・入力・Mapの不一致では取得時に破棄し、元のcold Exactへ戻る。入力変更は別lease、Stop/closeはworker静止とlease寿命の終了で古い結果を止める。

復元失敗・上限到達で不完全なPCMを継ぎ足さない。互換性不成立はcold経路、取消/致命的失敗は既存失敗処理とし、Readyを偽造しない。Playing中のFIFO保護・既存供給とReturnToA採用は変更しない。Ready/Pausedの初回採用はAへ位置合わせし、明示Play意思がなければA・実消費・周回を静止させる。

## 計測と独立検証

hostのnative Accepted→Readyは同じnative clockの差、位置合わせと最初のA RAW観測はsteady_clock秒の差。時計の生値を混ぜない。性能指標はsteady_clockの受付→位置合わせとReady観測→最初A RAWの和で、両版とも明示的な30ms静止確認を含む。再生装置48kHz/512 callbackの実測であり物理出音時間ではない。early要求は実際のfinalAnalysisフラグを記録し、完了済みなら「解析完了前の実施」としない。

旧固定Exact binaryのSHAと入力SHAを確認してRAWとMapを独立生成する。新製品RAWの全bit/全channel/フレーム/座標を比較し、非有限値は別FAIL。境界加工は旧RAWの終端/先頭と別実装の式から照合する。製品RAWだけで独立DSP oracleと呼ばない。試験コマンド・件数・参照hashは `results/phase62_terminal_initial` に記録する。性能、PCM、実時間期限、一般公開を別判定する。
