# Phase 61 Progressive Seek（契約版2）

DSPは音声信号処理、PCMは未圧縮サンプル列、OLAは重なり合成、FIRは有限長フィルターを指す。render epochは再生区間の世代、checkpointはDSP状態の保存点、FD leaseは開いたファイル記述子の寿命を保つ共有所有権である。RAW suffixはシーク開始以降の加工していないPCM列を指す。

## 対象とゲート

`ProgressiveMacPlaybackEngine` の明示的な実験APIである。Phase54 Legacy、Merodoa、submodule、既存GoldenとPhase60承認結果を変更しない。`Capabilities.contractVersion=2`、`seekRequests=true` は新しい要求APIの実装を示す。`seek=false` は公開機能のゲートが閉じていることを示す。契約、独立PCM、実時間、Sandboxの結果を確認するまでUIで有効にしない。Phase62には進まない。

## API

```cpp
auto receipt = player.requestSeekToInputFrame(frame, inputGeneration, renderEpoch);
auto receipt2 = player.requestSeekToInputSeconds(seconds, inputGeneration, renderEpoch);
auto snapshot = player.getSeekSnapshot();
auto history = player.seekHistory();
auto retired = player.closedEpochs();
```

すべて同じアプリ作業キューで呼ぶ。返り値の`id`は受付操作の識別子、`accepted`は要求の受付結果である。拒否にも有界な履歴と理由を残す。新しい有効要求だけが古いPending/Preparing/ReadyをReplacedにする。不正な新要求は先行の有効要求を取り消さない。履歴上限4096件を超えた場合はID0と理由を返す。`latest`は拒否を含む最後の試行であり、有効な進行中要求は`activeId`/`pendingId`または受付IDに対応する履歴で照合する。

`SeekOperation`はPending/Preparing/Ready/Completed/Replaced/Cancelled/Rejected/Failedを区別する。Readyは安全な先行FIFOが完成、Completedは新区間の参照を設置した状態であり、物理的な可聴完了ではない。非表示になり得る短いReady遷移も`readyNs`に記録する。入力世代、元/採用render epoch、内部session、要求入力フレーム、採用出力フレーム、要求速度、再計画数、失敗理由を公開する。

時刻はMach単調時計のナノ秒。受付・準備開始・Ready・参照切替・最初にPCMを受け取ったコールバック（ゼロ値も含む）を分ける。切替時刻は原子的な参照設置の直前に採る。`estimatedPresentationNs`は妥当性確認したHAL hostTime（不適切ならコールバック時刻）を使うソフトウェア目標であり、音響測定ではない。Paused/Ready/終端の要求で未提示の場合は0のまま。

既存のbool `seekToInputSeconds` は`seek=false`の間falseを維持する。契約版2のブリッジは`requestSeek*`へ移行し、受付成功を完了と表示しない。`setSpeed`には末尾に期待render epochを追加し、既存3引数はソース互換。ライブラリとヘッダーは同じ版で再ビルドする。

## 座標

入力フレームは原曲のサンプルレートの整数座標。秒は有限・非負を検査し、曲長を越える値を丸める前に拒否する。曲長の秒数ちょうどは終端フレームとなり、それ以外はlong doubleの`seconds * sourceRate`を最近接へ丸める。NaN/Inf/負値・曲長超過を拒否する。音声装置のレートを使わない。

出力開始位置は、その新区間の初期速度の確定Adaptive TimeMapから`llround(map.outputPositionForInputSample(inputFrame))`で求める。固定速度の全出力長は従来製品の`llround(inputFrames * timeRatio)`を維持し、開始位置はその範囲に収める。入力終端ちょうどでは出力長を開始位置とし、空suffixを扱う。単純な入力位置/速度で中間位置を求めない。

## 入力・解析の再利用

Phase58の`InputLease`は元ファイルのFD/識別、非公開のunlinked snapshot FD、SHA-256、任意の常駐マッピング、Phase56の最終不変解析を保持する。初回のみ全SHA・一時複製・mlock・解析を実行する。`createSeek`は同じleaseを保持し、新しいDSP/FIFO/速度計画だけを生成する。最初の最終解析がまだない場合は取消可能に待つ。

