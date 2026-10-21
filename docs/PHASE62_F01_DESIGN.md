# Phase62 F01: 初回供給jobと要求IDの同時公開

開始点はmain@b0352c6f4c22f100f161297769b26561dc07701b、clean。基準ソース一覧SHAはcefdb1294e89cb5280ad8f6df401eac59825212334e4110f958ca6f0d7c0199c。新しい実行先はbuild/phase62_f01_20261021_01。既存e5レビューの局所PASSと復旧後41/正常RT8の記録は保持する。今回のcommit/push/PRは行わない。

## 同期と所有権

seekLoopのLoop・Loop内seek・停止中速度準備は、同じEngine mutex内でjobID、loopID、seekVersion、入力世代とnextを選択・構築する。構築/enable成功後、その区間内のif(next)でactiveLoopSpeedRequestIDと非終端の外部Preparing/version/timeを公開する。構築済み供給版を制御側が知らない状態をmutex外へ公開しない。次要求BはAを保持対象にして受付でき、未発生のcommit/outputStarted/PCMを追加しない。後からterminalを復元する方式は使わない。

nextのstart、Ready待ち、callback切替待ち、stop/join、退役は従来どおりmutex外。旧FIFOと入力解析・InputLease寿命、最大2実行owner/2保存点の規則は不変。構築/enable例外はID公開前にcatch、通常取消・失敗・Stop・Clear・入力失効・破棄は既存のversion失効と共通退役cleanupでactive IDを0に戻す。採用/Started/Doneが勝った版は既存の完了/退役経路へ残す。早い0化や全要求Busy化を追加しない。

## 決定的な比較

LoopJobDispatchでAを通常APIから受理し、next構築後の最初のmutex解放直後、start前のLoopJobSelectedで通常workerだけを有限待機させる。ここでBを通常APIから受理する。比較版は同じhookより後に別mutexでactive IDを公開し、修正版は同じhookへ到達する前に公開済みである。hook自体からEngine APIを呼ばず、callbackは待機させない。旧比較版は観測/順序制御を加えたb035挙動であり純未改変binaryではない。

短曲dspDone＋未消費FIFOと、1秒曲のnormal checkpoint permit拒否の両理由を両Presetで確認する。job/要求/入力世代/準備版、初回Bの実session/epoch/PCM、A/Bの全ID終端とAの確定履歴不変を記録する。旧挙動の成功判定は単なるReplacedやtimeoutではなく、AがReplacedのまま実採用された不一致の観測である。選択直後のStop/Clear/準備失敗と直接closeは退役・ID回収・次要求回復を確認する。

## 変更と回帰の対応

|変更箇所|影響する実行体/driver|今回の扱い|
|---|---|---|
|Engine.mmのID公開移動、Engine.hの通常試験hook|Engineを含むadoption/fault/partial、Playing/外部台帳/API/PausedClear/Race、native5群|新Release/Debugへ再リンクして必要群を新規実行。旧28点不変の証明を転用しない|
|AdoptionReviewNativeのF01追加|同targetとそのinclude利用試験|旧比較/修正のF01両Preset、既存A1/A2/D09/Internal4096、直接closeと関連制御を新規実行|
|共有DSP/planner・そのdriverは無変更|動的640/重点20/形式54、Exact896/Golden25/有限322/reuse322、worker/cache|各依存・入力/参照/driver・compile条件・実行時sourceを照合し限定再利用。新Engineのbinary一致とは呼ばない|
|Engine.mmを直接includeするrenderer試験翻訳単位|境界872/独立handoff6（renderer関数本体は無変更）|CMakeのlibリンクだけでは非依存と判断しない。既存renderer4群を新binaryで再実行|
|既存CTest集合・証拠検証器|Release/Debug各20CTest、75単体検証|既存20件を減らさず再実行|
|D07/D08|Loop履歴H≤1、descriptor距離d-c≤44、下位512/513・stale-cycle|ID公開以外の前提を変えず、閉鎖を維持。到達不能上限の上位再現を再開しない|

有限ゲート/故障注入の機能試験と、ゲートなし正常RTの判定は分ける。正常RTは既存A=0/30/270秒と4100周を両Presetで直列実行し、装置bufferを復元する。独立凍結参照からPCMを得る条件、全161速度と既存境界式は変更しない。

公開・能力フラグは現行falseを維持する。今回の局所完了、一般公開、Merodoa既定採用の判定を分ける。別公開課題はREPORTの次作業表へ引き継ぎ、本修正へ無制限に広げない。
