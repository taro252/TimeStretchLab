# Phase 54 再生開始・解析再利用・シークAPI

## 1. 適用範囲

`playback_engine`（C++制御）と `macos_playback_engine`（AVAudioEngine出力）に追加するAPI。入力はmono/stereo、44.1/48kHz、PCM16/float32 WAV。Candidate/Baselineと0.40〜2.00倍速、小数6桁を維持する。音程、L1/L2、高速B、safe-density、FIFO設定は従来と同じ。

全曲の伸縮済みPCMを保存するキャッシュは使用しない。標準はリアルタイム合成、事前確保FIFO、不変な入力解析のメモリキャッシュ。Phase18/19のディスクPCMキャッシュは既存研究用経路として残るが、このAPIへ接続しない。

## 2. 最小利用例

すべての制御呼出しはアプリの作業キューで行う。音声コールバックから呼ぶのはC++コアの `renderAudio()` のみ。

```cpp
#include "platform/macos/MacPlaybackEngine.h"
using namespace ts::playback;

auto cache = std::make_shared<PlaybackAnalysisCache>(32 * 1024 * 1024, 64);
MacPlaybackEngine engine;
auto config = Configuration::candidate(0.50);
config.analysisCache = cache;
MacOptions output;
output.playbackGain = 0.5f;
output.seekFadeFrames = 64; // 0 / 64 / 128 / 256。DSP rawには適用しない。

if (!engine.prepare(inputWav, config, output)) {
    // core/native diagnosticsのエラーをUIへ渡す。
    return;
}
engine.play();
const auto id = engine.seekToInputSeconds(12.0);
// この戻り値は受付ID。移動完了や音声提示を意味しない。
auto seek = engine.getSeekSnapshot();
if (seek.id == id && seek.status == SeekStatus::Completed) {
    auto position = engine.getCurrentPlaybackPosition();
    // position.inputSecondsは原曲位置。出力装置で可聴となる位置とは異なる。
}
engine.pause();
engine.resume();
engine.stop();
engine.play(); // 同じ音源を先頭から。解析を再利用し、可変DSP状態は再作成。
```

`PlaybackEngine`にも同じseek/getterがあり、macOSに依存しない制御を再利用できる。CMakeは従来どおり `macos_playback_engine` へリンクする。公開設定とRenderResultは従来の集約初期化の先頭項目を維持し、追加項目は末尾に置く。ヘッダーとライブラリを同じ版で再ビルドする。Swift/Objective-C++ブリッジやMerodoaの変更はこのリポジトリには含まない。

## 3. 解析キャッシュ

| 設定・診断 | 意味 |
| --- | --- |
| `Configuration::reuseAnalysis` | 既定true。falseは解析を毎回行う安全な比較経路 |
| `Configuration::analysisCache` | 共有するキャッシュ。nullはプロセス共通の32MiB・64件 |
| `PlaybackAnalysisCache(bytes, entries)` | 記憶容量とエントリ数上限。0では保持しない |
| `setCapacity(bytes)` | 制御側から記憶容量を変更。使用中のデータは保持 |
| `diagnostics()` | 解析回数、hit、同時解析の共有、ハッシュ読取量、保持容量・件数・削除数 |
| `getStartupDiagnostics()` | 直近セッションのprepare、識別、解析、TimeMap、ワーカー初期化、先行蓄積のwall/スレッドCPU |

共有するのはPhase13の入力領域イベント・アンカー・検出フレーム。速度ごとのTimeMap、位相、OLA信号/重み、FIR、FIFO、要求generationは共有しない。Stop/EOS後、初期速度変更、別曲から戻った場合にも不変解析を再利用する。

初回は全ファイルSHA-256を計算し、解析前後のファイル識別情報を照合する。APFS上では開いた通常ファイルのdevice/inode/generation、サイズ、mtime/ctime/birthtime、WAV形式、解析仕様を索引とする。再利用時は全ファイルを再ハッシュしない。ファイルサイズ/mtimeを保った書換えでもctime変更で失効する。置換・シンボリックリンクの変更は開いた対象の識別で検査する。

APFS以外は軽量な同一性確認を採用せず再解析する。キャッシュを無効化する比較も可能。パスだけでは判定しない。特権によるファイルシステム情報の偽装、カーネル/ストレージ自体の破損は保証対象ではない。

入力の開いた記述子を保持し、WAV読取りは `/dev/fd` 用の `pread` で行う。検証と実際の合成が別のファイルへ切り替わる競合を避ける。再生中の元ファイル書換えはワーカーで検出して失敗にする。prepare後の選択は検証済みの開いたファイルに結び付く。新しいファイルへ切り替えるにはStop→prepareを行う。

未使用データを古い順に削除する。使用中の解析は破棄しない。空きがない場合は新規データをキャッシュへ保持せず、そのセッションのleaseとして使う。容量を使用中データより小さく設定した瞬間は、解放まで上限を超えることがある。解析所有容量を `analysisBytes`、保持分を `cacheResidentBytes` として示し、DSP作業領域やアロケータを含むRSSとは区別する。エントリ数上限は開いたファイル記述子の過剰保持も防ぐ。

高度な事前解析で `acquire()` を使う場合は、呼出し毎に空の`StartupDiagnostics`を渡し、返された `AnalysisLease` 全体の寿命を保持する。通常のアプリ利用はConfigurationにキャッシュを渡すだけでよい。同じファイルの生成中の要求は同じ結果を待ち、解析の重複を抑える。

## 4. シーク仕様

```cpp
uint64_t seekToInputSeconds(double seconds);
uint64_t seekToInputFrame(uint64_t frame);
SeekSnapshot getSeekSnapshot() const;
std::vector<SeekSnapshot> seekHistory() const;
```

