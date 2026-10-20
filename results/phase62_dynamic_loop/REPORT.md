# Phase62 動的Loop修正

判定：**INCOMPLETE / 局所全体NO-GO / 公開NO-GO**。実装済みの機能と実施した検証は下表の範囲。未実施を既存結果で埋めない。`currentCycleSpeedChanges=false`、`allowExperimentalLoops=false`、`publicLoopApproved=false`、`Capabilities.seek=false`を維持する。

## ソースと環境

- 調査基準・開始HEAD・検証完了時HEAD：`7c05319d8142ef53a70c95be4f214f293bb2428a`、branch `main`。開始時はclean。検証完了時点では強制リセット、commit、stage、push、PR、履歴書換えを行っていない。後続のコミット許可は末尾の追記を参照する。
- 検証完了時の未commitソースの識別：CMake/src/tests/scripts一覧のSHA-256 `238ad47151ac6d408d7c6eea6dbb5898dda6d43173ff245a238045043500d9f8`。全ファイルのSHAはSOURCE_MANIFEST、変更差分・新規ファイルはCHANGESETを参照する。基準SHAだけを最終状態の識別に使わない。実行可能ソース一式の保存archiveもGit管理外へ保存し、SHAと安全な復元先をMANIFESTへ記録する。
- PCM行列等の実行時一覧SHAは`3d72753045bf975a9ceb3bfb17ef2be9df65c4333416bf8c37f823aadb6c3ea4`。後続で複数周後のPause監査、通常制御の取消順序・部分切替Stop、境界入力/R照合、512周期・callback位相、実seek API試験を追加した。共通DSP/pipelineソースは不変、動的比較binaryもSHA `c9a462b007891f0ad139a24e3b02233156743e14356d97c7c5a589e910a4fcc1`で不変。影響する制御・境界試験は再ビルド・再実施し、元行列を新しいソース実行へ付け替えない。各実行時SHAと差分はFINAL_SOURCE_DELTA・各EXPECTEDを参照する。
- 最後の製品差分は速度受付時の古い延期理由クリアとKeepPosition初回の未対応理由表示の2行だけ（FINAL_METADATA_ONLY_DELTA）。DSP・renderer・所有権/供給コードは変えていない。影響する延期契約と最新要求の競合は最終238adソースで16観測を追加し、Safety/BoundaryもRelease/Debugで各2件再検査した。各native行列の実行時バイナリ10種はSHA一致の実体をGit管理外へ退避して保存し、最終ソースの実行に付け替えない。
- Apple M1、16GiB、macOS 26.6.2 (25G83)、Apple clang 21.0.0、CMake 4.3.3。製品と参照はarm64。制御用shell/Pythonの`uname -m`はx86_64だが、`lipo`で試験binaryのarm64を検査する。Releaseは`-O3 -DNDEBUG`、Debugは別build領域を使う。
- 実装・実出力の主作業場所：`build/phase62_dynamic_20261020/`。device 48,000Hz、buffer 512。音声試験・性能測定と高負荷ビルドを重ねず、すべて直列実行する。sandboxからは音声装置を取得できず、装置アクセスを許可したhostで実施する。

詳細なコマンド、各実行前EXPECTED、binary/input/reference SHA、期待/実施件数、結果の保存先はMANIFESTを参照する。ビルド失敗後の旧実行体は使用しない。日付は2026-10-20〜21（JST）。

## 修正した挙動

長い非cache Loopの現在producerで、Phase59の安全な生成位置から動的Mapを採用する。位相・左右履歴・OLA（重ね合わせの信号/重み）・FIR（フィルター履歴）・部分未公開PCM・planner取引を同じ所有者で保持し、固定checkpointへ偽装しない。新速度の次固定A→Bは第2所有者で先に準備・実時間参加・callback公開し、不可逆commit前に採用IDも公開する。動的Bは採用Mapから求める。現在周期FIFOをflushせず、現在周期のPCMと次周期の固定Exactを別々に照合する。

Pausedでは実際に停止したCとLoop/cycleを保持してExact再準備する。旧producerのjoinと参照解放後に最新要求のReadyForResumeを公開し、Resume/Playを一度も呼ばず観測できる。準備中の再開意思と再Pause取消、100→75→100、duplicate/置換、停止時FIFO破棄専用監査を扱う。準備をユーザーseekや周回へ加算しない。

進入混合は新旧それぞれのBでspanを分割する。B−1の指定Cを維持し、出力Mapの丸めでR=0ならPCMを作らずAへ接続する。初回seekは周回でなく、その後の自然B→Aだけを数える。定常境界は周期Lを短縮しない補正、進入は相補混合であり、順序を区別する。

