"""Render the audited measurements into the Japanese handoff report."""
import json,statistics as st,re
from pathlib import Path
from phase55_study import ROOT
O=ROOT/'results/phase57';v=json.loads((O/'VERDICT.json').read_text());assert v['verdict']=='A'
p=json.loads((O/'performance_statistics.json').read_text());matrix=json.loads((O/'matrix_summary.json').read_text())
release=(O/'ctest_deterministic.log').read_text();debug=(O/'ctest_debug.log').read_text()
time=lambda t:re.search(r'Total Test time \(real\) =\s+([\d.]+) sec',t).group(1)
s=f'''# Phase 57：増分DSP合成と全PCM完全一致検証

## 判定

**A：固定速度・オフラインの増分DSP合成は完全成立。Phase 58の実時間統合検証へ進める。**

全161速度・全8形式・Candidate/Baselineの短尺試験、代表9速度の3分/5分試験、複数チャンク条件で、変更前DSPとの全PCMを生ビット比較した。主たる正確性試験は**{v['exact_pcm_sessions']:,}セッション**。EOS通知前に正しいPCMを公開できた実行は{v['non_eos_pcm_sessions']:,}件。性能CSVでも、最初の公開時点で未受信の入力が実際に残っていたことを確認した。

このAは固定速度・オフラインの成立である。実FIFO、AVAudioEngine、再生中の速度変更、実時間CPU競合、callback期限、可聴開始、Merodoa/iOSは未実装・未検証。`realtime_verified=false`を維持し、Phase54の保存済み実時間FAILを合格へ変えない。

## 1. 基準・参照・保護

開始はmain、HEAD `ec087019626d9ff0d9f157245729b74ddb6847d7`、作業ツリーはクリーン。Phase55依存関係/設計/REPORT、Phase56設計/引継ぎ/REPORT/VERDICT、Phase53/54品質・Golden・アプリ契約を確認した。

共通化前のPhase36/39へリンクして`build/phase57_frozen/reference`を固定した。SHA-256は`{v['reference_binary_sha256']}`。各suiteは入力SHA、参照バイナリSHA、実験バイナリSHA、速度、preset、形式、出力長とraw PCM SHAを記録する。原則はraw float32 DSP出力を比較し、デバイス変換と出力ゲイン0.5を含めない。

計測項目を追加した参照は、基準Gitの元Phase36ソースを別オブジェクトとしてコンパイルし、既存archiveより先にリンクした`reference_timing`。Debugも同じ方法で`reference_debug`を固定した。元ソースSHAとリンク結果は`frozen_timing_reference.log`、`frozen_debug_reference.log`。変更後の従来入口と計測用参照は、それぞれ全8形式×代表7速度×両preset＝112件で変更前PCMと全バイト一致（`legacy_equivalence/`、`timing_equivalence/`）。新方式と変更後のコードだけを比較した証拠ではない。

保護監査は**{v['protected_files']:,}/{v['protected_files']:,}ファイル一致、Golden WAV 30/30一致**。`phase53-handoff`タグも固定値のまま。既存ファイルの変更例外はCMakeとPhase36内部共通化の2件だけで、Phase53〜56の結果・Golden・公開APIを変更していない。

## 2. 実装と変更ファイル

| ファイル | 役割 |
| --- | --- |
| `src/prototype/Phase36SynthesisCore.h` | 既存の解像度別合成・FIR・補助処理を共通化。品質算術を再実装しない |
| `src/prototype/Phase36StreamingSpeedEngine.cpp` | 共通部品を使い、従来の全曲入口と出力ループを維持 |
| `src/prototype/Phase57ProgressiveSynthesis.h/.cpp` | 確定snapshotの補給、継続DSP、事前確認、待機、生成/公開境界、終端管理 |
| `src/prototype/Phase57PinnedInput.h` | FD寿命と同一性検証、解析とDSPの独立pread reader |
| `src/prototype/Phase57Reference.cpp` | 変更前DSPのraw参照、別の計測用参照 |
| `src/prototype/Phase57Check.cpp` | 全サンプル比較、SHA、待機中の不変性、時刻/境界/CPU/所有量の記録 |
| `tests/Phase57Tests.cpp` / `Phase57Smoke.py` | 状態・故障・並行要求・入力切替・PCM統合試験 |
| `scripts/phase57_*.py` | 段階試験、逐次実行、共通化照合、Golden、保護監査、集計 |
| `CMakeLists.txt` | 独立実験targetと専用CTestの追加 |

内部APIは`ProgressiveSynthesisEngine`の`supplySnapshot`、`advance`、`cancel`、`fail`、`frontier`。1 producer・再入不可。要求速度は100万倍の整数で指定し、Phase56へその1速度だけを要求する。未要求の速度を同時構築しない。速度間のTimeMap/PCM補間も行わない。

**機械可読の`product_path_modified=true`は、既存Phase36内部を共通部品へ移したことを表す。** 製品API・ゲイン・FIFO・先行量・品質の変更や、増分経路の製品接続を意味しない。製品の最終リンクにPhase57/Phase56実験ライブラリが入らないことも検査した。実装共通化の数値回帰は上の独立参照とGoldenで確認した。

設計と安全境界は[増分合成設計](../../docs/PHASE57_PROGRESSIVE_SYNTHESIS.md)、比較方式は[PCM完全一致](../../docs/PHASE57_PCM_EXACTNESS.md)、次段階は[実時間引継ぎ](../../docs/PHASE57_REALTIME_HANDOFF.md)。

## 3. 状態継続と公開境界

Low/Mid/Highの位相、前回入力/出力位置、共有ピーク・位相差、OLAの信号と重み、FIRのブロック位置と蓄積を同じインスタンスに保持する。チャンク末尾でreset/flushしない。既存と同じ算術・順番で全PCMを生成し、入力不足をEOSや0埋めへ変換しない。

次の2,048出力フレームについて、FIRが必要とする変換ブロック全体と、各解像度のFFT入力窓・補間node・reset対象event・OLAへの将来寄与を処理前に確認する。条件が揃わなければ位相・OLA・FIRを動かさず待つ。map境界が同じ解析待ちでは照会も繰り返さない。Phase55の16,384フレーム切戻しを一般的な安全境界に流用していない。

EOSでは既知WAV全長と最終解析の入力数を照合する。完成mapから従来どおりの最終出力長を求め、最後の短いFIRブロックとpaddingを一度だけ処理する。全期間の出力長を単純なL/speedへ置き換えない。sinkは成功した公開ブロックだけを受け取り、後続解析で書き戻さない。生成済みと公開済みの量を分け、直前cancelやsink例外で生成済みだけが進んだ場合はsessionを破棄する。

## 4. 完全一致の実施結果

| 群 | 入力数 | 参照条件 | 全PCM一致セッション | 参照拒否条件 |
| --- | ---: | ---: | ---: | ---: |
'''
labels={'stage1_final':'Stage 1・代表7速度','stage2':'Stage 2・全161速度','long':'Stage 3・長尺9速度','natural':'既存自然音源7速度','rejections':'既存拒否の対照'}
for r in matrix:s+=f"| {labels[r['suite']]} | {r['inputs']} | {r['reference_cases']:,} | {r['exact_pcm_sessions']:,} | {r['matched_rejection_cases']} |\n"
s+='''
Stage 1は全8形式×6種類の素材。境界素材は4秒、他は0.5秒で全7チャンク条件。Stage 2は全8形式×6種類、各0.25秒の別fixtureを全161速度・両preset・1 Mid/5,003/不規則の3条件で照合した。4秒素材では128 Midでも複数チャンクを通し、hop境界直前/直後とEOS直前の過渡音を含む。

長尺はPCM16 Stereo 44.1kHzの3分人工反復と、Float32 Mono 48kHzの5分連鎖。0.40/0.41/0.50/0.99/1.00/1.01/1.50/1.99/2.00、両preset、128 Midを実施し、3分素材の0.50/1.00/2.00には32 Midと5,003も追加した。**長尺の全161速度・全8形式は未実施**。短尺の網羅と混同しない。

自然音源は既存MIX/Drums/Vocal/Bass/Guitarの各10秒抜粋。3分/5分は自然な長尺別楽曲の網羅ではない。生成レシピ、入力SHA、全条件は各manifestに保存した。

全サンプルのuint32生ビット、チャンネル順、出力数、全PCM SHAが一致した。各公開prefixを全曲参照とその場で照合し、真のEOSまで照合を続ける。待機の再呼出しで入力位置・OLA・FIR source・公開量が変わらないことも検査する。中間だけ/最終だけの一致やSHAだけでは主たる正確性PASSにしない。

既存Phase37が拒否する曲頭インパルス（入力3,001サンプル目、48kHz Mono Float32）では2.00倍の最初の圧縮アンカーが負位置になる。両preset・全7チャンクで同じ拒否を確認し、正常PCM件数へ加えていない。同じ入力の0.50倍は正常に全PCM一致し、使わない2.00倍の失敗で妨げられない。

'''
s+=f"性能入力にも別途**{v['performance_full_bit_validation_sessions']}セッションの全サンプル比較**を実施した。性能計測{v['performance_sessions']}実行は時間内の全サンプル走査を省き、出力数・SHAを検査した。これらを主行列の全サンプル一致件数へ重複加算しない。\n\n"
s+='''## 5. 異常系と失敗履歴

単体試験は解析待ち/入力不足、世代・未要求速度・境界逆行、未完了解析の仮EOS、EOS重複、解析側エラー、DSP/sink例外、予算不足、公開直前の別スレッドcancel、正常完了後のcancel、古いsnapshot保持、同一入力の並行要求、別入力への切替、ファイル置換/切詰め/読取り失敗を扱う。cancel/失敗を正常EOSへ変換しない。

初期共通化では非inline補助関数の重複シンボルでリンクに失敗し、共有headerのinline関数へ修正した（`build_check.log`）。数値を緩めて通した失敗ではない。

途中の異常系点検で、解析側cancelを受理した後に古い通常snapshotが届くと再開できる余地を確認した。回帰テストで再現FAILを保存し（`ctest_cancel_repro.log`）、終端を保持して後続通知を拒否するよう修正した。`ctest_cancel_guard.log`で修正確認後、主行列を最終版で最初から再実行した。中断した19,866セッションと修正前のStage 1は開発記録として保持し、最終件数へ加算しない。キャンセル以外の通常PCM比較には不一致がなかった。

## 6. 性能と早期生成

macOS arm64、Release、`-O3 -DNDEBUG`。すべての重い試験を逐次実行し、性能測定は他のDSP検証完了後に単独実行した。各条件5回・独立プロセス。OSファイルcacheはpurgeせず、CPU周波数や温度も固定していない。異なるpresetの測定群に見られる時間差を、品質や固有の処理コストの差へ一般化しない。検証済みWAVの形式・長さ受付後、解析構築/解析開始前を起点とする。初回の全内容SHA-256は別費用で、今回省略できたと主張しない。

全曲Aと増分Bの双方でsinkのインターリーブ化・SHAを含める。Bの解析CPUは入力読取/同一性確認/解析、DSP側CPUは事前照会/合成/公開sinkを含む。総wallの解析完了時刻には逐次実験で途中に実行したDSPも含まれ、純粋な解析CPUとは分ける。

'''
for suite,label in [('performance','長尺・32/128 Mid'),('performance_chunks','既存10秒MIX・全7チャンク')]:
    s+=f'### {label}\n\n| 入力 / preset / チャンク | A最初のPCM ms | B最初のPCM ms | A先行量 ms | B先行量 ms | A総CPU ms | B総CPU ms | CPU増減 |\n| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n'
    for r in p:
        if r['suite']!=suite:continue
        a=r['whole'];b=r['progressive'];m=lambda d,k:d[k]['median']*1000
        s+=f"| {r['input']} / {r['preset']} / {r['chunk']} | {m(a,'first_published_s'):,.3f} | {m(b,'first_published_s'):,.3f} | {m(a,'lead_ready_s'):,.3f} | {m(b,'lead_ready_s'):,.3f} | {m(a,'cpu_s'):,.3f} | {m(b,'cpu_s'):,.3f} | {r['cpu_increase_percent']:+.2f}% |\n"
    s+='\n'
