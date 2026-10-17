# TimeStretchLab Phase 60 結果

**Experimental Handoff：PASS。Gate 2未合格、一般公開向けは未成立。** この作業ではMerodoa本体・submodule・既定経路を変更していない。コミット・Pushは実施していない。

## 1. 実装内容

`ProgressiveMacPlaybackEngine` と `macos_progressive_playback_engine`、公開能力情報、独立A/Bホストを追加した。既存Phase58/59を所有する薄い接続層であり、DSP・TimeMap・L1/L2・safe-density・位相・OLA・FIRを変更していない。

## 2. 変更ファイル

新規：`src/platform/macos/ProgressiveMacPlaybackEngine.{h,mm}`、`src/playback/ProgressiveContract.h`、比較CLI2本、Objective-C++例、契約/API/結果集計テスト、Phase60実行/監査スクリプト、3文書と結果。既存の変更はCMakeとRealtimePipelineの読み取り専用位置標本だけ。旧MacPlaybackEngine/PlaybackEngine公開API・既定動作は不変。

## 3. 新エンジンAPI

prepare / play / pause / resume / stop / setSpeed / state / snapshot / position / core/native diagnosticsを公開。シーク能力falseで拒否する。prepareのtrueはAcceptedであり、Ready完了ではない。状態と速度要求のID/世代を区別する。詳細は[設計](../../docs/PHASE60_EXPERIMENTAL_ENGINE.md)。

## 4. ビルドとリンク

Release/Debug arm64とブリッジ例がビルド成功。アプリは新ターゲットを明示リンクする。承認旧版はSHA `039592e59cc1a525b495e38d3cedeb6c050792b1` を別CMake graphへexportし、全blobを検査して別プロセスで使用した。`LEGACY_BUILD.json`、`FINAL_BUILD_V4.json`、各実機manifestに実行体/ソースSHAを保存。

## 5. 実時間制御

入力常駐・Audio Workgroup・Mach policy・動的計画を必須指定。Ready後に昇格確認して開始し、Pause/Stop/EOSで静止・離脱・復元する。正式Progressive 14セッションのjoin/leave/restore対応：合格。OS全観測・確保全入口の証明ではない。C++ new/OS faultはnull。

## 6. 速度変更

40〜200%の161値をAPIから受付確認し、Ready中の160件置換と最後の保留、Stop取消、古い世代の拒否を検査した。動的実機では0.40から0.49、0.50、2.00、1.00への計画がCompletedとなり、同時要求0.41/2.00はReplacedとして保存。Candidate/Baseline各々の実Frontier・全Map・全raw PCMが固定旧参照と一致した。Appliedは可聴完了ではない。

## 7. ライフサイクル

Release/Debugの新API試験が成功：準備中Stop、予算拒否、同時準備拒否、失敗後の新prepare、Pause/Resume、要求中Stop、Stop→Play、EOS→Play、曲/世代分離、模擬route安全停止。正式代表12実行/14セッション、同一音源再始動4実行8セッションを別集計。再始動8件はprefix停止であり自然EOSと呼ばない。実装上のStopはコンストラクター内のSHA/複製完了を待つことがある。

## 8. 音質回帰

固定の独立参照12条件、動的6論理+7増分チャンク、Release/Debug関連CTest各19件が成功。実機PCMは13条件：Progressive callback受信rawとLegacy公開rawを分け、全Float32生ビット・長さ・順序・SHAを照合した。検証用参照はPhase57以前の固定参照と変更前Phase39/Phase36参照。1140/6216/51344の全研究行列は再実行せず、元結果と参照を保護した。

## 9. Golden

25/25。元WAVのSHAとraw生ビットを確認した。追加の結果集計/RIFF包み直し5試験も成功。ログはQUALITY_DRIVER、RESULT_TESTSを参照。

## 10. A/B実機試験

指定M4A由来の対応WAV：44.1kHz stereo Float32、13,706,110フレーム、310.796145秒。SHA `1fee0c9c5dd3302c02fe7f7215635a4478e0d058d4d636094998d92d29d65963`。同じWAV、Candidate、1.00倍、出力装置ID72/48kHz/512でA→B/B→Aを実行した。当時のMerodoa WAVの同一SHA・装置名・操作履歴は未確認。

|実行|計測|状態|不足frames|不足calls|callback期限|worker期限|host/sample/HAL|PCM|
|---|---|---|---:|---:|---:|---:|---|---|
|user_0_legacy|通常|Ended|0|0|0|未測定|0/0/0|未測定|
|user_1_progressive|通常|Ended|0|0|0|0|0/0/0|未測定|
|user_2_progressive|検証付き|Ended|0|0|0|0|0/0/0|PASS|
|user_3_legacy|検証付き|Ended|0|0|0|未測定|0/0/0|PASS|
|current_legacy_user|検証付き|Ended|0|0|0|未測定|0/0/0|PASS|

