# merodoa向け再生エンジン引き継ぎ仕様（Phase 53）

## 1. 適用範囲と固定版

TimeStretchLabは、音程を保って再生速度を変更するC++の音声処理ライブラリです。アプリは別リポジトリ `https://github.com/taro252/merodoa` で開発し、`external/TimeStretchLab/` にGit submoduleとして配置します。この文書に対応する完成コミットは **`phase53-handoff` タグ** で識別します。アプリではタグ名だけでなく、解決した完全なコミットSHAをsubmoduleの参照として固定してください。

音質基準は凍結済みPhase 5.3 Experimental 3500です。Phase 12/28の25本の参照WAV、低速B、高速B、位相・重ね合わせ（OLA）・周波数分割フィルター（FIR）の状態継続を保持します。開発版の統合が可能ですが、一般公開向けの音切れ・高負荷保証は完了していません。

| 項目 | Candidate（暫定標準） | Baseline（比較・切戻し） |
| --- | --- | --- |
| 速度 | 0.40〜2.00、小数6桁 | 同左 |
| 共通DSP | Experimental 3500、Phase37高速B、Phase42 safe-density | 同左 |
| 時間写像 | Phase40 C + L1 + L2 | Phase40 C、L1/L2なし |
| FIFO / 先行 / 生成 | 16,384 / 16,384 / 2,048フレーム | 16,384 / 12,288 / 2,048フレーム |
| ワーカー優先度 | 継承 | 継承 |
| 変更中の操作 | 最新1件だけ保留（Latest-Wins） | 同左 |

1.00倍速も位相ボコーダーで合成します。入力をそのまま渡すunity bypassとの切替はありません。0.50未満では半解析ホップを用い、通常密度へ戻すタイミングは窓重み・未来の合成ホップ・処理済み境界で判断します。アプリからこの条件を緩めないでください。

**対応実績はmacOS arm64のみ。iOS/iPadOSは未検証で、出力アダプターも未実装です。** C++コアはAppleのUIフレームワークへ依存しませんが、FFTにはApple Accelerateを使用します。現在のCMake構成全体はmacOS専用です。

## 2. submoduleの取得・固定・更新

以下は **merodoa側で実行する手順** です。Phase 53ではmerodoa自体を変更していません。

```sh
# 初回追加（すでに登録済みならsubmodule updateを使う）
git submodule add https://github.com/taro252/TimeStretchLab.git external/TimeStretchLab
git submodule update --init --recursive

# 引き継ぎ版を固定。SHAを表示・保管する。
git -C external/TimeStretchLab fetch origin --tags
git -C external/TimeStretchLab checkout --detach phase53-handoff
git -C external/TimeStretchLab rev-parse HEAD
git add .gitmodules external/TimeStretchLab
git commit -m "Pin TimeStretchLab Phase 53 playback handoff"
```

クローン後の復元は `git submodule update --init --recursive` です。TimeStretchLabのmainが更新されても、merodoaの参照は自動更新されません。

更新時はアプリ側で必要な変更・テスト結果をレビューし、明示した新SHAへ `git -C external/TimeStretchLab checkout --detach <新SHA>` を行います。アプリのビルド・再生回帰を実行してから `git add external/TimeStretchLab` とアプリ側コミットを作成してください。`git submodule update --remote` による無審査の追従や、submodule内の独自DSP改造は運用しません。DSP修正はTimeStretchLab側で行い、検証済みSHAを更新します。

## 3. ビルドと依存関係

必要環境：macOS、AppleのC++20/Objective-C++開発ツール、CMake 3.21以上。回帰検証はPython 3も使用します。Release/arm64を基準とし、他CPUやOSのビット一致は保証しません。

| ターゲット | 依存・役割 |
| --- | --- |
| `timestretch_core` | WAV、DSP、Apple Accelerate |
| `phase24_variable` → `phase36_variable` → `phase39_variable` | 既存の逐次DSP・TimeMap・safe-density。公開ターゲットが依存を解決 |
| `playback_engine` | C++の再生制御。`phase39_variable`へリンク |
| `macos_playback_engine` | 上記 + AVFoundation、Foundation、CoreAudio。アプリはこれへリンク |

アプリ側CMakeの最小構成例：

```cmake
cmake_minimum_required(VERSION 3.21)
project(merodoa_bridge LANGUAGES CXX OBJCXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
add_subdirectory(external/TimeStretchLab EXCLUDE_FROM_ALL)
add_library(merodoa_audio_bridge STATIC AudioPlaybackBridge.mm)
target_link_libraries(merodoa_audio_bridge PRIVATE macos_playback_engine)
target_compile_options(merodoa_audio_bridge PRIVATE -fobjc-arc)
```

