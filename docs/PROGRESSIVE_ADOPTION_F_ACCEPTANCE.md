# Progressive F受入・試聴記入表

作成時のF実アプリ受入は **NOT_RUN**。この表はMerodoa側の受入予定であり、engine方式承認、native単体の機能/RT結果、物理音響、人の評価を分ける。compiled承認表の変更後の最終archive/header/app identityは未確定のため、JSON欄はnullとする。Exact単独のengine承認があってもF全体・Interactive・Loopの承認にはしない。

機械可読台帳は [F_ACCEPTANCE.json](../results/progressive_adoption/F_ACCEPTANCE.json)。同時native実行を避け、実機試験は主担当の専用直列枠で行う。本作成作業では再生・録音・build・大量copyを実施していない。

## 旧素材を使う試聴表

4条件×RAW版/加工後版、計8 WAVの現SHAを限定確認し、旧LISTENING.jsonと一致した。元入力4本とcapture/metrics metadataも現SHAを照合した。旧source一覧SHAは`80e9c59efd5910183a6ac90d346c65dfc10f499ab16eba657fb54c705162e3d9`。`final_v9`品質台帳は旧`final_v8/release/phase62_fix_render_tests`で作られた素材であり、新candidateと呼ばない。

各WAVは旧検証済み第2定常周期を最低10秒へ単純反復し、最終gain相当0.5を一度だけ掛けたFloat32 WAV。時間方向の重なりや無音挿入はない。実アプリの連続出力・実際の操作遅延・物理録音ではない。旧LISTENINGのPASSは素材生成の技術判定で、人の試聴とacoustic captureは未実施だった。短Loopの入力100msと実Mapの出力周期を混同しない。

| 記入ID / 注目点 | 旧条件 | 素材形式・実周期・試聴長 | 聴く内容 | 人の結果 |
|---|---|---|---|---|
| L01 短Loop・低音 | `bass_100ms_2000000_candidate` | 48000Hz / 2ch / 1866f / 10.02975秒 | 低音の脈動、境界音量、周期の伸縮 | NOT_RUN / 未記入 |
| L02 打楽器 | `drums_long_2000000_candidate` | 48000Hz / 2ch / 47545f / 10.89573秒 | アタック、連打、境界直前直後の拍 | NOT_RUN / 未記入 |
| L03 stereo | `stereo_phase_100ms_2000000_candidate` | 48000Hz / 2ch / 2400f / 10.00000秒 | 左右定位、広がり、位相感の揺れ | NOT_RUN / 未記入 |
| L04 実録ピアノ | `piano_real_100ms_2000000_candidate` | 48000Hz / 2ch / 2079f / 10.00519秒 | 打鍵のアタック、余韻、境界の音量 | NOT_RUN / 未記入 |

- **L01**：`/Users/taro252/Docker/TimeStretchLab/build/phase62_fix/run_01/final_v9/listening_pack/bass_100ms_2000000_candidate/processed_gain05.wav`
  - 加工後SHA：`98bcba85c21ba1cbedb4ea881537579971890e8fd1d413cb37376156a9a2d4c0`
  - RAW版SHA：`6e21597f5b4d4803d5eb737ccc4d00b3255372d2b8d09967452d84e9f366ac84`（同dirの`raw_gain05.wav`）

- **L02**：`/Users/taro252/Docker/TimeStretchLab/build/phase62_fix/run_01/final_v9/listening_pack/drums_long_2000000_candidate/processed_gain05.wav`
  - 加工後SHA：`daf11fa55a9c0f2892306fba9dbdf412f0582efd3c90f63193e22f70cc0946cf`
  - RAW版SHA：`ed2fb7bb72d409584797d5ec1c5b81ffee06621e08a9ad5fce5ae2bb90c840c6`（同dirの`raw_gain05.wav`）

- **L03**：`/Users/taro252/Docker/TimeStretchLab/build/phase62_fix/run_01/final_v9/listening_pack/stereo_phase_100ms_2000000_candidate/processed_gain05.wav`
  - 加工後SHA：`bc344e072de6aec1ea1059685565445af26c8c1f53398fcce9681c5970fe7eb5`
  - RAW版SHA：`9bf2e9cf3b1d2e1039bb7f90e895f8af4d22edd8f661166e4207103614229ef5`（同dirの`raw_gain05.wav`）

