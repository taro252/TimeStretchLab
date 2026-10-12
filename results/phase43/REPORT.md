# Phase 43 — 実機再生と計測基盤の検証

## 現時点の判定

Phase 42 safe-density を独立した `phase43_play` に接続した。正式な Phase 30/36 プレイヤー、凍結済み Experimental 3500、Phase 12/28 Golden、Phase 18/19 のキャッシュとシークは変更していない。正式プレイヤーへの統合と最終音質判定は保留する。

Phase 43 中に計測基盤の欠陥が3点見つかったため、その修正と実測を優先した。過去の `phase39_sim` による長尺試験は、FIFOが空の間、消費を待つ。したがって、その `underrun=0` は実時間再生の根拠ではない。従来の `cpp_new_calls=0` も、計数機能なしの実行ファイルで記録された場合は**未計測**である。以前のワーカーブロック壁時計時間はFIFO待ち・書込みなどを除くDSP生成寄りの区間であり、ワーカー全体の停止時間と読み替えない。Phase 42 REPORTの長尺「FIFO不足0」はこの理由で取り消す。

## 計測修正

- `scripts/phase42_profile.py` は診断ONで `phase41_profile_sim` を選び、C++ `new` カウンターが有効にならなければ失敗とする。診断OFFは `phase39_sim` で、割当を「未計測」と記録する。対象はC++ `new/new[]`であり、すべての `malloc` やObjective-C確保を網羅しない。
- `Phase39PlaybackPipeline` はDSP生成区間、速度変更計画、履歴mutex待ち・保持、FIFO待ち・書込み、前回から次回のFIFO公開までのワーカー全周期を別々に記録する。各周期の壁時計とワーカースレッドCPU時間を対応付ける。FIFO待ち中に計画が走る場合があるため、区間内訳は重複し得る。単純合計は全周期と一致しない。
- 最初のFIFO公開には前回公開時刻がないため、公開間隔を `-1`（未測定）と記録する。2回目以降は前回公開時刻からの実測値である。
- `phase40_paced_sim` を使う長尺試験は `steady_clock` の絶対期限で64〜1,024フレームを消費し、不足時は待たずにゼロ埋めする。提示済み時刻と実PCM消費座標を別に保持する。Phase 43では3／5／10分入力をこの方法で再試験する。
- safe-densityガードには、DSPが実際に処理した各解像度の入力・出力フレーム履歴と、OLAリング内のHann²正規化重みを読取専用で渡す。予測重みと実重みの差が `1e-4` を超える候補を拒否する。ガード候補の前処理・窓重み検査・総時間を個別に記録する。

短尺MIXの3回切替（0.40→2.00→0.40→1.50）でカウンターOFFは `unmeasured`、ONは数値として区別できた。計測ON/OFFのraw WAV SHA-256は同じ `2270498ac2e9f0f8f96392f09984ed8a3aa171c985f5f4168c0e86f5183473c0`。表示した上位20ブロックのC++ `new` 合計は265回であり、**実測0回ではない**。初回ブロックの初期化246回を含み、全ワーカー期間の割当総数ではない。詳細は [`measurement/summary.csv`](measurement/summary.csv) とブロックCSVを参照。ガード3回はいずれも受理され、実OLA重みと予測重みの最大絶対差は `1.28e-7`、過去の一定ホップ仮定による履歴位置不一致はこの3条件で0だった。したがって、ここで検証した処理済み履歴について一致するが、すべての将来の窓重みを実測したわけではない。

修正した `scripts/phase42_profile.py` をMIX 3分の診断ON/OFF各1回で実行し、[`profiles/summary.csv`](profiles/summary.csv) にON=`measured`／OFF=`unmeasured`を明示した。ONの最大DSP生成壁時計／CPUは173.742／30.705 ms、全周期173.749／30.712 ms。OFFの最大DSP生成壁時計／CPUは97.369／30.403 ms、全周期97.373／30.407 ms。各実行は別時刻なので、差を計測機構の純粋なオーバーヘッドと断定しない。3回切替のガード総時間は0.290〜6.997 ms、窓重み検査は解像度ごとに記録した。候補は各1件で、安全位置なしのRejected時最悪値は未測定。

## 絶対時刻の長尺模擬コールバック

標準BCD（FIFO16,384、先行上限12,288、生成ブロック2,048）、MIXの3／5／10分入力、512フレーム要求、開始0.40→2.00倍速を1秒時点で要求した。`phase40_paced_sim` は絶対時刻で消費し、FIFO空時は待たずゼロ埋めする。これはmacOS実機試験とは別の模擬試験である。

| 入力 | 不足フレーム | 不足コールバック | 最長連続不足 | DSP生成最大壁時計 | 最大ワーカー全周期 | 最大全周期CPU |
|---|---:|---:|---:|---:|---:|---:|
| 3分 | 0 | 0 | 0 | 127 ms | 179 ms | 34 ms |
| 5分 | 0 | 0 | 0 | 182 ms | 182 ms | 29 ms |
| 10分 | **3,072** | **6** | **3,072フレーム／64 ms** | **352 ms** | **352 ms** | 38 ms |

3条件ともDSPのPCM出力長まで到達し書込拒否・コールバック期限超過は0だった。10分条件は6回の不足時にゼロを提示し、提示時間軸がraw PCMより3,072フレーム長くなった。生のPCM自体を巻き戻してはいない。最大352 msの壁時計と約38 msのスレッドCPUの差は長い非実行区間を示すが、OS上の実行待ち・I/O・ページフォルト・同期待機のどれかは未確定。全周期には通常のFIFO先行量制御の待機も含む。詳細は [`paced/summary.csv`](paced/summary.csv) と各ログに保存した。**この結果では実時間安定性に合格しない。**