同じ速度のMapは不変ページを共有する。別速度は再デコード/FFTをせず、閉鎖済みevent/anchorからPhase56の同じMapPrefixBuilderで計算する。解析・Map・DSPの入力世代はleaseのまま保持し、各区間のsession、render epoch、独立したキューを分ける。通常ファイルの同一性監視を解析/監視workerで続け、削除・置換・権限失効を正常EOSへ変換しない。`/dev/fd`のパスを開き直さず、読み取り側はFD複製か既存常駐byte領域を使う。

`sourceHashPasses/sourceSnapshotCreations/residentLockCalls`は入力準備の呼出し数であり、各シークの後も1回を確認する。全プロセスのシステムコール全入口の計測ではない。security-scoped URL/Bookmark等の権限はホストがStop・最終破棄まで保持する。

## 正確な再構築とFIFO

最初の実装は位相、OLA信号/重み、FIR、密度、イベント位置を先頭から同じ算術順で再構築し、開始位置以前のPCMを破棄する。全曲伸縮済みPCMキャッシュは作らない。`discardedFrames`は保存点以降に再構築して捨てた実フレーム数で、保存点まで省略した範囲は`checkpointStartFrame`に分けて記録する。先頭の部分ブロックは値を変更せず有界な2048フレーム作業領域へ詰め、FIFOの空きに応じて公開する。Candidate16384/Baseline12288の先行量、FIFO容量16384、生成単位2048、gain0.5を維持する。部分PCMの空き待ちより先に昇格/降格要求を処理し、ReadyでFIFOが満杯でもPlay/Pauseのpolicy応答を妨げない。

先頭再構築の初回測定では300秒素材の270秒位置でReadyまで12.155秒を要した。このため、既定有効の有界checkpointを追加した。共有入力内で最大2個、入力世代・速度・同じ常駐byte領域に結び付ける。確定した固定Mapに対し、最も近い開始位置以前の保存点を選ぶ。位相vocoder、ステレオ履歴、OLA信号/重み、FIR蓄積、入力/出力位置、解像度キャッシュ、直近frame履歴を深く複製する。FFTは次の変換で作業領域全体を上書きするため新しいplanを作り、算術順は変えない。

保存はシーク準備の通常policy区間だけで行い、出力30秒間隔とReady直前に記録する。近接する保存点は置換し、上限2を超えない。全曲PCMを保存せず、曲長に依存しないDSPリングと確定解析/Mapだけを保持する。保持の見積りは各8MiB（既存256MiBの準備予約内）で、RSSやallocatorの厳密な上限と区別する。

復元は同じ最終Map全nodeと固定出力長の一致を検査してから、新区間のMapへ結び直す。次のPhase59要求には通常のFrontier/保護/密度検査を適用する。適用済み動的履歴・未確定解析・終了/取消/失敗状態・詳細work profileからは保存しない。詳細計測付き経路は先頭からの再構築を使う。適合する保存点より前のシーク、速度が異なる場合、まだ保存点がない初回の深いシークも先頭再構築となる。`seekCheckpoints=false`は同条件の性能対照用である。正確性比較・速度条件は緩めない。

## 非同期切替と寿命

Playingの準備中は旧区間を維持する。新FIFOのReadyとWorkgroup実時間policy確認後、コールバックが一度だけ読む`RenderTarget*`を原子的に切り替える。区間内に入力世代/session/render epochをまとめる。実行中コールバック数を先に加算してから参照を読み、旧参照を全読取りが終わるまで保持する。旧workerの停止、join、Workgroup離脱/復元、入力lease解放は通常threadで行う。

音声コールバックはFIFO消費・任意の有界な観測・事前確保診断だけ。DSP、I/O、確保、mutex、待機、ログ書込み、所有権の破棄を追加しない。検証用C++ new hookは明示時のみで、通常アプリにはglobal newの置換をリンクしない。

Readyは再生を始めず移動、Pausedは停止を維持する。未消費の完了シークでは位置APIも要求した入力フレームそのものを返し、出力丸め/終端clampの逆写像からずれた値を出さない。消費開始後は通常workerの入力/出力対応標本を返す。Playing中の旧区間が準備中にEOSへ達した場合は、新区間の準備まで無音が残り得る。この待ちを高速・無音切れの成功としない。Stop、入力変更、装置変更、破棄は保留/実行中のシークを取り消す。

