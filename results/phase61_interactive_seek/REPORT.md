# Interactive Seek：開発利用と検証結果

2026-10-18 JST。開始時HEADは `main@a9fe2224193dc2e3adae23d4c98fc96db387963f`、作業ツリーは空。検証終了時点（コミット依頼前）ではコミット・Pushを実施していない。以下の結果とPROVENANCEの作業ツリー状態は、その時点の記録である。

既存Fast Localを使う、明示opt-inの開発版Interactive Seekを実装した。旧FIFOの先読み全量を鳴らしてから移る待ちは廃止し、新FIFO・形式・Audio Workgroup/policyの確認後、次のrender機会から約5msで切り替える。一般公開承認と開発インスタンスの許可は分離し、`Capabilities.seek=false` は維持した。

## 今回の判定

|項目|判定・範囲|
|---|---|
|実装・操作ホスト|Release実行体で任意秒の実音声シーク、Pause/Resume、速度変更、Stopが可能|
|開発利用|本Macで検証した44.1/48kHz mono/stereo、専用直列キュー、明示opt-inで利用可能|
|旧FIFO待ち除去|達成。最終比較240操作とも旧残量を破棄し、有界な出力切替を実施|
|座標・順序・寿命・供給|制御270条件＋実際に旧FIFOを空にしたEOF試験2条件で機能通過。RAW順序・混合の不一致・非有限PCMは0、取得したFIFO不足カウンターは0。破棄後の未取得値は下記のとおりnull|
|実時間の今回の限定観測|Interactive比較240操作＋解析待ち24操作で供給・callback/DSP期限・時刻・確保の操作差分0。制御は最終診断を取れた250条件で当該カウンター0|
|Ready p95 200ms|mono 75.521ms。stereo 295.678msで**未達**。monoにも最大279.228msの外れ値1件がある|
|解析未完了|全曲解析待ちを残す。別24操作のReady p95 1669.478ms|
|既知音質問題|旧78/1080件の3dB超過を保存。今回の出力切替の主観試聴は未実施|
|一般公開承認|未承認。全装置、全TCC経路、音響loopbackは未網羅。関連Exact検査にはRelease/DebugのDSP期限超過が残る|

操作手順・API・Merodoa開発版への接続は [PHASE61_INTERACTIVE_SEEK_HANDOFF.md](../../docs/PHASE61_INTERACTIVE_SEEK_HANDOFF.md) を参照する。「一般公開未承認」を、明示opt-inの開発利用を一律拒否する条件にはしていない。

## 変更内容

- `src/playback/Phase61InteractivePlay.cpp`、`CMakeLists.txt`：小さな実音声操作ホストと新試験ターゲット。
- `src/platform/macos/ProgressiveMacPlaybackEngine.{h,mm}`：通常workerの準備・昇格確認、原子的切替スロット、callbackの相補線形混合、退役確認後の停止/解放。速度・session・世代照合、途中取消・準備失敗の監査も追加。
- `src/prototype/Phase61OutputTransition.h`：事前確保された係数・scratch、220/240フレームの状態持越し。
- `src/prototype/Phase58RealtimePipeline.{h,cpp}`：入力/解析leaseを共有するInteractive factory、確定解析の利用可能照会、InteractiveでDSP発行時包絡を無効化する選択。FIFO容量/先行量は変更していない。
- `src/playback/ProgressiveSeekContract.h`：能力/許可/承認の分離、PreparingAnalysis等の補助stage、切替・破棄量・時刻。
- `tests/Phase61OutputTransitionTests.cpp`、`Phase61InteractiveNativeTests.cpp`、`Phase61InteractiveEofTests.cpp`、`Phase61CallbackMallocProbe.{h,cpp}`：短いcallback、競合、混合前後、EOF、実ヒープ計測。
- `scripts/phase61_interactive_{baseline,verify,pcm,summary}.py`：旧HEADの隔離ビルド、同条件比較、RAW照合、個々の時間差からの集計。

