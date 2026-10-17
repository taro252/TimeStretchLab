"""全必須試験の終了後に、未観測を成功に変えず最終報告を作る。"""
import json
import re
import shutil
from pathlib import Path
from phase59_fix2_start_state import ROOT, OUT


def read(name):return json.loads((OUT/name).read_text())


def main():
    queue=read('COMPLETION_QUEUE.json');assert queue['stage']=='required_regressions_completed'
    quality=read('validation_final/summary.json');checks=read('checks_final/summary.json')
    device=read('device_final/summary.json');history=device['history']
    eos=read('eos_final/summary.json');audit=read('GIT_DELIVERY_AUDIT.json')
    assert quality['PASS'] and checks['PASS'] and audit['PASS']
    dynamic=[r for r in history if r['name'].startswith('dynamic_')]
    short=[r for r in history if r['name'].startswith('fixed_') and not r['name'].startswith('fixed_long_')]
    long=read('device_final/fixed_long_rows.json')
    native_eos=[r for r in history if r['name'].startswith('eos_repeat_')]
    legacy=read('legacy_final/summary.json');same=read('legacy_same_rate/summary.json')
    minimal=read('minimal_initial/summary.json');minimal_long=read('minimal_long/summary.json')
    startup=read('startup_cde/summary.json');startup_final=read('startup_cde_final/summary.json')
    wg=read('workgroup_minimal/summary.json');deep=read('legacy_deep/summary.json')
    deep_analysis=read('LEGACY_DEEP_ANALYSIS.json');inventory=read('ARTIFACT_INDEX.json')
    clock=read('TRACE_ANALYSIS_minimal_launch.json');rt=read('REALTIME_WORKER_TRACE.json')
    initial_legacy=read('legacy_investigation/summary.json')
    dynamic_n=sum(r['result']['sessions'] for r in dynamic);dynamic_pass=sum(r['result']['passed'] for r in dynamic)
    full_native=sum(r['result']['full_pcm_sessions'] for r in dynamic);prefix_native=sum(r['result']['prefix_sessions'] for r in dynamic)
    short_n=sum(r['result']['executions'] for r in short);short_pass=sum(r['result']['passed'] for r in short)
    eos_n=sum(r['result']['sessions'] for r in native_eos);eos_pass=sum(r['result']['passed'] for r in native_eos)
    assert dynamic_n==190 and short_n==36 and len(long)==8 and eos_n==40 and legacy['sessions']==12
    assert quality['dynamic_pcm_sessions']==1140 and quality['fixed58_pcm_sessions']==6216 and quality['fixed57_pcm_sessions']==51344
    def boolpass(summary):
        if 'PASS' in summary:return bool(summary['PASS'])
        return summary['passed']==summary['sessions']
    fixed_pass=short_pass==36 and all(r['PASS'] for r in long)
    eos_strict=all(r['functional_pass'] and r['interval_deadline_pass'] and (r['mode']=='normal' or r['realtime_cpp_new_pass']) for r in eos['modes'])
    eos_ok=eos_pass==40 and bool(eos['functional_pass']) and all(
        s['summary']['joins']==s['summary']['leaves']==s['summary']['restores']=='1'
        and s['summary']['active']=='0' and s['summary']['old_request_rejected']=='1'
        and s['summary']['terminal_operations']=='1' for m in eos['modes'] for s in m['sessions'])
    verdict=dict(minimal_sourcenode_test_implemented=True,startup_clock_root_cause_identified=False,
        startup_clock_verified=False,mid_playback_clock_root_cause_identified=False,
        os_client_overload_investigated=True,timestamp_discontinuity_classified=False,
        physical_audio_continuity_verified=False,legacy_fifo_root_cause_identified=False,
        legacy_fifo_regression_passed=False,eos_restart_verified=eos_ok,realtime_memory_investigated=True,
        os_trace_coverage_complete=False,dynamic_pcm_bit_exact=True,fixed_pcm_bit_exact=True,
        all_161_speeds_supported=True,latest_wins_verified=True,l1_l2_safe_density_verified=True,
        dynamic_native_passed=dynamic_pass==190,fixed_native_passed=fixed_pass,
        legacy_native_passed=bool(legacy['PASS']),fifo_underrun_free=False,
        callback_deadline_verified=False,workgroup_deadline_verified=False,
        golden_pass=len(checks['golden'])==25 and all(r['PASS'] for r in checks['golden']),
        git_blob_limit_verified=True,historical_failures_preserved=True,gate_2_passed=False,
        gate_3_ready=False,product_integration_ready=False,merodoa_changed=False)
    assert all(type(v) is bool for v in verdict.values())
    (OUT/'VERDICT.json').write_text(json.dumps(verdict,indent=2)+'\n')
    scope=dict(completion='B：条件付き成立、Gate 2未合格',
        dynamic_native_passed='今回の正式190件だけ。過去の189/190、原因未特定を取り消さない。',
        legacy_native_passed='今回の正式12件だけ。初期36件・別ビルド・追加48kHzの失敗を取り消さない。',
        legacy_fifo_regression_passed='現行診断版を含むPhase内の不足が残るためfalse。',
        timestamp_discontinuity_classified='C/D等の挙動分類はできたが、正当な時計切替・不具合・測定不良の最終分類は未成立。',
        callback_deadline_verified='本体の実測判定とOS/HALの全期限証明を区別。OS欠測と過去Client Overloadが残る。',
        workgroup_deadline_verified='個別試験の計数を参照。全EOSストレス/OS状態の包括的な証明は未成立。',
        eos_restart_verified='実機40件と合成12セッションのEOS機能・世代分離・Workgroup寿命を確認。期限超過の有無は別に判定する。',
        os_trace_coverage_complete='旧worker・過去初回・一部EOSのOS欠測と物理loopback未実施。',
        git_blob_limit_verified='実indexと一時提案index、ローカルorigin/main..HEAD検査。実Push時の最新広告ref検査は別。')
    (OUT/'VERDICT_SCOPE.json').write_text(json.dumps(scope,ensure_ascii=False,indent=2)+'\n')
    trace_rows=[]
    for p in sorted(OUT.glob('*TRACE_ANALYSIS_*.json')):
        if p.name.startswith('LEGACY_') and not p.stem.endswith('_reviewed'):continue
        if p.name=='TRACE_ANALYSIS_dynamic_no_request.json':continue
        d=json.loads(p.read_text());c=d.get('callbacks',0);known=d.get('fully_observed_callbacks',d.get('fully_observed',0))
        worker=f"{d['fully_observed_workers']}/{d['workers']}" if 'workers' in d else '—'
        trace_rows.append(f"|{p.stem}|{known}/{c}|{worker}|{d.get('first_three_callback_coverage',d.get('first_three_fully_observed'))}|")
    dynamic_rows='\n'.join(f"|{r['name']}|{r['result']['passed']}/{r['result']['sessions']}|" for r in dynamic)
    release_log=Path(next(r['log'] for r in checks['history'] if r['name']=='release_deterministic')).read_text()
    debug_log=Path(next(r['log'] for r in checks['history'] if r['name']=='debug_related')).read_text()
    counts=lambda text:re.search(r'0 tests failed out of (\d+)',text).group(1)
    report=f'''# TimeStretchLab Phase 59 Fix 2 結果

判定：**B（条件付き成立）、Gate 2未合格**。PCM品質は維持したが、時計不連続・旧製品供給停止の根本原因と、実時間安全性の全観測が未成立。Phase60 / Gate3 / Merodoa統合は実施していない。コミット・Pushはしていない。

## 1. 初回時計異常の原因

未特定。過去の0→1192、0→1436、0→1160を保存。最終Fixの0→1160は要求512、余分648で、FIFO正常・PCM一致・速度変更要求前。Mach橋渡し誤差0.75µsを含めても、最初の2 callbackと記録された合成advanceは重ならない。次合成は2回目出口の22.425959ms後だった。解析/制御/Workgroup/OS全体の除外ではない。`INITIAL_CLOCK_DSP_WINDOW.json`参照。

## 2. SourceNode単体実験

A直接PCM/B通常FIFOは{minimal['passed']}/{minimal['sessions']}、追加の自分の音声を30秒停止後A・A90秒・B90秒は{minimal_long['passed']}/{minimal_long['sessions']}。全OSのidleは未計測。初回異常の非再現からDSPを原因と決めない。C固定/D要求なし/E要求ありは{startup['passed']}/{startup['sessions']}、最終診断欄の代表再確認は{startup_final['passed']}/{startup_final['sessions']}。Workgroup有無だけを切り替えた追加実験は{wg['passed']}/{wg['sessions']}で、普通のBとは別集計。

## 3. AVAudioEngine / HAL時刻

raw Mach ticks、flags、sample/host、rateScalar、要求数、入口/出口、FIFO cursor、論理位置、制御イベントを記録。無効flagsを成功から除外せず別計数。sample進行と返却PCM量は別である。Aのlaunchではtrace epochがprocess entryより前、最初の3 callbackをOS観測できた。旧製品のlaunch/通知同期では先頭が欠測する試験もあり、通知後待機を加えた最終記録も実coverageで判定した。親Python timebase1/1とarm64側125/3を区別する。

|最終解析資料|OS既知callback / 全数|OS既知worker / 公開周期|最初の3 callback|
|---|---:|---:|---|
{chr(10).join(trace_rows)}

Apple契約・A〜H分類は[時計調査](../../docs/PHASE59_FIX2_CLOCK_FORENSICS.md)。挙動C/D等は区別できるが、正当なHAL切替という最終分類は未成立。独立loopbackなし、物理音声の連続性は未検証。

最終6回目は先頭active callbackがtrace epochの1.520994666秒後に入ったが、先頭3回に一意なIOProc対応がなく未観測。819 callback中371、218公開周期中98だけをOS既知とした。旧製品CSVのcallback thread IDがない窓を別threadへ推定接続しない。A285/D113では出力AU通知のhost/sample/要求数とSource実行窓も一致したが、物理出力の証明ではない。

JSON Native経路377実行の139221 callback行ではhost/sample flags無効0。rateScalar保存34767行は0.9999577960420503〜1.0、残る104454行は未保存で1を補完しない。旧製品TXT経路は別集計。最終CDE各112行の状態IDは制御マーカーと全件一致し、初期D traceのnominal ID1とは区別した。

## 4. 途中再生Client Overload

依頼書の6ではなく原本989−471=**518余分フレーム**。遅い入口は8015→8016の21.92775ms、その次の8016→8017がhost22.415625ms / 実入口11.17525ms。clientの11.206833ms BlockedとOS Client Overloadを確認したが、異常待機中のsyscall・dtsecurity状態が欠測。通常HAL待機も約10.5msあるためBlocked全量を原因と断定しない。Decompress11.792µsだけで11ms待機を説明しない。

原本SHA照合後のコピーからHALサーバーを抽出し、2.962437秒・2.973586秒に0フレームのWrite Safety Violation、約0.33秒間隔の装置zero timestampに大きなanchor切替がないことを確認。過負荷の原因・正当な時計切替・可聴連続性の証明にはならない。`MIDPLAY_HAL_REVIEW.json`参照。

## 5. 旧製品FIFO不足

旧Candidate1319、旧Baseline8208、最終Baseline234の原本を維持。今回の初期比較は{initial_legacy['passed']}/{initial_legacy['sessions']}、合計不足{initial_legacy['missing_frames']}。旧原本Candidate時計異常、旧原本Baseline8016不足、現行診断Candidate2482不足を別に保存した。現行の次公開間隔160.745667ms、次周期CPU36.679ms、publish入口到達前に不足開始。ただしpublish入口はDSP計算完了点ではなく、外側入力確認・Seek suffix処理がその前にある。解釈訂正を`LEGACY_MARKER_INTERPRETATION.json`に保存。

正式最終比較{legacy['passed']}/{legacy['sessions']}、追加48kHz比較{same['passed']}/{same['sessions']}、深い別ビルド{deep['passed']}/{deep['sessions']}。深い記録はPCM sink、入力確認、公開、待機、書込みを分離し、Mach標本はworker寿命内・取得成功だけ採用。詳細は`LEGACY_DEEP_ANALYSIS.json`と[旧FIFO調査](../../docs/PHASE59_FIX2_LEGACY_FIFO.md)。旧数学版のtraceでも2918不足があり、失敗worker周期は欠測。新経路との独立原因も未証明。

正式最終のFAILは旧原本smoke Candidate、1290不足。session1/epoch1/callback127〜129で470/121、471/0、470/0を返した。時計不連続0・測定PASS・受信PCM PASSでも、ゼロ埋めを含む音声品質はFAIL。以前の1319とは別試験として保存する。現行の深い6試験と最終traceでは不足が起きず、そこでの入力確認最大0.06975msから初期失敗の原因を推定しない。

## 6. EOS再始動

実音声周期の正式実機は{eos_pass}/{eos_n}。Release/Debugの通常・周期付き・高速排出は`eos_final/summary.json`に別集計し、機能成功={str(bool(eos['functional_pass'])).lower()}、全モード期限込み成功={str(eos_strict).lower()}。以前の約4.8秒非CPU時間、app復元前のOS降格、Debug待機を取消していない。Workgroup生成/昇格/join/leave/復元ticksを追加し、原閾値を維持した。高速排出を実機周期試験として扱わない。

今回の期限超過はRelease周期付き0、高速6、Debug周期付き44、高速172。通常policy排出では実時間blockなし。高速排出でapp離脱前のpolicy2以外の標本をRelease1316/Debug7860取得し、昇格直後2/97から1/0への変化を確認した。Mach橋渡しの実測幅210〜461nsでjoin/leave内に収まる標本だけ使う。最悪非CPU残差は232.512ms/456.166msで、連続OS状態・降格理由・過去4.8秒の全因果は未解明。`EOS_FINAL_SCHEDULER_REVIEW.json`参照。

## 7. メモリ・ページフォルト

要求なし動的traceの{rt['fully_observed']}/{rt['intervals']}実時間合成区間と113/113 callback本体をOS照合し、合成区間内VM観測{rt['realtime_interval_fault_observations']}。worker準備中のVMは別集計。診断/captureの領域を登録し、準備時にwrite-touchしたが、圧縮復帰の禁止やAccelerate内部/全scratchの全帰属は未成立。旧PhaseLocker Zero Fillの領域帰属、全実機・全EOSのOS状態は未観測を残す。全領域mlockなし。

## 8. 実施した修正

独立SourceNode/FIFO再現器、有界raw時計/FIFO cursor、制御/退役worker履歴、Workgroup寿命ticks、診断領域の準備時write-touchを追加。未公開/重複profileをOS既知周期に数える解析を修正し、旧解析を残して`*_reviewed.json`へ再集計した。旧製品の生成後確認は別ビルドだけで深く観測。時計補正・初回除外・閾値緩和・FIFO拡大・推測policy修正は適用していない。

Experimental3500、161速度、50ms遷移、Latest-Wins、L1/L2/Phase50/safe-density、STFT/位相/過渡/OLA/FIR、浮動小数点順序、生ビット、gain0.5を維持。最適化済み6ソースSHAは旧Fixと同じ。

## 9. 変更前後の比較

|項目|Phase59 Fix|Fix2正式最終|
|---|---:|---:|
|動的実機|189/190|{dynamic_pass}/{dynamic_n}|
|旧製品実機|11/12|{legacy['passed']}/{legacy['sessions']}|
|固定短尺|36/36|{short_pass}/{short_n}|
|固定長尺|8/8|{sum(r['PASS'] for r in long)}/{len(long)}|
|実機EOS|40/40|{eos_pass}/{eos_n}|

最終候補SHAは`FINAL_CANDIDATE.json`、旧原本は`START_STATE.json`と`PROTECTED_REFERENCES.json`。追加成功で以前のFAILを置換していない。診断追加の実行体と旧原本/旧数学版は区別する。

## 10. 動的PCM完全一致

**1140/1140**。隣接の全161速度往復640/640を含む。Latest-Wins・L1/L2/Phase50/safe-density・Map/Snapshot・chunk/formatを既存条件のまま比較。Float32全生ビット・長さ・順序・SHAが独立参照と一致。161²の全初期/目標ペア網羅を意味しない。`validation_final/summary.json`とdriver各manifest参照。

## 11. 固定PCM完全一致

Phase58 **6216/6216**、Phase57 **51344/51344**。Phase57は入力形式で分割したが、PCM比較・参照・品質条件を変更していない。失敗PCMは残し、成功時の作業用PCMだけ生成レシピ/SHAを残して再利用する。Phase56増分解析はCTestを含む既存回帰で確認。

## 12. 実機検証

動的の全曲PCM比較は{full_native}件、意図的なStop/Cancel/Route等のprefix比較は{prefix_native}件。prefix一致を全曲完走と呼ばない。

|動的suite|PASS / 全数|
|---|---:|
{dynamic_rows}

固定短尺{short_pass}/{short_n}、固定長尺{sum(r['PASS'] for r in long)}/8、EOS{eos_pass}/40、旧製品{legacy['passed']}/12。追加単体・CDE・同形式・Workgroup・別ビルド・OS付き試験は正式件数へ混ぜない。今回の全FAILは`FINAL_MEASUREMENTS.json`に抽出し、raw logs/capture/traceを管理外保存した。FIFO不足、拒否、callback/HAL/host/sample/DSP期限、PCM、世代、newを各元summaryで評価。全OSフォルト0とは言っていない。

## 13. CTest・Golden

Release deterministic **{counts(release_log)}/{counts(release_log)}**、Debug関連 **{counts(debug_log)}/{counts(debug_log)}**、Golden **25/25**。競合検査TSan2件、ASan/UBSan4件、時計/欠測解析6件、Git容量ガード試験が成功。追加の供給解釈3件も成功し、寿命外標本の誤採用と生成済み状態の逆推論を防ぐ。Phase54 cache/seek、39/42/50/51、EOS/Cancel、所有権を既存回帰で維持。Debug全CTestを実行したという意味ではない。全コマンドと終了値は`checks_final` / `SUPPLY_ANALYSIS_TESTS.json`。

## 14. ディスク容量

開始空き{read('START_STATE.json')['free_bytes']:,} bytes、最終index作成時空き{inventory['free_bytes']:,} bytes。今回保存証拠{inventory['total_bytes']:,} bytes。trace予算改訂もV1/V2/V3を保存し、累積16GiB・同時4GiB・空き下限8GiBを維持。元のFAIL/Golden/固定参照を削除していない。

大きなWAV/PCM/XML/trace/バイナリは`build/phase59_fix2_artifacts`。`ARTIFACT_INDEX.json`から全ファイルmanifestのSHA・サイズ・保存場所・レシピ・復元方法を参照する。提案Git blobは50,000,000 bytes未満、実index不変、既存pre-commit/pre-push有効。ローカルの送信予定履歴も検査したが、Pushは未実施。最新広告refの検査は実Push時に必要。

## 15. 未解決問題

初回時計の機序、途中Client Overloadの待機先/因果、旧FIFO停止の最終原因、新旧経路の原因独立性、過去EOS非CPU時間/降格、全領域のVM帰属と全OS coverage、物理音響出力の連続性。未観測は正常に補完しない。

## 16. Gate 2最終判定

**B：条件付き成立。Gate 2未合格。** PCM品質は成立。反復成功によって原因解明を代替していない。`VERDICT.json`は全項目boolean、個々の適用範囲は`VERDICT_SCOPE.json`に記録。Gate3 ready / product integration ready / Merodoa changedはfalse。

## 17. 次の作業

保存した不足時の生成後確認区間とOS待機先を対応付ける。初回異常が起きたその試験で、開始前からのclient/HAL/workerの完全なOS記録を取得する。独立loopbackで物理出力を測定する。結果から初めて必要な起動制御/供給修正を選び、元の期限とPCM契約で再検証する。Phase60・Merodoa統合には進まない。
'''
    (OUT/'REPORT.md').write_text(report)
    print('報告書・boolean verdict作成：B、Gate2未合格')


if __name__=='__main__':main()
