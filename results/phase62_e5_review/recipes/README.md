# e5レビュー修正の再現

対象はTimeStretchLabのみ。作業時HEADはmain@e5dc91675723b7163b10cc3ea2323710033caeaaで、コードの識別にはSOURCE_MANIFESTとSOURCE_DELTAを併用する。commit/pushは行わない。

実行先は `build/phase62_e5_review_20261021_01`。大きなRAW/WAV/trace・実行体・全ログ・過去失敗はこのGit管理外ディレクトリに保存する。既存出力先がある場合、各recipeは停止する。再実行時は新しい一意な作業先を選び、BASE/出力引数を変更する。既存証拠を消して再使用しない。

1. `verify_references.py --output build/<unique>/REFERENCE_VERIFIED.json` で保存参照を照合する。復元は `results/phase59/FROZEN_REFERENCE.json`、`results/phase62_finish/references/` のmanifest、および `docs/PHASE62_DYNAMIC_LOOP_VALIDATION.md` の既存手順に従う。変更後DSPから再生成しない。
2. `build_review.py --build build/<unique>/candidate_build --output build/<unique>/BUILD_REVIEW.json` でRelease/arm64をビルドする。失敗後の旧binaryを使用しない。保存SOURCEとbinary SHAを各試験のbuild-provenanceへ渡す。
3. `scripts/phase62_review_validation.py` でA/B、D02〜D06/D09〜D11の36program/202checksを実行する。入力は既存mix.wavと事前宣言した240ms/1秒/120秒のfixture。生成レシピ・SHAは作業先inputsとBASELINE_EXPECTED、各EXPECTEDに記録する。
4. `scripts/phase62_finish_validation.py`、`scripts/phase62_finish_control_validation.py`、通常API独立参照driverでPlaying74、制御42、cache12、API16、Paused/Clear24、Race各8を実行する。今回の成功子184は実行時source795ddのまま保存し、最終差分の28実行体・依存一致を別証明した。最終ソースで新規に全群を実行する場合、この限定再利用は不要である。
5. `run_final_pipeline.py` は今回作業先の部分混合6件再実行・限定同一性証明・Release/Debug各20CTest・offline9群・native5群を直列実行する。復元された今回の履歴証拠を使うrecipeなので、初回から再現する場合は同ファイル内の各コマンドを新しい作業先へ実行する。Release aliasは既存canonical buildへ、Debug aliasはstrict buildへ向ける。aliasでconfigureしない。
6. 全PCM/oracle driverには既存のNumPy付きPython 3.12を用いる。今回の絶対位置はENVIRONMENTと各EXPECTEDを参照する。既定Python 3.14のNumPy欠落をDSP差分へ読み替えない。
7. 各子の最終統計・必須ID一意一致・終了0・timeoutなし・source/binary不変を確認してから `assemble_review.py` で小さい索引を生成する。復旧前のnative失敗は履歴としてINCOMPLETEを保持し、全必須群がPASSでなければ局所GOは生成しない。

`verify_native_equivalence.py` はBUILD04→05の検証器変更だけの歴史的な限定証明、`certify_final_review.py` はBUILD04/06→07の部分混合試験変更も含む限定証明である。以前の同一性証明のキー名 `all_30_binaries_identical` は誤記で、実際に全件比較したRelease一覧は29点。最終証明は29点中28点不変、残る部分混合実行体1点は6本再実行と明記した。旧証明と実行済recipe本文は作業先 `executed_recipes/` に保持し、件数訂正を成功実施件数の変更に用いない。

実音声・性能測定は1担当が直列実行する。通常側ゲートや故障注入を正常RT承認へ加算しない。実機装置buffer変更はguardで復元し、窓の取り逃し・復元失敗はPASSにしない。独立DSP、planner、Map、RAW、境界数式、最終ゲイン、位置/周回、heap/owner/供給、正常期限を分けて判定する。

今回の集計は以下。保存先が既存なら停止するため、再現時は一意な作業先へ変更する。`assemble_review.py` は既存のMANIFESTを上書きしない。

```sh
PHASE62_PYTHON=/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$PHASE62_PYTHON results/phase62_e5_review/recipes/verify_references.py --output build/<unique>/REFERENCE_VERIFIED.json
$PHASE62_PYTHON results/phase62_e5_review/recipes/audit_baseline.py
$PHASE62_PYTHON results/phase62_e5_review/recipes/run_cache_baseline_repro.py
$PHASE62_PYTHON results/phase62_e5_review/recipes/assemble_review.py --native-run native_final_v2
```

`run_cache_baseline_repro.py` は旧cache競合を観測する隔離比較版を作る。旧依存104件のSHAを保存内容へ一致させ、実行前にsnapshot/source/binary/input/driverを固定する。旧PartialMix/Fault2件の未復元はこのtargetの依存外と記録し、純e5版や独立DSP参照とは呼ばない。両子exit1/FAILで旧A→新BのRejectedを検出した場合だけ、再現用親を「期待した旧不具合の再現成功」とする。失敗した初回configure・当時recipeは保持し、新しいv2作業先で構築後に実行した。当時cache04へ不足した実行時source記録を補記しない。

復旧前のnative_final/v2は同じ最初のcontrol1本が0/3checksで開始待ち失敗。41本の残り40（正常RT8本を含む）はNOT_RUN/BLOCKED。通常再生、標準afplay、旧成功ビルドも開始できず、根本原因は未確定。buffer512へ復元済み。装置回復後はREPORTのコマンドでnative5群を新しい保存先へ実行し、旧失敗を残す。期限や供給判定は変更しない。参照・ソース・実行体・driver不変ならoffline9群の再実行は不要。


## 装置復旧後の索引更新

native_recovered_01は全5群41program・指定正常RT8・外側装置guardがPASS。ソースや実行体は変更していない。履歴55ファイルを先にB/metadata_before_audio_recovery_01/filesへ全byte照合して保存し、history/BEFORE_AUDIO_RECOVERYに対応表を残した。旧MANIFEST/ARTIFACTSもhistoryへ保存し、旧失敗run/親を上書きしない。

```sh
$PHASE62_PYTHON results/phase62_e5_review/recipes/assemble_review.py --native-run native_recovered_01 --refresh-archive results/phase62_e5_review/history/BEFORE_AUDIO_RECOVERY.json --device-recovery-report results/phase62_e5_review/USER_DEVICE_RECOVERY.json
$PHASE62_PYTHON results/phase62_e5_review/recipes/finalize_artifacts.py --refresh-archive results/phase62_e5_review/history/BEFORE_AUDIO_RECOVERY.json
```

この更新は保存済み旧索引とのSHA/byte一致を先に要求する。全41実ID・全exit0・RT8実IDの全PASS・guard復元から局所判定を作り、ARTIFACTSはMANIFESTの判定と残件を使う。seek機能のworker期限1件は旧faにもある観測として別ファイルへ記録し、一般RT承認へ使わない。公開・Merodoa既定採用falseは維持する。
