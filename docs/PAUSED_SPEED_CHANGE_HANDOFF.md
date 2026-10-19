# 停止中の速度変更：Merodoa 接続仕様

## 対象と位置づけ

通常の `ProgressiveMacPlaybackEngine` の `Paused` と、出力前の `Ready` を対象とする。速度変更を「同じ原曲入力位置から、新速度で出力する次の世代（epoch）の準備」として扱う。Merodoa 本体・submodule は変更していない。一般公開の承認、Legacy 既定、Phase 61 Interactive/FastLocal の許可条件、Phase 62 の opt-in と公開 NO-GO は変更しない。ネイティブ Loop が有効な場合と解除準備中の場合の速度要求は、既存 Phase 62 の経路・拒否条件を維持する。

開始 HEAD は `406a1fde0b130bbe5ae3ce7a1666cce696db9c99`（Phase 62 Fix 込み）、開始時の `main` は差分なし。本変更は未コミット差分である。症状の採用 SHA `88d5247fd6b67996f4d315d5cb0fb23caf8a9f0c` と現行開始 HEAD の両方で原因を確認した。調査基準 `d25433c88a1bae83b89168a26f1c6c9d8053a644` への巻戻しは行っていない。

## 原因と処置

両版とも pause は callback を静止させ、AVAudioEngine を pause し、`setRealtimeRendering(false)` を実行する。一方、従来の setSpeed は停止中も同じ pipeline の `requestSpeed()` へ送信していた。

- `transitionStep()` は renderingRequested=false の間、Pending を Submitted へ進めない。
- Phase 59 の Completed は、実消費カーソルが completionOutputSample に達し、safe-density（密度変更に必要な処理が安全に完了した状態）を満たすことが条件である。
- 旧速度 PCM が先読み上限まで FIFO（音声を順に取り出す待ち行列）を占める。無音で消費して解消すると停止位置と消費記録が壊れる。
- `requestSpeed()` は dspDone=true でも拒否する。末尾 PCM が残っている停止中や短い曲でも発生する。
- 従来の resume は新速度の準備を待たず、startAudio を呼び出していた。

既存の Completed 条件、位相、OLA（重ね合わせ）、FIR（周波数帯域の分離処理）、消費済み・公開済み PCM の保護は変更しない。旧 FIFO を消費せず保持し、Phase 61 `createSeek()` が提供する独立 DSP/FIFO と共有 InputLease を利用する。ユーザーのシーク履歴、シーク数、AB 周回イベントには速度準備を追加しない。

## Merodoa から使う API

ヘッダーは `src/platform/macos/ProgressiveMacPlaybackEngine.h`。作成、制御、停止、破棄は従来どおり、メインスレッド以外の同じ専用直列キューで行う。callback から呼んではならない。

```cpp
// Ready または Paused。UI の「一時停止」表示だけで native 状態を推定しない。
auto before = engine.getStateSnapshot();
auto receipt = engine.setSpeed(0.75, before.session,
                              before.inputGeneration, before.renderEpoch);
// receipt.result == Phase39RequestResult::Accepted は受付。
// 準備完了ではない。receipt.id を保存する。

// 同じ直列キューで、UI を止めずに適宜取得する。
auto now = engine.getStateSnapshot();
if (now.stoppedSpeed && now.stoppedSpeed->id == receipt.id) {
    auto operation = *now.stoppedSpeed;
    // operation.state を判定し UI へ渡す。
}

// 準備中に再開してもよい。
bool accepted = now.state == progressive::State::Paused
    ? engine.resume() : engine.play();  // Ready では play()
// true は再開意思の受付。Playing への遷移を snapshot で追跡する。
```

`setSpeed()` の既存の引数・戻り型は維持する。ただし停止中の Accepted は Phase 59 操作ではなく、新しい停止中準備操作を返す。Merodoa のブリッジは `ProgressiveStateSnapshot::stoppedSpeed` と `resumePending` を公開する必要がある。既存の `pending/active/lastResult` や `operationHistory()` だけを監視する接続では完了を検知できない。

