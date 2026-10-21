# e5dc9167 修正の検証

レビュー基準はe5dc91675723b7163b10cc3ea2323710033caeaa。現行の基準証拠と過去の失敗は保持する。今回の一意な実行先はbuild/phase62_e5_review_20261021_01。実行ソースはCMakeLists.txt、src、tests、scriptsのファイル一覧SHAで識別し、ビルド前後一致・実行体SHAをBUILD_REVIEW記録へ残す。build後のソース変更や失敗後の旧binaryを最終runへ使用しない。

## 注入する機能試験

scripts/phase62_review_validation.pyが実行前に必須program/check ID、コマンド、入力・実行体・driver・ビルド来歴SHAを固定し、全processを直列実行する。終了コード0、完了marker、全IDの一意な完全一致、期待件数、ソース/実行体不変が必要。timeoutや競合窓の取り逃しはPASSとしない。試験設定でDSPや通常制御を止める試験は正常RT期限評価と別枠にする。

- A1: sync後/native CAS前で通常制御だけを止め、取消勝ちと実callback Started勝ちを分ける。
- A2/D09: 全曲240msのdspDone＋未消費FIFO、別に1秒入力の実normal checkpoint permit拒否から、初回Bの旧外部IDと最新要求を追う。
- B/D06: 同一通常ownerに4096個の同値要求を各Duplicate確定まで待って蓄積し、Keep自己反復Ready後の下位LimitReachedと外部Failed/InternalLimitを確認。
- D02/D03: 実planner開始/提案窓、実engineの古い版拒否→Requested、取消/rollback/新受付、cache旧A期限判断後の新B隔離。
- D04: 実装置buffer64/128で0<cursor<Nを観測し、実操作の通常側決定点も確認。全取り逃しを失敗化し、装置bufferを復元する。
- D05/D09/D10/D11: 実join戻り値、checkpoint permit、epoch予約、実準備期限を通す。予約がowner生成前に拒否される場合は退役workerが存在しないことを確認。その他は失敗owner退役を待ち、Pausedでは退役中のPlay拒否と停止Cを確認する。

## 下位試験と不変条件

PHASE62_HISTORY_INVARIANT.mdの対象はLoop ownerだけで、通常速度変更へ一般化しない。履歴512の実下位上限とproposal rollbackを試験する。PHASE62_DESCRIPTOR_INVARIANT.mdは必要な最古と最新公開cycleの距離をFIFO/pending/callback/部分初回/R0/両sourceから導出する。古いcycle不一致を実共通ヘルパーで拒否する。これらをLoop実枯渇・追越し再現とは呼ばない。

## 最終回帰

既存18件を保持し、上記2件を加えた20件をRelease/Debugで実行する。既存のconfigure/build/ctest全6stageも維持する。外部台帳、Playing全12program/74checks、Paused/Clear、通常API独立比較16件、cache、Race、動的640/重点/形式、Exact896/Golden25、固定有限/reuse、境界872およびnative供給/期限の該当既存driverを新binaryで実行する。RAWは旧凍結参照から得て、製品RAWから期待DSPを作らない。

```sh
python3 results/phase62_e5_review/recipes/build_review.py --build build/phase62_e5_review_20261021_01/candidate_build --output build/phase62_e5_review_20261021_01/BUILD_REVIEW_FINAL.json
python3 scripts/phase62_review_validation.py --build build/phase62_e5_review_20261021_01/candidate_build --inputs build/phase62_e5_review_20261021_01/inputs --output build/phase62_e5_review_20261021_01/review_final --build-provenance build/phase62_e5_review_20261021_01/BUILD_REVIEW_FINAL.json
python3 scripts/phase62_gate_runner.py --root . --build-base build/phase62_e5_review_20261021_01/strict_builds --release-build build/phase62_e5_review_20261021_01/candidate_build --output build/phase62_e5_review_20261021_01/strict_final
```

既存のfocused/remaining recipesはruntime/release→candidate_build、runtime/debug→strict_builds/debugの参照用aliasを通して実行する。aliasでビルドはしない。実際のコマンド・SHA・全統計は結果manifestに記録する。全必須項目が閉じるまでは局所INCOMPLETE/NO-GO。公開flags、物理loopback/試聴、Merodoa実統合等の別ゲートは更新しない。


## 最終実行の固定点

