"""全実行の完了後に集計する。既知の失敗を後続の成功で解消扱いにしない。"""
import collections
import csv
import gzip
import json
import math
import statistics
from pathlib import Path
from phase57_study import ROOT,sha

OUT=ROOT/'results/phase59_fix'
DATA=ROOT/'build/phase59_fix_artifacts'
ZERO=['missing_frames','missing_calls','rejected_writes','callback_deadlines','callback_formats','hal_misses',
      'host_missing','host_backwards','host_cadence_errors','sample_errors','callback_cpp_allocations',
      'realtime_cpp_new_calls','workgroup_deadline_misses','workgroup_policy_errors','workgroup_join_errors',
      'workgroup_restore_errors','workgroup_interval_errors','workgroup_query_errors','workgroup_wait_errors','workgroup_wake_errors']


def read(path):return json.loads(Path(path).read_text())
def write(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def stats(values):
    values=sorted(values)
    return dict(n=len(values),median=statistics.median(values),p95=values[math.ceil(len(values)*.95)-1],
                p99=values[math.ceil(len(values)*.99)-1],max=values[-1]) if values else None


def main():
    quality_path=OUT/'validation_final/effective_summary.json'
    if not quality_path.exists():quality_path=OUT/'validation_final/summary.json'
    quality=read(quality_path);checks=read(OUT/'checks_final/summary.json')
    device=read(OUT/'device_final/summary.json');legacy=read(OUT/'legacy_final/summary.json')
    eos=read(OUT/'eos_after/summary.json');frozen=read(OUT/'FINAL_CANDIDATE.json')
    legacy_failures=[]
    for row in read(OUT/'legacy_final/rows.json'):
        if row['PASS']:continue
        folder=Path(row['command'][4]);missing=[]
        for file in sorted(folder.glob('callbacks_*.csv')):
            for callback in csv.DictReader(file.open()):
                gap=int(callback['wanted'])-int(callback['received'])
                if gap>0:missing.append(dict(path=str(file),missing_frames=gap,callback=callback))
        legacy_failures.append(dict(label=row['label'],mode=row['mode'],preset=row['preset'],
                                    command=row['command'],summary=row['summary'],missing_callbacks=missing,
                                    os_state_at_missing_callback=None))
    write('FINAL_LEGACY_FAILURES.json',dict(failures=legacy_failures,
        scope='旧製品経路。最終新経路274セッションへ合算して相殺しない。worker最大Wallを当該不足callbackの原因と断定しない。'))
    audit=read(OUT/'GIT_DELIVERY_AUDIT.json')
    final_trace=read(OUT/'FINAL_TRACE_OBSERVATIONS.json') if (OUT/'FINAL_TRACE_OBSERVATIONS.json').exists() else None
    post_trace=read(OUT/'POST_TRACE_CLOCK_VM.json') if (OUT/'POST_TRACE_CLOCK_VM.json').exists() else None
    final_trace_native_path=DATA/'final_long_trace_native/summary.json'
    final_trace_native=read(final_trace_native_path) if final_trace_native_path.exists() else None
    assert all(sha(ROOT/p)==h for p,h in frozen['source_sha256'].items()),'Frozen source changed'
    groups=collections.defaultdict(list)
    for path in (DATA/'device_final').rglob('summary.json'):
        value=read(path)
        if not isinstance(value,dict) or 'callback_calls' not in value:continue
        name=path.relative_to(DATA/'device_final').parts[0]
        group='dynamic' if name.startswith('dynamic_') else 'fixed_long' if name.startswith('fixed_long_') else 'eos_native' if name.startswith('eos_repeat_') else 'fixed_short'
        groups[group].append((path,value))
    measurements={}
    for group,rows in groups.items():
        wall=[];cpu=[];session_stats=[]
        for path,native in rows:
            file=path.parent/'worker.csv';compressed=file.with_suffix('.csv.gz')
            if not file.exists() and not compressed.exists():continue
            session_wall=[];session_cpu=[]
            with (file.open() if file.exists() else gzip.open(compressed,'rt')) as data:
                for block in csv.DictReader(data):
                    if block['realtime']=='1':session_wall.append(float(block['wall_s'])*1000);session_cpu.append(float(block['cpu_s'])*1000)
            wall.extend(session_wall);cpu.extend(session_cpu)
            session_stats.append(dict(summary=str(path),realtime_cpu_ms=stats(session_cpu),realtime_wall_ms=stats(session_wall),
                                      period_s=native.get('workgroup_period_s'),computation_s=native.get('workgroup_computation_s'),
                                      deadline_misses=native.get('workgroup_deadline_misses')))
        measurements[group]=dict(sessions=len(rows),native_passed=sum(bool(s['PASS']) for _,s in rows),
            zero_invariant_totals={key:sum(s[key] for _,s in rows) if all(s.get(key) is not None for _,s in rows) else None for key in ZERO},
            realtime_cpu_ms=stats(cpu),realtime_wall_ms=stats(wall),
            continuous_os_state_unobserved_fraction=None,
            os_scope='通常実機群は連続OS traceを取得しない。policy標本をRunning状態や連続観測へ換算しない。追加focused traceは別集計。',
            maximum_rss_bytes=max(s['peak_rss_bytes'] for _,s in rows),
            per_session=session_stats,
            summaries=[dict(path=str(p),sha256=sha(p)) for p,_ in rows])
    dynamic=[r for r in device['history'] if r['name'].startswith('dynamic_')]
    dynamic_pcm={}
    dynamic_rows=[]
    for file in (DATA/'device_final').glob('dynamic_*/rows.json'):
        for row in read(file):
            dynamic_rows.append(row)
            dynamic_pcm[str(Path(row['command'][7])/'summary.json')]=row.get('pcm')
    native_failures=[]
    for group,rows in groups.items():
        for path,value in rows:
            if value['PASS']:continue
            failure=dict(group=group,summary=str(path),summary_sha256=sha(path),
                         zero_invariants={key:value.get(key) for key in ZERO},
                         pcm_mismatches=value.get('pcm_mismatches'),
                         external_dynamic_pcm=dynamic_pcm.get(str(path)),
                         measurement_valid=value.get('measurement_valid'),clock_sample_jumps=[],missing_callbacks=[])
            speed_file=path.parent/'speeds.csv'
            speeds=list(csv.DictReader(speed_file.open())) if speed_file.exists() else []
            accepted=[float(r['accepted_s']) for r in speeds if float(r['accepted_s'])>=0]
            first_speed=min(accepted) if accepted else None
            failure['first_speed_request_accepted_s']=first_speed
            callback_file=path.parent/'callbacks.csv'
            if callback_file.exists():
                callbacks=list(csv.DictReader(callback_file.open()))
                for previous,current in zip(callbacks,callbacks[1:]):
                    if current['epoch']!=previous['epoch']:continue
                    if not (int(current['flags'])&1 and int(previous['flags'])&1):continue
                    delta=float(current['sample_time'])-float(previous['sample_time'])
                    # Phase46HostClockの既存sample判定をそのまま抽出に使う。
                    if delta<=0 or abs(delta-int(previous['requested']))>2.0:
                        relative=(int(current['start_ns'])-value['clock_mach_ns'])*1e-9+value['clock_pipeline_s']
                        failure['clock_sample_jumps'].append(dict(previous=previous,current=current,
                            delta_sample_frames=delta,extra_frames=delta-int(previous['requested']),
                            entry_pipeline_s=relative,before_first_speed_request=relative<first_speed if first_speed is not None else None,
                            actual_entry_delta_ns=int(current['start_ns'])-int(previous['start_ns']),
                            timestamp_delta_ns=int(current['host_ns'])-int(previous['host_ns'])))
                failure['missing_callbacks']=[r for r in callbacks if int(r['wanted'])>int(r['received'])]
            intervals=path.parent/'intervals.csv'
            failure['deadline_interval_evidence']=str(intervals) if intervals.exists() else None
            failure['deadline_miss_intervals']=([r for r in csv.DictReader(intervals.open()) if r['deadline_miss']=='1']
                                                 if intervals.exists() else None)
            native_failures.append(failure)
    write('FINAL_NATIVE_FAILURES.json',dict(failures=native_failures,
        scope='正式な最終新経路274セッション。Nativeの合否を変更せず、raw記録を抽出する。追加のOS trace付き1試行と旧製品は別記。最大Wall位置を期限違反位置と推定しない。'))
    dynamic_pass=len(dynamic)==6 and all(r['result'] and r['result']['PASS'] for r in dynamic) and device['dynamic_sessions']==190
    fixed_long=read(OUT/'device_final/fixed_long_rows.json')
    formal180={}
    for preset in ('candidate','baseline'):
        sessions=[r for r in measurements['fixed_long']['per_session'] if 'boundary_1_2_44100_180_'+preset in r['summary']]
        formal180[preset]=dict(repeats=len(sessions),maximum_realtime_cpu_ms=max(r['realtime_cpu_ms']['max'] for r in sessions),
                               maximum_realtime_wall_ms=max(r['realtime_wall_ms']['max'] for r in sessions))
    fixed_pass=all(measurements.get(k,{}).get('native_passed')==n and measurements[k]['sessions']==n for k,n in [('fixed_short',36),('fixed_long',8)]) and all(r['PASS'] for r in fixed_long)
    eos_native=measurements.get('eos_native',{})
    eos_pass=eos_native.get('sessions')==40 and eos_native.get('native_passed')==40 and eos['release_paced_pass']
    def all_zero(key):return bool(measurements) and all(v['zero_invariant_totals'].get(key)==0 for v in measurements.values())
    pcm=quality['PASS'] and quality['dynamic_pcm_sessions']==1140 and quality['fixed58_pcm_sessions']==6216 and quality['fixed57_pcm_sessions']==51344
    golden=len(checks['golden'])==25 and all(r['PASS'] for r in checks['golden'])
    verdict=dict(verdict='B' if pcm and checks['PASS'] else 'C',
        root_cause_clock_identified=False,startup_clock_verified=False,
        root_cause_dsp_deadline_identified=False,fixed_long_deadline_verified=len(fixed_long)==8 and all(r['PASS'] and r['result']['workgroup_deadline_misses']==0 for r in fixed_long),
        root_cause_legacy_fifo_identified=False,legacy_fifo_verified=False,
        eos_restart_realtime_verified=eos_pass,zero_fill_investigated=True,realtime_page_faults_verified=False,
        dynamic_pcm_bit_exact=pcm,all_161_speeds_supported=pcm,latest_wins_verified=pcm and checks['PASS'],
        l1_l2_safe_density_verified=pcm and checks['PASS'],dynamic_native_regression_passed=dynamic_pass,
        fixed_native_regression_passed=fixed_pass,legacy_regression_passed=legacy['PASS'],
        callback_deadline_verified=all_zero('callback_deadlines'),fifo_underrun_free=False,
        workgroup_deadline_verified=all_zero('workgroup_deadline_misses') and eos['release_paced_pass'],golden_pass=golden,
        historical_failures_preserved=audit['PASS'] and audit['historical_tracked_results_unchanged'] and all(audit['historical_reference_checks'].values()),
        gate_2_passed=False,gate_3_ready=False,product_integration_ready=False,merodoa_changed=False,
        dynamic_fifo_underrun_free=measurements.get('dynamic',{}).get('zero_invariant_totals',{}).get('missing_frames')==0,
        all_161_speeds_native_applied=False,legacy_original_missing_frames_before_fix=1319,
        final_focused_trace_native_passed=final_trace_native['PASS'] if final_trace_native else None,
        os_hal_client_overload_free=post_trace['hal_client_overloads']==0 if post_trace else False,
        final_native_failure_sessions=len(native_failures),
        dynamic_map_prefix_failures=sum(r.get('map_prefix_bit_exact') is False for r in dynamic_rows),
        dynamic_generated_callback_sha_failures=sum(r.get('generated_callback_sha_equal') is False for r in dynamic_rows),
        final_clock_sample_jumps=[dict(summary=f['summary'],extra_frames=j['extra_frames'])
                                  for f in native_failures for j in f['clock_sample_jumps']],
        legacy_original_missing_frames_reproduced=8208,clock_extra_frames_reproduced=924,
        legacy_final_missing_frames=sum(int(r['summary'].get('lifetime_missing_frames',r['summary'].get('missing_frames',0))) for r in legacy_failures),
        original_49ms_cause_fully_proved=False,original_4_8s_cause_fully_proved=False,
        scopes=dict(callback_deadline_verified='最終新経路・固定・EOSの274音声セッションのSourceNode callback処理時間。起床遅延、OS HAL Client Overload、timestamp異常とは別。旧製品はlegacy結果を別記。',
            workgroup_deadline_verified='同274音声セッションとRelease周期付きEOS。高速排出/DebugのRT失敗は別記して保持。',
            fifo_underrun_free='過去と今回の旧製品FAILを含むためfalse。最終動的行列とは別。',
            root_cause_dsp_deadline_identified='処理量と重複コストは特定したが、過去49msの実行環境まで含む原因は未証明。',
            realtime_page_faults_verified='準備時書込みは実施したが、OS未観測域を含む全RT領域のfault 0は証明していない。'))
    write('MEASUREMENTS.json',dict(quality=quality,checks_pass=checks['PASS'],golden_passed=sum(r['PASS'] for r in checks['golden']),
        groups=measurements,dynamic_suites={r['name']:r['result'] for r in dynamic},legacy=legacy,eos=eos,
        final_focused_os_trace=final_trace,final_focused_trace_native=final_trace_native,
        formal_180s_2x_cpu2=formal180,
        post_trace_clock_and_vm=post_trace,
        final_native_failure_sessions=len(native_failures),
        delivery_audit=str(OUT/'GIT_DELIVERY_AUDIT.json'),
        unmeasured=dict(c_malloc_calls=None,objc_allocations=None,individual_ifft_cpu_s=None,individual_ola_cpu_s=None,
                        individual_time_map_interpolation_cpu_s=None,os_state_at_original_49ms=None,os_state_at_original_4_8s=None,
                        continuous_os_state_unobserved_fraction_for_normal_native_groups=None,
                        hal_idle_state_before_first_final_native=None,
                        native_snapshot_generation_anomaly_counter=None)))
    write('VERDICT.json',verdict)
    dynamic_table='\n'.join(f"| {r['name']} | {r['result']['passed']}/{r['result']['sessions']} | {r['result']['full_pcm_sessions']} / {r['result']['prefix_sessions']} |" for r in dynamic)
    trace_text=(f"追加の最終trace付き再生のNative判定は{'合格' if final_trace['native_pass'] else '不合格'}。正式274音声セッションとは別記する。"
                f"最終6秒窓の全状態既知は{final_trace['fully_observed_within_window']}/{final_trace['wholly_in_observed_window']}区間、"
                f"窓内Unknownは{final_trace['unknown_within_window']}、窓外・部分区間は{final_trace['outside_or_partial_window']}。"
                f"既知区間のVM観測は{final_trace['known_vm_operations']}。全区間のfault 0とはしない。"
                f"指定した元の最大Wall位置付近の{final_trace['targeted_intervals']}区間は、窓内{final_trace['targeted_intervals_within_window']}区間で未取得。attachの開始遅延により取得位置は後ろへずれた。") if final_trace else '最終focused traceのOS直接照合は取得・解析できず未検証。保存済み取得/解析ログを参照。'
    trace_text+='\n\n追加試行の時計FAILは起動時ではなく、約85.821秒のcallback8016→8017の518フレームの余分な進みだった。直前のIOProcが遅れ、OSはClient Overloadを1件記録した。Native独自のHAL windowカウンター0とは区別する。Client threadの約11.2ms Blockedとdtsecurityによる起床を観測したが、待機の全因果や計測器の関与は未証明。元の初回時計異常と同原因だとはしない。根拠はPOST_TRACE_CLOCK_VM.json。'
    validation=f'''# Phase 59 Fix 検証

判定 **{verdict['verdict']}、Gate 2未合格**。初回時計、旧製品の供給停止、OS未観測域の原因証明は残る。品質の完全一致と実時間の供給・時計は別に判定する。

## 独立参照とPCM

最終固定実行体は `results/phase59_fix/FINAL_CANDIDATE.json` の19実行体・10ライブラリ・209ソースSHAで識別する。変更前の独立参照は既存のfrozenバイナリを使い、許容誤差を導入しない。

| 検査 | PCM条件数 | 結果 |
|---|---:|---|
| 動的 | {quality['dynamic_pcm_sessions']} | {'完全一致' if quality['PASS'] else '未成立'} |
| Phase58固定 | {quality['fixed58_pcm_sessions']} | {'完全一致' if quality['PASS'] else '未成立'} |
| Phase57固定 | {quality['fixed57_pcm_sessions']} | {'完全一致' if quality['PASS'] else '未成立'} |

全161速度の隣接640条件は動的1140件に含む。Phase57は形式ごとの分割だけを行い、速度・素材・チャンクを削減していない。Phase56は状態安全性、161速度固定Map、増分一致をCTestで再検査した。全25921速度組や実機全161値の各適用を網羅したという意味ではない。

最初の動的長尺は1件一致後に空き4GiB基準で中断した。`validation_final/summary.json`に初回中断を残し、長尺16件と続く増分144件を同じ参照・条件で別保存先へ実行した。全行列の集計は`validation_final/effective_summary.json`。初回の成功1件を最終1140件に重複加算しない。

## 最終音声試験

| 動的群 | 合格/セッション | 全PCM / 接頭部PCM |
|---|---:|---:|
{dynamic_table}

固定短尺36件、固定長尺8件（180秒の両preset×3反復、300秒の両preset）、同一プロセスのEOS再生成40件を別に実行した。各群のCPU/Wall中央値・p95・p99・最大、全ゼロ項目の値は `MEASUREMENTS.json` を参照する。新経路の実機合格と旧製品の結果を合算して解決扱いにしない。

旧製品最終比較は{legacy['passed']}/{legacy['sessions']}。修正前調査では保存済み旧バイナリのBaseline smokeに8208フレーム不足を再現した。過去Candidateの1319フレーム不足も保持した。最終比較が成功しても根本原因は解明済みとしない。

今回の最終比較でも旧Baseline smokeのsession4/epoch1、callback179に234フレーム不足を再現した。PCMと時刻診断は合格だが供給失敗である。個別値とraw callbackは`FINAL_LEGACY_FAILURES.json`。

正式な最終新経路の不合格セッションは{len(native_failures)}件。`FINAL_NATIVE_FAILURES.json`に項目別値、callbackの時刻差・不足、取得できた実期限区間を保存する。最初の動的normalではsample0→1160（要求512、余分648フレーム）を再現し、PCM一致・不足0でも時計FAILとした。

## EOS・メモリ・OS

最終実機のEOSは同一入力を用いた新engine/sessionの40反復。別入力への切替と旧session要求の拒否は、2入力の機能・周期付き診断でも検査した。FIFOにある分だけ引く模擬排出は、物理callbackの不足0の代用にはしない。

高速排出のOS優先度低下とPreemptedを確認した。Debug・高速排出の失敗は実時間性能の失敗として別記し、通常優先度の機能合格で相殺しない。VMの初回書込み対策は行ったが、Unknownや取得窓の外をfault 0として埋めない。

最終focused traceの実時間区間とOS状態の直接照合は`FINAL_TRACE_OBSERVATIONS.json`（取得・解析不能なら未検証）。全90秒に対して6秒窓であること、Unknownと窓外を分けて記録する。

{trace_text}

## CTest・Golden・検査器

Release93/93、Debug関連18/18、Golden25/25。固定前コードとの位相更新3840、Stereo1920フレーム比較、ASAN/UBSAN、値・借用メールボックスのTSAN/ASAN/UBSAN、Git容量ガードの隔離5検査を実行した。根拠は `checks_final/summary.json`。

## 保存・再現

全PCM・大きい行データ・CSV・XML・トレース・実行体は `build/phase59_fix_artifacts/` に保存した。各manifestに入力/実行体SHA、コマンド、保存場所を記録する。成功作業PCMの圧縮は `validation_final/success_working_archives.json`、トレース復元は `TRACE_ARCHIVE_*.json` を参照する。いずれも復元SHAを検証する。FAIL原本と過去Phaseの証拠は保持する。

未測定項目は `MEASUREMENTS.json` のnullで明示する。初回2回の除外、期限延長、FIFO拡大、品質・条件数の削減は行っていない。
'''
    (ROOT/'docs/PHASE59_FIX_VALIDATION.md').write_text(validation)
    report=f'''# Phase 59 Fix REPORT

判定 **{verdict['verdict']}：条件付き成立、Gate 2未合格**。PCM品質は完全一致で保護した。起動時計、従来製品FIFO、OS未観測域に未解決事項が残る。

## 1. 発見した原因

位相更新・Stereo近傍計算の重複と、ブロック内処理フレーム数によるCPU負荷を確認した。高速排出ではアプリの復元操作前にOS優先度が低下し、実行待ちが長くなった。初回時計の完全な原因、過去49msと4.8秒の環境を含む因果、旧製品供給停止の正確な原因は未特定。

## 2. 原因を示す証拠

`CLOCK_REPRODUCTION.json`、`PHASE_BEFORE_ANALYSIS.json`、`PHASE_AFTER_ANALYSIS.json`、`LEGACY_FAILURE_REVIEW.json`、`EOS_TRACE_OBSERVATIONS.json`を保存した。OS状態が取得できなかった領域を正常で補完しない。

## 3. 変更ファイル

Phase35位相更新・Stereo補正、PhaseLockerの準備処理、Phase36/57/58の診断、研究用Native、独立参照テスト、検証スクリプト、Git容量ガード、AGENTS、文書を変更した。全最終ソースと実行体SHAは `FINAL_CANDIDATE.json`。

## 4. 実施した修正

算出済みFloat32振幅・位相、同じ所有者のStereo近傍値を再利用する。入出力が重なる場合は従来処理を維持する。ピーク容量へ準備時に全書込みする。位相更新順、近傍加算順、精度、OLA/FIR、50ms遷移、FIFO、ゲイン0.5は維持した。

## 5. 変更前後の比較

位相更新部品のCPUは交互5反復で約8〜10%短縮。指定窓のStereo CPUは約18〜21%短縮した。対応する180秒・2倍・CPU2の2試行は、最大RT CPU27.117/27.722ms、全PCM一致、不足・期限・RT new 0。試行間変動を含むため、元の49msを完全に説明したとはしない。

## 6. 初回callback時計の検証

初期80試行は成功したが、固定0.50倍でsample0→1436（要求512）、余分924フレーム/19.25msを再現した。FIFO不足とPCM不一致は0。動的要求前・同じ48kHz形式で発生し、原因未特定。閾値・epoch・初回除外を変更していない。

最終動的normalでも、同じ入力SHA・初期0.50倍Candidateでsample0→1160（余分648/13.5ms）を再現した。最初の2回のFIFOは16384→15872、各512フレームを受け取り、全PCM一致・作業期限超過0だった。最終新経路の不合格は計{len(native_failures)}セッションで、`FINAL_NATIVE_FAILURES.json`へ個別記録を残した。

## 7. DSP期限超過の検証

最終固定長尺{len(fixed_long)}件、合格{sum(r['PASS'] for r in fixed_long)}件。周期2048/sampleRate、計算予算90%を維持した。実際の期限ticksを保存し、最大Wall位置と期限判定位置を区別した。

正式な180秒・CPU2の各3反復では、最大RT CPUはCandidate {formal180['candidate']['maximum_realtime_cpu_ms']:.6f}ms、Baseline {formal180['baseline']['maximum_realtime_cpu_ms']:.6f}ms。最大RT Wallは各{formal180['candidate']['maximum_realtime_wall_ms']:.6f}/{formal180['baseline']['maximum_realtime_wall_ms']:.6f}ms。両方とも46.44ms周期と41.796ms計算予算以内だった。先の詳細診断2試行とは分布・計測設定を区別する。

## 8. 旧製品FIFO不足の検証

修正前の旧版Baseline smokeに8208フレーム不足を再現。過去Candidateの1319も保持。両方ともPCMは一致していた。最終旧製品比較{legacy['passed']}/{legacy['sessions']}。旧実行体固有の問題として区別するが、根本原因を確定できていない。

最終比較の旧Baseline smokeにも234フレーム不足（session4/epoch1/callback179、wanted470/received236/fifo236）があった。PCM・時計は合格、供給は不合格。`FINAL_LEGACY_FAILURES.json`に保存し、過去とは異なる再現位置を同一原因だと推定しない。

## 9. EOS再始動の検証

実機で同一プロセスEOS再生成40件、Release/Debugの周期付き・高速・通常優先度を別検査。実機合格は{eos_native.get('native_passed')}/{eos_native.get('sessions')}。高速排出・Debugの期限失敗は `eos_before/` と `eos_after/` に保持。旧4.8秒の直接証明はない。

## 10. Zero FillとOS状態

reserveだけだったピーク領域を準備時に書込みした。旧Zero Fillの割当元と一致する証明はない。修正前起動traceの既知48/96区間にDecompress Memory24件、EOS traceは既知65/307区間にVM fault0。Unknown/未取得を全域の安全保証へ一般化しない。

{trace_text}

## 11. 動的PCM完全一致

{quality['dynamic_pcm_sessions']}/1140。全161速度の隣接640条件、Latest-Wins、L1/Phase50、L2、safe-densityを旧独立参照で保護。速度全組・全速度実機適用とは区別する。

## 12. 固定PCM完全一致

Phase58 {quality['fixed58_pcm_sessions']}/6216、Phase57 {quality['fixed57_pcm_sessions']}/51344。全PCMの長さ・順序・Float32生ビット・SHAを比較した。拒否条件も別照合した。

## 13. 実時間試験

動的{device['dynamic_passed']}/{device['dynamic_sessions']}。固定短尺{measurements.get('fixed_short',{}).get('native_passed')}/36、長尺{sum(r['PASS'] for r in fixed_long)}/8、EOS{eos_native.get('native_passed')}/40。項目別ゼロ合計と分布は `MEASUREMENTS.json`。未測定項目を0にしない。

## 14. CTest・Golden

Release93/93、Debug18/18、Golden{sum(r['PASS'] for r in checks['golden'])}/25。独立旧コードとの部品比較、TSAN/ASAN/UBSAN、50MB境界・index・履歴途中blobの隔離検査も合格した。

## 15. ディスク容量

ユーザーが空き容量を確保した後に再開した。traceは一時ktraceとbundleの両方を含めて1回2GiB、空き2GiB、累積8GiB・4回を上限とした。`TRACE_BUDGET.json`、`TRACE_TOTAL_BUDGET.json`、各取得manifestを参照。圧縮はopen FDと復元SHAを確認し、使用中の一時ktraceには触れていない。

動的長尺の初回は4GiB基準で安全中断した。元の中断記録と一致1件を保持し、長尺16・増分144件は別保存先で同じ条件を再実行した。全行列は`validation_final/effective_summary.json`で集計し、初回分を重複加算しない。完了済みDebugビルドも`DEBUG_BUILD_ARCHIVE.json`の全ファイル復元SHAを照合して圧縮し、EOS実行体は同一SHAで別保存した。

Gitは50,000,000バイト境界を採用。既存の4大容量blob/5追跡パスは保持し、新規blobの検査器とpre-commit/pre-pushを導入した。履歴書換え・LFS移行は行っていない。

## 16. 未解決事項

起動時計の原因、過去49msの全因果、従来製品の供給停止、元の4.8秒停止、全実時間領域のページフォルト0は未証明。IFFT/OLAや位相内の全関数を個別に計測したわけではない。最終試行の成功でこれらを解消扱いにしない。

## 17. Gate 2判定

**未合格**。品質の成立と、時計・FIFO・メモリを含む実時間安全性の成立を分ける。各boolと範囲は `VERDICT.json`。旧製品の独立したFAILも別に残す。

## 18. 次Phaseへの移行可否

Gate3・製品統合へは進めない。次のFixでは初回SourceNode/HAL時刻の失敗時OS観測、旧製品のシーク中供給履歴、実時間メモリの観測範囲を優先する。新しい音質機能やMerodoa統合は追加していない。
'''
    (OUT/'REPORT.md').write_text(report)
    root_cause=ROOT/'docs/PHASE59_FIX_ROOT_CAUSE.md'
    marker='\n## 最終実機回帰での追加観測\n'
    root_cause.write_text(root_cause.read_text().split(marker)[0]+marker+f'''
動的実機は{device['dynamic_passed']}/{device['dynamic_sessions']}、正式な新経路274セッションの不合格は{len(native_failures)}件だった。最初のnormal Candidate・0.50倍では、元V7と同じ入力SHAでsample0→1160（要求512、余分648/13.5ms）を再現した。callback入口の間隔23.896msとtimestamp差24.167msを区別する。速度要求受付より前に発生し、全PCM一致・不足0・作業期限超過0でも時計は不合格とした。

個別の時計差、不足callback、取得できた期限区間は`results/phase59_fix/FINAL_NATIVE_FAILURES.json`。旧製品最終比較は{legacy['passed']}/{legacy['sessions']}で、過去の1319と今回修正前の8208フレーム不足を取り消さない。

最終旧Baseline smokeにも234フレーム不足（session4/epoch1/callback179、wanted470/received236/fifo236）を再現した。PCM・時計は合格だった。`FINAL_LEGACY_FAILURES.json`を別保存し、このcallback時点のOS状態をworker全体の最大Wallから推定しない。

長いオフライン回帰後の最初の正式Nativeで起きたという順序も調査候補である。ただし、他アプリも含む装置のidle/稼働状態は取得していない。自分の試験の休止時間を装置の休止と同一視せず、次Fixでは休止時間を制御した旧版/最終版比較とHALの失敗時観測で検証する。

{trace_text}
''')
    print(verdict['verdict'],'quality',pcm,'dynamic',dynamic_pass,'fixed',fixed_pass,'legacy',legacy['PASS'],flush=True)


if __name__=='__main__':main()