停止中の ID は最上位ビットを立てた `uint64_t` で、残りがエンジンの生存期間を通した 1〜4096 の連番である。Phase 59 の小さい session 内 ID と区別する。Swift は UInt64 等で保持する。符号付き 64bit や JavaScript の Number へ縮小せず、JSON を介する場合は十進文字列等で損失なく受け渡す。epoch/session が変わっても、受付時の ID は変わらない。`stoppedSpeedHistory()` で同じ ID の結果を取得できる。履歴はエンジン生存期間で最大4096件、新入力で消さない。上限超過は LimitReached、無効速度は従来どおり例外、古い識別子は Stopped を返し、有効な先行要求を取り消さない。

Stopped/Ended からの次回 Play、速度保存・再準備の既存契約は変更しない。今回の準備経路は Ready/Paused 専用である。

## snapshot の意味

`state` は再生状態、`stoppedSpeed.state` は準備状態であり別々に扱う。

| 準備状態 | 意味 |
| --- | --- |
| Preparing | 受付済み。停止位置の捕捉、解析待ち、マップ・DSP/FIFO の準備、最新性確認のいずれかを実施中 |
| ReadyForResume | 最新の希望位置・速度の次 epoch が準備基準を満たし、音声停止中に出力対象として確定済み |
| Replaced | より新しい有効な速度要求に置き換えられた |
| Cancelled | stop、入力変更、破棄、装置変更、制御の所有権変更等で取り消された |
| Failed | 準備失敗。reason を表示・記録し、自動再開しない |

ReadyForResume は Phase 59 Completed ではない。完了 RAW 出力座標、聴こえている速度の実測値、音響出力時刻は生成しない。`outputStarted` は実際の startAudio 成功を示すだけであり、最初の音響出力の測定ではない。準備済みでも旧 epoch の退役処理が残る間、再開要求は resumePending に保持し、通常 worker の後処理完了後に開始する。

`resumePending=true` は再開意思を保持していることを示す。準備中も元の Ready/Paused を維持する。`play()/resume()` の true は受付、Playing は実際の AVAudioEngine 開始成功を表す。すぐに EOF となる場合は Ended へ進む。再開の受付と即時の Playing を同一視しているブリッジは、snapshot の監視へ変更する。既存の即時再開では挙動を維持し、新しい準備待ちに対して true の意味を受付まで拡張した。snapshot の構造体追加もあるため、古い C++ バイナリとの ABI 互換を主張しない。新しい依存 SHA でブリッジを再ビルドする。

一度 outputStarted=true となった準備操作は過去の記録である。後の再生中速度変更や明示 seek でその操作を Preparing に戻さない。現在の適用先は snapshot の session/renderEpoch/appliedTargetSpeed で判断し、準備要求の結果は保存した receipt.id と照合する。

再開待ちの取消には `pause()` を呼ぶ。Paused では再度呼べ、Ready でも保留中の再開を取り消せる。準備自体は続けてよいが出力は開始しない。後から明示的に再び resume/play できる。stop、曲変更のための stop→prepare、破棄、装置変更でも自動再開を取り消す。

## 停止位置と epoch の対応

停止位置は UI 秒数、200ms キャッシュ、入力時間×速度、wanted を累積する presented から計算しない。callback 静止後の実際の consumed と、DSP が採用し制御 worker が確認済みの TimeMap を対応付ける。

pipeline の `stoppedPosition()` は通常スレッド専用・待機なし。renderingRequested=false を確認し、採用済み mapVersion、consumed の組が一貫するときだけ標本を返す。確認がまだ取れなければ null を返し、準備 worker が後で再試行する。制御用 frontier mailbox を複数 reader で読む実装にはしていない。非同期 positionMailbox の標本を停止位置として無条件には使わない。Ready/Paused の位置表示でも、非同期標本の output が consumed と異なるものは採用しない。