## 独立Mac再生

`phase43_play` はPhase 39/42研究ワーカーを専用スレッドで動かし、AVAudioEngine側は事前確保したSPSC FIFOから読み、足りない場合にゼロを埋める。音声コールバック内でFFT、TimeMap計画、ファイルI/O、mutex、ログ、明示的なC++確保を実施しない。再生ゲインはraw DSPと分離する。

短尺MIXの0.40→2.00倍速、無音出力による実機スモーク試験はEOSまで終了し、提示365,440フレーム、期待365,440フレーム、FIFO不足0、書込拒否0、コールバック期限超過0、コールバック内C++割当0だった。最大コールバック時間0.0071 ms、最大DSP生成区間111.0 ms、適用座標の到達遅延1,610.5 msを測定した。これは1回の短尺試験であり、長尺や負荷時の実時間安全性を証明しない。

同じ10秒入力の無音実機試験で、2.00→0.40倍速は出力770,625フレームまで排出し、適用座標のコールバック到達564.98 ms、最大ワーカー全周期76.77 ms、最大コールバック0.0083 msだった。0.40→2.00→0.40の2回変更は出力781,300フレームまで排出し、各適用座標の到達遅延1,610.38／522.65 ms、最大ワーカー全周期108.01 ms、最大コールバック0.0072 msだった。両試験ともFIFO不足・書込拒否・期限超過・コールバック内C++割当は0。無音試験であり、クリックや音質の試聴確認ではない。

## System Trace

MIX 3分のSystem Traceを1本取得したが、旧CSVには絶対時刻がなく、対象ワーカーブロックとの直接照合はできない。その後、CSVへUnix時刻とスレッドIDを追加した。追加のTrace取得2回は、Instrumentsの一時ファイルによるディスク容量不足で保存に失敗し、失敗した一時ファイルは削除した。

新計測で短尺MIXのSystem Traceを取得し、同一ワーカースレッドIDとUnix時刻を使って [`traces/mix_short_join.csv`](traces/mix_short_join.csv) に照合した。最大記録ブロックのワーカー全周期は壁23.893 ms／CPU23.883 msで、この短尺例では長い壁時計停止は再現しなかった。System Traceの状態行が覆った時間は9.955 msで、残る13.937 msは分類できない。Trace行の被覆が不足するため、「Running」等の内訳で当該ブロック全体を説明したとは扱わない。10分実時間模擬試験で生じた352 ms停止との時刻照合もない。この短尺例だけでは長時間停止の原因は未特定である。

続いて同一実行で3分MIXを計測・記録した。最大ブロックのワーカー全周期は壁159.733 ms／スレッドCPU34.665 ms。[`traces/mix_3m_profiled_join.csv`](traces/mix_3m_profiled_join.csv) では、同じスレッドIDと時刻に重なるSystem Trace状態として **Preempted 114.925 ms**、Running 20.465 ms、未分類24.342 msを得た。同期ブロックやRunnable待機は、この記録された区間では0。したがって**この159.7 ms事例ではOSによる実行中断が壁時計超過の主な要因と強く支持される**。ただし状態表は全区間を覆わず、System Trace自体の負荷もある。10分模擬試験の352 ms停止は別実行であり、その原因まで確定したとは扱わない。標準FIFOの10分不足に対する対策も未検証である。

## 未完了と統合条件

Phase 12/28 Golden 25本は `scripts/phase42_golden_audit.py` で保存済みSHA-256とPhase 36ストリーミングコピーの両方に一致した。`scripts/phase42_validate.py` は31/31条件で独立オフライン参照との全サンプル一致を確認し、MIX／Drumsの0.40→2.00ではPhase 41異音解消WAVのSHA-256も維持した。検証で再生成された追跡対象のPhase 42 CSVはHEADへ戻した。`ctest --test-dir build --output-on-failure -j4` は49/49件成功した（壁時計331.40秒）。Drums・Vocal・Guitar・Bassを含む全素材の実機切替、実機3／5／10分EOS、10分FIFO不足発生時のSystem Trace照合、ユーザー試聴は未完了。加えて、10分模擬試験で発生したFIFO不足の原因と対策が必要である。これらが揃うまでPhase 43を正式再生経路へ統合しない。

## 再現・試聴手順

```sh
cmake --build build -j4
ctest --test-dir build --output-on-failure -j4
python3 scripts/phase43_measurement_check.py
python3 scripts/phase43_paced_long.py  # 3/5/10分を絶対時刻で再生、数分かかる
PHASE_PROFILE_OUT=results/phase43/profiles PHASE_PROFILE_QUICK=1 python3 scripts/phase42_profile.py

# 以下は音が出る。音量を確認してから実行する。
build/phase43_play results/phase31/input/mix.wav 0.4 results/phase43/smoke_schedule.csv
build/phase43_play results/phase31/input/mix.wav 2.0 results/phase43/reverse_schedule.csv
build/phase43_play results/phase31/input/mix.wav 0.4 results/phase43/multi_schedule.csv
```

試聴では以前のMIX約3秒付近の異音、Drumsアタックと余韻、Vocal子音、Guitarのピッキング、Bassの持続音を確認する。raw DSP比較は `phase42_validate.py` のWAVを用い、AVAudioEngineの再生ゲインと混同しない。Mac実機でのMIX／Drums双方向と複数回切替については今回**無音設定のみ**であり、ユーザー試聴はまだ行っていない。
