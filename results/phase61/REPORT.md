# Phase 61 Progressive Seek 検証記録

実装開始点は `main@fc28efd93`（FD保持方式への修正済み）。開始時の作業ツリーは空。実装・検証の完了時点ではコミット・Pushを行っていない。その後の利用者の依頼に基づき、変更と検証結果をコミットする。仕様は `docs/PHASE61_SEEK_SPEC.md`。Phase62、Merodoa本体、submodule、既存Golden、Phase60の承認結果を変更しない。

## 実装

- 原曲入力フレームと厳密な秒数受付、確定Adaptive TimeMapの出力座標を使用する。
- 契約版2の非同期要求・受付ID・8状態・理由・入力世代・render epoch・段階別時刻を公開する。旧bool APIはゲートfalseの互換動作を保つ。
- Phase58の保護入力/FD/常駐領域/最終Phase56解析を共有し、シークでは全SHA・一時複製・mlockを繰り返さない。
- Playingの旧FIFOを維持し、次のReadyとWorkgroup確認後に原子的参照交換する。参照中のcallbackが完全に終わってから旧区間を停止・破棄する。
- Latest-Wins、速度変更時の同ID再計画、Stop/入力変更/装置変更での取消、Paused維持を実装する。
- 正確な先頭再構築に加え、同入力・同速度のDSP保存点を最大2個保持する。全曲伸縮済みPCMはキャッシュしない。

## 先行試験と修正履歴

初期ビルドではatomic同士の代入2箇所を修正した（`build/phase61/initial_build_failed.log`）。中間位置のReady試験では先頭の部分ブロックと従来の2048単位の空き待ちが組み合わさり、15619/16384で止まった。自分が開始した試験を70秒後に停止し、部分PCMを有界な作業領域へ詰めて残りの空きにも公開するよう修正した。失敗ログは `build/phase61/quick/standard.log`、修正後のStandard/Workgroup双方の結果を同じフォルダーに保存した。

保存点追加前のRelease回帰22/22、Debug回帰22/22も通過したが、最終成績とは分けて保存する。300秒素材の270秒位置では独立参照とsuffix 2,880,256フレームが完全一致し、Readyまで12.1552秒、ピークRSS 88,948,736 bytesだった。初回の深いシークは遅いため、保存点方式を追加した。測定器はオフラインFIFO消費であり実機提示遅延ではない。`deep_head`の最初の起動失敗はコピー先の実行権限欠落で、試験開始前のPermissionError。実行権限を保って再実行した証拠も残す。

また、オフラインPCM比較後のコード点検で、部分PCMが満杯FIFOの空きを待つ間に昇格/降格要求を処理できない順序を修正した。Workgroup経路を選ぶだけの検査と、実際に昇格させる検査を区別し、後者を追加して再検証する。先行の非昇格PCM行列は証拠として保持する。

## 最終検証

最終判定は公開シーク **NO-GO**。契約版2の実験API、PCM正確性、今回の実機範囲は通過した。初回深部シークの約12秒と未検証の全実機条件を残し、`Capabilities.seek=false`を維持する。

## 条件と参照の独立性

