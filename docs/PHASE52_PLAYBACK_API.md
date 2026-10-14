# 開発版再生エンジン API（Phase 52）

## 位置付け

`playback_engine` は C++ の再生・要求制御ライブラリ、`macos_playback_engine` は AVAudioEngine を所有する macOS アダプターです。既存の Phase 30/36 プレイヤーはそのまま保持しています。新規 GUI はありません。Candidate は開発版の暫定標準で、公開製品の品質保証ではありません。

| 設定 | Candidate | Baseline |
|---|---|---|
| 速度キー | 0.40〜2.00、小数6桁 | 同左 |
| 合成コア | Experimental 3500、Phase 37高速B、Phase42 safe-density | 同左 |
| TimeMap | Phase40 C + L1 + L2 | Phase40 C |
| FIFO / 先行上限 / 生成 | 16,384 / 16,384 / 2,048 | 16,384 / 12,288 / 2,048 |
| ワーカーQoS | 継承 | 継承 |
| Busy中の要求 | 最新1件を保持 | 同左 |

設定は `Configuration` で渡します。`dspOptions()` でTimeMap方式、L1、safe-density、FIFO、先行量、生成量、継承QoSの解決済み設定を確認できます。アプリ経路は研究CLIの環境変数を参照しません。`verificationHooks` は障害注入用で通常は初期値のまま使用します。設定・入力の変更は停止後の `prepare` で行います。再生中にCandidate/Baselineを交換しません。

## 利用例

```cpp
#include "platform/macos/MacPlaybackEngine.h"
using namespace ts::playback;
MacPlaybackEngine player;  // 所有者はアプリの再生サービス

// ファイル解析・先行蓄積を伴うため、UIやaudio callbackではなく作業キューで実行。
auto config = Configuration::candidate(0.40);
MacOptions output;
output.playbackGain = 0.5f;  // AVAudioEngineのmixerで適用。raw DSPには含めない。
if (!player.prepare(filePath, config, output) || !player.play()) {
    auto error = player.getPlaybackDiagnostics().error;
}

player.setSpeed(2.00);
player.setSpeed(0.75);       // Busy中なら保留。さらに操作すれば保留1件を置換。
player.pause();             // 未再生FIFO・位相・OLA・FIRを保持
player.resume();            // 同じPCM消費位置から継続
player.stop();              // callback静止後にワーカー停止
player.prepare(filePath, Configuration::baseline(0.40), output); // 開発版の切戻し
player.play();
```

入力はprepareからstopまで内容・パスを固定したWAVを使用します。外部ファイルの差替え防止やMP3等のデコードはアプリのメディア管理層へ分離します。

アプリ側のライフサイクル呼出しは1本の制御・作業キューにまとめてください。`setSpeed` と状態照会は制御スレッドで利用できます。制御APIはロック・確保・ファイル解析・待機を行うためaudio callbackから呼べません。C++単独で出力先を実装する場合、唯一のレンダーAPI `PlaybackEngine::renderAudio` を **1本の消費側** から呼びます。任意の読み取りフレーム数、mono/stereoの非インターリーブfloat32に対応します。

## 状態と速度要求

- `prepare` → Ready → `play` → Playing → `pause` → Paused → `resume` → Playing。
- FIFO排出完了 → macOS側Draining → Ended（raw EOS到達。音声品質の合否は別判定）。`stop` → Stopped。ワーカーエラー → Failed。
- `getStateSnapshot()`：状態・要求速度・実行中目標・active/pending/直近結果を一括取得。セッションIDと不足フレーム数も公開します。
- `getRequestedSpeed()`：最新のユーザー意図。拒否された値も履歴に残ります。
- `getAppliedTargetSpeed()`：ワーカーがTimeMapへ計画を適用した目標。可聴速度の即時変更を意味しません。
- `getActiveSpeedChange()`：送信済みまたは適用済みの変更。`applyOutput` / `completeOutput` を公開します。
- `getPendingSpeedChange()`：まだ送信していない最新1件。
- `operationHistory()`：Completed / Replaced / Duplicate / Rejected / Cancelled / Configured を含む履歴。`session` と要求 `id`、ワーカー `generation` を区別します。最大4,096記録、それ以降は最古記録を捨て、件数を診断へ表示します。

Busy中の操作は実行中のTimeMapを改変せず、保留要求だけを置換します。置換された要求はReplaced。遷移完了と安全密度の処理完了を待って次を送ります。拒否は終端結果として記録し、後続要求は実際の現在TimeMapから計画します。停止・EOS・エラーで未完要求をCancelledにし、永久保留を防ぎます。