位相ボコーダー、FFT、OLA、FIR、密度、確定TimeMap、500ms prerollのアルゴリズムは変更していない。新しい161速度索引、全曲伸縮済みPCMキャッシュは作っていない。既存Exact、既存Golden、過去の承認ファイル、Merodoa本体/submoduleは変更していない。

## APIと所有権

`requestInteractiveSeekToInputFrame/Seconds(value, inputGeneration, renderEpoch, session)` は3識別子を必須にする。既存 `requestFastLocalSeekToInputFrame/Seconds` と `allowUnvalidatedFastLocalSeek=true` も利用可能。秒/フレーム検査、曲長ちょうど、161速度の規則は維持する。従来の500/1000/2000ms研究引数も残し、新Interactive標準は500ms固定とした。旧bool APIは公開ゲートに従ってfalse。

`seekAvailability()` は実装能力、このインスタンスのopt-in/現在の許可、公開承認を別フィールドで返す。既存8状態を維持し、補助stageにPreparingAnalysis/PreparingFifo/SwitchReady/Transitioning/Finishedを追加した。受付IDと実完了、最初のPCMは別に観測する。

新旧の所有者は通常側が保持する。callbackはRequestedをStartedへ取得し、新PCMの最初のフレームから係数 `(i+1)/N`、旧側 `1−(i+1)/N` で混ぜる。最大2 FIFO、最大240フレームの混合であり、残りは新FIFOのみ。係数和1、先頭の読み飛ばしなし。旧EOFは有効残量だけ使い、期待されたEOFをunderrunへ加算しない。Done＋参照静止後、旧workerを通常側で降格・join・破棄する。

開始前はLatest-Wins、開始後は有界切替と旧退役を終えて次の準備へ進む。最大2 DSP所有者。Pauseは停止を維持し、Stop/route/破棄時に参照を解放してから入力leaseを終える。準備/昇格/公開前の失敗で旧区間をフェードしない。開始前切替を同じ速度指定で取り下げた場合も再準備し、Readyで取り残さない。開始後の速度照会/要求は新epochへ向ける。

取消した準備workerも監査・累積カウンターへ含める。`preparedOnly=true` は未提示の準備、未割当epochは0。routeで部分混合を中止した場合の時刻・混合数も保持する。入力世代をまたぐカウンター差分は取らない。過去の1回を後続全操作の新規失敗へ数え直さない。

## 同条件のRelease比較

最終主資料は `build/phase61_interactive_seek/interactive_final/` と [SUMMARY.json](SUMMARY.json)、各JSONL。旧側は `baseline_matched_v3/` にHEADの元ソース/ヘッダーを `git show` で隔離し、**同じヒープ計測付きホスト**でビルドした。checkout/resetはしていない。変更していないDSPライブラリとWorkgroup支援オブジェクトだけを再利用し、ソース・依存物・実行体SHAをmanifestへ記録した。

条件：各音源300秒、0.40/0.50/1.00/2.00倍、Candidate/Baseline、30/150/270/285秒と未訪問 `83*rate+12345` フレーム、各3反復。1音源120操作。初回訪問で、入力インスタンスごとに各位置は1回。FIFO 16384、Candidate先行16384、Baseline12288、500ms preroll、callback記録上限8192、音量0.5を両側で揃えた。ホストは順次起動し、同時再生しない。

MacBookAir10,1、16GiB、macOS 26.6.2、arm64 Release `-O3 -DNDEBUG`。装置ID72、MacBook Airスピーカー、48kHz、通常512フレーム。mono入力は48kHz float32、stereo入力は44.1kHz float32。速度/位置の異なる120件をまとめた実測p95であり、各セル3反復から安定した母集団p95を推定したものではない。

|音源/経路|件数|受付→FIFO Ready p95|受付→新PCM callback p95|各操作のFIFO Ready→新PCM p95|HAL提示推定 p95|
|---|---:|---:|---:|---:|---:|
|mono 旧|120|96.964ms|455.260ms|360.380ms|468.255ms|
|mono 新|120|75.521ms|84.545ms|10.313ms|97.521ms|
|stereo 旧|120|248.762ms|636.462ms|391.158ms|649.836ms|
|stereo 新|120|295.678ms|304.553ms|10.405ms|317.900ms|