- MacBookAir10,1 / Apple M1 / メモリ17,179,869,184 bytes。macOS26.6.2 (25G83)、Apple clang21、SDK27.0。C++実行体はarm64。制御用Pythonはx86_64で動作しているため、Pythonのmachine表示をC++実行体のarchitectureと取り違えない。
- 出力装置はMacBook Airのスピーカー（ID72）、48kHz、512フレーム。実機中は大量比較・コンパイルを並走させない。OSのキャッシュを消していない。
- 形式行列は1.5秒の境界fixture、PCM16/Float32 × mono/stereo ×44.1/48kHz。速度は0.40/0.50/0.75/1.00/1.25/1.50/2.00、Candidate/Baseline、位置0/中間+17/最終フレーム/終端。Standardと実昇格Workgroup各1回、合計896ケース/構成。
- 別の長尺検証は既存の300秒/48kHz/mono/Float32素材、Candidate/0.5倍、270秒・285秒位置。素材SHAは `13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0`。
- 独立参照はPhase57以前の `ec087019626d9ff0d9f157245729b74ddb6847d7:src/prototype/Phase36StreamingSpeedEngine.cpp` を復元し、現在のseek/DSP保存点コードを通さず全曲一括レンダーする。参照のソースSHAは `4ffec7c4db196f51e89bd4ebaf336020ae71d0969c31393a40752b4a37ed3899`。Releaseの実行体SHAは `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。DebugはDebugの独立参照を使う。
- 比較は許容誤差0で、全チャンネル・全suffixフレームのFloat32ビット列、長さ、SHA、TimeMap開始座標を確認する。callback観測はgain0.5より前のRAW。Phase61のために既存Golden、速度行列、品質条件を変更していない。

## 実機で完了した試験

`phase61_native_tests` の20ケースは、両presetのReady/Playing/Paused/64連打/完了後の再シーク/準備中速度変更/Stop/模擬route変更/入力消失/終端である。連打では161速度受付後に固定速度へ戻し、64要求のLatest-Winsと、不正な後続要求が有効要求を置換しないことを確認する。古い入力世代・session・render epochの速度操作を拒否し、Paused/Readyの絶対座標も検査する。入力消失をFailedとして検知するケースは期待した失敗であり、正常EOSとして扱わない。

|実機群|機能|供給・期限・寿命の検査|RAW完走suffix|RAW前半/途中|空終端|
|---|---:|---:|---:|---:|---:|
|48kHz stereo 最終|20/20|20/20|12/12|14/14|2/2|
|44.1kHz mono 最終|20/20|20/20|12/12|14/14|2/2|
|Sandbox Esprit 先行|20/20|20/20|12/12|14/14|2/2|
|Sandbox 利用者選択 最終|20/20|20/20|12/12|14/14|2/2|

4群ともFIFO不足/不足callback/拒否書込み、callback期限超過、worker期限超過、計測したcallback/workerのC++ new、host時刻の間隔異常、sample連続性異常、HAL窓超過は0。Workgroup参加/離脱/通常policy復元とエラー検査も通過した。各入力世代で全SHA・保護複製・mlockは各1回。完了後の再シークでは保存点使用を実際に確認した。

161速度は低レベル`createSeek`の受付と公開`setSpeed`の受付を検証した。公開シークは64連打と完了後の再シークで検証した。各群には、速度変更・連打中の旧区間の動的prefixが4件ある。これらは世代と順序を検査し、固定速度参照の比較対象には含めない。新区間の固定suffixは独立参照と完全一致した。既存Phase59の動的PCM回帰も別に実行した。

実機の受付から最初の新PCMまで（Playing系10完了/群）は次の値だった。Ready/PausedからのPlay/Resume待ちを混ぜない。

|群|最小ms|中央値ms|最大ms|全16完了の受付→Ready最大ms|受付→参照設置最大ms|
|---|---:|---:|---:|---:|---:|
|48kHz stereo 最終|86.820|276.639|297.585|487.081|487.082|
|44.1kHz mono 最終|44.694|143.038|148.579|320.978|320.983|
|Sandbox Esprit 先行|122.714|350.051|371.428|596.230|596.232|
|Sandbox 利用者選択 最終|118.966|329.788|660.314|652.265|652.399|

参照設置と最初のcallbackは異なる。推定提示時刻はHAL hostTimeによるソフトウェア目標で、物理スピーカーの音響測定ではない。全完了の個別時刻、Preparing開始、再計画数、理由は各群の `seeks.json` と `build/phase61/NATIVE_METRICS_FINAL.json` に保存した。

## メモリ・FD・TCC

|実機群|ピークRSS bytes|入場予約 bytes|callback最大ns|
|---|---:|---:|---:|
|48kHz stereo 最終|95,387,648|270,741,548|71,334|
|44.1kHz mono 最終|62,898,176|269,849,708|64,292|
|Sandbox Esprit 先行|157,155,328|270,555,308|63,916|
|Sandbox 利用者選択 最終|154,910,720|270,555,308|27,208|

入場予約はallocator/RSSの厳密な強制上限ではない。1つの外部所有者、最大2個の生きたrender区間、最大2個のDSP保存点、既存1GiB入場予算を維持する。保存点は8MiB/個の既存DSP見積りを準備予約内に含める。音声callbackは原子的な参照読取りとFIFO消費のみで、世代付きRAW観測と事前確保診断を使う。旧参照はcallbackの読取りが全て完了してから通常threadで破棄する。

C++ newの計測は検証実行体の明示hookであり、malloc/Objective-C/VM確保やOS page faultの全入口は測定していない。これらを0/PASSと表現しない。通常アプリにはglobal newの置換をリンクしない。細かいwork profile付きでは保存点を使わず、正確な先頭再構築へ戻る。

署名は `com.apple.security.app-sandbox=true` と `com.apple.security.files.user-selected.read-write=true`。AppKit起動後に選択シートを表示し、CUAで次を実際に選択した。

- 音源 `/Users/taro252/Music/Music/Media.localized/vividblaze/PERIDOT/08 Esprit.m4a`（10,801,242 bytes、SHA `a64123f1360dfe19070ed1a3b6819320c85532686fd51773d0a58cb0ae7178af`）。
- 出力先 `build/phase61/sandbox_io`。
- 主試験 `sandbox_io/run_36801`。入力/出力URLのsecurity scope開始は両方true、ホームはSandboxコンテナー、選択範囲外の既存 `SANDBOX_DENIED.txt` のopenはFD=-1/errno=1で拒否。
- 先頭176,400フレームを1回だけWAV化した。WAVのSHAは `15f145df7e0d034e3afd5f3bd7ca023c11e09a5b40ced3c7372c62378a5adddc`。この4秒WAVで20入力セッションを作り、各入力内のシークでは元デコード・全SHA・複製・mlockを繰り返さない。

最初のUI取得にはtimeoutがあり、独立した初回run_36210も20件完了していた。このrunの元選択経路/原本パスは観測できていないため、名前付きEsprit主試験に含めない。保持した別のWAV（SHA `2d0511b88f2991c3a43a7ab9851e3ec4a481b6001448dab6c5728d9b756866fa`）に対する独立RAW比較12suffix/14prefix/2終端は通過し、補足証拠として保持する。UI可視性を改善したシート方式で、指定音源の主試験を改めて完了した。


最終の入力座標照会を含む端末40ケースも再通過した。Sandbox最終run_44689は利用者側の選択操作で開始され、元ファイルパスは観測できていない。保存した4秒WAVのSHA `386117e6972829181ddf74abff28a923b9673b12a0e27ac61fa6debd19139989`を再現seedとする。security scopeは双方true、範囲外openはFD=-1/errno=1、20ケースの機能/供給/期限/寿命と12suffix/14prefix/2終端のRAW比較が全て通過した。両presetでPreparingを観測してから速度を変更し、同じ受付IDのreplans=1を確認した。初回Espritの20ケースとこの最終20ケースを区別して記録する。

Sandbox実再生は先頭4秒の抜粋であり、元のM4A全長、期限切れbookmark、File Provider、権限取消/TCC失効の全経路は未検証。通常ファイルの削除・同一byte列への置換・終端Readyの入力監視はCTestで検証した。入力leaseとスコープは最終停止・worker終了まで保持し、`/dev/fd`再openを使わない。

## 装置・既存回帰

実出力装置ID72の公称レートを48kHzから44.1kHzへ変更し、保留シークがCancelled、RouteChangedによる停止、route_changes=1を確認した。終了時に48kHzへ復元し、設定・復元APIともstatus=0だった。これは同じ装置の実構成変更の試験で、物理装置の抜差しや別装置への差替えは未検証。切替瞬間の無欠損再生をこの試験の成功条件にはしていない。

既存Phase60 Adapter/Lifecycleは既存 `results/phase31/input/mix.wav`（10秒）を使い、Release/Debugの4実行を全て通過した。追加Python回帰はPhase59Fix2Forensics6/6、SupplyAnalysis3/3、Phase60Result5/5。過去のPhase60全A/B実機行列を今回の新しい成功として読み替えない。

## 最終CTest・PCM・Goldenの個別成績

|CTest|Release 秒/結果|Debug 秒/結果|
|---|---:|---:|
|phase54_analysis_cache|0.115 PASS|0.701 PASS|
|phase54_seek_pcm|34.704 PASS|107.332 PASS|
|phase56_state_safety|0.054 PASS|0.197 PASS|
|phase56_fixed_preset_maps|0.035 PASS|0.073 PASS|
|phase56_incremental_exact|1.484 PASS|2.017 PASS|
|phase57_state_safety|0.216 PASS|0.756 PASS|
|phase57_pcm_exact|4.384 PASS|11.260 PASS|
|phase59_certified_planning|0.158 PASS|0.748 PASS|
|phase59_dynamic_pcm|17.326 PASS|48.957 PASS|
|phase61_contract|0.011 PASS|0.004 PASS|
|phase61_checkpoint|9.853 PASS|24.936 PASS|
|phase61_safety|0.912 PASS|1.902 PASS|
|phase61_pcm_suffix|9.985 PASS|28.930 PASS|
|phase60_contract|0.008 PASS|0.003 PASS|
|phase59_request_control|4.780 PASS|11.631 PASS|
|phase59_fix_frozen_vocoder|0.934 PASS|2.175 PASS|
|phase59_fix_frozen_stereo|2.234 PASS|5.099 PASS|
|phase58_state_safety|0.952 PASS|1.901 PASS|
|phase58_fifo_pcm|4.221 PASS|10.489 PASS|
|phase58_fix_diagnostics|0.645 PASS|1.484 PASS|
|phase58_fix_trace_analysis|0.194 PASS|0.184 PASS|
|phase58_fix_mailbox|0.395 PASS|0.503 PASS|
|phase58_fix_worker_lifecycle|0.401 PASS|0.395 PASS|

Release23/23（94.07秒）、Debug23/23（261.93秒）。実昇格後の独立RAW行列はRelease896/896、Debug896/896。各448ケースで保存点を使用し、長尺で保存点上限2を実測した。Workgroupは生成が残る区間で実参加し、参加/離脱/復元が釣り合う。終端などDSP完了済みの場合は参加不要である。Golden25/25は各WAV全SHAとRAW PCM全SHA、長さ、EOS、不足0を確認した。

|構成|実参加セッション|保存点使用|完全一致|
|---|---:|---:|---:|
|release|216|448|896/896|
|debug|216|448|896/896|

## 長尺の結果と未達

300秒素材の270秒は入力12,960,000→出力25,919,744、285秒は入力13,680,000→出力27,359,871である。入力/速度の単純な割算ではこの座標にならない。独立フルレンダーの全出力は28,800,000フレーム。

|オフラインFIFO消費|受付→Ready秒|保存点|ピークRSS bytes|全suffix|
|---|---:|---:|---:|---:|
|初回270秒|12.103000|0|110,198,784|2,880,256 完全一致|
|270秒後の285秒、保存点無効|12.703500|0|91,930,624|1,440,129 完全一致|
|270秒後の285秒、保存点有効|0.695445|25937920|111,050,752|1,440,129 完全一致|

285秒のsuffix SHAは両方式とも `db1af060a41dbdd542bd120a728466531781f5efa45bc412b32dcf57bce3f89f`。保存点は出力25,937,920から再開し、最大2個、累積19回作成した。OS/ファイルキャッシュを消去した測定ではない。

|Playing実機|受付API処理ms|受付→Ready秒|参照設置秒|最初のPCM秒|HAL推定提示秒|
|---|---:|---:|---:|---:|---:|
|入力270秒|0.005167|12.175808|12.175967|12.178696|12.191669|
|入力285秒|0.001875|0.725361|0.725519|0.732585|0.745579|

受付処理は専用制御threadでAPIを呼んで返るまでであり、UI→制御キューの待ち時間は含まない。実機長尺は各新epochの最初のPCMを確認後1秒間観測し、旧/270秒/285秒の3prefixが独立参照に一致した。全suffixの一致は上記オフライン検査で確認した。長尺実機のFIFO不足、callback/worker期限、C++ new、host/sample/HAL異常は0。Workgroup寿命は正常、全SHA/複製/mlockは各1回。ピークRSS168,378,368 bytes、予約383,637,548 bytes、callback最大12,833nsだった。

初回の深部シークは約12秒のままで、高速シークの目標を全域では達成していない。保存点のない位置・別速度・保持点より前への移動では先頭再構築する。旧区間が先にEOSへ達すると準備中の無音待ちが残る。これを今回の短尺の不足0や保存点使用時の改善で隠さない。


## 再実行・証拠保管

主なWAV/RAW/CSV/sample/app/実行体はGit管理外の `/Users/taro252/Docker/TimeStretchLab/build/phase61` へ保存する。CTestの一時fixtureは`build/phase61_*`等にも作り、JUnitが実行結果と保存先を記録する。成功した形式行列の一時参照RAWは、全SHAと生成レシピを記録後に試験側で解放する。失敗ログ・既存Golden・重要な既存検証証拠を削除しない。

以下は実行コマンドの形である。同名の出力ディレクトリを上書きしないため、再現時は新しい保存先を指定する。ReleaseとDebugは別々に実行する。

```sh
cmake -S . -B build/phase61/release -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build/phase61/release --parallel 4 --target phase61_contract_tests phase61_checkpoint_tests phase61_safety_tests phase61_seek_check phase61_seek_reference phase61_native_tests phase61_sandbox_app phase61_device_route_tests
ctest --test-dir build/phase61/release -R '^(phase54_|phase56_|phase57_|phase58_|phase59_|phase60_|phase61_)' --output-on-failure --no-tests=error -j1
python3 -B scripts/phase61_freeze_reference.py --build build/phase61/release --output build/phase61_repro/oracle_release
python3 -B tests/Phase61SeekSmoke.py build/phase61/release/phase61_seek_check build/phase61_repro/oracle_release/phase61_frozen_reference --full --output build/phase61_repro/suffix_release
python3 -B tests/Phase61Golden.py --probe build/phase61/release/phase54_core_probe --output build/phase61_repro/golden
build/phase61/release/phase61_native_tests build/phase61/native_inputs/boundary_48000_2.wav build/phase61_repro/native
python3 -B scripts/phase61_verify_native.py --input build/phase61/native_inputs/boundary_48000_2.wav --sessions build/phase61_repro/native --reference build/phase61_repro/oracle_release/phase61_frozen_reference --output build/phase61_repro/native_pcm
build/phase61/release/phase61_native_tests results/phase56/long/chain_300s.wav build/phase61_repro/deep_native --deep
python3 -B scripts/phase61_verify_native.py --input results/phase56/long/chain_300s.wav --sessions build/phase61_repro/deep_native --reference build/phase61_repro/oracle_release/phase61_frozen_reference --output build/phase61_repro/deep_native_pcm --expected-sessions 1
build/phase61/release/phase61_device_route_tests build/phase61/native_inputs/boundary_48000_2.wav build/phase61_repro/route.json
```

既存回帰を実行する際は各CTestが使う旧Phaseの実行体もビルドする。Git内の `COMMANDS.json` に主要な全target/コマンド/終了コードを収録した。元の実行記録は `validated_driver.json`、`native_driver.json`、`python_regressions.json`、`deep_native_driver.json` に保存する。形式fixtureは `Phase61SeekSmoke.py` → `phase57_study.fixture(...,'boundary',1.5)`、実機fixtureは同じ関数に4秒を指定する。Sandboxの復元は上記M4AをNSOpenPanelで選び、保存済みの4秒WAV SHAと一致を確認する。元選択が未観測の補足runは保存済みWAV自体をSHA検査して復元する。

300秒の既存入力WAVはGit管理外であり、同一SHAになる生成レシピも新しい保存先で再確認した。復元は既存ファイルを上書きせず、次のように行う。

```python
from pathlib import Path
import sys, hashlib
sys.path.insert(0, 'scripts')
from phase56_study import pulse_payload, write_wav
path = Path('build/phase61_repro/chain_300s.wav')
path.parent.mkdir(parents=True, exist_ok=True)
assert not path.exists()
write_wav(path, 48000, 1, 3, pulse_payload(48000, 1, 3, 300, True))
assert hashlib.sha256(path.read_bytes()).hexdigest() == '13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0'
```

独立参照の復元は `scripts/phase61_freeze_reference.py` が固定commitからソースを取り出し、選んだ構成のflagsでコンパイル・先行リンクする。ソース/実行体/flags/コマンドは各oracle manifestへ記録する。RAWの復元はその実行体へ `input micros preset output.f32 inputFrame...` を渡し、manifestのSHA・フレーム数を検査する。大容量ファイルをGitへ移さない。

## 変更ファイル・API・Merodoa

主な変更は `ProgressiveSeekContract.h`（新要求/状態/秒変換）、`ProgressiveContract.h`（契約版2と上限）、`ProgressiveMacPlaybackEngine.{h,mm}`（非同期制御とcallback参照切替）、`Phase58RealtimePipeline.{h,cpp}`（共有入力/解析・suffix FIFO）、`Phase57ProgressiveSynthesis.{h,cpp}` と `Phase36SynthesisCore.h`（正確な保存点）である。新しいPhase61試験・独立参照・検証script・Sandbox harnessとCMake/CTestを追加した。完全な一覧と各ファイルSHAは `SOURCE_MANIFEST.json` に記録する。

利用APIは `requestSeekToInputFrame/Seconds`、`getSeekSnapshot`、`seekHistory`、`closedEpochs`。`setSpeed`末尾に期待render epochを追加した。受付IDと実完了、Readyと可聴提示を区別する。`getCurrentPlaybackPosition`は現在区間の入力/出力対応、診断の累積提示数と `currentEpochPresentedFrame` は別の値として公開する。

Merodoaへ渡すには、同版ヘッダー/ライブラリで再ビルドし、既存boolシークから契約版2の受付/履歴/理由/世代照合へ移行する。専用直列キューから照会し、原曲フレームをUI座標とし、Pausedのまま移動する。入力権限leaseを最終破棄まで保持し、古いsession/render epochの速度要求・UI応答を採用しない。公開seekフラグがfalseの間は一般UIで有効化しない。Merodoa本体・submoduleの変更は実施していない。

## ゲートと保護監査

- 実装/API契約、独立固定PCM、Golden、今回測定した短尺/長尺の実機、Sandboxの選択範囲境界、実装置レート変更の停止/復元：本報告の条件でPASS。
- 公開seek：**NO-GO**。`seekRequests=true`、`Capabilities.seek=false`を維持する。初回深部の約12秒、旧区間EOS時の待ち、全長・全7速度の長時間実機行列と引継ぎGate2の再承認を残す。
- 物理装置差替え、bookmark期限切れ/File Provider/TCC失効の全経路、OS確保/ページフォールト、音響提示は未検証。未測定を0や成功にしない。
- Merodoa、submodule、既存Golden/manifest、Phase60 REPORT/VERDICTとFD回帰記録は変更しない。Git容量検査は50,000,000 bytes境界を使う。生成物はGit管理外とし、既存履歴の書換え/LFS移行は実施しない。実装・検証中はコミット・Pushも実施しなかった。

`VERDICT.json`に各試験の個別値、`COMMANDS.json`にコマンドと終了コード、`ARTIFACT_MANIFEST.json`に保管物のSHA/サイズ、`SOURCE_MANIFEST.json`に変更ファイル、`PROTECTION.json`に保護監査を記録する。これらJSONのHEAD・作業ツリー・コミット未実施の情報は検証完了時点の記録である。構成時のengine SHAはHEADを示すため、検証した差分の識別にはsource manifestも使用する。Phase62には進めていない。
