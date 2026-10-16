# Phase 58：製品採用の判定と引継ぎ

## 採用判断

判定はB（条件付き成立）。既定のPlaybackEngineへ統合しない。Merodoaの変更も行わない。固定速度の解析/DSP分離、実FIFO、実機コールバック、独立参照との生ビット比較は実装したが、通常負荷でFIFO不足が再現した。動的速度変更は未実装で、Gate 1〜4を通過した製品エンジンではない。

音質アルゴリズム、FIFO容量・先行量、生成ブロック、出力ゲイン、Golden基準を維持する。DSPを簡略化したり先行量を減らしたりして起動時間や供給結果を改善した扱いにしない。

## 従来経路と新経路

| 項目 | Phase54製品経路 | Phase58独立経路 |
| --- | --- | --- |
| 解析 | 全曲完了後に準備 | 確定snapshotに沿って合成、長い未確定連鎖は全曲終了を待つ |
| DSP状態 | 既存Phase36 | 同じ算術を使う継続Phase57 |
| 固定出力長 | `llround(inputFrames * timeRatio)` | 製品式を明示して一致検証 |
| FIFO | 既存値 | 同じ容量・preset別先行上限 |
| 再生中の速度変更 | 既存Phase39契約 | 未実装 |
| 解析キャッシュ | 既存hit/missと入力同一性契約 | 共有キャッシュなし、再準備時も識別・解析 |
| 入力保持 | 既存FD・検証 | 元FD・同一性監視＋非公開WAVバイト複製 |
| 不足時 | 既存診断 | 不足を記録、真のEOSや正常PCMと区別 |
| 再生API | 既存公開API | 検証用C++内部クラス・CLIのみ |
| 製品既定値 | 維持 | 未接続 |

起動時間・CPU・メモリの実数は[REPORT](../results/phase58/REPORT.md)と`startup_final/statistics.json`に記録する。比較は同一入力・0.50倍・preset・Release・出力装置で各5回。従来のwarmは同じ製品オブジェクトのStop→Play、新経路のrestartは同じプロセス内で旧セッションを完全終了し新規作成する。新経路に既存キャッシュhitと同等の機能があるとは解釈しない。

Coldは新規プロセスの解析キャッシュmissを表す。OSのファイルキャッシュや音声ドライバーの履歴は消去していない。独立参照生成後に従来A→新経路Bの順で測定し、この順序の効果を完全に分離した実験ではない。

起動比較のMIXは44.1kHz/Float32/Stereoの30/180/300秒（`startup_input_formats.json`）。Phase57の290秒PCM16オフライン計測とは入力・計測境界が異なるため、約52msと直接比較しない。

最終同期修正版の再測定は`startup_after_ready_fix/statistics.json`に保存し、REPORTの最終比較表はこちらを使用する。初期版の`startup_final`は別版の観測結果として保持する。

Peak RSSはプロセス生存期間の最大値であり、restart単独のメモリ差分ではない。新経路の実機検証器は全参照PCMとcallback記録を事前確保するため、製品DSPだけのRSS比較ではない。`reference_bytes`、`source_snapshot_bytes`、snapshot所有量、FIFO、入力一時領域を併記する。入力複製のOSページキャッシュ・一時ストレージはRSSに含まれない。

## API設計案（未実装）

既存`prepare()`が成功した時点のReady契約は変更しない。採用する場合は別の非同期準備入口を追加する。

| API案 | 契約 |
| --- | --- |
| `prepareAsync(source, config)` | 受付ID・入力世代・sessionを即時返す。Readyの成功通知とは区別 |
| `preloadAnalysis(source)` | 確定結果だけを同一性付きで共有。失敗・取消・部分解析を完成キャッシュへ登録しない |
| `getPreparationProgress(session)` | 受信入力、閉鎖event、確定map、生成可能範囲、公開PCM、先行量を返す |
| `getStartupDiagnostics(session)` | 受付から各段階の時刻、cache hit/miss、CPU・資源・測定有効性を返す |
| `getProgressivePlaybackState(session)` | 状態・解析完了フラグ・失敗・取消理由を返す |

状態はAccepted（受付）、Analyzing（解析中）、PcmAvailable（正しいPCM生成可能）、Ready（所定FIFO先行量）、Playing（再生中）、Paused、Ended、Failed、Cancelledを区別する。AnalysisCompleteはReady/Playingと独立したフラグとする。制御側への通知にはsessionと入力世代を付け、旧通知を新入力へ適用しない。通知配送は音声callbackで行わない。

Ready直後のPlay、Ready前のPlay保留、キャンセルの完了通知、期限付きの失敗、入力一時領域不足の拒否を定義する必要がある。現在の入力識別・複製コンストラクターは同期であり、これ自体を`prepareAsync`実装済みとして扱わない。

Gate 2通過までは新経路へ再生中速度変更APIを公開しない。将来は要求ID・論理位置・session・世代、Latest-Wins、保護境界、要求の全終端状態を既存仕様へ合わせる。固定map交換や別DSPの再初期化で代用しない。

## 停止・入力・アプリ側の責務

callback静止→音声出力停止→実行中callback終了→通知解除→worker停止・join→DSP/snapshot/FIFO/FD解放の順序を守る。失敗セッションを再開せず新規作成する。未公開状態から全曲方式を選択することは可能だが、公開済みPCMへ別DSPのPCMを継ぎ足す連続性は証明していない。途中の切替は安全停止・再準備とする。

MerodoaのSwiftUI更新、Bookmark解決、Sandboxのアクセス権寿命、ファイル選択・一時領域の許可はアプリ側に残す。ネイティブ検証器がホスト上で動作したことは、アプリSandbox下で同じFD・一時領域運用が成立した証明ではない。今回はアプリコードを変更しない。

## Phase58 Fixで先に行うこと

1. 保存済み不足ケースを同じ入力SHA・2.00倍・Candidateで再現し、Audio System TraceでDSP非実行区間とライブラリ内部待ちを分離する。CPU時間と経過時間の差だけでは原因を断定しない。
2. workerの期限設計を見直す。現在のQoS指定はリアルタイム実行権ではない。リアルタイムworkerとAudio Workgroupの適用可否を、事前確保・I/O分離・有界な同期と併せて検証する。通常スレッドへ参加APIを足すだけで解決したとしない。
3. 元パス監視をDSPから分離した入力方式を維持しつつ、一時コピーの上限・失敗・OS資源量を予算化する。固定長不足・状態破壊・旧世代混入を回帰する。
4. 固定速度の通常・CPU競合・長尺でGate 1を再検証してから、同一DSP状態を継続するPhase39動的接続と論理イベント再現器を実装する。
5. 全161速度の初期/目標網羅、Latest-Wins、L1/L2/safe-density、速度変更中停止・再開・不足を検証する。その後に物理装置/サンプルレート変更と全ライフサイクルを検証する。
6. 公開API・キャッシュ統合、入力長ごとの起動・CPU・メモリ予算を確定し、Gate 4で採用判断する。

従来製品にも実機Candidateの初期callback時刻不連続が残る。raw一致・FIFO不足0・期限超過0でもhost/sample基準が不成立だった。既存バイナリの同一性を確認したうえで、初期のAVAudioEngine/SRCと提示時刻を別途追跡する。過去phase44のFAILと今回のFAILの両方を保持する。

調査の根拠はAppleの[Audio Workgroups](https://developer.apple.com/documentation/audiotoolbox/understanding-audio-workgroups)と[Instrumentsによる音声性能解析](https://developer.apple.com/documentation/audiotoolbox/analyzing-audio-performance-with-instruments)。これらの仕組みは今回の新経路へ実装したものではない。
