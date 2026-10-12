# Phase 42 — 解析密度切替の安全判定と実時間統合準備

> **Phase 43計測訂正（2026-10-13）:** 本報告の長尺 `phase39_sim` における「FIFO不足0」は、FIFOが空なら消費を待つ模擬方式での値であり、実時間再生の証拠にはならない。また、当時の `phase39_sim` はC++割当カウンターを有効化しておらず、上位ブロックの割当0は「未計測」と読む必要がある。従来のワーカーブロック時間はFIFO待ち・書込み・計画などを含む全周期ではない。修正後の実測と10分の絶対時刻模擬試験におけるFIFO不足は [Phase 43 REPORT](../phase43/REPORT.md) を参照。元の測定CSVは履歴として保持する。

## 判定

Phase 41で異音が消えたMIX 0.40→2.00倍速の遅延密度切替を回帰基準に固定した。研究用の `safe-density` モードでは、TimeMap、各解像度の実際の解析カーソル、将来の合成ホップ、Hann²の重ね合わせ重み、イベント保護、公開済みPCMとDSP確定境界を照合して解析密度の切替位置を決める。Phase 39/40の既定モードと、正式Experimental 3500、Phase 30/36プレイヤー、キャッシュ・シークには変更を加えていない。

MIXとDrumsの0.40→2.00はPhase 41遅延切替raw WAVとバイト一致した。ユーザーはPhase 42のMIX・Drums・Vocal・Guitar・Bassの両方向試聴をすべて確認し、「違和感はなさそう」と評価した。これは対象クリップに関する聴感結果であり、macOS実機再生や全ての未知音源の品質保証ではない。

**正式macOS再生経路への統合と製品採用は保留する。** 研究用模擬コールバックは良好だが、ワーカーの長い壁時計停止の発生源をまだ確定できないため、実時間性能のリスクが残る。

## 安全な解析密度の選択

- Low/Mid/HighのFFT窓長は8,192／4,096／1,024。通常解析ホップは2,048／1,024／256、半解析ホップ（フレーム密度は2倍）では1,024／512／128サンプル。
- 低速から通常密度へ戻す候補はTimeMapの遷移完了以降、高速から半密度へ増やす候補は遷移開始以降とする。イベントの保護区間（開始前2フレーム、終了後5フレーム）を避ける。
- 候補が各解像度の最後の処理済み入力より未来で、出力側の変更禁止境界より未来であることを確認する。前回の密度切替が未処理の場合は、新たな密度変更を拒否する。過去フレームへの追加はしない。
- 実際の次解析位置から各解像度の解析フレーム列を先読みし、TimeMap上の合成ホップが正かつ窓長未満であることを確認する。既存PhaseVocoderは前フレームとの**実解析距離**を位相伝播に渡す。位相・OLA・FIRを再初期化しない。
- 周期Hann窓の二乗和を出力サンプルごとに計算し、TimeMap遷移開始から密度切替後の窓1枚分まで、全解像度で最低0.15を要求する。候補はMidの1,024入力サンプル間隔で探索し、安全位置が見つからなければ要求を `NoSafeInterval` として拒否する。0.15は研究用の保守的な閾値であり、聴感を代替しない。
- 入力FIFO16,384、先行上限12,288、DSPブロック2,048の既定BCDを維持する。音声コールバックはFIFO読み出しだけで、ガードの計算はDSPワーカーで行う。

実装は [`Phase42DensityGuard.cpp`](../../src/prototype/Phase42DensityGuard.cpp) と研究用 [`Phase39PlaybackPipeline.cpp`](../../src/prototype/Phase39PlaybackPipeline.cpp)。従来の `normal`／`delay-density` は再現比較のため残した。独立参照は保存した `density_input` を使い、同じTimeMapと解析密度履歴で再合成する。

## 双方向・複数回切替

[`validation.csv`](validation.csv) にMIXの10方向と5つの複数回スケジュール、Drumsの10方向、Vocal/Guitar/Bassの各2方向を記録した。合計31条件で、研究用逐次出力と独立オフライン参照は**31/31でWAVバイト一致**、速度要求時点のFIFO公開済みPCM接頭部も**31/31で全サンプル一致**した。すべての出力は有限で、出力長とEOSは各TimeMapに一致した。単独の固定0.40／2.00については、MIX・Drums・Vocal・Guitar・Bassの既存Phase 39固定参照とも一致した。

MIX・Drumsの0.40→2.00は [`Phase 41の遅延切替参照`](../phase41/REPORT.md) と各1/1でバイト一致し、以前ユーザーが聞いたMIX約3秒の異音を再導入していない。従来方式C、高速方式Bの固定参照、Phase 41の診断WAVは変更していない。

解析密度を実際に変更した23要求では、ガードが評価した合成ホップ最大値はLow 3,840、Mid 1,920、High 480サンプルで、それぞれの窓長未満だった。連続ホップ間の最大変化はLow 2,775、Mid 1,387、High 347サンプル。Hann²重みの記録最小値は各解像度0.603で、設定した下限0.15を超えた。局所速度の評価範囲は0.267〜4.000倍であり、要求速度そのものより広い。これはTimeMapのイベント保護と補償による瞬間値で、聴感上の自然さを保証しない。Drums 2.00→0.40ではイベント保護と重み条件により候補を12箇所調べてから密度を変えた。安全性を優先した適用延期として記録し、応答性への影響を評価する。各要求の座標・試行数・窓重みは [`plans/`](plans/) にある。

## 音質の客観検証と試聴

