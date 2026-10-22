# Phase62 A1/A2 追加修正

開始点は独立checkout `/Users/taro252/Docker/TimeStretchLab`、main、clean、`e4a990787f149b546827fd4dcb96b9708b3662f2`。A1は単独ローカルコミット `f3292945f3edafd5664b10c60d6eb9a90d0a2aaf`。A1_MANIFESTはその時点の記録で、全体の最終記録はmanifest.jsonを使う。A2はその後の別変更単位とし、この報告を含むコミットの40桁SHAを最終回答で渡す。push/PR/履歴書換え/Merodoa変更は行わない。

## 判定

|範囲|結果|限定事項|
|---|---|---|
|A1 確定速度履歴不変|PASS|旧13/14 FAILを再現、修正後の両Preset主14/14。単独候補を保存|
|A2 AB初回性能|PASS（互換保存状態がある同prepare再要求）|新prepare初回、Clear、キー不一致のcold Exactは高速化対象外|
|最終コードの影響回帰|PASS（限定範囲）|最終147/147、独立70/70、性能6/6、F01比較70/70、Release/Debug各20/20|
|一般公開 / Merodoa既定採用|NO-GO / NO-GO|実時間期限・公開能力・実アプリ統合等は別承認|

## 実装と最終ソース識別

A1は旧owner停止/join後の破棄数をClear Snapshotへ残し、速度要求別には `clearContinuation && !terminal` と要求/Loop/入力/準備版の一致を満たす場合だけ記録する。Clear前個別照会を基準に、後の個別/履歴/close監査の39フィールドを比較する。[A1_REPORT.md](A1_REPORT.md)、[A1_REPRO.json](A1_REPRO.json)、[設計](../../docs/PHASE62_TERMINAL_CLEAR_DESIGN.md)。

A2は既存の完全固定A保存点をInputLeaseの任意一枠へ共有し、同一解析・入力・Preset・速度・A/B・全Map座標の場合だけ新epochへ復元する。位相/左右履歴/OLA/FIR/PCM/カーソルを一体でcloneし、新snapshotとMap全ノードを既存契約で再検査する。取得時に任意枠を空け、古いworkerの再公開は準備版で抑止する。C≠Aの部分再準備と通常KeepPositionでは任意枠を先に解放し、必須保存点の枠を確保する。[設計](../../docs/PHASE62_INITIAL_EXACT_REUSE.md)。

最大2実行owner、同lease最大2不変checkpoint、FIFO16,384、短区間RAW96,000、既存1GiB/24MiB予約を維持する。保存枠は既存permit付きオブジェクトの共有参照で、第三の実行ownerではない。callback/周回の実時間処理へのmutex/確保/ログ追加なし。初回以外の通常手動seek opt-in、FastLocal、DSP演算/音質/許容誤差、公開能力は変更しない。

最終ビルドは `a2_build_record_04/BUILD.json`、ソース一覧SHA-256 **2684e23e4dff9f3837a1964ec6932aa2ce0e0daba9192f84344024312c6f2c61**。A2コード差分SHA-256 **0dae876e03575cdc197ac39f3a37f271ecf37e60b4f732a6584557c2527cfc19**、`FINAL_CODE_STATE_04.json`/`A2_CODE_DIFF_04.patch`に保存。検証時はf329…＋明示した未コミット差分であり、基準SHAに変更を含めたとは扱わない。実行体は `candidate_binaries_04/MANIFEST.json` と保存コピーで識別する。ビルド時の埋込みGit SHAはf329…、変更後コードは上記inventory/差分で識別し、埋込みSHAだけを完成ソースの識別子にしない。

## 性能（同一300秒入力、Release）

48kHz stereo PCM16人工入力、Baseline 1.00、AB長2秒、M1/MacBookAir10,1/16GiB、macOS26.6.2、Apple clang21.0.0、CMake4.3.3、arm64、C++20、`-O3 -DNDEBUG`。操作shellはRosetta x86_64だが実行体はarm64。音声装置48kHz/512 callback。入力SHA-256 **f44e0a246945fd35b3853c5e2988b9b87f739f496fbd57839ccc4ef481cd28b0**。