`AudioPlaybackBridge.mm` はmerodoa側で作成する薄いブリッジです。公開includeディレクトリとフレームワークはターゲット依存で伝搬します。研究用CLIの環境変数やマクロは不要です。`EXCLUDE_FROM_ALL` と対象ターゲット指定で研究用実行ファイルをアプリの通常ビルドから外します。アプリ専用ビルドでは `-DBUILD_TESTING=OFF` を指定できます（アプリ全体のテスト構成への影響も確認してください）。

ビルド成果物は各アプリのビルド領域へ置き、submodule内にコピー・コミットしません。SwiftアプリのXcodeプロジェクトとCMake生成ライブラリを結ぶビルド設定はmerodoa側の責務です。

TimeStretchLab単独の検証：

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j 3
ctest --test-dir build --output-on-failure
# 別実行：他のDSP試験と競合させない。
cmake -S . -B build -DTIMESTRETCH_ENABLE_REALTIME_TESTS=ON
ctest --test-dir build -L realtime --output-on-failure
cmake -S . -B build -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
```

## 4. 入力音声と所有権

入力はファイルパスで渡す **RIFF/WAVE、非圧縮、monoまたはstereo、44,100または48,000 Hz** です。受理する形式コードはPCM16（1）またはIEEE Float32（3）。24bit、WAVE_FORMAT_EXTENSIBLE、RF64、圧縮WAV、MP3/M4Aは現行読取りAPIの対象外です。

ファイル内のPCMはサンプルごとのL/Rを並べた配置で、PCM16はリトルエンディアン符号付き16bit、Float32はリトルエンディアンIEEE754です。stereoは2チャンネル、monoは1チャンネル。内部レンダーAPIのfloat32はチャンネルごとに分けた非インターリーブ配置です。NaN/Inf入力は拒否します。

RIFFのチャンク長は32bitです。出力の制限は `36 + frames × channels × 4 <= UINT32_MAX`（44バイトヘッダーを使う現行float WAVの場合）。WAV生成やアプリ側デコード前に長さを検証し、4GiB以上をRF64として黙って渡さないでください。速度低下で出力が長くなる点も考慮します。

merodoaのメディア層でAVFoundationによりMP3/M4A/WAVを読み、必要なら対応形式のFloat32 WAVへデコードする設計とします。これはアプリ側の将来実装です。DRM音源は取り込み対象外です。

アプリが入力ファイルを所有します。prepare開始からstop完了、さらに再起動用に保持する間は、削除・置換・内容変更をしないでください。TimeStretchLabが元音源を移動したり所有権を取得したりすることはありません。媒体識別、デコードキャッシュ、差替え防止、削除時期はアプリ側で管理します。

## 5. 公開API・戻り値・例外

ヘッダー：`platform/macos/MacPlaybackEngine.h`、C++単独の消費側を実装する場合は `playback/PlaybackEngine.h`。

| API | 戻り値・条件 |
| --- | --- |
| `prepare(path, Configuration, MacOptions)` | bool。解析・構築失敗はfalse。Playing/Paused/Draining中はlogic_error。不正速度・設定・ゲインはinvalid_argument |
| `play()` | bool。Readyから開始。Playingはtrueのまま。Pausedではfalse（resumeを使う）。Stopped/Endedからは先頭で再初期化。Drainingはfalse |
| `pause()` / `resume()` | bool。Playing→Paused / Paused→Playingのみ。FIFO・DSPを保持。他状態はfalse |
| `stop()` | void。callback静止後にワーカー停止。要求をCancelledにしStoppedへ。ユーザー停止をEOSにしない |
| `setSpeed(double)` | uint64の要求ID。有限・0.40〜2.00・小数6桁以外はinvalid_argument。有効値でも状態/安全区間によりRejectedになる |
| `getPlaybackState()` / `getStateSnapshot()` | 状態 / 一括スナップショット。ライフサイクルを変更しない |
| `getRequestedSpeed()` / `getAppliedTargetSpeed()` | ユーザーの最新意図 / ワーカーが計画を適用した目標。可聴速度と同義ではない |
| `getCurrentPlaybackPosition()` | 消費したraw出力位置、TimeMap逆変換の原曲位置、各秒数。デバイスに既に渡した音の遅延は別 |
| `getPendingSpeedChange()` / `getActiveSpeedChange()` | optional。保留1件 / 実行中。要求ID、session、generation、適用・完了座標 |
| `getPlaybackDiagnostics()` / `getNativeDiagnostics()` | 供給不足・ワーカー / 装置・callback・時刻・確保計測状態 |
| `callbackRecords()` | callback静止後だけ詳細記録を返す。再生/Draining/処理中はlogic_error。診断取得では停止しない |

boolのfalseではコア診断の `error` とネイティブ診断の `error` を両方確認します。公開APIで発生するstd::exceptionはブリッジ境界で捕捉し、Swiftへ文字列・エラーコードとして渡してください。割当失敗なども例外になり得ます。失敗を成功状態へ読み替えません。

ライフサイクル操作は1本のアプリ制御・作業キューに直列化します。prepare/play/stop/pauseには解析・先行蓄積・静止待ちがあるため、UIメインスレッドや音声callbackから呼びません。通常の状態照会にもロックやコピーがあるため、制御キューで取得し、値だけをUIへ渡します。

**音声callbackから使えるライブラリAPIは、C++コアの単一消費側 `renderAudio()` だけです。** macOSアダプターを使用するアプリはそれも直接呼ばず、アダプターのSourceNodeに任せます。状態・履歴・位置・診断・setSpeedなどの制御APIはcallbackから呼べません。

## 6. ライフサイクルと要求状態

- Empty → prepare → Ready → play → Playing。
- Playing → pause → Paused → resume → Playing。PCMの重複・欠落を起こさず、未再生FIFO・位相・OLA・FIRを保持。
- raw EOS → Draining → Ended。HALの末尾PCM目標時刻と5ms余裕を待つのはライフサイクル管理側。診断取得はこれを短縮しません。
- stop → Stopped / User。stop後のplayは先頭から、最新要求速度で再初期化。停止位置からのresumeではありません。
- 装置/レート変更 → callback静止 → AVAudioEngine停止 → ワーカー停止 → Stopped / RouteChanged。自動再開なし。ユーザーのplayで新形式を取得して先頭から再生。
- ワーカーエラー → Failed。EOS成功ではありません。診断を保存し、明示stop/prepareで新セッションを作ります。

同じ入力と設定でも再初期化ごとにsession IDが変わります。速度操作の要求IDとワーカーgenerationは別の識別子で、前セッションの完了を新セッションへ混入させません。

要求はPending → Submitted → Applied → Completed。Completedはraw消費側への完了座標到達と安全密度処理の成立を表し、耳への実測提示ではありません。変更中の最新保留だけを置換し、古い保留はReplacedとして記録します。Duplicate、Rejected、Cancelledも区別します。Rejectedは終端結果で後続を妨げません。停止/EOSで未完要求をCancelledにし、永久保留を残しません。Ready/Stopped中のsetSpeedはConfiguredとなり、次回開始速度を設定します。

シークAPIは未対応です。Phase18/19の固定0.50 PCMキャッシュを任意速度履歴の途中復元へ使いません。Candidate/Baseline変更はstop後のprepareだけで行います。

## 7. Swift/SwiftUI側ブリッジの契約（実装はmerodoa側）

Objective-CヘッダーにはC++型を露出させず、Objective-C++ `.mm` 内で `std::unique_ptr<MacPlaybackEngine>` を所有する薄いクラスを作ります。prepare/play/pause/resume/stop/setSpeed、状態・位置・診断の取得を転送します。

Swiftへ公開する値は再生状態、停止理由、session、要求ID、要求速度、実行中目標、保留/実行中/完了/拒否、原曲秒数・出力秒数、アンダーラン件数、エラーです。optionalはnull許容値へ、例外はNSError等へ変換します。要求速度と適用中速度を同一UI値として上書きしません。

専用直列DispatchQueueで制御APIとスナップショット取得を行い、SwiftUI更新だけをMainActorへ送ります。C++オブジェクトと入力WAVの所有者はアプリの再生サービスです。破棄時もそのキューでstopを完了してからエンジンを解放します。callbackが参照するFIFO/RenderStateをSwift側から解放しません。

Swift側から音声callback、解析カーソル、TimeMap、OLA/FIR状態に直接アクセスしません。ブリッジやSwiftUI本体の実装はPhase 53の対象外です。

## 8. 最小利用例

ビルド可能な例は [`examples/mac_playback_handoff.cpp`](../examples/mac_playback_handoff.cpp) です。Candidateでprepare/play、setSpeed、pause/resume、StateSnapshot、stop、Baseline切戻しを実際の公開ヘッダーで確認します。

```cpp
#include "platform/macos/MacPlaybackEngine.h"
#include <chrono>
#include <iostream>
#include <thread>
int main(int argc,char** argv) {
    if(argc!=2){std::cerr<<"Usage: playback_handoff_example input.wav\n";return 1;}
    using namespace ts::playback;
    try {
        MacPlaybackEngine player;
        MacOptions output;output.playbackGain=0.5f;
        if(!player.prepare(argv[1],Configuration::candidate(0.40),output)||!player.play())return 2;
        auto request=player.setSpeed(2.00); // Request ID, not an immediate audible change.
        std::this_thread::sleep_for(std::chrono::seconds(1));
        if(player.getPlaybackState()==PlaybackState::Playing){
            if(!player.pause()||!player.resume())return 2;
        }
        auto view=player.getStateSnapshot();
        std::cout<<"session="<<view.session<<" request="<<request<<" requested="<<view.requestedSpeed<<" target="<<view.appliedTargetSpeed<<'\n';
        player.stop();
        if(!player.prepare(argv[1],Configuration::baseline(0.50),output)||!player.play())return 2;
        while(player.getPlaybackState()==PlaybackState::Playing||player.getPlaybackState()==PlaybackState::Draining)
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        const auto d=player.getPlaybackDiagnostics();
        const auto state=player.getPlaybackState();player.stop();
        return state==PlaybackState::Ended&&d.missingFrames==0&&d.rejectedWrites==0&&d.error.empty()?0:2;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
```

```sh
cmake --build build --target playback_handoff_example -j 3
./build/playback_handoff_example input.wav
```

この実行は音を出します。制御キューの代わりにCLIのメインスレッドを使用しています。アプリでは前節の直列キューに置き換えてください。終了コード0はこの例のEOS/供給条件で、詳細な計測・参照PCM保証を代替しません。

## 9. 品質判定と既知の制限

不足時はゼロ埋めし、診断OFFでもフレーム数・件数・時刻を保持します。Endedと音声PASSは別です。検証CLIの捕捉プロセス終了コード0は独立PCM照合の完了を意味しません。summaryのPCM/CSV/セッション判定は照合前INDETERMINATEで、`scripts/phase52_validate.py` / `phase53_validate.py` の共通判定後に確定します。詳細計測とPCM検証は検証CLIで行い、音声品質、計測品質、CSV完全性、参照PCM一致を独立判定します。stop/restartを含む全セッションが有効でなければ全体PASSにしません。SHAの対象は **FIFO公開済みのraw float32 PCM接頭部** で、生成済み・消費済み・SourceNodeへ渡したフレーム数を別記録します。`generatedFrames` はDSPが出力ブロックとして準備したPCM（未公開ブロックを含む）、従来名 `producedFrames` はFIFO公開済みPCMです。`device_raw_frames` はSourceNodeへ渡したrawフレームを入力サンプルレートで数え、SRC後の物理装置フレーム数ではありません。`presentedFrames` はゼロ埋めも含む要求時間軸で、消費座標とは別です。

主な未解決事項：

- 約1.4〜1.6秒などの速度反映遅延。過渡音保護、公開済みPCM、密度変更の安全条件が関係します。
- Busy中の最新要求は安全完了まで待ちます。Latest-Winsは即時切替ではありません。
- 長いOS停止・高CPU負荷でFIFO不足が起き得ます。高負荷下の製品品質保証は未完了。
- 0.40倍速には多少の水っぽさが残ります。0.25倍速は初回リリース対象外。
- 実機でhost/sample時刻不連続が観測されています。計測FAILを無条件にPASSへ変更しません。
- 物理装置変更・幅広い装置/負荷の反復、iOS実機は未検証。macOS実績をiOS保証に流用しません。
- シーク、DRM取り込み、MP3/M4Aデコード、Swiftブリッジは現行統合APIの対象外。

rawにはピーク1.0超えがあり得ます。再生段の独立ゲイン（既定0.5）でヘッドルームを管理し、Goldenやrawキャッシュを正規化しません。C++ callback確保計数0も、Objective-Cランタイム/malloc全体の証明とは区別します。

iOS対応時はmacOS固有のCoreAudio装置プロパティ、route監視、HAL提示時刻モデル、出力形式取得を新アダプターへ置き換え、AVAudioSessionの中断/route管理を設計します。DSP/APIの制御と所有権の契約は再利用し、音声callbackの禁止操作を維持します。

## 10. 将来機能の責務

ピッチシフトは−12〜＋12半音、1半音単位、テンポと独立操作、セント単位UI不要というアプリ側の将来要件です。現行TimeStretchLabには実装しません。

Stem分離の候補は `ssmall256/demucs-mlx-swift`、Vocals/Drums/Bass/Other、キャッシュ済みStem再生と各音量/Mute/Soloです。モデルの採用・デコード・キャッシュ・ミキサー・各Stem同期はアプリ側で別検証し、現行の単一再生サービスが既に対応すると仮定しません。

TimeStretchLabはタイムストレッチDSPの責務を維持します。Phase 53でピッチ・分離・Stemミキサー・デコード・iOS出力を追加していません。最終検証結果と保留項目は [`results/phase53/REPORT.md`](../results/phase53/REPORT.md) を参照してください。