[`acoustics.csv`](acoustics.csv) に切替周辺の10ms RMS包絡、短時間スペクトル変動、最大波形微分、局所最大ピークの位置・3dB幅、直前20msと直後20msのエネルギー比、L/R相関、Side/Mid、左右の位相差の二乗平均、有限値を記録した。局所最大ピークが必ず速度変更そのもののアタックとは限らないため、測定値は異常検出の補助とし、自然さを数値だけで順位付けしない。0.40→2.00のMIX・DrumsはPhase 41 rawと完全に同じため、同レポートのアタック4件、余韻、定位の診断がそのまま適用できる。Phase 37方式Bの固定高速TimeMapとDSP処理には手を加えていない。

比較クリップは [`audition/`](audition/) に、全音源・全方式に共通の**固定ゲイン0.40**で保存した。音源ごとのピーク正規化・LUFS補正は行わず、raw DSPデータは [`raw/`](raw/) に別保存した。MIX・Drumsの0.40→2.00／2.00→0.40と、Vocal・Guitar・Bassの両方向を優先試聴した。ユーザーは全ファイルを確認し、違和感はなさそうと回答した。

## 模擬コールバック・長尺ワーカー

[`paced/summary.csv`](paced/summary.csv) に最終ビルドの34条件を記録した。MIX・Drumsの両方向で64／128／256／512／1,024フレーム要求、各実音源で70%のCPU競合、MIXとDrumsの競合条件の反復を含む。**34/34で正しいEOS**、FIFO不足0、書き込み拒否0、コールバック期限超過0だった。最大コールバック処理時間は0.078ms、ワーカー最大壁時計時間は92.6ms、最大RSSは17.1MiB。要求から適用音声の模擬コールバック到達までの遅延は中央値576.7ms、p95は1,608ms、最大1,618.9ms。模擬実行の成功をmacOS実機のリアルタイム安全性の証明とは扱わない。

3／5／10分のMIX・Drums、通常／CPU競合、診断ON/OFF、反復の計20条件を最終ビルドで再測定した。すべてEOSに到達し、FIFO不足・書き込み拒否・コールバック期限超過は0だった。計測値は [`profiles/summary.csv`](profiles/summary.csv) と診断ON時の上位20ブロックに保存した。ワーカーブロックの最大壁時計時間は301.8ms（Drums 3分、高負荷・診断OFF）、最大スレッドCPU時間は39.6ms。各試験のp95最大は30.7ms、p99最大は35.5ms、100ms超のブロックは合計8件。最大コールバック時間は0.808ms、最大RSSは22.9MiB、TimeMap計画CPU時間の最大は6.97msだった。診断ON時の最悪例では、同一ブロックの壁時計175.7ms、CPU19.5msで、壁時計の超過は主に位相処理とIFFT/OLA区間で観測された。このブロックのFIFO待ちとC++ `new` は0で、WAV読込は壁時計8.9ms／CPU0.5msだった。FIFO書き込み待ちや診断mutex待ちだけでは説明できず、スケジューリング停止など外部要因の可能性がある。ただし停止時のOSスレッド状態を直接採取していないため、**原因は未確定**であり、以前の188〜704ms停止が解消したとは判断しない。

20条件の内訳は、MIX・Drumsの3／5／10分を通常負荷・診断ON/OFFで各1回、3分をCPU競合・診断ON/OFFで各2回である。高CPU負荷の5／10分反復は未実施である。

System Traceを使う場合は次の形でDSPワーカーを追跡する。スレッドの実行中／待機中を確認し、Time Profilerの演算スタックと段別の壁時計・CPU記録を照合する。Trace自体は端末固有の大容量診断ファイルとしてGit管理しない。

```sh
xcrun xctrace record --template 'System Trace' \
  --output results/phase42/profiles/mix_3m_system.trace --launch -- \
  build/phase39_sim results/phase14/benchmark/mix_repeat_180.wav - \
  0.4 1.0:2.0 512 results/phase42/profiles/mix_3m_system_plan.csv \
  2048 C safe-density
```

## 回帰と統合判定

Phase 12／28の固定Goldenは [`golden_audit.csv`](golden_audit.csv) のとおり**25/25で保存済みSHA-256およびPhase 36コピーと一致**した。正式Phase 5.3 Experimental 3500、Phase 30/36、Phase 18/19のキャッシュ・シーク、Phase 10.1の処理には変更を加えていない。Phase 34低速BとPhase 37高速Bの既定処理も変更していない。

最終ビルドで `ctest --test-dir build --output-on-failure -j4` を実行し、追加の `phase42_safe_density` を含む**49/49件が成功**した（実時間307.98秒）。

結論として研究用の双方向密度ガードは有力だが、**正式macOSプレイヤーへの統合は未承認**。次の条件は、長尺ワーカー停止のSystem Traceによる原因の切り分け、実機でのFIFO・期限と試聴、イベント密集時の拒否／延期の実測、切替前後のアタック保持である。

## 再現手順

```sh
cmake -S . -B build
cmake --build build -j4
ctest --test-dir build --output-on-failure -j4
python3 scripts/phase42_golden_audit.py
# 以下のNumPyを使うスクリプトは、NumPyを導入したPython環境で実行する
"/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" scripts/phase42_validate.py
"/Users/taro252/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" scripts/phase42_acoustics.py
python3 scripts/phase42_paced.py
python3 scripts/phase42_profile.py
```

研究コードは実験用であり、正式のmacOS再生経路には接続していない。