時間差は**同じ操作の2時刻を引いてから分布を集計**した。p95同士の引算を内訳としていない。新SwitchReady→混合開始のp95はmono 10.164ms/stereo 10.252ms、最大10.625/10.690msで、512/48kHzの次callback周期に対応する。混合長はmono240/stereo220フレーム。混合処理のCPU時刻差と音の5ms持続は別である。

新240操作の旧FIFO開始残量はmono10752〜16384、stereo9660〜16384フレーム。退役後の意図的破棄量はmono10512〜16384、stereo10048〜16384。生産者が少量補充するため単純な残量−混合長とは一致しない。通常underrunは0。新旧両側で、操作差分と入力寿命累積のFIFO、callback期限、host/sample/HAL時刻、DSP期限、C++ new、主要Cヒープ呼出し/解放は0だった。

Ready自体のstereo悪化は隠さない。確定解析後の局所DSP/FIFO準備が主な残存区間で、今回そのFFT/FIR等の内訳プロファイル、温度/周波数は採取していない。Readyの変動をFIFO待ち除去の効果や温度のせいと断定しない。新Ready最大はmono279.228ms/stereo614.669ms、200ms超は1/120・31/120。

先行版 `native_final/` はmono Ready/新PCM p95 76.465/82.979ms、stereo216.206/222.573msだった。こちらも保存するが、最終の主値には採用していない。一部の先行JSONは旧退役の監査完了前を読んで破棄量0が未確定値として出た。最終ホストでは旧epochの監査完了を待って量を採取した。初期の `new_mono_v1/` は操作ホストと重なった診断で、主性能比較から除外した。

## 解析待ちを別条件で測定

`interactive_final/early_stereo/`：4速度×2preset×3反復の24操作、初期Ready後すぐ270秒へ要求。全24件でplay時の全曲解析は未完了だった。

- 受付→Ready p95 **1669.478ms**、最大1742.760ms。
- 準備開始→確定解析利用可能の観測 p95 **1520.436ms**。
- 受付→新PCM p95 1677.532ms、HAL推定1690.877ms。
- SwitchReady→開始 p95 9.374ms。FIFO/期限/時計/確保の操作差分0。

PreparingAnalysisを公開し、待ち中の取消/置換を許す。未確定Mapを確定扱いする回避は行っていない。今回のFIFO修正で全曲解析待ちを解消したとは判断しない。

## 制御・callback・PCM

27種×2preset。Gate、Ready、Playing、Paused、準備中Pause、64連打、連続、準備中速度、シーク後速度、Ready置換、同速度Ready要求、準備中/Ready時Stop、準備中/Ready時route、昇格前/公開前失敗、入力消失、EOF、破棄、および混合開始後のPause/Stop/連打/速度/route/破棄を含む。

|構成|機能|最終native診断があるケースの供給/時計/期限/確保/退役検査|
|---|---:|---:|
|Release 48k stereo 装置64|54/54|50/50|
|Release 44.1k mono 装置64|54/54|50/50|
|Debug 48k stereo 装置64|54/54|50/50|
|Debug 44.1k mono 装置64|54/54|50/50|
|Release 48k stereo 装置512|54/54|50/50|

破棄4ケース/構成は、破棄完了・後続出力なし・別engineで予約予算を再取得できることを確認した。破棄後のnative最終診断は取得できないのでJSONはnullであり、0/PASSへ補完していない。ヒープの外部カウンターとPCM監査は破棄中も有効。期待した入力消失/準備失敗の処理通過を、入力が健全なままとの判定へ読み替えない。

実callbackは48kで64、44.1kで58/59等の小さい単位を処理し、混合位置を持ち越した。途中routeでは64/128フレーム等で中止した事実を記録した。装置バッファは各回512へ戻し、API再照会でも復元を確認した。通常スレッドからSPSCカーソルをリセットしない。