Latest-Winsでcommit済み境界版を取消さず、未開始版は退役後に置換する。旧planner取消回収中のBusyは再試行する。取消直後のPauseでは旧A版を採用しない。Clearはenabled=falseのまま有効出力を維持し、必要なcommit済み境界版を使った後、**明示的な固定Exact再準備**でBから通常再生へ接続する。動的履歴をB以後へ連続した結果とは呼ばない。Clear待ち速度は理由付き拒否し、解除後に再要求する。

Applyingが供給再検査でRequestedへ戻る場合も、DSP取引の取消確認後にcallback経路を閉じる。Stopは出力静止を先行させ、Startedの部分混合を待ち続けない。準備版を指すcallback targetを確実に外してからjoin・監査・解放する。正常なStop取消を音声供給障害としない。

## 修正前の最小再現

基準SHAから`git archive`した製品ソースを別領域でビルドし、修正前実行体を保存した。

| 条件 | 修正前の実測 | 修正後の比較対象 |
|---|---|---|
| 8秒Loop前半の100→75 | 500ms観測で適用なし、operationなし、B待ち | 最終native probeと旧planner/DSPの実測Frontier再生 |
| LoopをPause後125要求、Resume 0回 | 5秒でReadyなし、stopped operation不在、CがAへ移る | Resume前Ready、C/Loop/消費/可聴出力の固定 |
| R=1、N=220、callback64でB跨ぎ進入 | Bを越えるpresented、span上限による安全停止 | 独立RAWと新旧両側B分割の最終PCM |

最新要求75/100/40/200、Pause中75、Clear供給維持、Stop、内容の異なる入力への再準備と古い文脈の拒否も基準版で観測した。7項目中、現在周期未適用とResume前Ready欠落/C巻戻しの2項目をREPRODUCED、正常な5項目をPASSとして保存する。Clear完了と独立PCMはこの短い基準観測へ含めない（`baseline_race_run_v1`）。

修正前ログ：`baseline_native_probe_device.log`、`baseline_boundary.log`。最後に同じ境界試験ソースを新しい基準SHA archiveへコピーし直し、製品6主要ファイルがGitの基準版と一致することを確認して再ビルドした。`baseline_boundary_v6.log`でもR=1/N=220/callback64の範囲超過と安全停止を再現した。試験ソースとbinary SHAはBASELINE_BOUNDARY_V6_EXPECTED、製品ソース照合はBASELINE_BOUNDARY_V6_SOURCEに保存する。修正前の成功件数は今回の成功件数に含めない。

## 検証台帳（実行時ソースは各EXPECTEDで識別）

