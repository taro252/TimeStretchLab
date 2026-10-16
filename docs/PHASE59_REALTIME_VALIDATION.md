# Phase 59：実時間速度変更の検証

## 環境と順序

Apple M1 / MacBookAir10,1 / 16GiB / macOS26.6.2。Release arm64、内蔵出力、48kHz/512フレームをセッションごとに確認する。Python実行系のx86_64表示と、音声実行体のarm64を混同しない。環境取得の失敗も `ENVIRONMENT.json` に残し、追加で取得した実機情報を `hardware.txt` に保存する。

計画・保護境界・決定論的全PCM・161速度の確認後に、`phase59_native` を使う。音声再生中は他のDSP試験、ビルド、大きなOSトレース書出しを同時に走らせない。

## callbackの計測とPCM比較

callbackは既存FIFOを読み、raw PCMを事前確保済みの検証領域へ順番に保存する。計測用の追加コピーを含めて期限を判定する。共有所有権、解析、計画、mutex、ファイルI/O、C++ newを持ち込まない。

動的要求の実際のFrontierはOS進行によって変わるため、事前に別の壁時計試験のPCMを正解として置かない。停止・callback静止・worker joinの後に実際の適用計画を保存し、変更前の全曲解析＋Phase39/42/50/36へ再現して全Float32ビットを照合する。Nativeの記録段階のPASSと、独立参照とのPCM合格は別であり、最終driverは両方を要求する。

callback CSVから提示位置の連続性、受領量、不足量、時刻を確認する。EOSは全PCMと最終長、ウィンドウ停止は接頭部として分類する。FIFO不足を後から届いたPCMのSHA一致で隠さない。

## 必須指標

要求受付、worker認識、計画開始/終了、計画Wall/CPU、適用確認時刻、適用/完了出力位置、FIFO公開・callback提示位置を別々に保存する。callbackが適用/完了座標を初めて越えた記録も対応付ける。

FIFO不足、書込み拒否、callback期限、HAL、host/sample時刻、PCM欠落・重複、不一致、実時間C++ new、callback C++ new、作業区間期限超過、旧session/入力世代の混入を独立に判定する。要求からMap適用までの中央値/p95/p99/最大と、実際の提示到達時刻を混同しない。

Audio Workgroup参加・離脱、Mach実時間policy、実測優先度、Pause/Resumeの降格/再昇格、終了時復元を確認する。workerのWall/CPU差は非CPU時間であり、OSトレースなしにすべてをPreemptedと分類しない。

## 負荷・寿命・故障

通常、CPU競合2スレッド、メモリ保持、連続操作、大きな変更、過渡音素材、3分/5分、Pause/Resume、途中Stop、EOSを分けて記録する。負荷配列の保持とOS全体のメモリ逼迫は異なる。

計画処理・確保の故障と、実時間昇格前の故障を明示的に注入する。検出できた故障注入を正常音声セッションの成功件数へ入れない。失敗を正常EOSへ変換せず、再使用せず、未完要求を取消し、workgroupを解放する。昇格前故障の注入は実際のApple APIが失敗した環境の測定とは区別する。

## 診断量・容量・制限

worker、詳細イベント、スレッド標本はPhase58 Fixの固定上限を維持する。長尺で標本上限に達した区間は未観測であり、callback記録欠落とは別である。プロセスPeak RSSには検証用PCM領域・診断領域が含まれる。常駐入力・複製FD・Map容量・Snapshot容量と分けて示す。

`START_STATE.json` のWAV512MiB、raw作業512MiB、一時参照256MiB、詳細CSV256MiB、トレース512MiB、保存証拠1536MiB、空き下限4GiBを目安に、各試験の生成量と空きを記録する。成功PCMは1条件の作業領域を再利用し、入力はレシピとSHAを保存する。既存results・Golden・参照・FAIL証拠は削除しない。