シークは要求時点以降の最新受付速度を新区間の初期速度とする。準備中に速度が変われば同じ受付IDで再計画する。Phase59の既存動的履歴を別区間へ移植しない。旧区間の未完了速度操作は停止時にCancelledとなる。新しい操作は入力世代・session・render epochを照合する。

## 診断・予算

一つの実験エンジンが一つの入力leaseを所有し、準備/現行の最大2区間を既存1GiB以下の入場予算内で保持する。Snapshot/Mapの3スロット上限は各区間に適用される。旧区間の診断は最大16件、各速度履歴は末尾256件とdrop数を保持する。入力内の不足・拒否・品質失敗の累積は履歴削除後も保持し、最後の成功で隠さない。診断の`presentedFrames`は従来互換の入力寿命内の論理要求数、`currentEpochPresentedFrame`は現在区間の絶対論理座標である。生成/公開/消費と位置APIは現在区間の絶対座標、品質カウンターとプロセスCPUは入力寿命内の累積として区別する。

SourceNodeを作り直さないシークではhost/sample時計の検査を継続する。Pause/Resumeだけは時刻検査のepochを更新し、PCM区間のrender epochと区別する。既存`MacCallbackRecord.epoch`は時計のepochであり、新しいPCM observerのrender epochとは異なる。検証CSVも`clock_epoch`と表記し、sessionと`captures.json`/シーク履歴からPCM区間を照合する。ゲートはPCM、FIFO、callback/worker期限、Workgroup寿命、予算、Sandboxを別々に判定し、未測定はnull/未検証として残す。

## 検証・Merodoaへの渡し方

新しいCMake/CTest、全形式/7速度/両presetの全PCM suffix、161速度受付、連続シーク、Stop、入力変更、route変更、Sandbox実再生を検査する。固定参照はPhase57以前のPhase36を先にリンクする独立実行体で、Release/Debugは同じ構成の参照を使う。Golden25と既存Phase56〜60の回帰を保持する。大容量生成物は`build/phase61`へ保存し、SHA/manifest/再実行コマンドをGit内の結果へ記録する。

Merodoa側は契約版2の要求/結果型、render epoch付き位置・速度・PCM監査をブリッジへ追加し、同じ専用直列キューで照会する必要がある。入力権限leaseと同一版ヘッダー/ライブラリを保持する。公開seekゲートがfalseの間は一般UIへ有効化しない。Merodoa本体やsubmoduleの変更は本Phaseでは行わない。


## 試験の再実行

`phase61_contract`、`phase61_checkpoint`、`phase61_safety`、`phase61_pcm_suffix`をCTestへ登録した。安全性試験は満杯FIFOでの昇格/降格、終端Readyでの入力監視、同じbyte列への置換検知も含む。`Phase61SeekSmoke.py --full`は1.5秒の境界fixtureを8形式・7速度・2preset・4位置・2worker経路で896回検査する。生成が残るWorkgroup経路ではReady後に実際に昇格し、観測policyと離脱/復元を検査する。終端などDSP完了済みの経路は参加不要である。

実機は自動CTestから分離する。`phase61_native_tests input.wav output_dir`は4秒の検証素材で20ケースを実行する。`phase61_native_tests chain_300s.wav output_dir --deep`は再生中に270/285秒へ移り、初回再構築と保存点再開の受付・Ready・切替・最初のPCMを記録する。各区間の観測は最大32秒に制限し、入力全長に比例する伸縮PCMを保持しない。独立RAW比較は`phase61_verify_native.py`、長尺では`--expected-sessions 1`を指定する。

`phase61_sandbox_app`はApp Sandbox + user-selected read/writeの署名を付け、NSOpenPanelで音源と出力先を選ぶ。音源の先頭4秒を一度だけWAVへ変換し、そのWAVで同じ20ケースを実再生する。OSが承認したURLのアクセスを試験終了まで保持し、選択範囲外の既存ファイルの拒否も記録する。端末ホストからの再生とSandbox内再生を混同しない。最終成績・使用したbinaryの識別・未測定範囲は`results/phase61/REPORT.md`とmanifestへ記録する。
