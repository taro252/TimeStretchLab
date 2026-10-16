# Phase 58 Fix：検証方法と適用範囲

最終の件数・数値・合否は [REPORT](../results/phase58_fix/REPORT.md) と [VERDICT](../results/phase58_fix/VERDICT.json) に記録する。本書は試験を再現し、結果の意味を判断するための条件を示す。

最終V3は585/585音声セッション成功（全PCM503、接頭部82）、Phase58固定PCM6,216、Phase57全PCM51,344、Golden25、Release決定論的CTest88、Debug関連11、既存製品実機8、厳格な実時間CTest2が合格。旧34,807ファイルの保護と、1,549セッション・511,713 callbackの記録整合性を確認した。Gate 1は測定範囲でA、動的変更の実装へ着手可能。製品統合は未実施。

## 入力・実行体・環境

基準HEAD、OS、Xcode、Clang、実機、入力と実行体のSHAを `results/phase58_fix/START_STATE.json`、各manifest、`candidate_v2_binary.json` に保存した。Python実行系はRosettaのx86_64表示だが、検証実行体はCMakeでarm64 Release（-O3 -DNDEBUG）を指定している。Apple M1、16GiB、内蔵装置72、48kHz、512フレームで測定する。

通常負荷は外部アプリの活動を排除した専用OSではない。負荷試験は実行体内のCPU競合2スレッド＋128MiB、別ケースで512MiBまでの常駐配列である。OS全体のメモリ逼迫、物理装置変更、物理音響遅延は測っていない。

## 反復と診断

`phase58_fix_repeat.py` は毎回新しいプロセス・Pipeline・AVAudioEngineを作り、独立セッションとして直列実行する。最終300回の入力・FIFO・先行量・生成ブロック・ゲイン・装置条件は修正前と同じである。試行ごとの開始終了UTC、コマンド、終了コード、標準出力、全callback CSV、worker CSV、設定、PCM一致を保存する。

`profile=off` では詳細・ブロック記録・スレッド標本を止める。ブロックの最大Wall/CPUと供給間隔、PCMとFIFO・callbackの安全判定は維持する。未取得の段階別分布を0としない。標準方式＋入力常駐も別群で比較する。20回の比較群は計測の機能確認を含む限定的な比較であり、低頻度不具合の解消判定は最終反復やOS証拠と合わせて行う。

OSトレース3回は同一プロセス内の独立Pipelineセッションであり、独立プロセス300回へ加算しない。計測器の負荷も含む。修正前の診断試行、時刻異常によるFAIL、トレース取得手順の失敗、容量不足時の不完全XMLを保存し、成功率のために除外しない。

## PCMと実音声の判定

固定参照 `build/phase58_frozen/product_reference` は変更前の独立Phase36演算と製品の出力長契約から生成する。SHA `3a3b04454f754c35afa4cac121a726fa31c44a6854761a7de5f71aa057f2a957` を保持する。Native callbackは事前に読み込んだ参照に対し、ゲイン適用前のraw PCMを全受領サンプルのビットで比較する。EOSでは全出力長・SHAも一致を要求する。

ウィンドウ測定・模擬経路変更・起動比較では接頭部一致を判定する。これを末尾までの一致へ読み替えない。全PCMは別のオフライン行列とEOS試験で確認する。ハードウェアのアナログ出力や下流のレート変換後のビット一致を測定したわけではない。

FIFO不足、callback不足回数・最大連続不足、書込み拒否、PCM不一致、callback期限、HAL期限、host/sample時刻、記録欠落を独立に判定する。FIFO不足があっても後からPCMが全部届けばraw SHAが一致し得るため、SHAだけで合格にしない。

従来Phase46の時刻判定を変更しない。host進行の許容は100µsまたは2サンプルの大きい方、sample進行誤差は2フレーム以内。HALは同じ研究用の余裕を使い、callback実行時間が要求フレーム数/sample rateを超えた件数も別に測る。Pause/Resumeはepochを更新する。時計橋渡しの不確かさも保存する。