本試験は物理音響遅延、全装置、全OSの無条件保証ではない。過去の製品host/sample異常の原因解決も主張しない。最終件数・失敗・適用範囲は [REPORT](../results/phase59/REPORT.md) / [VERDICT](../results/phase59/VERDICT.json) にまとめる。

最終版の動的実機試験は190/190条件が合格した。内訳は通常30、負荷90、Pause/Stop30、大量要求6、素材/EOS近傍30、長尺4。178件が全PCM一致、途中停止12件が接頭部PCM一致だった。要求からMap適用までの中央値31.023ms、p95 467.883ms、p99 970.215ms、最大1114.219msを記録した。先行時計異常と固定長尺・旧製品の回帰失敗を含む総合判定はB、Gate 2未合格である。

要求認識は、DSPが世代通知を読み、Frontierを公開した時刻である。通常側の計画受付時刻と区別し、この認識を得てから計画する。`speeds.csv` の `worker_seen_s`、`planner_seen_s` を別に記録する。

起動直後のhost/sample時計の不連続を1件観測しており、後続の成功で合格へ読み替えない。追加トレースでは再現せず、実時間98ブロックのうちOS状態を完全観測できたのは64ブロックだった。そこでは `PhaseLocker::analyzePeaks` 内のZero Fillを1件（5.708µs）観測した。ページ割当がないという保証はしない。詳細は `startup_trace_known_coverage.json` と最終REPORTに記録する。

EOS後の同一プロセス内の新規Playは、計画適用後に通常優先度へ戻して排出する機能検査も追加した。音声周期を無視した実時間workerの高速排出では、Releaseで約4.8秒の非CPU区間と待ち時間超過を観測した。周期を付けたReleaseは成功したが、Debugの実時間実行は30秒の待ち時間を超えた。OS側の予算制限の可能性はあるが、該当OS状態は未取得であり断定しない。これらの失敗は `eos_restart_diagnostic*` と `eos_restart_paced` に保持し、通常優先度の機能検査やRelease実機の成功で解決済みとはしない。

保存容量の当初下限4GiBで、通常30件とload14件の完了後に未開始条件が中断した。音声子プロセスの終了を待って整理し、成功PCMのSHA/再生成手順を照合して作業領域を解放、成功Debugビルド・派生XML・回帰行データを無損失圧縮した。固定参照・FAIL・元トレース・旧Phaseのデータは保持。残る保存量の見積りに基づき再開前に下限を3GiBへ更新した（STORAGE_REBUDGET）。検証済みの音声セッションは繰り返さず、未開始条件だけを再開する。整理中は音声計測を行っていない。

ユーザーの明示許可後、Instrumentsに未保存記録がないことを確認して通常終了し、関連DTServiceHubを終了した。今回の一時ktrace約1.48GBを約137MBへ圧縮し、復元した全バイトのSHA一致と開いているプロセスがないことを確認して元一時ファイルを解放した。元の保存済みtrace bundleと過去のktraceは保持した。復元手順・属性・SHAは `CURRENT_TRACE_ARCHIVE.json` に保存した。

取得時のバックエンド一時ktraceと保存済みtrace bundleの合計は少なくとも約1.56GBで、当初のトレース予算512MiBを超過した。最終保存量が圧縮で減ったことと、取得時に予算を守れたかを分けて記録する。

固定速度の実機回帰では180秒境界素材/2倍/CPU競合2でCandidateに作業期限超過2件、Baselineに3件を観測した。全PCM一致・FIFO不足0でも両条件は不合格とする。従来製品の変更前バイナリCandidate smokeではFIFO不足1319フレームを観測した。再構築側の成功で相殺しない。該当実行のOS状態を取得していないため、原因や今回の変更との因果を断定しない。時系列は `DEVICE_FAILURE_TIMELINES.json` に保持する。

検証用capture配列とcallback記録配列は再生前に値初期化する。全ページを明示的に書込みタッチする処理やmlockはないため、物理ページ常駐やcallbackのVM fault 0まで確認済みとはしない。実時間C++ new 0と、ページ割当・C/Objective-C確保の有無は別の指標である。
