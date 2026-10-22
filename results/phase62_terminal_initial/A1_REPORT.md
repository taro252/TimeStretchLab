# Phase 62 A1：Paused Clearの確定速度履歴不変性

A1の限定判定はPASS。旧版で既知の変更を13/14 checksのFAILとして検出し、修正版では両Presetの主試験各14/14と、直接影響する回帰を含む28プログラム・147/147 checksが成功した。A2性能、一般公開、既定エンジン採用の判定には広げない。

## 旧版の実API再現

基準SHAは `e4a990787f149b546827fd4dcb96b9708b3662f2`。比較用 `baseline_02` は、このSHAの `ProgressiveMacPlaybackEngine.mm` と新試験・新helperを組み合わせたもの。保存されたEngineソースが基準SHAと完全一致することを確認した。旧Engineは新helperを呼ばない。

Baseline、Release/arm64、48kHz mono・6秒の人工入力、A=24000・B=28800（100ms）、初期1.00で、3周回→Pause→1.25→ReadyForResume→明示Resume→同じIDの実PCM Completed→再Pause→Clearを実行した。装置は48kHz、callbackは512フレーム。入力SHA-256は `ce21edd20991206d32bef0f45c6025025f90639be37ed8408261961f718bf1c2`。

Clear直前のネイティブ個別照会を基準として39フィールドを比較した。同一ID `9223372036854775809` の `discardedForPausedClearFrames` だけが0から12288へ変わり、Clear後の個別照会・明示履歴・close後の独立終了監査で同じ変更を観測した。他の38フィールドは同一で、Completed、`clearContinuation=false`、session=3、render epoch=6、完了時刻等も変わらない。bridge/VMの終端キャッシュやClear後に凍結した値は期待値に使っていない。

旧ownerのjoin済み値では、公開総数32359−出力開始位置19559−実RAW消費512=12288。Clear Snapshotの破棄数も12288だった。終了監査は1回配送・1件の即時所有コピー・全worker join・退役完了、Accepted ID集合も完全一致した。この終了成功と確定履歴不変のFAILを分けて記録した。子プロセスexit=1、timeoutなし、13 checks成功・M14のみ失敗。詳細・全フィールド名・元証拠SHA-256・Merodoaの14 checks対応は [A1_REPRO.json](A1_REPRO.json) に保存した。

元証拠：`build/phase62_terminal_initial_20261022_01/a1_baseline_01/`。Merodoa参照は `33ddcb6e3dafcb4f5f408a465b726824bf9f5005` の `NativeAudio/Tests/LoopBridgeIntegrationTests.mm --audit-immutability`。M01〜M14を元のcheck順に対応させ、M14では明示履歴との全フィールド比較も要求する。

## 修正と帰属

旧owner停止・join後に実破棄数を確定し、Clear自体の `LoopSnapshot.pausedClearDiscardedFrames` を保持する。要求別の計数は `LoopSpeedLedger::recordPausedClearDiscard()` を通し、同じ要求ID・Loop ID・入力世代・準備版であり、`clearContinuation=true` かつ未終端の行だけへ記録する。ReadyForResumeの公開は旧ownerの退役と計数確定の後に維持する。

全フィールドを比較するserializerと、Engine破棄後にも値を所有する独立終了監査sinkは既存試験を再利用した。callbackへの待機・割当て・ロック・I/Oは追加しない。未終端移管の順序確認は既存の通常worker用有限gateだけで行う。

## 修正版の限定回帰

保存先は `build/phase62_terminal_initial_20261022_01/a1_fixed_02/`。ソース一覧SHA-256は `dc578f33a1d33d3d6c515549f8b2f9802f3232006ad666293f819362d32f9347`。`SUMMARY.json` を読み取り再検査し、全28行でexit=0・timeoutなし・期待check数=実check数・PASSを確認した。SUMMARYのSHA-256は `d1bf3391f528a419e8cca962a5f451514a2cd2e667501874c7f9980204b0e9ee`。

|試験群|実行数|checks|結果|
|---|---:|---:|---|
|確定済みCompletedのClear不変（両Preset）|2|28|PASS|
|未終端clearContinuation・過去不変（両Preset）|2|16|PASS|
|速度要求なしClear（両Preset）|2|10|PASS|
|既存Paused Clearの6経路（両Preset）|12|24|PASS|
|既存直接close・独立終了監査（両Preset）|2|12|PASS|
|既存F01供給保持・Clear取消の3経路（両Preset）|6|40|PASS|
|全4終端状態・identity/移管ガードの局所試験|1|7|PASS|
|既存台帳上限・受付境界の単体試験|1|10|PASS|
|合計|28|147|PASS|

主試験のClear前個別照会・後個別照会・明示履歴・close所有コピーについて、両Presetとも39フィールドの完全一致を追加で読み取り確認した。Completedの要求別破棄数は0のまま、Clear SnapshotにはBaseline=12288・Candidate=16384の実破棄数が残る。

未終端移管は両Presetとも最新ID `9223372036854775810` を維持。停止位置C=24832、Clear準備版5、入力世代1で、旧ownerのjoin後にReadyForResumeを公開し、実破棄数を最新行だけへ記録した。明示Resume前の位置・PCM・周回は静止し、再開後は同じIDが実PCMでCompletedとなり、過去Completedと最新終端の全フィールド不変・終了監査のAccepted集合を確認した。Baselineの実破棄数12288、Candidateの16384は各実行のRAW実消費とjoin済み公開総数から求め、過去の定数を期待値にしていない。

速度要求なしClearでも外部速度行を作らず、同じ実破棄数がSnapshotに残る。主試験・移管・速度要求なしの6代表実行はmissing=0。callback/worker期限超過の観測値は0だったが、実時間期限保証は `NOT_ASSESSED` とする。

先行した `a1_fixed_01` は通常sandboxの装置取得制限で音声26プログラムが準備前に実行不能となった記録で、実機製品FAILとは判定しない。局所2プログラムの17 checksのみ成功した。元記録は変更せず、音声部分をNOT_RUN相当として分離した。その後の `a1_fixed_02` を有効な限定回帰結果として使う。

## 引継ぎと判定範囲

公開構造体・全39フィールド・受付ID・終了監査APIは変更しない。終端行の比較から診断フィールドを外さず、Snapshotと要求行の帰属を分ける。終了監査の受け手は配送中に即時所有コピーし、Engine破棄後に参照やspanを保持しない既存契約を維持する。

Merodoaでは固定候補へ更新後、同じ `--audit-immutability` をまずBaseline 48kHz mono・100ms ABで14/14要求する。未終端Paused要求のClear移管、明示ResumeまでのC静止、要求別実破棄数とSnapshot、close後全フィールド・Accepted集合の限定再試験も行う。Sandbox/TCC/Bookmark、独立DSP品質参照、物理出音時間は本A1判定に含めない。

過去D07/D08/F01の保存証拠と限定PASSは変更しない。A1は限定PASS、A2初回性能は別報告、公開・既定採用はNO-GO維持。最終候補40桁SHA、保持checkout、証拠manifestの最終ハッシュは統合担当が確定する。
