# Phase 59 Fix REPORT

判定 **B：条件付き成立、Gate 2未合格**。PCM品質は完全一致で保護した。起動時計、従来製品FIFO、OS未観測域に未解決事項が残る。

## 1. 発見した原因

位相更新・Stereo近傍計算の重複と、ブロック内処理フレーム数によるCPU負荷を確認した。高速排出ではアプリの復元操作前にOS優先度が低下し、実行待ちが長くなった。初回時計の完全な原因、過去49msと4.8秒の環境を含む因果、旧製品供給停止の正確な原因は未特定。

## 2. 原因を示す証拠

`CLOCK_REPRODUCTION.json`、`PHASE_BEFORE_ANALYSIS.json`、`PHASE_AFTER_ANALYSIS.json`、`LEGACY_FAILURE_REVIEW.json`、`EOS_TRACE_OBSERVATIONS.json`を保存した。OS状態が取得できなかった領域を正常で補完しない。

## 3. 変更ファイル

Phase35位相更新・Stereo補正、PhaseLockerの準備処理、Phase36/57/58の診断、研究用Native、独立参照テスト、検証スクリプト、Git容量ガード、AGENTS、文書を変更した。全最終ソースと実行体SHAは `FINAL_CANDIDATE.json`。

## 4. 実施した修正

算出済みFloat32振幅・位相、同じ所有者のStereo近傍値を再利用する。入出力が重なる場合は従来処理を維持する。ピーク容量へ準備時に全書込みする。位相更新順、近傍加算順、精度、OLA/FIR、50ms遷移、FIFO、ゲイン0.5は維持した。

## 5. 変更前後の比較

位相更新部品のCPUは交互5反復で約8〜10%短縮。指定窓のStereo CPUは約18〜21%短縮した。対応する180秒・2倍・CPU2の2試行は、最大RT CPU27.117/27.722ms、全PCM一致、不足・期限・RT new 0。試行間変動を含むため、元の49msを完全に説明したとはしない。

## 6. 初回callback時計の検証

初期80試行は成功したが、固定0.50倍でsample0→1436（要求512）、余分924フレーム/19.25msを再現した。FIFO不足とPCM不一致は0。動的要求前・同じ48kHz形式で発生し、原因未特定。閾値・epoch・初回除外を変更していない。

最終動的normalでも、同じ入力SHA・初期0.50倍Candidateでsample0→1160（余分648/13.5ms）を再現した。最初の2回のFIFOは16384→15872、各512フレームを受け取り、全PCM一致・作業期限超過0だった。最終新経路の不合格は計1セッションで、`FINAL_NATIVE_FAILURES.json`へ個別記録を残した。

## 7. DSP期限超過の検証

最終固定長尺8件、合格8件。周期2048/sampleRate、計算予算90%を維持した。実際の期限ticksを保存し、最大Wall位置と期限判定位置を区別した。

正式な180秒・CPU2の各3反復では、最大RT CPUはCandidate 31.003334ms、Baseline 33.088292ms。最大RT Wallは各31.009167/33.088333ms。両方とも46.44ms周期と41.796ms計算予算以内だった。先の詳細診断2試行とは分布・計測設定を区別する。

## 8. 旧製品FIFO不足の検証

修正前の旧版Baseline smokeに8208フレーム不足を再現。過去Candidateの1319も保持。両方ともPCMは一致していた。最終旧製品比較11/12。旧実行体固有の問題として区別するが、根本原因を確定できていない。

最終比較の旧Baseline smokeにも234フレーム不足（session4/epoch1/callback179、wanted470/received236/fifo236）があった。PCM・時計は合格、供給は不合格。`FINAL_LEGACY_FAILURES.json`に保存し、過去とは異なる再現位置を同一原因だと推定しない。

## 9. EOS再始動の検証

実機で同一プロセスEOS再生成40件、Release/Debugの周期付き・高速・通常優先度を別検査。実機合格は40/40。高速排出・Debugの期限失敗は `eos_before/` と `eos_after/` に保持。旧4.8秒の直接証明はない。