<!-- FINAL_VALIDATION_TABLE -->
| 検証 | 期待/実施 | 結果・範囲 |
|---|---:|---|
| 実出力の現在周期・動的履歴Pause/Resume・Resume前Ready | 2Preset/2 | PASS。独立旧planner、Map(B)、全チャンネルRAW prefix一致 |
| commit後置換、Clear、取消直後Pause | 6/6 | PASS。最大所有者2、停止後0、callback new/malloc/free・missing/padding・期限/時計異常は各0 |
| Clearの明示Exact・独立RAW/最終混合PCM | 2/2 | PASS。旧末尾/新B以後RAW、混合220フレーム、窓外2505/2513フレームの差分・非有限各0。実mixerゲインは別 |
| Paused Loopの独立Exact PCM | 8/8 | PASS。4形式、C→Bと次A→B、自然2周、窓内/外の数式、Resume前Ready |
| 未commit連打→最新200、Paused75、Clear/Stop/入力世代、KeepPosition理由 | 16/16 | PASS。両Preset各8観測。通常workerだけを遅延、callbackを止めない。KeepPosition2件は延期契約だけで、現在周期機能を合格に数えない |
| Paused Loop制御 | Release 20/20、Debug 20/20 | PASS。両Preset各10件、最新要求・再開意思・取消・入力/装置/close、2周後のC/周回/FIFO監査 |
| 通常Paused独立PCM / 制御 | 36/36、84/84 | PASS。最後の制御修正をリンクした新binary、旧参照SHAを再確認して回帰 |
| 全161速度の動的適用 | 640/640 | PASS。隣接160組×双方向×2Preset、各Preset全161値が実Applied、独立planner/Map/RAW一致 |
| 重点動的遷移・形式・中盤 | 20/20、48/48、6/6 | PASS。重点20、形式48、長Loop中盤6。代表形式で全速度、残る7形式で重点適用 |
| 動的B・次固定周期・異速度の最終PCM | 6/6 | PASS。独立動的/固定RAWと窓内/外・ΣL_i・ゲイン式。実rendererの手動接続host、HAL期限/実mixerは別 |
| B直前進入・callback分割・各形式/長さ | 680/680 | PASS。オフライン実renderer・固定Exactの手動接続。100/500/1000ms、および非cache 3000/5000ms、callback64/128/512/4096。旧側B跨ぎ、実R=0を含む。実seek APIとは別 |
| Exact896 / Golden25 / 固定161速度の有限RAW・reuse | 896/896、25/25、322/322、322/322 | PASS。新binaryの独立旧参照、全ビット・finite・長さ |
| 影響する決定的回帰 | Release 16/16、Debug 16/16 | PASS。CTest名と最終JUnit件数を検査。最後の理由表示差分ではSafety/Boundary各2件を新binaryで再検査 |
| 故障/拒否/世代/装置の既存native制御 | 13/13 | PASS。意図的故障を通常品質の成功件数に含めない |
| 長尺固定速度warm A=0/30/270秒 | 6/6 | PASS。速度1.00、48kHz stereo PCM16、両Preset、非cache3秒区間。worker2、warm FFT生成0、warm破棄は各復元2048未満 |
| 100ms・速度2.00の長時間実出力 | 2×4100/2×4100周 | PASS。両Preset、missing/padding/new/malloc/free/期限/時計異常0、周期1804出力frame、正常反復 |
| native集計の型解釈 | 元wrapper 8行FAILを保持 | 既存JSONの整数1を`is True`で拒否した集計誤り。別SCHEMA_AUDITで13/13機能・8/8実測実時間を再検算してPASS。製品/成果物/基準は変更しない。型を正したwrapperでも13プログラムを新規に再実行してPASS |
| KeepPosition初回の現在周期変更、非0のA/複数周後の独立動的PCM、全状態の連打/上限/失敗注入、独立FastLocal方式 | 未実施/未対応 | NOT_RUN/INCOMPLETE。対応済み範囲へ算入しない |
| 内部最小全周期512出力フレーム・Bのcallback内位置 | 192/192 | PASS。両Preset、独立旧Map/RAW、新旧B跨ぎ。各callback64/128/512/4096でoffset=1/中央/末尾を実測。100ms公開入力下限は維持 |
| 実seek APIのC保持/B補正/実採用方式/再開PCM周回 | 44/44 | PASS。3速度×7件×2Preset＋R=0各1件。FastLocal/Interactive要求は実採用Exactとreasonを確認。独立DSP比較とは別 |
<!-- END_FINAL_VALIDATION_TABLE -->

NaN/Infは全ビット一致とは別に検査する。Phase62PcmAuditは製品RAWからの加工検算であり、単独を独立DSP oracleとはしない。Handoff hostの0.5ゲイン数式は実mixerゲインの測定ではない。実出力の全速度試験、物理loopback、試聴は上表のPASSへ含めない。

境界は合計872条件（680＋内部512周期192）。100msの184条件は独立入力C/R/Nまで照合する強化版で再実行した。APIのR=0は旧oracleでC=352801/B=352802、両者の出力176560を独立に求めて選んだ。停止中の指定Cを保持し、再開後の実PCMフレーム数から余分な初回周回0を確認する。範囲を8秒ちょうどに固定した最初の42件ではR=0が実現せず、その事実も元台帳に残す。

## 参照・素材・証拠