- **原曲座標**を指定する。秒→入力フレームは原曲サンプルレートで丸める。
- 出力位置は新しい初期速度のAdaptive TimeMapから求める。`seconds / speed` を位置計算に使わない。
- Ready/Playing/Pausedで受付。Stopped/Ended/Draining、範囲外はRejected。NaN/Inf/負の秒は例外。フレームは終端ちょうどを許可する。
- シーク後は新しい再生セッション。要求時点以降の最新有効速度を初期速度にする。速度が準備中に変われば新しい目標で再計画する。
- 古い速度履歴はコピーしない。未完了の旧速度操作はCancelled、新区間へ折り込まれた新しい設定はConfiguredとして記録する。
- 頭から位相・OLA・FIRを再構築し、出力を指定位置まで破棄する。先頭の部分ブロックは値を変えず詰め直し、Candidateの16,384先行蓄積を保つ。
- Playingでは準備中も旧区間を再生し、完成した新FIFOへ区間単位で切り替える。コールバックは区間状態を一度だけ読み、旧状態はコールバック静止後に破棄する。
- PausedではFIFOを消費せず移動し、Pausedを維持する。Readyでは新FIFOを準備し、Playを待つ。
- 新しい有効シークは古いPending/PreparingをReplacedにする。Stop/装置変更/破棄はCancelled。古い要求の完了で新しい状態を上書きしない。
- 不正な新要求を拒否しても、以前の有効要求は継続可能。最新拒否はsnapshot、以前の完了はhistoryに残る。`activeId/pendingId`も確認する。

`SeekSnapshot`はID、session、要求入力フレーム、採用出力フレーム、初期速度、状態、観測/準備完了時刻、再計画件数を持つ。Completedは新区間が再生可能になったことを示す。実際のコールバック到達や物理的な可聴時刻とは区別する。時刻はsteady_clockのナノ秒。新しいprepare/restartでは最新snapshotをID0へ初期化し、過去の終端履歴は保持する。

`seekHistory()`は最大128件。診断OFFでも不足件数を保持する。`lifetimeMissingFrames/lifetimeUnderrunCalls`はEngine生成からの累積で、シーク後に旧区間の不足を隠さない。

## 5. raw PCMと再生段

シーク後のrawは、同じ全入力・同じ初期速度・同じTimeMapで先頭から生成した参照の該当suffixと一致する。再生段の固定gainとフェードは比較に含めない。

`Diagnostics::outputStartFrame`は新区間の先頭出力位置。`producedFrames/consumedFrames/outputLength`は曲全体の出力座標で、区間の個数ではない。区間のFIFO公開個数は `producedFrames - outputStartFrame`。`rawPcmSha()`は `[outputStartFrame, producedFrames)` のFIFO公開float32 interleavedを対象とする。初期再生ではoutputStart=0なので従来の範囲と同じ。

`verifyRawPcm=true`は診断用。使用時は閉じた旧区間の `closedSegmentEvidence()` も最大16件取得できる。公開/消費範囲、初期速度、plans、raw SHA、不足・ワーカーエラーを保存する。使用していないReady区間の範囲は空で、空SHAになる。メタデータだけで、PCMキャッシュではない。

macOSの `seekFadeFrames` は0/64/128/256。暫定既定64。シークで新sessionの最初のサンプルへ線形フェードインを掛ける。強いアタックがちょうど先頭にあると弱まる可能性がある。比較WAVと試聴に基づいてアプリ側で選択する。raw/FIFOへ焼き込まない。

## 6. 制限と性能

解析再利用によって再解析コストを除くが、Coldは全曲解析と初回ハッシュが必要。シークのDSP再構築は指定位置までの長さに比例し、深い位置では待ち時間が残る。チェックポイント、途中だけの位相再構築、全曲PCMディスクキャッシュは追加していない。

終端ちょうどのシークでも現行フォールバックはワーカーが先頭からの処理を終了してEOSを確定するため、出力サンプルが0の新区間でEnded通知を待つ時間が残る。途中のStop/新しいシークでキャンセル可能。これは高速化の未達事項であり、即時EOSの保証とはしない。

旧曲が準備中に終端へ到達すれば、移動先が完成するまで無音待ちになることがある。音切れを隠した即時シークとは扱わない。新しい要求の連打は最後の要求を優先するが、準備を何度もやり直すため総時間が延びる可能性がある。高負荷でFIFO不足が出れば、その条件は不合格。一般公開向け保証ではない。

Draining中の制御は従来の安全条件を維持する。物理装置変更後は安全停止し、形式再取得を含むPlay/prepareを明示的に行う。自動再開、MP3/M4Aデコード、ピッチシフト、iOS/iPadOS、SwiftUI、Stem処理は含まない。

## 7. 計測値の読み方

`StageTiming`は壁時計時間と実行スレッドのCPU時間を分ける。`prepare`の中に識別・解析・pipeline生成が含まれ、`metadata`は識別処理にも含まれる。`prefill`は制御スレッドの待ち時間で、ワーカーのCPU時間ではない。TimeMapはワーカー初期化にも含まれる。これらを足して総時間としない。

Play前のTimeMap/worker/prefillの0は未開始を示す。AVAudioEngineの構築・起動はMacDiagnosticsで取得する。`firstPcmMachNs`は最初の有効PCMを含むSourceNodeコールバックの開始時刻で、物理的に音が出た時刻ではない。mach/steadyの橋渡し情報とPlay開始時刻から受付→コールバック待ち時間を計算する。音響ループバックは実施していない。

`closedSegmentEvidence()`は検証用で、実機試験は停止/コールバック静止後に取得する。raw SHA照合、音声不足、コールバック期限、計測CSVの完全性は独立して評価し、途中のセッションのFAILを最終区間だけで隠さない。