`phase61_output_transition` は44.1/48k、mono/stereo、chunk 1/7/64/128/512/4096、旧有効数0/17/240の72条件を通過。相補係数、有限値、新先頭順序、旧EOFのゼロ補完を検査した。

追加 `eof_fallback_48000_2/`、`eof_fallback_44100_1/` はN−1へ移った混合中に次を予約し、次回切替時に**旧FIFO残量0・旧受信0**を実測した。新側240/220フレームを混ぜ、欠落/underrun/確保/期限超過0。混合後の実PCMを `post_transition.f32` として別保存した。ここはCandidate・0.50倍の2条件で、全preset/速度の空FIFO実機網羅とはしない。

callback内でFFT/解析/FIR/I/O/確保/解放/mutex/待機/ログ/Objective-C呼出しを追加していない。追加処理は高々2 FIFOの読取り、事前確保ゲインの乗算/加算、原子通知でO(frames×channels)。コールバックのソースSHA不変は今回の合否条件にしていない。

検証専用dylibはmalloc/free/calloc/realloc/posix_memalignと主要malloc_zone系を実フックし、ホスト起動時にmalloc/freeが検出できる自己検査を行う。C++ newも別計測。全malloc実装/VM/OS内部を網羅したと主張しない。通常の操作ホストやライブラリにこのdylibを必須依存としていない。

`observeEpochPcm` の混合前RAWをepoch別に保存し、`observeOutputPcm` で混合後を各入力・ゲインと全数照合、有限値/連続callback座標も検査した。postは単一epochのsuffixとしてハッシュしていない。各FIFOの座標、混合位置、受信数は `output_spans.csv` へ分離した。Releaseの両形式で、独立したオフラインlocal実行体とのRAW照合は計12全suffix・60prefix・8空suffixが一致。これは同一local DSPの**統合検査**で、先頭連続レンダーとの音質合格ではない。

混合終了後に追加ゼロや旧epochが混入すれば上記全数照合が失敗する。入力自身の無音、意図したEOF、相関/位相による混合中の減衰は分離する。旧Sandboxの20/30を新しい無音判定で上書きしていない。今回の新クロスフェードの主観試聴・全音源の追加無音評価は未実施。

## Exact・FD・Golden回帰と失敗

- Release/Debug関連CTest：**各25/25**。Phase54/56/57/58/59/60/61、161速度、FD保持・入力変更、worker/policy復元等を含む。ログは `regression_final/ctest_{release,debug}.log`。
- 独立した凍結全曲参照を使うRelease Exact：**896/896 PCM一致**。8WAV形式×7速度×2preset×4位置×2実行方式。checkpoint hit448、常駐最大1（上限2以内）、実Workgroup join/leave/restore 各216。
- **上記Release ExactのDSP期限カウンター1件**：`48000_2_1_2000000_candidate`、入力0、workgroup。追加の同条件10反復でもPCM10/10だが期限超過1件があり、残課題として再現した。これは音声callbackを使わない全suffix照合ホストのWG検査で、HAL失敗とは別。根本原因の特定/修正は完了していない。
- 最終Native Exact 48k stereo：Release機能20/20・計測20/20。Debug機能20/20・計測18/20（Candidate/Baselineの速度準備でDSP期限各1、FIFO/callback確保/時計/退役エラー0）。Debug失敗をReleaseの説明へ流用しない。
- 先行Native Exact両形式：Release機能40/40・計測40/40、Debug機能40/40・計測38/40。先行と最終のログを別保存した。
- Native RAWの独立凍結参照照合：最終48k stereoと先行44.1k mono、Release/Debugの4構成。各12全suffix・14prefix・2空suffix、計48/56/8すべて一致。
- Phase60 lifecycle：Release/Debugとも先行・最終で通過。prepare取消、入力変更、選択元消失、停止・復元等。
- Golden：既存WAVのSHAを検査し、RAW SHA/生成数/消費数/EOSを照合、**25/25**。

896 PCM成功と期限超過は別判定である。実時間を含む全項目が無条件合格したとは報告しない。過去のRelease時刻不連続/DSP期限問題も保存している。