C++ callback new計測と、実時間workerの昇格中全寿命のnew計測は別カウンタである。準備中のnewは0でなくてもよい。C mallocやObjective-Cの全確保まで測っていない。検証実行体に計測フックがない項目はnullとする。

## 固定速度・素材・寿命

実機行列は44.1/48kHz、Mono/Stereo、PCM16/float32、Candidate/Baseline、0.40/1.00/2.00のEOSに加え、無音・単発・連続アタック・持続音・連鎖・自然素材を含む。30秒MIXは0.40/0.41/0.50/0.75/0.99/1.00/1.01/1.25/1.50/1.99/2.00の11速度を測る。負荷下でも両presetの代表速度を測定する。

Pause/Resume、EOS後の再作成、Stop→Play、模擬経路変更で世代の混入・不正EOS・キャンセルを確認する。模擬通知を物理装置変更と表現しない。以前の長尺4条件は同じ180秒境界/300秒連鎖素材と速度・presetを使い、EOSまで再実行する。

`phase58_fix_study.py` は全161固定速度を含む計6,216のオフラインFIFO消費セッションを担当する。修正後の常駐入力・借用Snapshot経路を通すが、実機の速度で消費しないため実時間昇格は行わない。実時間スケジューリングの実証はNative試験に限る。

Phase57は元のmap終端契約の独立参照 `build/phase57_frozen/reference`（SHA `461c26d10b0fd8a781cbffcbbab49072f501e02172e2a7c2f26e3e49a0253a1e`）で再検証する。製品長の参照へ置き換えない。Golden25、Phase56解析、Phase54固定/cache/seek、Phase39動的変更・L1/L2/safe-densityは既存の契約を保つ。

## 起動・CPU・メモリ

30/180/300秒の同じMIX、0.50倍、両presetを用い、従来Phase54・Phase58最終同期修正版・今回Fixを3回ずつ比較する。新プロセスのColdと同一プロセス内Stop→Playを分ける。ColdはOSファイルキャッシュ消去を意味しない。旧Phase58初期測定も残し、最終同期修正版との今回の同条件比較を混同しない。

入力検証、SHAと複製、常駐完了、解析開始、Event/Map確定、最初の生成/公開、Ready、AV開始、最初の有効callback、全解析完了を別時刻で保存する。CPUは解析・DSPのworker寿命とプロセス測定を分ける。Ready以降のPlay→callbackだけで入力準備の負担を隠さない。

検証用の独立参照読込み・生成は起動計時前である。一方、プロセスPeak RSSには事前読込み参照や診断領域を含む。従来製品実行体はこの参照を内部に保持しないため、RSSの単純比較は製品メモリ差の測定にならない。Fixの入力常駐バイト数、非公開一時ストレージのバイト数、参照バイト数を併記する。再始動時のPeak RSSはプロセス寿命最大値で、各再始動単独の最大値ではない。

## 監査と再実行

実機再生中に重いビルド、別DSP検証、巨大OSトレースの書出しを並列実行しない。`phase58_fix_regression.py` は実機終了後にRelease全体、Debug関連、決定論的CTest、全PCM、Golden、基準HEADの全既存ファイルを検査する。ビルド・CTest・競合検出器は直列、独立した出力先を持つ全PCM試験群のみ最大3群を並列実行する。Phase57 stage2はstage1の合格後に開始する。この並列部分のWall/CPU/RSSを単独の性能測定として扱わない。共有Snapshot受渡しには競合・メモリ検出器も適用する。

`phase58_fix_statistics.py` はFAILを含む全分布を集計する。標本観測から全期間の優先度や非実行時間を補完しない。`phase58_fix_measurement_audit.py` ではcallback CSVから出力位置・不足・期限用実行時間を再集計する。この監査PASSは音声FAILをPASSへ変換するものではない。

全再実行は存在しない新規出力先へ行う。旧Phase53〜58、Golden、固定参照の保護監査と最終diffを確認する。既存製品の過去のhost/sample不連続は別問題として保存し、新経路のFIFO改善によって解決したとしない。
