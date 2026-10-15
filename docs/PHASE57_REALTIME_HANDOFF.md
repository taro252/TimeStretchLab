# Phase 58への増分合成引継ぎ

## 引き渡す内部機能

Phase57は固定速度・オフラインの`ProgressiveSynthesisEngine`を実装する。入力追加、解析確定、DSP合成、PCM公開の境界を分け、同じLow/Mid/Highの位相・OLA・FIR状態を継続する。161速度を1速度ずつ検証する。製品PlaybackEngine、MacPlaybackEngine、Merodoaへ接続する公開APIではない。

workerは1本のproducerとしてDSPを所有し、advance/supplySnapshot/sinkからの再入を禁止する。解析側が取得した共有不変snapshotを、世代と要求速度を保ったまま供給する。受信量だけの通知と、mapが増えた通知を区別する。engineは最新snapshot1個を保持し、補給時に配列を丸ごとコピーしない。

## workerへの接続手順

1. 入力所有者が元ファイルの寿命・FD・世代を保持する。解析とDSPには同じ固定入力を与え、ファイルを変更しない。
2. 解析を継続し、確定境界が増えたsnapshotを制御キューでworkerへ渡す。キューは有界にし、同世代の古い通知を必要に応じて最新へまとめる。
3. workerで`supplySnapshot`を呼び、`advance`を繰り返す。1回最大2,048出力フレーム。`NeedsMoreAnalysis`と`NeedsMoreInput`では状態を保持して停止し、次の必要な通知まで待つ。
4. `Produced`で得たPCMをworker側の有界なキュー/FIFOへ移す。sinkのポインターは呼出し中だけ有効。音声callbackへ借用ポインターやshared_ptrを渡さない。
5. 正常EOS、cancel、失敗を別の終端状態として処理する。workerを停止してからDSP、解析lease、入力の順に破棄する。

現行のPinnedInput検証関数はPhase56のfailInput通知を含む単一producerの実験用である。Phase58で解析とDSPを別スレッドに分ける際は、FD検証と解析への失敗通知を分離し、failInputは解析producerへキューで伝える。このアダプターをそのまま共有して並列呼出ししてはならない。

現在は既知WAV用であり、生PCMが到着するring入力は未実装。3つのDSP readerは位置非依存のpreadを使う。workerだけがファイルI/O・検証・確保を行う。音声callbackへ解析、FFT、共有所有権操作、mutex、I/O、メモリ確保を追加しない。

## PCMをFIFOへ渡せる条件

mapの確定node数だけでは公開しない。全解像度の必要な補間node、resetのevent範囲、入力FFT窓、OLAへの将来寄与、FIRの変換ブロック全体が揃っていることを処理前に検査する。詳細は`PHASE57_PROGRESSIVE_SYNTHESIS.md`。16,384出力フレームを切り戻す経験則は使わない。

engineが生成しても、公開直前の入力変更・cancel・sink失敗で公開量が進まない場合がある。`generated`と`published`を同一視しない。古い世代のPCMを新しいFIFOへ流さない。公開済みPCMを後から別mapで修正しない。

既定のFIFO/先行/生成はCandidate16,384/16,384/2,048、Baseline16,384/12,288/2,048を維持する。Phase57の「先行量相当が揃った」はオフラインのフレーム数到達であり、実FIFOの蓄積、SourceNode callback、可聴再生の成功ではない。

## 解析が追いつかない場合

確定mapが不足したらDSPを進めずworker側で待つ。仮EOS、末尾map外挿、品質低下、0埋めで追いついた扱いにしない。長いイベント連鎖では全曲EOSまでmapが増えない場合があり、固定時間内に再生を開始できる保証はない。通常素材の早期公開実績から全楽曲へ保証を広げない。

製品で既に再生中のFIFOが尽きた場合の停止・再蓄積・エラー表示は未設計。Phase58は不足を正確に記録し、無音補填を品質成功として隠さない。全内容SHA-256、解析cacheの同一性・入力変更契約も残す。

## CPU・メモリ・並行性

オフライン逐次処理の性能を実時間のCPU競合へ一般化しない。小さい解析チャンクのsnapshot公開回数、入力検証回数、DSP起床回数を含めて測る。32/128 Midの値と最初のPCM/先行量の時刻、総CPUを別々に比較する。

engineは曲長に比例するPCMを保持せず、1出力ブロックと固定のDSP配列を持つ。最新snapshotは1個。Phase56の共有ページ所有量、解析内部列、DSP作業領域予約、FIFO、キュー、FFT内部確保、プロセスRSSを分けて予算化する。8MiBのDSP予約値は厳密allocator上限ではない。多数sessionの総予算や同一音源へのflight共有は未実装。

同一入力の複数要求は別session/世代/FDで独立に扱う。結果を自動的に1解析へまとめる機能はない。入力切替では旧producerのcancel/終了を受理し、旧snapshotとPCMの寿命を整理してから新世代を進める。

## EOS・cancel・失敗

正常EOSだけが末尾paddingと最後の短いFIRブロックを許可する。既知WAVの全長と最終解析入力数が異なる通知は拒否する。完了済みEOSは後からcancelで変更しない。取消要求と最後の公開が同時の場合は、公開直前の確認を終端の順序点とする。既に成立した公開を遡って取り消す機能はない。

DSP・sink・I/O・解析の失敗後に同じDSPを再開しない。途中で変更された状態をロールバックしたと主張しない。失敗sessionの残りPCMを正常EOSとして流さず、完成解析cacheへ部分結果を登録しない。

## 速度変更と製品接続前の条件

現在のsessionは固定速度。要求速度は400000〜2000000を10000刻み。各解析は必要な1速度だけを要求する。161固定速度の一致を、再生中の速度変更の一致へ広げない。L1/L2、safe-density、Latest-Wins、既処理位相と公開PCMの境界を守る速度履歴mapの補給は次段階で設計する。

製品へ接続する前に、少なくとも解析とDSPの別worker競合、FIFOの不足と再蓄積、callback期限、装置/形式変更、Stop/Pause/Resume/EOS、同時要求・寿命、速度変更、負荷・OS停止、実機の開始時刻と可聴遅延を検証する。現在の公開API、出力ゲイン0.5、Golden、先行量を緩めない。

Phase54の保存済み実時間FAILと未保証事項は保持する。Phase57のオフライン一致だけで`realtime_verified`をtrueにせず、実時間統合の成否はPhase58で判断する。Phase58へ進めるかの実測に基づく判定はPhase57 REPORT/VERDICTを参照する。