- **L04**：`/Users/taro252/Docker/TimeStretchLab/build/phase62_fix/run_01/final_v9/piano_listening_pack/piano_real_100ms_2000000_candidate/processed_gain05.wav`
  - 加工後SHA：`72e2dbebe1298ca2e52653a2637a1e8ab001b72b41b1bd92a6378680f936f307`
  - RAW版SHA：`c03e4c66f54ffa84228c911feefc23157118ce6facea7b5b91db2dd3762a3b80`（同dirの`raw_gain05.wav`）

各IDについて、試聴者、日時、装置/ヘッドフォン、音量、RAW/加工後の提示順、反復数、クリック/音量/低音/左右/拍/アタックの観察、判定、実際に再生したWAV SHAを記入する。未記入はnull/NOT_RUN。新candidateのWAVは別ID/C01〜C04とし、この旧教材の合否を転記しない。容量の都合で品質条件や反復を減らさず、音源はGit外のbuildへ保存する。

## 現candidate収録の手順（全て未実施）

本表のF試聴用captureはC01固定Loop、C02異速度、C03Exact seek、C04Clear/再ONを別群にする。別途存在するnative機能/独立PCM結果を否定する意味ではなく、これらの音楽素材・実アプリ・人の試聴用clipが未実施という意味である。

1. 未使用の`B/f_acceptance_RUN/`を予約し、実行前EXPECTEDに最終source/commit、host/app/archive/header/validator SHA、元assetと派生Float32 WAV SHA、入力rate/ch、Preset/速度、A/B/Cの入力frame、実行順・反復・固定ID集合、装置/OS/buffer、capture上限、目標と統計法を固定する。A/Bの秒変換は実rateから求め、端数frameを黙って丸めない。`raw.f32`と`output_before_gain.f32`はgain前である。
2. C01の固定参照は既存de70凍結実行体を明示し、新出力先にだけ全曲RAWとMapを作る。CLIは`FROZEN INPUT SPEED_MICROS PRESET NEW_REF.f32 A_INPUT B_INPUT`。期待binary SHAは`de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`。stdout Mapへ`input_positions=[A,B]`を元commandから追加し、RAW SHA/長さ/rate/chと接続する。候補DSPで期待PCMを作らない。
3. 短いC01の既存capture CLIは`phase62_initial_loop_native INPUT PRESET A_SECONDS DURATION_SECONDS 1 final 3 SPEED NEW_CAPTURE`（final解析、独立した1要求、自然3周期）。または`progressive_adoption_ab_native INPUT PRESET A_SECONDS DURATION_SECONDS SPEED fresh Playing C_SECONDS NEW_CAPTURE`を使い、そのhostの自然2境界条件を3周期実施と呼ばない。両方ともLoop研究用opt-inの単体hostで、製品ApprovedOnlyの未承認Loopを有効化した実アプリ受入にはならない。
4. C01を新`results/progressive_adoption/recipes/validate_capture.py --capture NEW_CAPTURE --input INPUT --host-binary HOST --reference-binary FROZEN --reference-raw NEW_REF.f32 --reference-map MAP --output NEW_AUDIT`で独立全bit/ch/finite/長さ/座標/境界式/混合検証する。固定5checksと最終統計を確認し、性能/RT判定は別保存。source/reference/binaryのSHAは実行前後で一致させる。
5. C02は旧/新speedの固定RAWだけで動的Map区間を代用しない。実要求・実commit frontier・planner/Map node・新旧epoch/source範囲を保存し、bb22由来captured reference（SHA`1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818`）の実Frontier再計算＋独立float32境界/混合式で照合する。C03は各Exact速度のde70全曲RAWから実suffix/Mapを照合し、移行中の旧側もそのepoch固有参照を使う。C04は同速度ClearのB通常継続、異速度Clearの明示固定Exact継続、旧/新混合を別参照に接続する。fixed単一参照用validatorへ異速度全区間を渡してPASSにしない。
6. C02〜C04は既存`phase62_dynamic_seek_native INPUT PRESET NEW_OUT [R0_INPUT_B]`、`phase62_dynamic_controls_native INPUT PRESET NEW_OUT`、`phase62_partial_mix_native clear|replace|stop INPUT PRESET NEW_OUT`を操作/寿命の足場にできるが、これらの全てが試聴に足る連続PCMをexportするわけではない。現F用の前後clip exporterは **未実装/NOT_RUN** として残す。通常threadで事前確保した有限RAW/spansへ、開始250ms前〜完了後1秒を目安に、操作単位で元の時系列を記録する。callbackにログ・確保・I/Oを追加しない。独立参照と対応できないepochや切れた区間を0で埋めずINCOMPLETEとする。
7. RAW/program 96000f、有限span上限・owner2/保存点2を事前計算する。長い3周期などが上限を超える場合は既存hostへ無理に渡さず、通常側へ有限windowを退避できる別収録計画が必要。短く変更して同一条件PASSとはしない。定常10秒の教材化は独立照合済み周期だけの反復と明示し、異速度/seek/Clearの遷移前後は反復・つなぎ直し・無音補完で加工しない。
8. 検証済みgain前clipからWAVへ変換するときだけFloat32で`sample * 0.5`を一度実施する。既存`raw_gain05.wav`/`processed_gain05.wav`へ再度掛けない。normalize、limiter、resample、dither、fadeの追加をしない。WAV/PCM SHA、全frame/ch、nonfiniteと超過peakを記録する。既存`scripts/phase55_study.py::write_wav`を通常側の包装に使えるが、現`listening_pack.py`をそのまま起動すると旧final_v9の固定出力先へ向くため新収録レシピとして実行しない。
9. F実アプリから同一asset/派生PCM/設定で操作し、service・native・UI時刻とidentityを保存する。人の試聴と物理loopbackは別の受入IDに記入し、ソフトウェアRAW一致やnative単体RTで埋めない。

