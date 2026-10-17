# Phase 60 Merodoa開発版への引き継ぎ

Merodoa本体・submodule・設定は変更していない。現行承認SHA `039592e59cc1a525b495e38d3cedeb6c050792b1` は旧経路として保持する。Phase60のコミット/Pushは別途の明示依頼で行うため、今回のビルド元HEADだけをPhase60完成SHAとして採用しない。レビュー後の完成コミットをsubmoduleへ固定し、実行体/ソースmanifestと照合する。

## リンク

macOS arm64、C++20、Objective-C++ ARC、CMake 3.21以上。`macos_progressive_playback_engine` へ明示的にリンクし、`platform/macos/ProgressiveMacPlaybackEngine.h` を `.mm` でincludeする。旧 `macos_playback_engine` は従来どおり。能力/速度の値型は `playback/ProgressiveContract.h`。

```cmake
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory(external/TimeStretchLab EXCLUDE_FROM_ALL)
target_link_libraries(merodoa_audio_bridge PRIVATE
    macos_playback_engine macos_progressive_playback_engine)
target_compile_options(merodoa_audio_bridge PRIVATE -fobjc-arc)
```

CMakeの推移依存を利用する。現在Merodoaの `libtool -static` による単一archive方式を継続する場合は、旧リストに `macos_progressive_playback_engine`、`phase58_realtime`、`phase57_synthesis`、`phase59_transition`、`phase56_incremental` を追加し、共通ライブラリは1回ずつ含める。AVFoundation/Foundation/CoreAudio/AudioToolbox/Accelerateを最終リンクする。通常アプリへ検証CLIやglobal new計測フックをリンクしない。

Phase60へsubmoduleを更新したアプリのLegacyは、そのcheckoutの `macos_playback_engine` である。これはPhase54公開経路を維持するが、共通DSPにはPhase57〜59 Fixの既存変更が含まれ、承認039592eの実行体そのものではない。CLIの `legacy` は比較基準を厳密にするため承認039592eを別プロセスで実行し、`legacy-current` は同一checkoutの既存製品経路を実行する。アプリと同じ版差を比べる場合は後者も確認する。2版の同名DSPシンボルを同じアプリへ混在リンクしない。

実際にコンパイルする例は `examples/phase60_bridge.mm`、確認ターゲットは `phase60_bridge_example`。本体ライブラリは比較CLIへ依存しない。

## 操作の変換

EngineのLegacy/ExperimentalとPresetのCandidate/Baselineを別に保持する。Engine選択後に対応するC++所有者を1つだけ生成する。実験エンジンを既定にしない。旧/新切替はStop・破棄・入力権限保持の確認後、新規prepareで行う。再生中のPCM継ぎ足しや暗黙の切戻しはない。

```cpp
ts::playback::ProgressiveOptions o;
o.preset = ts::playback::Preset::Candidate;
o.initialSpeed = 1.00;
auto player = std::make_unique<ts::playback::ProgressiveMacPlaybackEngine>();
player->prepare(protectedWavPath, o); // Accepted
// 同じ直列制御キューへ後続の短い照会を予約する。
// Readyを確認してUIへ値を通知し、明示Playで player->play()。
auto state = player->getStateSnapshot();
auto receipt = player->setSpeed(0.41, state.session, state.inputGeneration);
// request IDと全状態を保存。Appliedを可聴完了と表示しない。
player->stop(); // 準備/出力/worker静止を待つ
player.reset(); // この後で入力lease/権限を解放
```

Swiftの `PlaybackService.prepare` を完了扱いにするのはReadyを受けた後である。C++のprepareがtrueを返した時点ではAcceptedにすぎない。直列DispatchQueueへ `asyncAfter` 等で照会を再予約し、準備operation revision/選択通番とsnapshot.preparationを照合する。待機ループで制御キューを占有するとStopを実行できないため、Ready待ち中もキューへ制御を戻す。SwiftUI/MainActorでは待機・C++照会をしない。FailedのerrorをNSErrorへ変換する。

現行SwiftのPlaybackStateにはAcceptedがないため、画面状態はpreparingへ対応付け、準備段階Accepted/Preparingを別属性で保持する。残りは既存のlower-camel名へ明示変換する。例のNSDictionaryは生のC++値を示す教材で、現行ブリッジのCodable JSONへそのまま混ぜる形式ではない。Objective-C++境界では既存guardErrorと同様にC++例外とNSExceptionの両方をNSErrorへ変換する。

Pending/Submitted/Applied/Completed/Replaced/Duplicate/Rejected/Cancelledは `phase59::SpeedOperation` に対応する。ID、session、inputGeneration、generationをそれぞれ値へコピーする。適用/完了座標は `change.plan.appliedOutputSample/completionOutputSample`。低水準Busy/LimitReachedを受付成功と表示しない。期待世代を指定して古いUI操作を拒否する。

位置はsource rateのraw出力座標と、通常workerの対応位置標本を使用する。入力位置標本の `sampledOutputFrame` は現在の `outputFrame` と同時刻とは限らない。未取得の入力位置を速度×時間で捏造しない。装置の48kHz、Sourceの44.1kHz、装置提示遅延は別の欄にする。

既存の非optional sourceFrameへ未取得を0として渡さず、実験用readingで位置の有効性と対応するsampledOutputFrameを追加するか、UIで最後の有効標本だけを表示する。prepare通番、native session/input generation、メディア層の選択revisionは異なる値として扱う。

## 入力とSandbox

対応WAVへのデコードはMerodoa媒体層の責務。Phase60 APIはM4A/MP3デコーダーを持たない。今回の指定M4Aは試験前にmacOS afconvertで変換した。Merodoaの当時のデコード済みWAVとの同一SHAは未確認である。

security-scoped URL/Bookmark、EngineWAVInputのFD、読取ロック、管理コピーleaseは準備受付からStop・最終破棄まで、さらにStop→Play用に保持する間は継続する。非公開複製を作っても原本の同一性監視は続く。原本を削除・差替えするとFailedになり得る。コピーがあるから権限を先に解放してよいとはしない。

通常macOSホストでのmlock/一時FD成功と、Merodoaの署名済みApp Sandboxでの成功は別である。後続のアプリ試験では、Bookmark失効、準備取消中の権限寿命、mlock拒否、テンポラリ容量、複数入力の予算を検証する。常駐失敗は開始前Failed。旧経路へ戻す場合も失敗診断を保存し、停止・新規prepareで戻す。

## 未対応・残る条件

シーク、部分再開、解析cacheの共用、入力複製の省略、iOS、長時間の監査無制限化、物理loopback、一般公開向け音切れ保証は未対応/未成立。512適用計画・4096操作上限をUIへ伝え、LimitReached後に自動再送しない。実験統合の成功とGate 2/一般公開の判定を別に維持する。

`results/phase60/REPORT.md` と `VERDICT.json`、A/Bの入力・装置・実行体SHAを確認してから開発版で選択可能にする。製品既定の変更はこの引き継ぎの対象外である。
