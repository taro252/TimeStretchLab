# Phase 56：継続状態を持つ増分解析

## 適用範囲

実験用`phase56_incremental`は、PCMチャンクを追加しながら解析状態を継続する。入力の先頭からSTFTを再実行しない。全曲参照はPhase55完成SHA `14d30be6a7a2dc164eead5a5d747c60fba806b49`の既存実装であり、Phase13、TransientDetector、TransientEventMap、アンカー、Phase37/39を含む既存ソースを変更していない。製品PlaybackEngine、完成解析cache、Merodoaへ接続しない。

STFTは短い窓ごとに周波数成分を調べる処理、TimeMapは入力位置と出力位置の対応表である。「Through」はすべて**末尾を含まない要素数**とし、入力サンプル位置と解析フレーム番号を区別する。ここでの完全一致は解析と固定速度TimeMapの一致であり、PCM合成の一致や再生開始時間の改善を意味しない。

## 内部API

`src/prototype/Phase56ProgressiveAnalysis.h`の`ProgressiveAnalysisSession`を使う。

| 操作 | 契約 |
| --- | --- |
| コンストラクター(rate, channels, generation, limits, requestedSpeeds) | 44.1/48kHz、Mono/Stereo、0以外の世代。固定Experimental 3500解析。要求速度の整数列。既定は400000〜2000000を10000刻みの全161速度、空列は解析だけ |
| appendInput(generation, absoluteOffset, planarPointers, frames) | 受信済み位置と同じoffsetだけ受付。非インターリーブfloat32。内部で最大1,024サンプルずつコピーして解析を進める |
| advanceAnalysis() | 取得済みの完全な窓を処理。入力不足は待たず戻る。cancel要求も確認する |
| getSnapshot() | 読取り専用の共有所有権。別スレッドから取得可能 |
| finishInput(generation) | **真のEOSの明示通知**。残るpadding・検出・event・map末尾を一度だけ確定。最後の公開直前にもcancelを確認 |
| cancel() | 別スレッドから可能な要求。解析側が次の境界で受理してキャンセルsnapshotを公開する。完了済みEOSは取り消さない |
| failInput(generation, error) | 入力アダプターからの失敗通知。正常なEOSや完成cacheへ変換しない |
| statistics() | 解析側または解析静止後だけ。処理回数、コピー量、メモリの診断 |

解析を進める操作は**1本のproducerに直列化**する。getSnapshotとcancel以外を並行に呼ばない。オブジェクトを破棄するときはproducerを終了してから破棄する。snapshot自体はsession破棄後も保持可能。いずれも音声callback用APIではない。

finishInputの任意の第2引数は、完了commit直前の故障・キャンセルを再現するテスト専用hookである。通常は渡さない。末尾mapの計算中に来たcancelも、最終snapshotのcommit前なら受理する。commitと同時の要求では正常EOSが先に成立する場合があり、既に成立したEOSは変更しない。

0長チャンクはEOSではなく、解析を進めない入力として受け付ける。世代違い、隙間・重複のあるoffset、null channel、NaN/Inf、設定上限超過は失敗する。エラー時に直前の確定済みデータを参照できても、エラーsnapshotの続きを正常再開してはいけない。新しいsessionと世代を作る。

## 継続する状態と確定条件

### STFTと特徴量

入力は1chあたり8,192サンプルのringに保持する。FFT=4,096、hop H=1,024、左右padding=2,048、絶対フレーム番号kの窓は`[kH−2048,kH+2048)`。右端が受信済み入力に入るまで処理しない。先頭の負位置だけを0にし、チャンク末尾をpaddingにしない。

窓のコピー、左右のFFT、各binのnorm加算、sqrtを既存の順で実行する。既存`TransientDetector::pushMagnitudes()`をそのまま使い、前回float logスペクトルとdouble logEnergyを維持する。この既存オブジェクトの`finalize()`は呼ばない。

### 閾値・検出

`IncrementalDetector`が過去12フレームのfluxの中央値と中央値絶対偏差を同じ順序で計算する。算術は既存式に対応させた実験用実装で、既存一回解析の意味は変えていない。直前・次のflux、cooldown=2、lastDetected、lookback=1を継続する。

threshold/strengthは特徴量が揃えば確定する。detectedは次の特徴量を待つ。resetAppliedには次の検出が遡る可能性があるので、非EOSでは分類完了数からさらに1フレームを引いたprefixだけを公開する。EOSでは最後の局所最大を既存と同じ「次がない」規則で判定し、全フレームを公開する。

Phase55の反例のような古いtrueを残す再finalizeは行わない。暫定フィールドを後から修正できるのはproducer内部だけである。

