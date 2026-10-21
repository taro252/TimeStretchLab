# Phase62 残件修正の検証

レビュー基準は `c4bdbb44d92a367369e8ecf3c51fd50cb3abed4c`。実装は [設計](PHASE62_REMAINING_DESIGN.md)、実測件数と判定は [REPORT](../results/phase62_finish/REPORT.md) と同ディレクトリのmanifestを参照する。古いrunを新ソースの実施へ数え直さない。

## 環境と実行順

macOS/Accelerate/CoreAudio、arm64のReleaseを中心に使う。Release/Debugは別build。ビルド・重いPCM比較・実出力は直列。各runは未使用の `build/phase62_finish_20261021/` 配下に作り、実行前EXPECTEDへ条件ID・source/binary/input/reference SHAを保存する。既存の出力先を再利用しない。

```sh
python3 -B scripts/phase62_gate_runner.py --root . \
  --build-base build/phase62_finish_20261021 \
  --output build/phase62_finish_20261021/NEW_deterministic
```

決定的試験はconfigure/build/CTestを両構成で実施する。必須18名称の完全一致、JUnitのfailure/error/skipped=0、全6stage、run_complete、ソース不変を検査する。検査途中のSUMMARYはPASSにならない。

追加targetは `python3 -B results/phase62_finish/recipes/build_record.py --build build/NEW/release --output build/NEW/BUILD.json` でビルドする。今回実行したコマンドと保存先はREPORTを参照する。成功時のソース一覧SHA・各binary SHA・compiler/configuration/architecture・ログSHAを `BUILD_ALL_V5.json` の形式で保存する。失敗時に以前のbinaryを使わない。`phase62_finish_validation.py` はこの対応が一致しなければ実行を拒否する。

NumPyを使うoracle driverには今回の実測と同じarm64 Pythonを使う。

```sh
PYTHON=/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$PYTHON -B scripts/phase62_finish_validation.py --suite paused-clear \
  --build build/phase62_finish_20261021/release --input results/phase31/input/mix.wav \
  --output build/phase62_finish_20261021/NEW_paused_clear \
  --build-provenance build/phase62_finish_20261021/BUILD_ALL_V5.json
$PYTHON -B results/phase62_finish/recipes/run_focused_final.py \
  --build-base build/phase62_finish_20261021 \
  --output build/phase62_finish_20261021/NEW_focused \
  --build-provenance build/phase62_finish_20261021/BUILD_ALL_V5.json
$PYTHON -B results/phase62_finish/recipes/run_remaining_gates.py --group offline \
  --build-base build/phase62_finish_20261021 --output build/phase62_finish_20261021/NEW_offline
$PYTHON -B results/phase62_finish/recipes/run_remaining_gates.py --group native \
  --build-base build/phase62_finish_20261021 --output build/phase62_finish_20261021/NEW_native
```

## 試験の役割

| 層 | 実行前の計画 | 比較・合格条件 |
|---|---|---|
| 外部台帳 | 5program、42checks | 実4096受付境界、duplicate、開始済み履歴、上限の副作用なし、拒否理由、全ID終端、最大owner2/停止後0 |
| cache重点 | 12program | 部分cache/全曲非cache/100ms 2倍、実Map95999/96000/96001、保護済みFIFO全prefixと部分PCM、動的採用または理由付き固定B確定 |
| Playing競合 | 12program、74checks | 全receipt、NoOp、commit後置換、必要版のB保持、Clear移管、上限/Stop/別入力/close。close後の公開台帳が取得不能ならINCOMPLETE |
| Paused・初回Clear | 12program、24checks | 初回取消/Started後Clear、旧commitと停止中新準備、手動seek置換、Ready、開始済み未PCM窓。停止C/周回/無出力、旧FIFO破棄の専用監査 |
| 通常APIの独立比較 | 16program | A0/非0A/cold/warm3/部分C/KeepPosition/実Map境界、両Preset。自然Bと次固定全周期まで全列RAW/Map/最終PCM |
| 既存行列 | 各EXPECTEDで固定 | 640動的遷移、重点20、形式40+中点6+追加8、Exact896/Golden25/有限322/reuse322、B680+内部512周期192。強化184は重複加算しない |
| 実出力回帰 | 各EXPECTEDで固定 | Paused/Clear/seek/通常Paused、Release/Debug機能、故障、長尺warm A0/30/270、100ms 2倍4100周を両Preset |