## F必須受入項目

| 固定ID | 確認対象 | 状態 | 実結果/証拠 |
|---|---|---|---|
| F01.native_v3_package | 同時header/binary | NOT_RUN | null |
| F02.product_policy | 製品設定・方式別承認 | NOT_RUN | null |
| F03.serial_control_queue | 専用直列制御queue | NOT_RUN | null |
| F04.real_app_times | 実アプリの時刻とID | NOT_RUN | null |
| F05.sandbox_TCC | Sandbox/TCC/入力lease | NOT_RUN | null |
| F06.input_and_route_recovery | 入力・装置の復旧 | NOT_RUN | null |
| F07.limit_recreation_and_owned_audit | 実上限とengine再作成 | NOT_RUN | null |
| F08.current_candidate_capture | 現candidateの試聴用capture | NOT_RUN | null |
| F09.human_listening | 人の試聴 | NOT_RUN | null |
| F10.normal_RT | 通常実時間 | NOT_RUN | null |
| F11.physical_loopback | 物理loopback | NOT_RUN | null |
| F12.stop_close_lifetime | 停止/closeと監査context | NOT_RUN | null |

**F01.native_v3_package 同時header/binary**：最終TimeStretchLab commit/source・archive SHA・公開header群SHA・アプリbuild/署名/archを保存。contractVersion=3とprepare v3リンクタグを確認。意図した旧header/新archive等の混在がリンク拒否されることも別負試験。

**F02.product_policy 製品設定・方式別承認**：macOSProductのApprovedOnlyを実アプリbridgeから使用。exact/interactive/nativeLoopsのapproved/configured/effective/allowed/reasonを別表示。最終承認表でExactのみ有効ならInteractive/Loopを自動Research化しない。旧包括publicSeekApproved=falseとExact個別trueを両立して読む。ExactはrequestSeek*、InteractiveはrequestInteractiveSeek*を使い分け、旧bool seek APIの包括ゲートをExact有効化の判定に使わない。

**F03.serial_control_queue 専用直列制御queue**：MainActorやcallbackでprepare/request/stop/close/joinを実行しない。専用serial queue名・thread IDと順序を記録。Play/Resume/seek/速度/Clear/再ON/入力切替の最新revisionを照合し、同時native呼出し・UIの同期join待ちを発生させない。

**F04.real_app_times 実アプリの時刻とID**：UI意図→service enqueue→dequeue→native開始/accepted→analysis/FIFO Ready→switch Started→実first PCM→Done→reading生成→MainActor受信→UI反映を同じapp engine/prepare UUID・native engineSerial/inputGeneration/session/renderEpoch/操作IDで結ぶ。HAL推定と物理時刻は別欄。目標と母集団/統計法を事前固定。