UIは「要求」「実行中目標」「変更中」「保留中」「完了」「拒否」を別表示できます。`Applied` は計画適用、`Completed` は完了座標がPCM消費側へ到達し密度条件も成立した状態です。音響ループバックを行っていないため、実際の耳への提示時刻ではありません。

## 位置・pause・終了

`getCurrentPlaybackPosition()` は **消費済みraw PCMの出力位置** とTimeMapの逆変換による入力位置を返します。出力秒数と原曲秒数は別値です。再生装置のバッファやSRCによる提示遅延は別です。

pauseとEOSではHAL目標時刻に基づき読取り済みPCMの末尾を待ちます（5msの制御側余裕。音響ループバックによる証明ではありません）。

pauseではPCM消費を止め、FIFOとワーカーを保持します。ワーカーは先行上限まで生成し、その後待機します。resumeでは未再生PCMから継続し、重複・欠落させません。

stop後のplay、EOS後のplayは **先頭からの再初期化** です。最終要求速度は引き継ぎます。停止位置からの再開はシークとして未対応です。Draining中のplay/prepareは拒否し、末尾排出の完了または明示stopを待ちます。

装置またはサンプルレートの変更は通知後に形式を再確認し、callbackを静止→AVAudioEngine停止→ワーカー停止とします。停止理由はRouteChangedでEOSとは区別します。入力位置・要求速度の照会値は保持し、ユーザーの `play()` で装置形式を再取得して先頭から再生します。自動再開しません。物理装置変更が通知されるまでの時間はOS依存です。

## callbackとメモリ

callbackはFIFO読取り・不足分のゼロ埋めと、事前確保領域への軽量計測のみ。DSP・TimeMap・ファイルI/O・ログ・動的確保・ブロッキングmutexは禁止です。ゲインは別のAVAudioEngine mixerに置きます。

Diagnostic OFFでも不足フレーム数、発生件数、最大連続不足、最初と最後の単調時刻を保持します。事前確保2,048件の不足リングが一周したら上書き件数を公開します。詳細native callback記録は任意（262,144件で上限、超過はdropとして測定FAIL）。C++ `new` カウンターは検証CLIの計測であり、Objective-Cランタイムやmalloc全体の証明ではありません。

アダプターはcallbackが静止するまでcoreを破棄せず、SourceNodeが保持する事前準備済みRenderStateの寿命を保ちます。位相・OLA・FIR・TimeMapはDSPワーカーのみが所有します。位置逆変換に必要な読み取り専用TimeMapコピーは制御側へ公開し、callbackでは参照しません。

## シークとの接続仕様

Phase18/19の固定0.50 PCMキャッシュ・高速シークは変更しません。今回のエンジンにはseek APIがありません。将来は停止・callback静止・入力/速度/キャッシュキー検証・新規セッション構築を明示的な操作として統合します。可変速度履歴の途中から位相/OLA/FIRを復元したり、0.50固定キャッシュを任意速度音声として読みません。

## ビルド・試験

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j 3
ctest --test-dir build --output-on-failure
# 上記は決定論的回帰。OSの期限試験は別に登録する。
cmake -S . -B build -DTIMESTRETCH_ENABLE_REALTIME_TESTS=ON
ctest --test-dir build -L realtime --output-on-failure
cmake -S . -B build -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
```

Phase44/45の旧テスト名と厳密な判定は維持します。登録分類のみ変更し、OS起床遅刻でINVALIDになる期限試験を通常のDSP回帰から分離しました。過去の68/69を成功へ読み替えません。

```sh
build/playback_demo results/phase31/input/mix.wav results/phase52/manual_001 candidate 0.40 --actions actions.csv
```

`actions.csv` は `seconds,action,value` ヘッダーに続けて `1,speed,2.00`、`3,pause,0`、`3.25,resume,0` 等を記入。時刻は再生開始後の壁時計時間で、pause中も進みます。`--silent` はmixerゲイン0、`--offline` は固定速度の非実時間WAV生成です。入力/設定の反映、再生装置、raw PCM照合、音声品質と測定品質はそれぞれ保存します。保存済みsummaryは上書きしません。

`python3 -B scripts/phase52_validate.py fixed|controls|long|audible|golden|audit` で独立検証できます。実機試験は他のDSP回帰と同時実行しないでください。速度変更の計画完了後も、先行PCMと過渡音保護により操作応答が遅れる場合があります。残る制限はREPORTを参照してください。

アプリ側CMakeでは `add_subdirectory(TimeStretchLab)` と `target_link_libraries(MyApp PRIVATE macos_playback_engine)` でリンクします。速度スライダーの値は小数6桁へ量子化して渡し、不正値の例外を処理してください。