s+='''### 長尺の総時間とメモリ

| 入力 / preset / チャンク | A総wall ms | B総wall ms | A Peak RSS MiB | B Peak RSS MiB | B snapshot Peak MiB |
| --- | ---: | ---: | ---: | ---: | ---: |
'''
for r in p:
    if r['suite']!='performance':continue
    a=r['whole'];b=r['progressive'];s+=f"| {r['input']} / {r['preset']} / {r['chunk']} | {a['wall_s']['median']*1000:,.3f} | {b['wall_s']['median']*1000:,.3f} | {a['peak_rss_bytes']['median']/2**20:.3f} | {b['peak_rss_bytes']['median']/2**20:.3f} | {b['snapshot_peak_bytes']['median']/2**20:.3f} |\n"
s+='\nMiBは2²⁰bytes。Aは従来のresult/診断集計、Bは新しい前線統計も含む各経路全体の比較であり、FFT単体の性能差ではない。\n\n'
s+='''最大値・母標準偏差、解析/DSP別CPU、総wall、最初のevent/map/生成/公開、先行量相当、解析完了、Peak RSS、snapshot所有量とコピー量、各チャンクの時間・進行境界は`performance_statistics.json`と各CSVに保存した。待機時間は、必要データ不足を返してから次の解析通知/EOSで再開するまでのオフライン経過であり、実時間スレッドの待機・期限測定ではない。

'''
for r in p:
    if r['suite']=='performance' and r['input']=='mix_290s' and r['preset']=='candidate':
        f=r['frontiers'][0];b=r['progressive'];s+=f"290秒MIX Candidate・{r['chunk']}では、解析CPU中央値{b['analysis_cpu_s']['median']*1000:.3f}ms、DSP側CPU中央値{b['dsp_cpu_s']['median']*1000:.3f}ms、最初の生成中央値{b['first_generated_s']['median']*1000:.3f}ms。最初のPCM公開時の受信量は{f['input_frames_at_first_pcm']:,}入力フレーム。全入力受信前に{f['pcm_before_all_input_received']:,}PCMフレームを公開した。先行量相当に到達した時点の受信量も{f['input_frames_at_lead']:,}で、未受信の入力が残っていた。最初の公開時刻中央値{b['first_published_s']['median']*1000:.3f}ms、解析完了時刻中央値{b['analysis_done_s']['median']*1000:.3f}ms。\n\n"