**F05.sandbox_TCC Sandbox/TCC/入力lease**：署名したSandbox実アプリで選択許可/拒否/取消/再起動bookmark失効/権限変更を実施。元assetのsecurity scopeと派生Float32 PCM/FDのleaseを全join/最終監査コピー完了まで保持する。chmod模型をTCC成功にしない。

**F06.input_and_route_recovery 入力・装置の復旧**：入力削除/置換/保持FD変更・装置抜去/レート変更から理由付き安全停止。再選択/再prepareと明示再開で復帰し、Pausedを自動Playingにしない。旧callback/完了を新UUIDへ混入させない。

**F07.limit_recreation_and_owned_audit 実上限とengine再作成**：実4096枠LimitReachedで有効FIFOを維持。入力/検査済み派生PCM/速度/C/Loop方針/停止状態/明示再開意思を保存し、Stop→close→全join→receiveFinalOperationAuditを所有コピー→新engine UUID/prepare UUID→prepare→明示復元。ID1の再利用を旧engine ID1と混同しない。

**F08.current_candidate_capture 現candidateの試聴用capture**：後述C01〜C04を最終source/binary/input/reference/validator/scheduleへ固定。RAW/全ch/長さ/finite/Map/混合と適用位相を独立検証し、gain前RAWから一度だけ0.5を掛けたWAVを保存。現F用の異速度/seek/Clear clipは未測定。

**F09.human_listening 人の試聴**：L01〜L04の旧教材と現candidate C01〜C04を別記。listener/実行時刻/device/volume/順序/反復/気づき/合否/試聴したWAV SHAを入力。旧metadataのtechnical PASSを主観承認にしない。

**F10.normal_RT 通常実時間**：最終候補の対応環境でcallback new/C malloc/free、worker/callback期限、欠損/padding/host/sample/HAL/Workgroup、最終joinを実測。正常系は全0、未測定はnull。故障注入と通常系、native単体と実アプリを分離。

**F11.physical_loopback 物理loopback**：実DAC/ADCまたは選定した外部音響測定で出力・入力device/時計/配線/レート/buffer/校正/録音SHAを記録。ソフトウェアtap、gain前RAW一致、HAL推定だけで物理無欠落にしない。起動最初のcallbackも除外しない。

**F12.stop_close_lifetime 停止/closeと監査context**：Playing/Paused/Preparing/採用Started中のStop/close/アプリ終了を専用queueで実施。callback静止、worker全join、最終監査1回配送と全Accepted集合/終端39fields、owner0と最大2/保存点2を確認後にobserver context/FD/security scopeを解放。

復旧時にStop→prepareだけで実4096履歴が消えると仮定しない。`receiveFinalOperationAudit`の借用データは受信中に所有コピーし、最終配送以前にcontext/入力leaseを解放しない。時刻の分布はUI/service/nativeごとに同一操作差分から計算し、native p95をアプリ全体p95へ転記しない。

F受入の判定は実施後に機能ごと記入する。空欄やnullは成功ではない。engine Exact方式承認、旧Golden/Exactの限定再利用、旧Loop教材のSHA確認のいずれも、F・人の音質・通常RT・物理無欠落を一括承認するものではない。


## 最終native素材・監査の追記

最終source `2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392` の固定AB実収録4WAVを `B/current_audition_02` へ用意した。`MANIFEST.json`に各WAV・実収録・独立PCM監査のSHAがある。A30/A270 fresh/prewarmの実callback全出力に設定ゲイン0.5を掛けたもので、リピート/リサンプル/無音追加はない。実装置ゲインや物理連続性を証明しない。Fで該当区間の短い自然周回・進入を確認し、低音/打楽器/stereo・異速度/seek/Clearは上記別項目で実候補を収録する。以前のstage07素材/旧final_v9も履歴として保存した。

通常速度の最終回収は`receiveFinalEpochAudit`の所有コピーも必須。Release/Debugで各300Acceptedを4条件、各56項目を検証したが、実アプリ側のアーカイブ容量/serial queue/UUID/最終Reject=0の受入を代用しない。sinkは通常threadでengine mutex保持中に呼ぶため再入しない。全join/参照解放後の最終`epochAuditConfigured/Calls/Rejected`と期待ID集合を照合する。上のF12項目の人/アプリ実施状態は引き続きNOT_RUN/null。