### イベント

`IncrementalEvents`は特徴量・threshold/strengthが確定したactiveフレームだけを順番に消費する。detected flagを候補選択に使わない点も既存と同じ。

距離≤4、または距離≤12かつenergy<既存peakの20%なら統合する。最も大きいfluxへpeakを動かし、endとstrengthを更新する。`attackEndFrame`は既定の`preserveAttackRegion=false`の統合結果どおり、初期onsetの値を保持する。選択的resetの別設定を暗黙に追加しない。

イベントの閉鎖は次のいずれかで行う。

1. 次の候補が既存の距離・energy条件で統合されず、新しいeventになる。その候補まで確定した時点で前のeventへ戻る経路はない。
2. 直近end=eのあと、e+12までの候補判定を処理しても統合候補がなかった。候補の確定数Cに対し`C > e+12`。
3. 真のEOSでactive候補がすべて終わった。

12は連鎖全体の長さではない。連鎖が続く間はopen eventを保持し、閉鎖済み配列へ加えない。16/128/4,096/16,384フレームの分類器入力と、約14,066解析フレームを持つ実際の5分PCM連鎖で検証する。

### 精密アンカー

候補によって暫定peakが変わった時点で、既存`TransientAnchorLocator`を単一eventへ適用する。窓は`[pH−H,pH+2H)`、crest≥20、runner-up比≥3、内点必須。候補のFFT窓が完全なので、必要な3,072入力サンプルも揃っている。8,192サンプルringにはこの窓が残る。

peakが動けば暫定アンカーを交換し、eventが閉じた時点でだけ公開する。peakが長期間動かなくても値を保持しておくため、後から古いPCMを読み直す必要がない。これが任意に長い連鎖を短いPCM ringで扱う条件になる。

## 増分TimeMap

`MapPrefixBuilder`は要求した速度のmapを並行に構築する。既定は0.40〜2.00倍を0.01刻みの全161速度。速度を100万倍した整数で指定し、反復double加算で速度値を生成しない。既存Phase39と同じ`1.0 / (double(speedMicros)/1000000.0)`で比率を計算する。要求順を保持し、重複・範囲外・同時161列超過は初期化時に拒否する。閉じたpeakまでの区間しか計算・公開しない。将来eventは前のeventのendから最低5フレーム離れ、伸張側pre-roll=2・圧縮側の左肩=3は前の閉鎖peakへ届かない。連鎖中のeventの仮末尾を右端に使わない。

伸張側は保護重み総和、アンカー補正差、区間長から既存と同じbaseline/depthを計算する。**区間境界でdouble出力位置を再初期化しない。** 先頭からの加算順と各nodeのllroundを維持する。

圧縮側はPhase37の肩重み、minimumBaseline、容量制約とfallbackを維持する。区間始点は丸め済み理想アンカーに合わせ、区間末尾を明示的に理想値へ丸め直す。伸張側とは別の規則をそのまま保持する。eventがない曲はPhase37の例外経路どおり、全体の単純な累積加算になる。

Phase37が非単調な区間・不正なMidホップで拒否する入力は、増分側もProcessingエラーとする。例えば曲頭近くの精密アンカー補正が最初の圧縮アンカーを負位置へ動かす場合である。失敗した計算途中のnodeを公開せず、既存の不成立条件を近似で回避しない。

解析結果自体と、特定速度のmapの成立は別である。requestedSpeedsで必要な速度だけを指定でき、空列ならTimeMapを構築しない。2.00のmapが既存でも成立しない入力について、解析だけ・0.50だけの増分処理は既存の対応する結果と一致することもテストする。全161速度を要求したsessionでは、いずれかの要求速度のmap失敗を隠さず、session全体を失敗させる。

小数6桁の固定速度指定も既存Phase39の整数表現に対応する。0.666667倍の選択指定を独立に照合したが、全小数6桁の網羅はしていない。session開始後に要求速度の追加・変更はしない。必要なら新sessionを作る。

等倍も解析を通し、閉鎖境界までのnodeを順に公開する。素通しの新しい再生経路は追加しない。

最後の区間とpadding nodeはfinishInputだけで生成する。固定出力長が既知でも、未来eventの位置は既知ではない。CandidateのL2とBaselineのCは**同じ初期固定速度の座標列**を使うことを161速度の専用テストでも確認する。速度変更の保護・計画・密度切替は別問題であり、このbuilderは実装しない。

## Snapshotの所有権と境界

