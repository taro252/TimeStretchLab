# Phase 12 正式音質基準：Experimental 3500

## 採用判断と適用範囲

ユーザーの4方式ブラインド試聴と別曲での試聴に基づき、**Phase 5.3 Experimental 3500 Hz** を今後の製品版に向けた正式な音質基準とする。Phase 5.3 High は従来基準、Experimental 2500 Hz は保存済み比較候補として残す。Phase 9C、Phase 10、Phase 10.1 のコードと成果物も保存する。Phase 10.1 の過渡音モードは音質基準に含めない。

この文書は**音質目標の固定**であり、既存CLIや `StretchConfig` の既定モードを切り替える実装ではない。現行の `QualityMode::High` 既定値は維持し、基準の出力は必ず `--quality experimental` を明示して作る。新しい位相制御やクロスオーバー探索は行わない。

## 信号処理の固定値

| 項目 | 採用値 |
| --- | --- |
| Low | FFT 8192、解析ホップ2048 |
| Mid | FFT 4096、解析ホップ1024 |
| High | FFT 1024、解析ホップ256 |
| 窓と再構成 | 周期Hannを解析・合成に使用、OLAは窓の二乗和で正規化 |
| 共通時間軸 | Midのイベント検出・時間写像をLow/Mid/Highで共有し、各解析位置に補間 |
| 合成 | `high + LP250(low−mid) + LP3500(mid−high)` |
| 低域FIR | Blackman窓付き対称2049タップ、250 Hz、4096点FFT畳み込み |
| 高域FIR | Blackman窓付き対称513タップ、3500 Hz、4096点FFT畳み込み |
| 位相 | 瞬時周波数による伝播、ピーク領域への位相ロックON、低振幅binの状態リセット |
| 過渡音 | 検出・イベント統合・適応時間写像・精密アンカー・従来の全bin位相リセットをON |
| ステレオ | 左右でイベント時刻とピーク領域を共有し、StereoPhaseCoherenceをON |
| 出力 | 速度 `s` に対し `round(inputFrames / s)` フレーム、入力と同じサンプルレート・チャンネル数、32-bit float WAV |

採用プロファイルの追加固定値は、ステレオ整合強度1.0、低域整合強度0.5、過渡音感度3.0、最小スペクトル変化量0.02、リセット強度閾値0.25、検出履歴12フレーム、検出後の休止2フレーム、候補の遡り1フレーム、イベント最小間隔4フレーム、減衰後続の統合範囲12フレーム、前肩2フレーム、後肩5フレーム。これらは今回のゴールデンで使用した現行実装の値であり、将来変更する場合は新しい基準版とハッシュを作る。

`enableSelectivePhaseReset`、Partial Tracking、PVSOLA、Phase 9Cのsinusoidal/residual処理はOFF。現行CLIでは `--phase-locking on --transient on --adaptive-time-map on --precise-anchoring on --stereo-coherence on --quality experimental --low-crossover-hz 250 --high-crossover-hz 3500 --chunked on --chunk-size 16384` を固定する。速度だけを0.50／0.75／1.00に変更する。1.00倍は現行オフライン実装の**サンプル単位のunity bypass**であり、3解像度を通過した音の品質検証にはならない。

## ゴールデン参照

基準WAVと全長SHA-256は [`results/phase12/golden/manifest.csv`](results/phase12/golden/manifest.csv)、構成と実行環境は [`baseline.json`](results/phase12/golden/baseline.json) に固定した。DSP本来の無加工float WAVは `results/phase12/golden/raw/`、使用した入力のコピーは `results/phase12/golden/input/` に保存した。**rawのゴールデンWAVへ試聴用の音量補正は一切適用していない。** 試聴用は別の `audition/` と [`audition_manifest.csv`](results/phase12/golden/audition_manifest.csv) に分離する。MIX／Vocal／Bassは既存Phase 5.3比較の45秒区間、Drums／GuitarはPhase 10.1比較の10秒区間を再利用する。

これらの実音源区間では精密アンカーはONでも採用位置が0件だったため、別に既存の人工クリック列0.50倍を**補助回帰**として固定した。19件のイベントすべてで精密アンカーが適用され、WAVとハッシュは [`anchor_diagnostic.json`](results/phase12/golden/anchor_diagnostic.json) に記録した。これは5種類の実音源による聴感基準とは分けて扱う。

比較に使うときは入力ハッシュ、ビルドのコード版、速度、出力長を先に照合し、波形差、過渡音、定位、聴感を順に確認する。SHA-256の完全一致は同じmacOS arm64、Releaseビルド、Apple Accelerate、同じDSPコードでの回帰基準。別OS・CPU・FFT実装での浮動小数点の末尾差は、最大サンプル差や帯域別指標で別途評価する。ハッシュ差だけを音質不合格としない。

この参照のコード版は `276bed754bcfe8c7b0f617e63e1f18b88d48e299`、`build/timestretch` のSHA-256は `d27dfe5ddf1dbc05c9ee96c756e3894be132eabff4e0475287318c413f734500`。ゴールデンの作成・検証手順は [`scripts/phase12_golden.py`](scripts/phase12_golden.py)、試聴コピーは [`scripts/phase12_audition.py`](scripts/phase12_audition.py)、補助クリックは [`scripts/phase12_anchor_diagnostic.py`](scripts/phase12_anchor_diagnostic.py)。通常実行は既存ファイルのハッシュ検証だけを行い、明示的な `--force` 指定時に再生成する。

WAVファイルは現在の `.gitignore` で除外されるため**ローカル作業領域に保持**し、Gitでは仕様、生成スクリプト、ハッシュ付きmanifestを管理する。別ホストや新規チェックアウトへ参照を移す際は、WAV本体と入力コピーをハッシュ確認付きで別途保管・転送する必要がある。

## 変更禁止と品質ゲート

Phase 12では新しいリアルタイムDSPを実装しない。今後の実装は独立した経路で進め、Experimental 3500のオフラインコードと15本のゴールデン出力を変更しない。Phase 10.1の全binリセット、局所時間写像、伸張債務返済、アンカー補正を、音質悪化の要因が未分離のまま製品経路へ持ち込まない。リアルタイム化の差分、リスク、検証順は [`PHASE12_REALTIME_PLAN.md`](PHASE12_REALTIME_PLAN.md) に記す。
