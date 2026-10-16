"""Summarize measured gates; retain every failed audio condition."""
import collections,csv,gzip,json,math,re,shutil,statistics,subprocess
from pathlib import Path
from phase57_study import ROOT,sha
from phase59_native_validation import wav_info
OUT=ROOT/'results/phase59'
def read(path):return json.loads((OUT/path).read_text())
def write(name,data):(OUT/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
def stats(values):
    values=sorted(values)
    if not values:return dict(n=0)
    return dict(n=len(values),median=statistics.median(values),p95=values[math.ceil(len(values)*.95)-1],p99=values[math.ceil(len(values)*.99)-1],max=max(values))
def csv_rows(path):
    opener=path.open if path.exists() else lambda **kwargs:gzip.open(path.with_suffix(path.suffix+'.gz'),'rt',**kwargs)
    with opener() as file:return list(csv.DictReader(file))
def main():
    quality=read('quality_final/summary.json');reg=read('regression_final/summary.json');debug=read('debug_final/final_summary.json')
    assert quality['PASS'] and reg['PASS'] and debug['PASS']
    assert read('eos_restart_functional/summary.json')['PASS']
    assert read('eos_pending_final/summary.json')['PASS']
    final=read('FINAL_CANDIDATE.json');assert all(sha(ROOT/p)==h for p,h in final['source_sha256'].items())
    assert all(sha(ROOT/'build/phase59_frozen/final'/name)==h for name,h in final['binary_sha256'].items())
    suites={s:read('quality_final/'+s+'/summary.json') for s in ['priority','all161','materials','long','incremental_chunks','incremental_formats']}
    native={s:read('device_final/dynamic_'+s+'/summary.json') for s in ['normal','load','lifecycle','burst','materials','long']}
    native_rows=[]
    for group in native:
        for index,r in enumerate(read('device_final/dynamic_'+group+'/rows.json')):
            native_rows.append(dict(group=group,index=index,**r))
    failures=[]
    for r in native_rows:
        if not r['PASS']:
            failures.append(dict(group=r['group'],index=r['index'],native_exit=r['native_exit'],pcm=r.get('pcm'),
                nonzero_invariants={k:v for k,v in r.get('zero_invariants',{}).items() if v!=0},conditions_valid=r.get('conditions_valid'),policy_sampling=r.get('realtime_policy_sampling')))
    logical_rows=[]
    for suite in ['priority','all161','materials','long']:
        logical_rows.extend(json.loads(line) for line in (OUT/'quality_final'/suite/'rows.jsonl').read_text().splitlines())
    assert all(r['actual']['map_sha256']==r['reference']['map_sha256'] and r['actual']['frames']==r['reference']['frames'] and r['actual']['same_dsp_instance'] for r in logical_rows)
    pairs={(r['initial_speed'],target) for r in logical_rows for _,target in r['requests'] if 400000<=target<=2000000 and target%10000==0}
    inputs={}
    for manifest in list((OUT/'quality_final').glob('*/manifest.json'))+list((OUT/'device_final').glob('dynamic_*/manifest.json')):
        for source in json.loads(manifest.read_text()).get('inputs',[]):
            path=Path(source['path']);digest=sha(path);assert digest==source.get('sha256',source.get('input_sha256'))
            entry=inputs.setdefault(str(path),dict(path=str(path),sha256=digest,metadata=wav_info(path),manifests=[]));entry['manifests'].append(str(manifest.relative_to(OUT)))
    write('INPUT_FORMATS.json',dict(inputs=list(inputs.values()),format_axes=sorted({(v['metadata']['encoding'],v['metadata']['bits'],v['metadata']['channels'],v['metadata']['rate']) for v in inputs.values()})))
    plan_counts=collections.Counter()
    for suite in ['priority','all161','materials','long']:
        for path in (OUT/'quality_final'/suite).glob('case_*/actual.operations.csv'):
            for op in csv.DictReader(path.open()):
                plan_counts[op['status']]+=1
                if op['status'] in ('Applied','Completed'):
                    plan_counts['with_l2_held_frames']+=int(op['held_frames'])>0
                    plan_counts['with_density_switch']+=int(op['density_input'])>0
    latencies=[];plan_cpu=[];plan_wall=[];workers=[];present_apply=[];present_complete=[]
    for r in native_rows:
        folder=OUT/'device_final'/('dynamic_'+r['group'])/f"case_{r['index']:03d}"/'native'
        workers.extend(w for w in csv_rows(folder/'worker.csv') if w.get('realtime')=='1')
        operations={int(op['id']):op for op in csv.DictReader((folder/'speeds.csv').open())}
        for op in r.get('operation_timings',[]):
            latencies.append(op['request_to_map_apply_s']*1000);plan_cpu.append(op['plan_cpu_s']*1000);plan_wall.append(op['plan_wall_s']*1000)
            for field,target in [('apply_presented',present_apply),('completion_presented',present_complete)]:
                if op[field]:
                    s=r['native'];pipeline_time=(op[field]['end_ns']-s['clock_mach_ns'])*1e-9+s['clock_pipeline_s']
                    target.append((pipeline_time-float(operations[op['id']]['accepted_s']))*1000)
    native_exact=all(r.get('pcm',{}).get('PASS',False) and r.get('map_prefix_bit_exact',False) and (not r.get('native',{}).get('eos') or r.get('map_complete_bit_exact',False)) and r.get('reference',{}).get('frontiers_exact',False) for r in native_rows)
    keys=list(native_rows[0]['zero_invariants'])
    totals={k:sum(r['native'].get(k,0) for r in native_rows) for k in keys}
    measurements=dict(native_suites=native,final_native_sessions=len(native_rows),final_native_passed=sum(r['PASS'] for r in native_rows),
        final_native_failures=failures,prior_clock_failure_count=1,prior_clock_failure_resolved=False,
        sandbox_no_audio_attempts=1,reference_scope_mismatch_sessions=3,canonical_pcm_exact=native_exact,zero_invariant_totals=totals,
        request_to_map_apply_ms=stats(latencies),request_to_presented_apply_ms=stats(present_apply),request_to_presented_completion_ms=stats(present_complete),
        plan_cpu_per_operation_ms=stats(plan_cpu),plan_wall_per_operation_ms=stats(plan_wall),
        realtime_blocks=len(workers),realtime_wall_ms=stats([float(w['wall_s'])*1000 for w in workers]),
        realtime_non_cpu_ms=stats([max(0,float(w['wall_s'])-float(w['cpu_s']))*1000 for w in workers]),
        realtime_policy_sampled_blocks=sum(r['realtime_policy_sampling']['blocks_with_samples'] for r in native_rows),
        realtime_policy_unobserved_blocks=sum(r['realtime_policy_sampling']['realtime_blocks']-r['realtime_policy_sampling']['blocks_with_samples'] for r in native_rows),
        realtime_policy_observed_priorities=sorted({p for r in native_rows for p in r['realtime_policy_sampling']['priorities']}),
        native_operation_states=dict(collections.Counter(state for r in native_rows for state in r.get('operation_states',[]))),
        burst_operation_states=dict(collections.Counter(state for r in native_rows if r['group']=='burst' for state in r.get('operation_states',[]))),
        peak_rss_bytes=max(r['native']['peak_rss_bytes'] for r in native_rows),
        peak_rss_by_group={g:max(r['native']['peak_rss_bytes'] for r in native_rows if r['group']==g) for g in native},
        map_peak_estimate_bytes=max(r['native']['transition_map_peak_bytes'] for r in native_rows),
        snapshot_peak_bytes=max(r['native']['snapshot_peak_bytes'] for r in native_rows),
        borrowed_snapshot_owners_max=max(r['native']['borrowed_snapshot_owners'] for r in native_rows),
        borrowed_map_owners_max=max(r['native']['transition_map_owners'] for r in native_rows),
        planning_attempts=sum(r['native']['transition_plan_attempts'] for r in native_rows),
        stale_replans=sum(r['native']['transition_stale_replans'] for r in native_rows),
        analysis_deferrals=sum(r['native']['transition_analysis_deferrals'] for r in native_rows),
        dynamic_deterministic_sessions=sum(s['pcm_sessions'] for s in suites.values()),logical_pairs=len(pairs),logical_plan_counts=dict(plan_counts))
    write('MEASUREMENTS.json',measurements)
    device=read('device_final/summary.json');fixed_long=read('device_final/fixed_long/summary.json');legacy=read('device_final/legacy_product/summary.json')
    fixed_rows=read('device_final/fixed_long/rows.json');legacy_rows=read('device_final/legacy_product/rows.json')
    fixed_failures=[dict(input=r['input'],preset=r['summary']['preset'],exit=r['exit'],
        deadline_misses=r['summary']['workgroup_deadline_misses'],missing_frames=r['summary']['missing_frames'],
        pcm_complete_exact=bool(r['summary']['pcm_complete_exact'])) for r in fixed_rows if not r['PASS']]
    legacy_failures=[dict(label=r['label'],mode=r['mode'],preset=r['preset'],exit=r['exit'],
        missing_frames=int(r['summary'].get('missing_frames',0)),summary=r['summary']) for r in legacy_rows if not r['PASS']]
    write('DEVICE_REGRESSION_FAILURES.json',dict(fixed_long=fixed_failures,legacy=legacy_failures,
        original_coordinator='device_final/summary.json',resumed_coordinator='device_resume_after_trace_archive/summary.json',
        cause='期限超過とFIFO不足を観測。該当実行のOS状態未取得につき、原因や変更との因果は未確定。'))
    fixed=[read('device_final/'+r['name']+'/summary.json') for r in device['history'] if r['name'].startswith('fixed_') and r['name']!='fixed_long']
    fixed_count=sum(r['executions'] for r in fixed)+fixed_long['sessions'];fixed_pass=sum(r['passed'] for r in fixed)+fixed_long['passed']
    measurements.update(fixed_device_sessions=fixed_count,fixed_device_passed=fixed_pass,
        legacy_device_executions=legacy['executions'],legacy_device_passed=legacy['passed'],
        device_regression_failure_manifest='DEVICE_REGRESSION_FAILURES.json',
        device_failure_timeline_manifest='DEVICE_FAILURE_TIMELINES.json',
        dynamic_zero_invariant_scope='最終動的6群のみ。固定速度と旧製品は別の失敗台帳を参照。')
    write('MEASUREMENTS.json',measurements)
    fixed_reg={s:read('regression_final/phase58_'+s+'/summary.json') for s in ['short','all_speeds','long']}
    pcm_reg={s:read('regression_final/phase57_'+s+'/summary.json') for s in ['stage1','stage2','long','natural','rejections']}
    golden=read('regression_final/golden/summary.json');golden_pass=len(golden)==25 and all(r['PASS'] for r in golden)
    native_load=native['load']['PASS'];native_long=native['long']['PASS'];all_pcm=all(s['PASS'] for s in suites.values()) and native_exact
    verdict=dict(verdict='B',dynamic_transition_implemented=True,dynamic_pcm_bit_exact=all_pcm,
        all_161_initial_speeds_covered=len(suites['all161']['initial_speeds'])==161,all_161_target_speeds_covered=len(suites['all161']['target_speeds'])==161,
        all_25921_pairs_tested=False,latest_wins_verified=True,l1_verified=all_pcm,l2_verified=all_pcm and plan_counts['with_l2_held_frames']>0,
        safe_density_verified=all_pcm and plan_counts['with_density_switch']>0,phase50_boundary_verified=all_pcm,snapshot_consistency_verified=all_pcm,same_dsp_instance_verified=True,
        realtime_worker_safe=False,realtime_worker_allocations=totals['realtime_cpp_new_calls'],
        fifo_underrun_free=totals['missing_frames']==0 and not any(r['missing_frames'] for r in fixed_failures+legacy_failures),
        dynamic_fifo_underrun_free=totals['missing_frames']==0,
        callback_deadline_verified=totals['callback_deadlines']==0,realtime_transition_verified=False,
        long_track_verified=native_long and suites['long']['PASS'] and fixed_long['PASS'],
        high_load_verified=native_load and fixed_long['PASS'],
        dynamic_long_track_verified=native_long and suites['long']['PASS'],dynamic_high_load_verified=native_load,golden_pass=golden_pass,
        legacy_regression_passed=all(s['PASS'] for s in fixed_reg.values()) and all(s['PASS'] for s in pcm_reg.values()) and legacy['PASS'] and fixed_pass==fixed_count,
        gate_2_passed=False,gate_3_ready=False,product_integration_ready=False,merodoa_changed=False,
        final_native_sessions=len(native_rows),final_native_failures=len(failures),prior_clock_failure_resolved=False,
        eos_restart_functional_verified=True,eos_pending_cancel_verified=True,debug_realtime_stress_passed=False,unpaced_realtime_stress_passed=False,
        realtime_worker_safe_scope='有界適用・借用所有権・C++確保を検査したが、OS状態未観測域とRT Zero Fill、起動時計異常の未解決を残す。',
        dynamic_pcm_scope='同じ要求/Frontier/適用計画の旧全曲解析＋動的Phase39/36。先行全計画Phase35との同値性は未成立。',
        storage_original_floor_maintained=False,storage_revised_minimum_free_gib=3,capacity_interrupted_groups=5,
        trace_peak_budget_maintained=False,
        fixed_device_failures=fixed_failures,
        legacy_device_failures=[{k:v for k,v in r.items() if k!='summary'} for r in legacy_failures],
        not_tested=['全25921組','長尺の全161速度','実機で全161速度を各初期・目標として物理適用','実際のApple API失敗・OS全体のメモリ逼迫','全OS・全出力装置・物理音響遅延'],
        blocking_issues=['初回2コールバック間のhost/sample不連続1件の原因未特定',
            *([str(f) for f in failures]),
            *(['固定180秒/2倍/CPU競合2の両presetで作業期限超過を観測'] if fixed_failures else []),
            *(['変更前の旧製品Candidate smokeでFIFO不足1319フレームを観測'] if legacy_failures else [])])
    write('VERDICT.json',verdict)
    quality_table='\n'.join(f"| {name} | {s['pcm_sessions']} | {'合格' if s['PASS'] else '不合格'} |" for name,s in suites.items())
    native_table='\n'.join(f"| {name} | {s['passed']}/{s['sessions']} | {s['full_pcm_sessions']} / {s['prefix_sessions']} |" for name,s in native.items())
    release=(OUT/'regression_final/release_ctest.log').read_text();debug_log=(OUT/'debug_final/final_1.log').read_text()
    release_total=re.search(r'out of (\d+)',release).group(1);debug_total=re.search(r'out of (\d+)',debug_log).group(1)
    report=f'''# Phase 59 REPORT

判定 **B：条件付き成立、Gate 2未合格**。動的速度変更と同一計画の全PCM一致は成立した。起動時host/sample時計の不連続1件、固定長尺の作業期限超過、旧製品のFIFO不足を観測しており、原因は未特定。後続の成功でこの失敗を除外しない。製品・Merodoaへの統合は行っていない。

## 1. 実装内容

閉鎖イベントから確定prefixを作り、既存Phase39の50ms遷移、L1/Phase50、L2/C、Phase42 safe-densityを共有する。未来情報不足はPendingAnalysis。通常側で作った不変Mapを、同じPhase57 DSPの位相・OLA・FIR状態へ有界に適用する。FIFO容量16384、先行量16384/12288、生成2048、ゲイン0.5を維持した。

TimeMapは入力位置を出力位置に対応させる表、prefixは先頭から確定した範囲、FrontierはDSPの現在の処理境界を表す。PCMは音声サンプル列、FIFOは生成順に渡す有限の音声バッファである。

## 2. 変更ファイル

`src/prototype/Phase59*`、`Phase58RealtimePipeline`、`Phase57ProgressiveSynthesis`、`Phase36SynthesisCore`、`Phase39TimeMap`、研究用Native、診断とメールボックス、CMake、Phase59テスト・検証スクリプト・4文書を追加/変更。共有変更は確定prefix入口と動的モードに限定。基準HEADは `bb22efcbd27f999e8ffe85bbe3f03e20895be3f2`、main。開始時clean。最終実行体/全src SHAは [FINAL_CANDIDATE](FINAL_CANDIDATE.json)。保護対象54461ファイルの変更監査は [protected_assets_delivery](protected_assets_delivery.json)。

## 3. 動的TimeMapの一致結果

全Map node、適用/完了境界、保護区間、密度切替、出力長を独立参照と照合した。旧全曲入口と確定prefix入口は同じsubmit算術を使用。単体検査では168 prefix、両presetの2非最終適用、古い版/入力世代/処理済みnode拒否、取引rollback、公開時bad_allocを確認。実際のDSP Frontierが進んだ候補は再計画し、既使用nodeを変更しない。

## 4. PCM完全一致結果

最終版の決定論的動的検証 **{measurements['dynamic_deterministic_sessions']}条件**。全Float32生ビット、順序、長さ、SHAが一致した。解析保留後は実際の適用Frontierを旧全曲解析＋Phase39/42/50/36へ再現し、元の予定適用位置との同一性は主張しない。

| 試験 | 全PCM条件数 | 結果 |
|---|---:|---|
{quality_table}

参照SHAは [FROZEN_REFERENCE](FROZEN_REFERENCE.json) と [CAPTURED_REFERENCE](CAPTURED_REFERENCE.json)。変更前ヘッダー/ライブラリを保存し、基準Gitからの再構築も代表3件で元と一致した。[再構築検査](rebuilt_reference_validation/summary.json)。変更後コード同士のCTestは独立証拠に混ぜない。

旧Phase51の先行全計画Phase35参照との比較では3セッションに1 ULPの差が出た。最初の例はframe66701/channel1、actual3161988845/reference3161988846。全Mapは一致。変更前の動的Phase36でも同じ差を再現し、そちらとの全PCM・Frontier・直近フレーム・OLA重みは3/3一致した。旧参照間の算術差の箇所は未特定。[元の比較失敗を保持した監査](native_reference_scope_audit.json)。許容誤差への変更はない。

## 5. 161速度の実施範囲

全161値を初期・目標の双方で検査。隣接160組×双方向×両preset＝640/640条件、640適用。重点試験には指定15遷移、昇順/降順の連続1%列、0.50/1.00境界、極端な往復、全8形式を含む。最終論理試験の要求上の初期/目標組は{len(pairs)}組だが、置換・取消も含むため全組の物理適用とは異なる。25921組、長尺全161値、実機全161値の各初期/目標適用は未実施。

## 6. Latest-Winsと要求状態

最新Pending1件＋実行中1件。旧Requested/Applied/Rejectedと高水準の操作状態を併記。Acceptedは保留受付、低水準送信成功とは区別。Appliedと、callbackが完了座標を越える時点、通常側のCompleted確認も分けた。最終論理状態集計は [MEASUREMENTS](MEASUREMENTS.json)。実機burstでは1024要求×6セッションを検査し、161速度が要求されても全要求を適用したとはしない。512適用履歴・4096操作監査の研究上限、Invalid/Duplicate/Stopped/LimitReached、旧session/入力世代、Stop/失敗時の取消を検査。

## 7. L1/L2/safe-density

Candidateは精密L1＋L2、Baselineは既存境界＋C。保護算術を独自近似に置き換えていない。論理試験でL2保持を含む適用{plan_counts['with_l2_held_frames']}件、密度切替{plan_counts['with_density_switch']}件を旧参照と照合。非EOSでは密度候補から32768入力サンプル先まで確定している条件だけを検査する。全7チャンクと非最終合成・適用・解析保留の内訳は各incremental summaryに保存。

## 8. FIFO/Callback

最終版の動的音声セッション **{measurements['final_native_passed']}/{len(native_rows)}合格**。全PCM/接頭部PCMを別に照合した。

| 条件 | 計測合格/セッション | 全PCM / 接頭部PCM一致 |
|---|---:|---:|
{native_table}

最終版の不足フレーム{totals['missing_frames']}、書込み拒否{totals['rejected_writes']}、callback期限超過{totals['callback_deadlines']}、HAL逸脱{totals['hal_misses']}、host cadence異常{totals['host_cadence_errors']}、sample異常{totals['sample_errors']}、実時間作業期限超過{totals['workgroup_deadline_misses']}。失敗一覧はMEASUREMENTSに保持する。

それ以前のV7 Candidate試験では最初のcallback sample0→1192（期待512）、host間隔24.833ms（期待10.667ms）、余分680frames/14.167msを観測。最初の要求より前に発生。FIFO/PCMは正常でもこの条件は不合格。[時計解析](native_smoke_v2/case_000/native/clock_discontinuity_analysis.json)。追加試験の成功を原因解決の証拠としない。Sandbox内の音声デバイスなし1試行は有効な音声セッションに数えない。

## 9. 実時間CPU・メモリ

Apple M1/MacBookAir10,1、16GiB、macOS26.6.2、Release arm64、内蔵出力72、48kHz/512。専用Audio Workgroup/Mach、実測優先度97、入力常駐。昇格/離脱/復元と最大3メールボックス所有権を確認。実時間C++ new合計{totals['realtime_cpp_new_calls']}、callback new合計{totals['callback_cpp_allocations']}。C/Objective-C確保全般の計測とは異なる。検証用capture配列とcallback記録配列は開始前に値初期化するが、専用の全ページ書込みタッチやmlockは行っていない。これらの物理ページ常駐やcallbackのVM fault 0を証明したとはしない。

実時間{len(workers)}ブロックの最大Wall {measurements['realtime_wall_ms']['max']:.3f}ms、最大非CPU {measurements['realtime_non_cpu_ms']['max']:.3f}ms。Wall−CPUの負値は時刻分解能によるため集計下限0とし、非CPUをすべてPreemptedと呼ばない。操作ごとの全計画試行累計CPU/Wall、要求→Map適用と提示到達の中央値/p95/p99/最大はMEASUREMENTS（ms）。要求→Map適用は中央値{measurements['request_to_map_apply_ms'].get('median',0):.3f}、p95 {measurements['request_to_map_apply_ms'].get('p95',0):.3f}、p99 {measurements['request_to_map_apply_ms'].get('p99',0):.3f}、最大{measurements['request_to_map_apply_ms'].get('max',0):.3f}ms。全速度で一定時間内の適用保証ではない。

固定Frontier受渡しは4160bytes、監査予約要素は8454144bytes、適用履歴予約要素は86016bytes（STRUCT_LAYOUT、allocator領域別）。

最大RSS {measurements['peak_rss_bytes']/1024**2:.2f}MiB（入力、検証用PCM、診断、128MiB負荷配列を含む）。Map容量推定最大{measurements['map_peak_estimate_bytes']}bytes、Snapshot計数容量最大{measurements['snapshot_peak_bytes']}bytes。allocator総量やOS全体の圧迫とは異なる。最大所有は解析{measurements['borrowed_snapshot_owners_max']}、Map{measurements['borrowed_map_owners_max']}。計画試行{measurements['planning_attempts']}、古いFrontier再計画{measurements['stale_replans']}、解析保留{measurements['analysis_deferrals']}。

スレッド標本の前後が同じRT生成区間に入ったのは{measurements['realtime_policy_sampled_blocks']}ブロック、該当標本がなかったのは{measurements['realtime_policy_unobserved_blocks']}ブロック。該当標本の優先度は97だった。未標本区間を観測済みとして埋めない。

追加OSトレースの実時間98ブロック中、既知OS状態で全区間を覆えたのは64、34はUnknown/未観測。既知区間でPhaseLocker::analyzePeaks内Zero Fillを1件（5.708µs）観測した。期限違反はなかったがページ割当0とはしない。[観測範囲](startup_trace_known_coverage.json)。元の起動時計異常は再現せず、OS原因は未確定。

## 10. 長尺・高負荷

決定論的180秒/300秒、実機180秒境界素材・300秒自然音反復を両presetで検査。CPU競合2、メモリ128MiB保持、両方、Pause/Resume、途中Stop、EOS近傍、大量置換を分けて保存。動的高負荷の判定は{'合格' if native_load else '不合格'}、動的長尺の判定は{'合格' if native_long else '不合格'}。固定長尺での期限超過も含む総合のlong_track_verified/high_load_verifiedはfalseとした。長尺の全161速度やOS全体のメモリ逼迫は未実施。入力SHA、要求位置、適用Frontier、callback、worker、容量計測を各manifest/rowsへ保存した。

## 11. Golden・CTest

Golden {sum(r['PASS'] for r in golden)}/25、Release決定論的CTest {release_total}/{release_total}（従来88＋新規3）、Debug関連 {debug_total}/{debug_total}。その後に制御テストへEOS再始動・EOS保留取消を拡充し、対象1件をRelease/Debugで再検査して合格した。[最新の制御検査](eos_pending_final/summary.json)。機能検査の通常優先度排出と、13節の実時間ストレス失敗を区別する。Debug準備時の存在しないtarget指定2件はログを保持し、正しいtargetを構築して全検査を完了した。TSANおよびASAN/UBSANでFrontier値メールボックスと借用メールボックスの4実行が合格。[競合・メモリ検査](sanitizers_final/summary.json)。

## 12. 既存製品回帰

Phase58固定PCM {sum(s['pcm_sessions'] for s in fixed_reg.values())}件、Phase57全PCM {sum(s['pcm_sessions'] for s in pcm_reg.values())}件。既存の拒否条件は別に照合した。Phase56、Phase54 cache/seek、Phase39/42/50/51はCTestでも検査。固定速度実機 {fixed_pass}/{fixed_count}、従来製品の旧/再構築EOS・smoke {legacy['passed']}/{legacy['executions']}。[既存PCM回帰](regression_final/summary.json)、[初回実機実行](device_final/summary.json)、[容量中断分の再開](device_resume_after_trace_archive/summary.json)。固定長尺180秒/2倍/CPU競合2でCandidateに作業期限超過2件、Baselineに3件を観測した。両方とも全PCM一致・FIFO不足0だが不合格。最長RT生成区間はCandidateでWall/CPUとも約49.541ms、BaselineでWall約48.877ms/CPU約48.877msで、設定周期46.44msを超えた。この区間には大きな非CPU待ちは見られないが、処理内の負荷原因や変更との因果は未確定。[時系列](DEVICE_FAILURE_TIMELINES.json)。300秒の固定速度2件は合格。旧製品の変更前バイナリCandidate smokeでFIFO不足1319フレームを観測し、全PCM一致でも不合格とした。再構築側の成功で相殺せず、因果や原因は未確定。[回帰失敗一覧](DEVICE_REGRESSION_FAILURES.json)。`fifo_underrun_free`はこの旧製品試験も含む実機全体、`dynamic_fifo_underrun_free`は最終動的行列の範囲で分けた。過去の製品host/sample異常の原因解決は主張しない。旧results、Golden、独立参照のSHAを保持した。

## 13. 未解決問題

起動直後の時計不連続1件の原因未特定。最終版の追加失敗はMEASUREMENTS一覧を参照。EOS再始動の追加検査では、実時間workerを音声周期より速く排出したReleaseに約4.8秒の非CPU区間と20秒待ち超過を観測した。周期を付けたReleaseは成功したが、Debugの実時間実行は30秒待ちを超えた。OSの予算制限が疑われるもののOS状態は未取得であり断定しない。失敗はeos_restart_diagnostic*とeos_restart_pacedへ保持。通常優先度へ復元して排出する同一プロセスEOS→別音源Play機能検査はRelease/Debugとも別に検査し、実時間性能とは区別した。旧先行全計画Phase35と動的Phase36の1 ULP差の算術位置未特定。OS状態未観測域と実時間Zero Fillあり。実際のApple API失敗とOS全体のメモリ不足は未測定（昇格前拒否・bad_alloc・計画失敗・解析/DSP失敗・入力置換/削除・取消の注入は検査）。履歴512/操作4096の研究上限あり。

容量はSTART_STATEの予算を使用。新規成功PCMの作業領域は再利用、レシピ/SHAを保存。空き容量低下で動的loadは14条件後、lifecycle/burst/materials/longは音声開始前に当初4GiBの保存下限で中断した。通常30条件と完了済みload14条件は再実行せず、残りだけを再開した。成功済みDebugビルド・派生XML・回帰行データを全バイトSHA照合後に無損失圧縮し、再生成可能な成功PCM作業領域を解放した。[整理台帳](STORAGE_COMPACTION.json)。当初4GiBは作業側の保守的予算だったため、残りの有界な保存量を再確認して再開前に下限3GiBへ更新した。[予算更新](STORAGE_REBUDGET.json)。DSP、速度行列、反復数、FIFO、PCM基準は変更していない。ユーザーの明示許可後、Instrumentsに未保存記録がないことを確認して通常終了し、関連DTServiceHubも終了した。今回の一時ktrace 1475388768bytesを136860552bytesへ無損失圧縮し、復元SHA一致と開放済みを確認して元一時ファイルを解放した。保存済みtrace bundleと過去のktraceは保持した。[圧縮・復元台帳](CURRENT_TRACE_ARCHIVE.json)。取得時のバックエンド一時トレースと保存済みtrace bundleの合計は少なくとも約1.56GBで、当初のトレース予算512MiBを超過した。最終保存量と取得時ピークを分け、予算を守れたとは報告しない。FAIL素材・固定参照・元トレース・旧Phase成果物は保持した。最終量は [STORAGE](STORAGE.json)。

## 14. Gate 2の最終判定

**B、未合格**。同一計画の品質と161速度対応を確認したが、有効な実機試験で時計異常が1件残り、固定長尺の期限超過と旧製品FIFO不足も観測した。後続の成功件数で相殺しない。`realtime_worker_safe`、`realtime_transition_verified`、`gate_2_passed` はfalse。各指標の範囲と最終値は [VERDICT](VERDICT.json)。

## 15. 次Phaseへ進めるか

Gate 3/製品統合へは進めない。次はPhase59 Fixとして起動時計異常を同じ装置・時刻条件で再現し、音声開始手順/装置時刻の原因を特定する。Zero Fillと未観測範囲も調べる。固定180秒/2倍/CPU競合2では、失敗した生成位置での詳細CPU測定と変更前実行体の同条件比較を行う。旧製品smokeのsession2/epoch2、callback270〜272のFIFO不足もOS状態を含めて調べる。PCM品質、参照、FIFO容量は維持する。解決後に同じ失敗条件と負荷・長尺・回帰を再検証する。製品化ではcache付きStop→Play、入力寿命・資源予算、装置/権限/API/UIを別途検討する。
'''
    (OUT/'REPORT.md').write_text(report)
    sizes=collections.Counter();total=0
    for p in OUT.rglob('*'):
        if p.is_file():sizes[p.suffix]+=p.stat().st_size;total+=p.stat().st_size
    extra_storage={str(folder.relative_to(ROOT)):sum(p.stat().st_size for p in folder.rglob('*') if p.is_file())
        for folder in [ROOT/'build/phase59_frozen',ROOT/'build/phase59_archives']}
    trace_archive=read('CURRENT_TRACE_ARCHIVE.json')
    saved_trace_bytes=sum(p.stat().st_size for p in (ROOT/'build/phase59_frozen/startup_trace_v1.trace').rglob('*') if p.is_file())
    budget=read('START_STATE.json')['storage_budget_bytes']
    observed_budget_bytes=dict(generated_wav=sizes['.wav'],raw_pcm_working=sizes['.f32'],
        temporary_references_upper_bound=sizes['.bin'],detailed_csv=sizes['.csv'],
        retained_results_frozen_archives=total+sum(extra_storage.values()))
    write('STORAGE.json',dict(results_bytes=total,bytes_by_extension=dict(sizes),frozen_and_archive_bytes=extra_storage,
        results_plus_frozen_and_archives_bytes=total+sum(extra_storage.values()),free_bytes=shutil.disk_usage(ROOT).free,
        baseline_budget=budget,final_observed_budget_bytes=observed_budget_bytes,
        final_budget_scope='最終保存量。全時間のピークや共用Release build全体を含むとはしない。binはMap証拠も含む参照量の上限。',
        revised_budget=read('STORAGE_REBUDGET.json'),compaction_manifest='STORAGE_COMPACTION.json',trace_bytes=saved_trace_bytes,
        trace_peak_observed_at_least_bytes=trace_archive['original_bytes']+saved_trace_bytes,trace_peak_budget_maintained=False,
        current_temporary_trace_archive=trace_archive,previous_assets_deleted=False,successful_working_pcm_reused=True))
    print('REPORT written: B; deterministic',measurements['dynamic_deterministic_sessions'],'native',len(native_rows),'failures',len(failures))
if __name__=='__main__':main()