s+='''5分の連鎖では全条件でEOS前PCMは0。全区間を仮mapで進めず、最初のPCMも先行量相当もEOS解析後になった。通常素材での早期生成を全素材・固定時間以内の保証へ広げない。

DSP作業領域は予算上8MiBと保守的に見積もり、最新snapshot1個を保持する。8MiBを一括確保する実装ではなく、FFT内部確保やallocator全体を含む厳密上限でもない。Peak RSS、snapshot計数所有量、DSPの予算見積りを別々に読む。小チャンクのCPU・コピー増加、多数session全体の予算も残る。先行量相当の到達は実FIFO蓄積・デバイス再生・可聴開始の実証ではない。

## 7. ビルドと既存回帰

'''
s+=f'''- Release全targetビルド成功、決定論的CTest **82/82、{time(release)}秒**。重い試験の同時実行を避け、`-j1`で実行した。Phase56増分解析とPhase54 cache/seekを含む。
- Debug関連CTest **6/6、{time(debug)}秒**。さらに基準ソースの独立Debug DSPと36セッションで全PCM一致。Debug/Releaseの構成間一致を主張した試験ではない。
- 更新した既存製品経路のGolden **25/25**でraw PCM SHA・出力数が一致。Goldenファイル全体SHAも30/30維持。
- 公開API、FIFO、先行量、2,048生成ブロック、ゲイン0.5、Phase53-handoff、Phase53〜56結果を維持。既存実時間FAILは消していない。

## 8. Phase 58へ進む条件と残るリスク

固定速度の増分合成の基盤としてPhase58へ進める。次を引き継ぐ。

- 再生中速度変更のL1/L2/safe-density、Latest-Wins、位相・OLA・FIRへの速度履歴補給は未実装。
- 実FIFOとworkerの背圧、解析/DSPのCPU競合、callback期限、装置変更、可聴遅延は未検証。内部共通化の数値回帰は通ったが実時間負荷は別に検証する。
- 現入力adapterは既知WAV・単一producer用。Phase58で別worker化する際はFD検証とPhase56へのfailInput通知を分離し、解析producerへ失敗をキューで伝える。現adapterをそのまま並行使用しない。
- 全内容識別と完成解析cacheの契約は残る。部分結果を完成cacheへ登録しない。同一音源の自動flight共有、多数sessionの総予算は未実装。
- 長尺全161速度・全8形式、自然な長尺楽曲の広い網羅、他CPU/OSは未検証。任意の長い連鎖では早期公開できない。
- sinkの借用PCMを次の呼出しまで保持せず、所有側へコピーする。終端後は古い通知で再開しない。workerを停止してからDSP・解析・入力を解放する。

## 9. 再実行

各出力先は新規にする。固定参照は共通化前の基準DSPで用意する。入力WAVと一時raw PCM、実行ファイルは既存のGit除外規則を使い、レシピとSHAは保存する。

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_OSX_ARCHITECTURES=arm64 -DTIMESTRETCH_ENABLE_REALTIME_TESTS=OFF
cmake --build build -j3
python3 -B scripts/phase57_study.py --suite stage1 --output results/phase57/stage1_new
python3 -B scripts/phase57_study.py --suite stage2 --prerequisite results/phase57/stage1_new/summary.json --output results/phase57/stage2_new
python3 -B scripts/phase57_study.py --suite long --output results/phase57/long_new
python3 -B scripts/phase57_study.py --suite natural --output results/phase57/natural_new
ctest --test-dir build -L deterministic --output-on-failure -j1
```

`phase57_frozen_core.py`は保存した基準ソースを検査し、変更前DSPオブジェクトを既存archiveより先にリンクする。新規作業コピーでは基準Gitからソースを復元できる。`--build build --destination build/phase57_frozen/reference_rebuilt`で作成し、試験へ`--reference build/phase57_frozen/reference_rebuilt`を渡す。保存済み参照は上書きしない。`phase57_pipeline.py`は段階と回帰・性能を逐次実行し、失敗時に停止する。最終の`phase57_summary.py`は実ファイルSHA・行列・全結果・回帰を検査してからVERDICTを生成する。
'''
(O/'REPORT.md').write_text(s)
print('Phase57 report generated from audited measurements')