`StoppedSpeedOperation` の次の情報をログへ残す。

- 捕捉元：inputGeneration、sourceSession、sourceRenderEpoch、mapVersion、consumedOutputFrame、positionCaptured。
- 希望先：resumeInputFrame、speedMicros、mode。
- 確定先：session、renderEpoch、outputStartFrame、readyNs。
- 相関情報：id、acceptedNs、state、reason、outputStarted。

seek 後に未消費なら、元の正確な requestedInputFrame を優先する。速度だけを何度変更しても、停止中の希望入力フレームを保持する。出力マップの丸めを逆変換して繰り返しずらさない。新旧 epoch の絶対 output 座標は同一である必要がない。新 epoch の consumed と presented は、自身の outputStartFrame に初期化する。旧 epoch の consumed は進めない。

明示 seek が重なれば最新の希望入力位置と最新速度を組み合わせる。実際の seek 操作は履歴に残し、速度変更だけの内部準備を seek として記録しない。Interactive 切替で新 epoch の PCM がすでに消費された後に pause した場合は、その新 epoch の実カーソルを捕捉する。元の seek 要求位置へ巻き戻さない。

## 準備方式・競合・資源

速度変更単独の準備は Exact を選ぶ。入力の再デコード、元解析のやり直し、AVAudioEngine 全体の再構築は行わない。元の特徴解析・FD・常駐入力を共有し、新速度のマップと DSP 状態を作る。Exact のため停止位置までの必要な前方処理は発生し、長い曲や遅い速度では準備時間が長くなり得る。既存の確定解析待ちとチェックポイントの条件・上限を維持し、期限は既存 prepareTimeout を使う。

許可済みの明示 Interactive/FastLocal seek に準備を合流する場合は、その選択を維持し、ReadyForResume.mode に実際の方式を記録する。FastLocal は局所的な位相初期化であり、Exact の PCM 完全一致を保証しない。速度変更だけのために opt-in を拡張しない。

既存 seek worker を共有し、同時の render epoch は旧と次の最大2つ、元入力の lease は共有する。次の準備を始める前に前の準備・退役を片づける。元解析が未完了なら、それを供給する旧 worker は次が Ready になるまで止めない。準備失敗・取消では次だけを停止・join し、確定前の旧 epoch を保持する。取消済みの準備にも最終診断を記録する。破棄と join は callback 外で行う。

速度変更は常に最新の有効要求を優先する。100→75→100% の最後の100%も新しい意図として受け付け、古い75%を残す Duplicate 判定はしない。再開意思は速度再変更でも保持し、新しい準備を待つ。要求版、入力世代、形式、希望速度・位置を切替時に確認し、古い世代の完了は出力対象へ切り替えない。

準備失敗では旧速度で勝手に再開せず、停止状態を保つ。AVAudioEngine開始自体の失敗はsnapshotのFailed/errorでも判定する。有効な新速度での再要求、または最新速度を使う新しい明示 seek の成功で復旧できる。失敗前の旧 epoch を再開して新要求成功と扱ってはならない。

## 検証の読み方と統合

実行条件・コマンド・PASS/FAIL/未検証・制限は [検証記録](PAUSED_SPEED_CHANGE_VALIDATION.md) に記載する。大きい音声・RAW PCM・トレースは build/ に置く。Git 管理する manifest と SHA-256 で元データ、独立参照、バイナリ、ソースを識別する。

未コミット差分の結果を開始 HEAD の結果として扱ってはならない。Merodoa 統合時には、採用する同内容を確定した完全 SHA と検証証拠の対応を記録し、ブリッジの UInt64 ID、stoppedSpeed、resumePending、Playing 判定を接続してから再現試験を行う。コミット、Push、既存履歴・Golden の変更は今回行っていない。