## 10. Zero FillとOS状態

reserveだけだったピーク領域を準備時に書込みした。旧Zero Fillの割当元と一致する証明はない。修正前起動traceの既知48/96区間にDecompress Memory24件、EOS traceは既知65/307区間にVM fault0。Unknown/未取得を全域の安全保証へ一般化しない。

追加の最終trace付き再生のNative判定は不合格。正式274音声セッションとは別記する。最終6秒窓の全状態既知は94/155区間、窓内Unknownは61、窓外・部分区間は1777。既知区間のVM観測は{'Decompress Memory': 3}。全区間のfault 0とはしない。指定した元の最大Wall位置付近の7区間は、窓内0区間で未取得。attachの開始遅延により取得位置は後ろへずれた。

追加試行の時計FAILは起動時ではなく、約85.821秒のcallback8016→8017の518フレームの余分な進みだった。直前のIOProcが遅れ、OSはClient Overloadを1件記録した。Native独自のHAL windowカウンター0とは区別する。Client threadの約11.2ms Blockedとdtsecurityによる起床を観測したが、待機の全因果や計測器の関与は未証明。元の初回時計異常と同原因だとはしない。根拠はPOST_TRACE_CLOCK_VM.json。

## 11. 動的PCM完全一致

1140/1140。全161速度の隣接640条件、Latest-Wins、L1/Phase50、L2、safe-densityを旧独立参照で保護。速度全組・全速度実機適用とは区別する。

## 12. 固定PCM完全一致

Phase58 6216/6216、Phase57 51344/51344。全PCMの長さ・順序・Float32生ビット・SHAを比較した。拒否条件も別照合した。

## 13. 実時間試験

動的189/190。固定短尺36/36、長尺8/8、EOS40/40。項目別ゼロ合計と分布は `MEASUREMENTS.json`。未測定項目を0にしない。

## 14. CTest・Golden

Release93/93、Debug18/18、Golden25/25。独立旧コードとの部品比較、TSAN/ASAN/UBSAN、50MB境界・index・履歴途中blobの隔離検査も合格した。

## 15. ディスク容量

ユーザーが空き容量を確保した後に再開した。traceは一時ktraceとbundleの両方を含めて1回2GiB、空き2GiB、累積8GiB・4回を上限とした。`TRACE_BUDGET.json`、`TRACE_TOTAL_BUDGET.json`、各取得manifestを参照。圧縮はopen FDと復元SHAを確認し、使用中の一時ktraceには触れていない。

動的長尺の初回は4GiB基準で安全中断した。元の中断記録と一致1件を保持し、長尺16・増分144件は別保存先で同じ条件を再実行した。全行列は`validation_final/effective_summary.json`で集計し、初回分を重複加算しない。完了済みDebugビルドも`DEBUG_BUILD_ARCHIVE.json`の全ファイル復元SHAを照合して圧縮し、EOS実行体は同一SHAで別保存した。

Gitは50,000,000バイト境界を採用。既存の4大容量blob/5追跡パスは保持し、新規blobの検査器とpre-commit/pre-pushを導入した。履歴書換え・LFS移行は行っていない。

## 16. 未解決事項

起動時計の原因、過去49msの全因果、従来製品の供給停止、元の4.8秒停止、全実時間領域のページフォルト0は未証明。IFFT/OLAや位相内の全関数を個別に計測したわけではない。最終試行の成功でこれらを解消扱いにしない。

## 17. Gate 2判定

**未合格**。品質の成立と、時計・FIFO・メモリを含む実時間安全性の成立を分ける。各boolと範囲は `VERDICT.json`。旧製品の独立したFAILも別に残す。

## 18. 次Phaseへの移行可否

Gate3・製品統合へは進めない。次のFixでは初回SourceNode/HAL時刻の失敗時OS観測、旧製品のシーク中供給履歴、実時間メモリの観測範囲を優先する。新しい音質機能やMerodoa統合は追加していない。