|A入力位置|条件|変更前中央値 秒|最終中央値 秒|n（各版）|目標判定|
|---|---|---:|---:|---:|---|
|0秒|新prepare初回|0.120644|0.117350|2|PASS|
|0秒|同prepare再要求|0.091663|0.096013|2|PASS（退行許容+0.25秒以内）|
|30秒|新prepare初回|3.359735|3.352128|2|PASS（cold退行制限）|
|30秒|同prepare再要求|3.344160|0.115776|2|PASS、96.54%短縮|
|270秒|新prepare初回|29.652722|30.063423|2|PASS（cold退行制限）|
|270秒|同prepare再要求|29.271878|0.120618|2|PASS、99.59%短縮|

目標は変更前計測後・実装前に `ACCEPTANCE_PLAN_01.json` で固定し、再要求30/270秒は中央値1秒以下かつ変更前20%以下、coldは1.20倍+0.25秒以内、A0は+0.25秒以内。変更後に緩めていない。各生値/最小/最大/中央値/nはbefore/after SUMMARYと `PERFORMANCE_COMPARISON_02.json` にある。

native受付→Readyはnative同一時計の差、操作位置合わせ/最初A RAWはsteady_clockの差。表は受付→A位置合わせ＋Ready観測→最初A RAWで、両版共通の30ms静止確認と明示Playを含む。時計の生値を跨いで減算しない。物理出音時間やp95ではない。

最終A270の再要求例では、P=12,959,744から256フレームだけ前置合成してOA=12,960,000へ接続する。新prepareは12,960,000フレームを合成するままである。解析完了前A0の別試行は両版とも要求前flag=0、同prepare再要求flag=1。最終解析前試行のanalysisWaitS=0.646647秒を分離しており、解析待ちを保存状態hitと混同しない。通常ClearのExact B継続にも今回の高速化を広げない。

## 新規検証と制約

全実音声/性能/重負荷ビルドを一担当で直列実行。全プログラムのexit/timeout、expected/executed/全ID、完了SUMMARYを検査する。新binaryを成功ビルドに対応付け、旧binaryを流用しない。

|試験|期待 / 実施|結果|証拠（原本基点以下）|
|---|---:|---|---|
|A1修正前14checks再現|14 / 13成功・M14失敗|期待したFAIL、exit1|a1_baseline_01。discardのみ0→12,288、39fields比較|
|A1単独修正の限定回帰|28 program・147 / 147|PASS|a1_fixed_02、BUILD_A1_01|
|変更前性能|7 program・14 / 14 samples|PASS|bench_before_02、baseline_02。e4 Engine＋新hostの隔離版で純e4 binaryではない|
|最終性能|7 program・14 / 14 samples、6 / 6判定|PASS|bench_after_02、PERFORMANCE_COMPARISON_02|
|最終A1/Paused Clear/F01/終了監査|28 program・147 / 147|PASS|a2_history_regression_02|
|最終独立RAW/Map/混合/B/資源|9 program・70 / 70、native14 / 14 rounds|PASS|a2_quality_03。7本の独立参照をSHA照合再利用|
|F01短全曲の追加比較|旧/最終各5 program、70 / 70|PASS|f01_timing_pair_01。中間FAILを消去/成功へ読替えしない|
|Release/Debug既存必須CTest|各20 / 各20|PASS|strict_01、全6/6 stages完了。skip/fail=0|
|参照出自・SHA|11 / 11|PASS|REFERENCE_AUDIT.json。再生/PCM比較そのものとは別|
|全161速度×両Preset・Exact896・Golden25の全面再実行|0（今回新規）|NOT_RUN|DSP演算/固定通常経路の変更なし。今回影響する初回復元/代表速度/境界/資源/共通ゲートを選択。過去F01/D07/D08の成功件数を新規へ付替えない|
|物理loopback・試聴・Merodoa実TCC/UI統合|0|NOT_RUN|今回の局所判定の対象外|
|全条件の実時間期限承認 / 一般公開 / 既定採用|―|未承認 / NO-GO|機能/性能PASSから拡張しない|