- 動的：旧`bb22efcbd27f999e8ffe85bbe3f03e20895be3f2`由来の凍結ライブラリとcaptured driver。binary SHA `1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818`。`results/phase59/FROZEN_REFERENCE.json` / `CAPTURED_REFERENCE.json`のソース・ライブラリ・driverを確認する。製品変更から参照を作り直さない。
- 固定Exact：旧`ec087019626d9ff0d9f157245729b74ddb6847d7`のoracle、binary SHA `de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。
- 既存必須素材`results/phase31/input/mix.wav` SHA `789d4c159e35b4c133a17913ad5a9c47b85970185e5d86b074d146afc1bb311e`、36秒素材SHA `f470d863955ab2b475392e008c39292fd1fd6bf44d71df7311c8b584b808b52b`。追加の決定的fixtureは各INPUT_RECIPE/EXPECTEDへ生成関数・引数・形式・SHAを記録する。必須素材の代用品として合格扱いしない。
- すべての大容量RAW/WAV/traceはGit管理外の上記build領域。保存場所・サイズ・SHA・再実行コマンドをMANIFESTと各台帳に記録する。既存証拠を削除しない。復元時は[検証手順](../../docs/PHASE62_DYNAMIC_LOOP_VALIDATION.md)と旧manifestを使い、参照が復元できなければBLOCKED。
- 容量監査：既存HEADの全履歴には50,000,000バイト以上のblobが4件あり、`check_git_blob_sizes.py history --tip HEAD`は既存違反を検出して終了値1。パス・サイズ・blob IDはEXISTING_HISTORY_BLOBSへ保存した。今回の追加ではなく、削除・履歴書換えは行わない。今回の変更/新規ファイルの容量、空のstaged検査、`git diff --check`はFINAL_WORKTREE_CHECKSへ分けて記録する。本検証完了時点ではcommit/push未実施。後続のコミット指示ではstaged容量検査を改めて行い、pushは行わない。
- 途中の14/20成功・6拒否は超高速オフライン消費でplannerが古くなる条件の記録。論理消費側を宣言要求位置で待つ試験へ訂正し、nativeの非同期Frontierは別に独立照合する。途中結果を最終件数へ流用しない。重点最終出力名の重複は開始前拒否であり、旧台帳を上書きしない。

## 残る制約と採用条件

現実装の現在周期変更は、AudioWorkgroupの長い非cache再利用owner（固定周期が96,000出力フレーム超）の範囲。短い先読み済み周期と保護範囲により合法な区間が残らない場合はBへ延期し、speedDeferReasonへ理由を残す。KeepPosition初回の通常ownerは従来のB待ちで、未対応である理由をspeedDeferReasonへ明示する。短Loopの1callback以内を保証しない。全範囲の現在周期対応として公開しない。

Loop手動seekの実採用方式はExact。Interactive/FastLocal要求をLoopで受けた場合もExactへ明示的に再準備し、操作のmode/reasonへ記録する。独立FastLocal位相方式の一般対応を証明したことにしない。追加故障注入・上限到達・全境界状態の網羅、動的履歴保持Clearは別に判定する。今回Clearは固定Exact方式を選択した。

残る実装/検証不足には、KeepPosition初回の通常ownerからの同等の動的プロトコル、commit前に置換された外部要求を含めて終端結果まで保持する有限台帳、上限時の拒否、準備失敗を重ねた全境界状態の検査がある。Clearは追加の独立固定Exact RAWと線形混合式で最終出力を比較した範囲を上記台帳へ分け、動的履歴保持Clearを実装・承認したことにしない。これらが残るため、局所全体の6条件達成とはしない。

長尺のcold prefixはA=0で約0.015秒、A=30で約3.2秒、A=270で約28.86〜28.95秒。一方warmは保存点復元後の区間だけを生成し、A=270の最終14回復元で合計3584出力frameだけを再生成破棄した。warm FFT plan生成は0、worker生成は2。Clear待ち中も自然反復が進むため、最終準備/復元数と計測開始時の4周を混同しない。cold時の0からAまでのExact履歴生成と、毎周期のprefix再生成の退行を区別する。長尺全速度の独立DSP全列や物理loopbackの代わりにはしない。

Merodoaには、LoopContext、LoopSnapshotの要求/動的operation/Map/cycle/B対応、StoppedSpeedOperationのReadyForResume・準備版・停止C、理由付き拒否/再要求、再開意思取消を渡す。受入時は最新IDと入力世代の一致、Resume前Ready、退役完了、実PCM/位置/周回、最大2所有者、callback供給を確認する。Merodoa本体・UI・submoduleは変更しない。

FastLocal長尺の既存失敗、stereo Ready目標、開始時計、Debug期限、主観音質、物理loopback、実TCC/実アプリ統合、一般公開承認は今回の局所結果で閉じない。必須検証が残る間、局所全体GOとしない。

## 2026-10-21 コミット許可後の追記

検証結果の報告後、利用者から今回の変更をコミットする指示を受けた。検証ソース一覧SHAと70ファイルの記録済みSHAが報告時から一致することを確認した。実装ソース・合格条件・既存証拠は変更せず、本追記と差分/容量監査の記録を更新してコミットする。MANIFEST等のHEAD・no stage/commitの記録は検証時点のスナップショットであり、その後の許可を否定するものではない。局所INCOMPLETE/NO-GOと公開フラグは維持する。push・PR作成・履歴書換えは今回の指示へ含めず、実施しない。