current_legacy_userは同一checkoutの既存製品経路で、承認039592eの旧版と版を区別する。旧版が今回不足0でも、過去80,765不足を否定しない。再現素材のPCMが当時と完全同一とは主張しない。比較詳細は[実機比較](../../docs/PHASE60_AB_VALIDATION.md)。

## 11. CPU・メモリ・起動と再始動

|実行|最初の要求→PCM秒|プロセスCPU秒|DSPワーカーCPU秒|最大RSSバイト|常駐入力バイト|
|---|---:|---:|---:|---:|---:|
|user_0_legacy|0.974551|50.715496|未測定|63160320|未測定|
|user_1_progressive|0.285781|54.316393|44.047811|192184320|109648924|
|user_2_progressive|0.357718|56.790204|43.634003|465289216|109648924|
|user_3_legacy|0.967161|51.432649|未測定|63242240|未測定|
|current_legacy_user|1.005254|47.464658|未測定|76513280|未測定|

通常計測だけをCPU/RSSの主比較とする。検証付きは旧版のworker SHAと新版の事前確保callback captureという異なる負荷を含む。RSSはプロセスの実メモリ使用量で、ここではプロセス生涯最大値。Coldは新プロセス・解析cacheなしで、事前入力SHAによるOS cacheの温まりを含む。OS cacheをpurgeしていない。

|同音源Stop→Play|session|要求→PCM秒|不足frames|
|---|---:|---:|---:|
|0_legacy|2|0.048641|0|
|1_progressive|2|0.178705|0|
|2_progressive|2|0.188251|0|
|3_legacy|2|0.059213|0|

入力複製/常駐はセッション当たり約109,648,924bytesずつ。自然EOS/Stopで実入力を解放し、診断値は保持する。512MiB/28,800,000フレームの入力上限、予約予算1GiB、同時入力/DSP所有1つを明示した。Phase54解析cacheは共用せず、Stop→Playで再準備する。

## 12. 実験統合の成立範囲

Experimental Handoff=PASS。明示選択、対応WAVの実出力、動的速度、診断、制御・所有権、比較・リンク手順を確認した。統合先の署名済みApp Sandbox、security-scoped URL寿命、実装置差替え、物理出力連続性は後続Merodoa試験。

## 13. 既存不具合と新規不具合

Phase59 Fix2の初回時計不連続、旧FIFO供給停止、OS欠測、物理loopback未実施は未解決のまま。今回の成功で過去FAILを置き換えない。今回の初回音源変換は拡張WAVとなり4実行が再生前に拒否された。原本・ログを保存し、PCM payloadを保持したRIFF包み直しで解消した。集計コードの空集合all()による成功も修正し、旧JSONを残してsummary_reviewedへ訂正した。音声APIの不足を無音補填で隠す修正はしていない。測定版CLIのanalysis_done_at_readyは入力受領完了を表す旧欄であり、全解析完了とは解釈しない。最終CLIは欄名を訂正し、MEASUREMENT_FIELD_REVIEWとFINAL_HOSTへ範囲を保存した。RTライブラリは全曲測定版と同一SHAで、最終CLIの短尺全PCMも再照合した。追加ターゲット登録直後のMake再読込順序によるビルド停止は明示configureで解消し、失敗ログを保存した。MerodoaのXcodeスキーム・MacLibraryViewには開始後の別差分を検出したが、この作業は操作せず保持した。接続7ファイル・HEAD・submoduleは不変。初回の全SHA監査と、当該UI/スキーム差分を区別した監査訂正をともに保存した。

## 14. Merodoaへの引き継ぎ可否

開発版の実験接続：PASS。[引き継ぎ](../../docs/PHASE60_MERODOA_HANDOFF.md) にCMakeの追加archive依存、専用直列キュー、Accepted/Ready、状態/速度/位置変換、入力lease、Stop/破棄と明示切戻しを記載した。Merodoa本体とsubmoduleの更新・SwiftUI設定画面は実施していない。固定するPhase60完成コミットは別途レビュー・コミット後に確定する。

## 15. 今後必要な修正

MerodoaのApp Sandbox実機・同一デコード済みWAVと装置での再現、入力権限/予算、長時間の操作上限対応、シーク能力の別設計、物理連続性と既知時計/OS問題の調査が残る。一般公開向けproduct_integration_readyはfalse。Gitは50,000,000 bytes制限と既存フックを維持し、大容量証拠はbuild/phase60にSHA/復元レシピ付きで保存する。