独立固定参照は旧Phase36の `phase61_frozen_reference`、SHA-256 **de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748**。元source/ec087、host/driver、旧archiveリンク契約と動的bb22参照の現SHAも監査した。参照出自と限界はREFERENCE_AUDITに記録し、変更後製品から参照を作らない。

品質の7native条件は48k mono PCM16の1.25短100ms/1.00非cache、44.1k stereo Float32 Candidate0.40非cache/2.00短区間、両Preset1.25のPlaying進入混合、300秒素材A270。offline両PresetではA0/非ゼロ/短100ms/3秒非cache/通常seek保存点との枠競合/速度・範囲・新lease・新Preset不一致を検査。全bit/全ch/フレーム/絶対Map座標/3自然周期、NaN/Inf=0、RAW→独立境界式→最終gain前出力を比較する。gain0.5は既存出力段に維持し、物理出力を検証したとはしない。同leaseのPreset変更はAPIが存在しないためNOT_EXERCISED、新leaseで確認する。

## 失敗・中間結果を保持

- baseline_01はhostコンパイルFAIL、旧binary未使用。bench_before_01はdriverの変数名衝突で途中INCOMPLETE、完全再実行before_02を主証拠にする。
- a1_fixed_01はsandboxから装置取得不能、音声未実施。装置にアクセスできる環境のfixed_02と分ける。
- a2_build_record_02は新entry hostのmain重複でコンパイルFAIL。guardを加えて再ビルドし、失敗buildのbinaryは使用しない。a2_quality_01は実行前manifestのPath直列化エラー、音声/参照0件。
- Build03で初回任意枠を部分C再準備まで保持してしまい、a2_history_regression_01の両Preset Clear継続2件が上限2で失敗した。C≠A時の通常制御で解放して修正し、Build04の同一回帰147/147で確認した。中間性能/品質PASSだけでは最終候補を承認しなかった。
- 同中間回帰のF01 Candidate短240ms全曲条件1件は、選択済み75%準備が受付期限を過ぎて安全失敗し、最新200%も取消（2/7成功）。理由・終端行・ログを保持する。期限/供給基準を緩めず、最終同条件および旧/最終各5回はPASS。単発超過の恒常的解消やRT保証を主張しない。
- A2_EVIDENCE_REVIEW.jsonはBuild03→04のbinary更新を検出した中間レビュー。最終の証拠と別扱いにする。

## 引継ぎ・再現

[VALIDATION.md](VALIDATION.md) と各recipesを使用する。大きな入力/RAW/trace/実行体はGit管理外 `build/phase62_terminal_initial_20261022_01` に保持し、manifestにSHA/コマンド/位置を残す。既存証拠削除なし、新規blob50,000,000 bytes未満をコミット直前に検査する。

Merodoa向け差分は [PHASE62_MERODOA_HANDOFF.md](../../docs/PHASE62_MERODOA_HANDOFF.md)。追加診断は `pipeline.loopReuse.initialCheckpointHit`（完全固定初回A保存状態の復元の有無）。既存checkpointStartFrame/coldDiscardedFrames/analysisWaitS/mapCpuS等と組み合わせる。速度要求39フィールドと終了監査配送/即時所有コピー/全joinのAPI契約は変えない。A1の14checks、正当なClear移管、同prepare再要求とfresh初回をbridge実アプリでも限定再確認し、同じheader/libraryで再ビルドする。

allowExperimentalLoops=false、publicLoopApproved=false、Capabilities.seek=false、currentCycleSpeedChanges=false、publicSeekApproved=falseを維持。既存FastLocal長尺、stereo Ready、開始時計、Debug期限、主観音質/物理loopback、Merodoaの権限・実アプリ統合は別ゲートのまま。