最終ソース一覧SHAは `cefdb1294e89cb5280ad8f6df401eac59825212334e4110f958ca6f0d7c0199c`。BUILD_REVIEW_07はRelease/arm64/Apple clang21、FP指定は既存のまま（fast-math追加なし）。RAW比較にはNumPyのある既存Python 3.12を用いる。既定Python 3.14にNumPyがなかったAPI初回16件FAILは保存し、既存runtimeで16件すべて再実行した。

```sh
PHASE62_PYTHON=/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$PHASE62_PYTHON results/phase62_e5_review/recipes/run_final_pipeline.py
```

このrecipeは部分混合6本、実行体同一性の限定証明、Release/Debug各20件、offline9群、native5群を直列実行する。既存の出力先がある場合は上書きせず停止する。再現時は一意な作業先へrecipeのBASEを変更し、既存素材のrestore手順と凍結参照SHA検査を先に行う。個別コマンドは `build/phase62_e5_review_20261021_01/final_pipeline/EXPECTED.json` と各子EXPECTEDに保存する。

最終変更は部分混合試験だけの停止前故障検査と取り逃し記録である。製品コードと他28実行体はBUILD04/06/07で一致する。成功した他の子runは元の実行ソースSHAのまま保持し、`certify_final_review.py` が差分、実行体、driver/importの一致を確認して適用範囲を限定する。失敗した親runや旧APIのFAILを成功へ付け替えない。

部分混合試験は、通常worker解放後に1ms単位で別条件を待っていたため窓を取り逃し、最大8回の再試行に達しない不備を修正した。callbackは止めず直ちに観測し、窓終了・観測期限をMISSED_WINDOWとして保存する。一般の製品Failed/供給/台帳違反は再試行に回さない。全8回未成立はFAIL、合格には実通常側決定点のStartedかつ0<cursor<Nと同じepochの実PCMが必要である。

## 装置復旧前の確定結果と実機の再開（履歴）

制御36program/202checks、限定一致で接続した既存制御184checks、Release/Debug各20CTest、選択したoffline9群はPASS。動的640・重点20・形式46＋8、Exact896/Golden25、固定有限322/reuse322、境界872、独立handoff6を今回実行した。境界872へhandoff6を合算しない。先頭4群の選択外NOT_RUNと全体PASS=falseは原本のまま保持する。

最終native行列は予定41program中、最初の同じcontrol1本を2回試行し、各0/3checks/first callback timeout。残り40本はNOT_RUN/BLOCKED。正常RT8本は41本の内数である。通常再生・標準afplay・旧成功ビルドも開始せず、根本原因は未確定。装置buffer512へ復元済み。局所全体はINCOMPLETE/NO-GOとし、過去の実機統計や故障注入の成功で不足を埋めない。

出力開始の回復後、以下を新しい保存先へ直列実行する。失敗したnative_final/v2は上書きしない。

```sh
PHASE62_PYTHON=/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$PHASE62_PYTHON results/phase62_finish/recipes/run_remaining_gates.py --group native --build-base build/phase62_e5_review_20261021_01/runtime --output build/phase62_e5_review_20261021_01/native_recovered_unique
```

コマンド・入力/参照/実行体/driver SHA、再現・失敗の詳細、残り全IDは [REPORT](../results/phase62_e5_review/REPORT.md)、[MANIFEST](../results/phase62_e5_review/MANIFEST.json)、[NATIVE_BLOCKER](../results/phase62_e5_review/NATIVE_BLOCKER.json) にまとめる。ソース等の不変を確認できればoffline9群の再実行は不要。変更があれば依存範囲の必要ゲートを再評価する。


## 装置復旧後の確定結果

同じ最終ソースcefdb129…・Release29実行体・native使用Release8/Debug1・参照・全41必須ID/元条件を維持してnative_recovered_01を実行。5群41program、指定正常RT8本、装置guard復元が全件PASSした。正常8本は不足/padding、callback確保/解放、callback/worker期限超過0、両Preset実消費4100周を確認。古い失敗親や統計は上書きしていない。既完了のstrict/offlineはソース等不変を確認して保持した。

seek機能試験のworker期限1件は旧faでも存在し、機能PASS/RT承認NOT_ASSESSEDの別観測として残す。採用Interactive/FastLocalの一般対応・seek切替の一般RT・公開承認を閉じない。原本・実コマンド・各SHAと統計はREPORT/GROUP_RESULTS/RECOVERY_PROVENANCE/FUNCTIONAL_DEADLINE_OBSERVATIONに記録する。