cache重点はDSP位置とFIFO累積位置の低レベル検算であり、それだけで独立DSPや実時間性能のPASSとはしない。`Phase62PcmAudit` も製品RAWを使う境界数式検算であり、独立DSP参照ではない。

通常API hostは製品のhandoffを書き込まない。外部ID/内部操作、入力世代、session/epoch、producer周期/Loop周期、Map版、B、callback累積位置を同じrunで採取する。同一commitの標本で `cumulativeStart + publishedAtCommit - localStart == FIFO write` を確認する。

動的plannerの独立再計算と、実際の計画を独立DSPへ与えたRAWの再現を分ける。次の固定A→Bは固定Exact oracle、最終境界PCMは独立RAWと製品へリンクしない別C++の数式から作る。全bit/全channel/長さ/有限性、窓内/窓外、L_iとΣL_i、周回を照合する。

callback観測はmainMixer前。hostの0.5ゲイン検算は実mixerや実音響の測定ではない。期限・時計・Workgroupは機能判定と分け、物理loopback・試聴・Merodoa実TCCは実施した場合だけ承認する。

## 参照の同一性と復元

動的oracleは旧 `bb22efcbd27f999e8ffe85bbe3f03e20895be3f2` に由来する `build/phase59_frozen/captured_reference`（SHA256 `1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818`）。固定oracleは旧 `ec087019626d9ff0d9f157245729b74ddb6847d7` に由来する `build/phase61/oracle_release_v1/phase61_frozen_reference`（`de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748`）。

復元は既存の `build/phase59_frozen/rebuilt_reference_v3/manifest.json`、`results/phase59/reference_driver_sources/`、`build/phase61/oracle_release_v1/manifest.json`、`scripts/phase59_rebuild_reference.py` / `scripts/phase61_freeze_reference.py` の現行レシピを使用し、元SHAを検査する。manifestの出力先を上書きせず一意のbuild配下へ復元する。製品の修正コードを取り込んで参照を作り直さない。必須原本 `results/phase31/input/mix.wav` が無い場合、そのゲートはBLOCKEDとし別fixtureで代用しない。

## 完全性・失敗の扱い

集計器の36条件（正例1/負例35）と追加10条件を実施し、configureのみ、Debug欠落、0件、重複、skipped/failure、timeout、欠けたchecks、古いbinary、件数不一致、途中終了をPASSへしない。旧schemaは不変の原EXPECTED/ログ/JUnitのSHAに基づく別監査とし、原本に完了マーカーを追加しない。

旧レシピを新buildで再実行する場合、原レシピSHAと適応版SHA、条件だけを読む旧EXPECTEDのSHAを残す。機能checks、観測、周期数を混ぜて一つの成功件数にしない。nativeの機能PASSで実時間期限FAILを隠さない。装置bufferの故障試験には親の復元guardを使用する。

大容量WAV/RAW/trace/logはbuild下へ保持する。Gitには小さい確定summary・ID集合・SHA・実行コマンドと保存場所を残す。未観測や検証不足があれば局所全体NO-GO、能力フラグfalseを維持する。

## 最終Clear修正の再検証と限定再利用

最終ソース一覧SHAは `fa2b6f4fea83e06b4d31433478ae01cae5d98c3465267c990625d4a30a171c8a`。長尺nativeで見つかったClear完了通知の競合を修正したため、決定的Release/Debug、全追加native/API、renderer872条件、既存native全群をこのソースで再実行する。`clearPending=false` を観測した時点で、保持されたResume意思の開始処理が成功済みであることも追加assertで確認する。

直前のソース `958f402ad625d1a9e5c38e210f6afb8c44589dae327f783bb1756051f20fedf2` で完走したDSP5群は、変更3ファイルへの依存がなく、最終buildと実行binaryが全ビット同一であることを確認して再利用する。動的640、重点20、形式46+8、Exact896/Golden25/固定有限322/reuse322が対象。旧runのソース・件数は変更せず、`REUSED_DSP_CERTIFICATE.json` に根拠を保存する。rendererは `run_remaining_gates.py --group renderer` を一意の新出力先で実行し直す。

通常Pausedの故障注入では、Failed公開後のRetiringPreparationを通常workerゲートで固定する。この窓でもPlay拒否・Ready維持・resumePending=falseを要求する。修正前は決定的にFAIL、修正後は21/21制御チェックがPASSした。最終全群でも同じassertを含める。callbackを試験ゲートで停止しない。