| フィールド | 意味 |
| --- | --- |
| inputGeneration | この入力だけの世代。sessionをまたいで再利用しない |
| speedCount / speedMicros | 要求速度の列数と100万倍の整数値。既定161列。要求順にmapを対応させ、mapForSpeedで正確な速度を検索 |
| receivedInputFrames | 受理した各チャンネルのPCMサンプル数 |
| featureThrough | 生成済みSTFT特徴量のフレーム数。暫定な分類フィールドは公開しない |
| detectorThrough | 全フィールドが不変な検出prefixの長さ。detector.sizeと同じ |
| closedEventCount / closedAnchorCount | 不変なevent/anchor要素数。常に同数 |
| mapThroughNode | 要求した速度で共通の公開済みnode数。indexとしては0〜count−1を読める。要求速度が空なら0 |
| activeFrameCount | 実入力の完全な窓に基づく候補フレーム数 |
| transientCount | 分類済み検出数。末尾に近い未公開のreset待ちフレームも含み得る。prefixから数え直す数とは区別 |
| isFinal / isCancelled / hasError | 正常EOS、cancel受理、失敗は別の終端状態 |

非空入力の最初のmap node=0だけでは実用的な区間がない。`mapThroughNode > 1`を最初の非空区間の観測条件にする。空入力の最終mapは既存参照どおり空。確定データに範囲外アクセスすると例外になり、暫定データの参照へフォールバックしない。

公開配列は64要素ページと深さ16の不変二分索引を共有する。変更ページと索引経路（最大17 node）だけを複製する。全配列の再コピーや解析の再実行は行わない。getSnapshotが返すshared_ptr<const Snapshot>は既存ページを変更せず、古いsnapshotを保持した読者と共存する。

スナップショット本体・ページ・索引オブジェクトの計数容量に既定64MiBの上限を設ける。本体は最大161列分の共有参照を持つ固定サイズで、要求速度を減らすと主にmapのページ・索引・内部座標列が減る。読者が古いsnapshotを溜めても無制限に成長させず、上限でAllocationエラーにする。復旧通知用snapshotは先に確保してあり、割当失敗を正常EOSにしない。計数はallocator管理領域やFFT内部確保を含む厳密RSSではない。

全161列を同時に構築・公開すると7列時より所有量・累積コピーが増える。性能試験は全161列で取り直し、旧7列の数値を流用しない。

内部の特徴列・座標列は保持するので、全解析メモリが曲長に依存しないわけではない。既定入力上限は48kHz換算10分、設定可能な安全上限は10億入力フレーム。連鎖に専用の長さ制限を設けたわけではなく、入力・メモリ予算に達した場合は明示的に失敗する。途中で誤ってeventを閉じて容量を節約しない。

## ファイル入力

PCM API本体はファイルを所有しない。実験用`PinnedWavSource`がFDを保持し、WavStreamReaderの`/dev/fd`/pread経路を利用する。Phase54と同じdevice/inode/generation、size、mtime/ctime/birthtimeと、選択パスの再openによる同一性を前後確認する。2つのFDで読取位置を共有しない。各readは最大131,072フレームへ制限する。

ファイル置換、内容・権限変更、読取失敗はsessionへ失敗通知する。完了前にファイルの所有者が内容を変更しない契約は継続する。完成解析cacheへの登録機能はない。製品の初回全内容SHA-256を不要にする設計ではなく、その待ち時間はPhase54/55の別コストとして残る。

## 完全一致の証拠と制限

既存一回解析に新しい共通primitiveを入れていないため、参照の浮動小数点計算順は完全に保持した。新規classifier/mapの算術は参照と対応させた独立コードで、将来の保守で不一致を生まないよう固定参照と照合を継続する。既存ソースと過去結果はGit blob監査でも検査する。

実装前の7速度参照バイナリ`build/phase56_frozen/reference`を保持し、161速度拡張前に未変更の既存ライブラリへリンクした`build/phase56_frozen/reference_percent`を別に固定した。v2直列化には速度の整数表と版識別子を追加した。共通7列の抽出と全解析フィールドは旧v1の生バイトへ復元して一致確認し、追加154列も未変更のPhase39で生成する。SHAと基準SHAを保存した。フィールドの生ビット、整数、flagをpaddingなしの順で直列化した参照結果に対し、中間の新規公開要素、保持した過去snapshot、最終全結果を比較する。最終の直列化SHAも比較する。不一致のfield/index/actual bits/reference bitsはstderrへ残す。

Debugも同じDebug設定の既存一回解析と比較する。ReleaseとDebug間のビット一致を要求した試験とは区別する。検証範囲・失敗履歴・性能・未実施項目は[Phase56 REPORT](../results/phase56/REPORT.md)に記載する。