## メモリ・TCC・残る制限

最終比較の新側ピークRSSはmono99,500,032バイト、stereo162,201,600バイト（検証ホスト込みのプロセス高水位）。既存1GiB予約上限とプロセス内1入力所有者を維持。全シークでsource hash/snapshot/mlockの累積各1を確認し、元の入力/解析を再利用した。装置へ渡したPCMは取り消せず、今回の上限はアプリFIFO内の待ちをなくしたもの。

今回の実機は通常プロセスであり、新callbackをApp Sandbox/TCC全経路で再承認していない。既存FD保持・保護入力の回帰は通過し、旧Sandbox実再生/拒否記録を変更していない。Merodoa開発版ではsecurity scopeを全所有者の停止・破棄まで保持する。新混合の主観試聴、実音響提示時刻、他装置、他OS、長時間連続運転、全ての競合の形式的証明は未完了。

旧長尺インパルス列の**78/1080失敗、閾値3dB**、主観試聴6クリップの「違和感なし」、旧Sandbox総合20/30は両立する記録としてそのまま残す。今回それらを再実行・閾値変更・一般公開承認への変更はしていない。Phase62へは進んでいない。

## 再現手順と保管

```sh
cmake -S . -B build/phase61_interactive_seek/release -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/phase61_interactive_seek/release --target phase61_interactive_play phase61_interactive_native_tests phase61_interactive_eof_tests -j 4
# Debugも同様に作成し、関連回帰用の通常ターゲットをビルドする
python3 -B scripts/phase61_interactive_baseline.py --output build/phase61_interactive_seek/baseline_matched_v3
python3 -B scripts/phase61_interactive_verify.py --suite interactive --output build/phase61_interactive_seek/interactive_final
python3 -B scripts/phase61_interactive_verify.py --suite regression --output build/phase61_interactive_seek/regression_final
ctest --test-dir build/phase61_interactive_seek/release -R phase61_output_transition --output-on-failure
```

既存の保存先は再使用せず、再検証時は新しい出力名を選ぶ。実行コマンド・終了コード・所要時間は各 `commands.json`、比較機械集計はSUMMARYとJSONL、全成果物のSHA-256/サイズ/絶対保存場所は `ARTIFACT_MANIFEST.json`、ソース情報は `PROVENANCE.json` に保存する。WAV/PCM/build/実行体/圧縮ソースはGit管理外の `build/phase61_interactive_seek/` に保管する。

- 300秒mono：`results/phase56/long/chain_300s.wav`、57,600,044バイト、SHA `13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0`。既存phase56のpulse_payload(48000,1,3,300,True)とWAV生成レシピを再使用。
- 300秒stereo：`build/phase61_fast_seek/music_300s.wav`、105,840,044バイト、SHA `fc8be98125b35e0b2bde0728ef8ccfc60ab2aee4462b72f61c55733ae277cf58`。`results/phase31/input/mix.wav` のdataを30回連結し、fmtを保持してRIFF/data長を更新する既存レシピ。
- 4秒実機fixture：`phase57_study.fixture(path, rate, channels, 3, "boundary", 4.0)`。48k stereo/44.1k monoの再生成SHA一致を `fixture_recipe_check/` で確認。
- 独立Exact参照：`build/phase61/oracle_{release,debug}_v1/phase61_frozen_reference`。旧記録の復元レシピと今回manifestのSHAで同一物を確認し、現在のDSPを参照として再利用しない。
- 旧比較ソースは `baseline_matched_v3/`、先行バイナリは `version_v1/` に保存。ソースsnapshotは基準HEADと一緒に別の作業場所で復元し、既存作業へ強制展開しない。

初期の型推論/リンク設定のビルド失敗もログを保存した。コミット準備時に実機テストソースの空行1行の末尾空白だけを除去した。検証時ソースとsnapshotのSHAは保存し、整形後のSHAをPROVENANCEへ別記した。検証証拠の削除、履歴書換え、LFS移行はしていない。50,000,000バイト以上の新規Git追加はなく、大容量資料はmanifest/レシピで参照する。
