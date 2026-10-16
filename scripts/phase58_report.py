"""Summarize completed evidence without upgrading partial gates to PASS."""
import json,re,statistics,time
from pathlib import Path
from phase57_study import ROOT,sha
base=ROOT/'results/phase58'
def read(path):return json.loads((base/path).read_text())
def ctest(name):
    text=(base/name).read_text();matches=re.findall(r'(\d+)% tests passed, (\d+) tests failed out of (\d+)',text)
    assert matches,name
    _,failed,total=map(int,matches[-1]);return dict(passed=total-failed,failed=failed,total=total)
assert read('legacy_realtime_complete.json')['done']
assert 'exit' in read('notification_lifecycle_complete.json')
assert not (base/'VERDICT.json').exists() and not (base/'REPORT.md').exists()
pcm={s:read('pcm58_'+s+'/summary.json') for s in ('short','all_speeds','long')}
matrix_lags=[]
for suite in pcm:
    for line in (base/('pcm58_'+suite)/'rows.jsonl').read_text().splitlines():
        for check in json.loads(line).get('checks',[]):
            if check.get('result') and 'ready_notification_lag_s' in check['result']:matrix_lags.append(check['result']['ready_notification_lag_s'])
reg57={s:read('regress57_'+s+'/summary.json') for s in ('stage1','stage2','long','natural','rejections')}
golden=read('golden25/summary.json');det=ctest('deterministic_ctest.log');debug=ctest('debug_ctest.log');rt=ctest('legacy_realtime_ctest.log')
startup_scope='startup_after_ready_fix' if (base/'startup_after_ready_fix/statistics.json').exists() else 'startup_final'
protected=read('protected_assets.json');csv_audit=read('measurement_audit.json');startup=read(startup_scope+'/statistics.json')
native=[]
for scope in ('startup_final','lifecycle_load_final','native_gate_product_final','native_long_final','notification_lifecycle_final','startup_after_ready_fix','reproduce_after_ready_fix'):
    for p in sorted((base/scope).rglob('summary.json')):
        d=json.loads(p.read_text())
        if 'callback_calls' in d:
            if not d['analysis_done']:
                for key in ('analysis_cpu_s','snapshot_peak_bytes','snapshot_copy_bytes'):d[key]=None
            native.append(dict(path=str(p.relative_to(base)),data=d))
expected_native_sessions=168+(60 if (base/'startup_after_ready_fix/summary.json').exists() else 0)+(20 if (base/'reproduce_after_ready_fix/summary.json').exists() else 0)
assert len(native)<=expected_native_sessions,'Unexpected extra sessions'
keys=('callback_deadlines','hal_misses','host_missing','host_backwards','host_cadence_errors','sample_errors','callback_formats','callback_records_dropped')
totals={k:sum(n['data'][k] for n in native) for k in keys+('callback_calls','missing_frames','missing_calls','rejected_writes','callback_cpp_allocations','pcm_mismatches')}
maxima={k:max(n['data'][k] for n in native) for k in ('callback_max_ns','callback_p95_ns','callback_p99_ns','max_consecutive_missing','max_dsp_wall_s','max_dsp_cpu_s','max_publication_gap_s','peak_rss_bytes')}
final_native=dict(sessions=len(native),expected_sessions=expected_native_sessions,missing_measurements=expected_native_sessions-len(native),passed=sum(bool(n['data']['PASS']) for n in native),measurement_valid=sum(bool(n['data']['measurement_valid']) for n in native),pcm_prefix_exact=sum(bool(n['data']['pcm_prefix_exact']) for n in native),pcm_complete_exact=sum(bool(n['data']['pcm_complete_exact']) for n in native),totals=totals,maxima=maxima,records=native)
legacy_native=[]
for preset in ('candidate','baseline'):
    p=base/('legacy_native_'+preset)/'summary.txt';values=dict(l.split('=',1) for l in p.read_text().splitlines() if '=' in l);legacy_native.append(values)
frozen=read('START.json')['references'];frozen_ok=all(sha(v['path'])==v['sha256'] for v in frozen.values()) and sha(ROOT/'build/phase57_frozen/reference')=='461c26d10b0fd8a781cbffcbbab49072f501e02172e2a7c2f26e3e49a0253a1e' and sha(ROOT/'build/phase58_frozen/product_reference')==read('frozen_product_reference.json')['sha256']
measurement_version=read('native_measurement_version.json');frozen_ok &= sha(measurement_version['path'])==measurement_version['sha256']
quality=all(p['PASS'] for p in pcm.values()) and all(p['PASS'] for p in reg57.values()) and all(g['PASS'] for g in golden) and frozen_ok
latency=all(s.get('native_cold_first_callback_s') and s.get('legacy_cold_first_callback_s') and s['native_cold_first_callback_s']['n']==5 and s['legacy_cold_first_callback_s']['n']==5 and s['native_cold_first_callback_s']['median']<s['legacy_cold_first_callback_s']['median'] for s in startup)
startup_rows=read(startup_scope+'/rows.json')
legacy_startup_error_keys=('callback_deadlines','hal_misses','host_missing','host_backwards','host_cadence_errors','sample_errors','format_errors','missing_frames','rejected_writes')
legacy_startup_quality=all(all(d and not any(d[k] for k in legacy_startup_error_keys) and not d['error'] for d in r['legacy']) for r in startup_rows)
startup_conditions=all(r['PASS'] and all(s and s['startup_timing_valid'] and (s['device_id'],s['device_rate'],s['device_buffer_frames'])==(72,48000,512) for s in r['legacy']+r['native']) and all(s['windowed'] and not s['route_stopped'] for s in r['native']) for r in startup_rows)
startup_conditions &= legacy_startup_quality
latency &= startup_conditions
legacy=det['failed']==0 and all(g['PASS'] for g in golden) and rt['failed']==0 and all(v['VERDICT']=='PASS' for v in legacy_native)
verdict=dict(verdict='B',gate_1='FAIL_UNRESOLVED_NORMAL_LOAD_FIFO_UNDERRUN',gate_2='NOT_IMPLEMENTED',gate_3='PARTIAL',gate_4='NOT_ADOPTED',
 fixed_speed_realtime_verified=False,progressive_pcm_exact=quality,dynamic_speed_verified=False,all_161_speeds_supported=False,all_161_speeds_transition_tested=False,latest_wins_verified=False,fifo_underrun_free=False,
 callback_deadline_verified=all(totals[k]==0 for k in keys) and all(n['data']['measurement_valid'] for n in native),high_load_verified=False,startup_latency_improved=latency,stop_resume_eos_verified=False,route_change_verified=False,legacy_product_regression_passed=legacy,
 historical_realtime_failures_preserved=protected['PASS'] and frozen_ok,product_integration_ready=False,merodoa_integration_performed=False,
 fixed_all_161_speeds_pcm_verified=pcm['all_speeds']['PASS'],fixed_pcm_sessions=sum(x['pcm_sessions'] for x in pcm.values()),phase57_pcm_regression_sessions=sum(x['pcm_sessions'] for x in reg57.values()),golden_pass=sum(bool(g['PASS']) for g in golden),
 callback_cpp_allocation_measured=all(n['data']['allocation_measured'] for n in native),callback_cpp_allocations=totals['callback_cpp_allocations'],targeted_fixed_lifecycle_pass=read('lifecycle_load_final/summary.json')['PASS'],long_native_pass=read('native_long_final/summary.json')['PASS'],cold_startup_scope='MIX 30/180/300s, 0.50, Candidate/Baseline, each 5 paired runs, callback latency only',warm_startup_improved=False,
 physical_audible_latency_measured=False,physical_route_or_sample_rate_change_tested=False,systemwide_memory_pressure_tested=False,dynamic_transition_pcm_sessions=0,product_default_changed=False,public_api_changed=False,shared_core_extended=True,full_stretched_pcm_disk_cache_added=False,private_source_byte_snapshot_added=True,private_source_snapshot_limit_bytes=512*1024*1024,
 remaining_failures=['通常負荷の2.00倍CandidateでFIFO不足が複数回再現。入力監視分離・非公開入力版でも20回中1回不足10240フレーム。','動的変更・Latest-Wins・速度変更中のライフサイクルは未実装。','物理装置変更・レート変更・OS全体のメモリ逼迫は未検証。'],created_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
verdict['notification_lifecycle_fix_verified']=read('notification_lifecycle_final/summary.json')['PASS']
verdict['ready_notification_verified']=read('ready_stress/summary.json')['PASS']
verdict['ready_notification_matrix_sessions']=len(matrix_lags)
verdict['ready_notification_matrix_max_lag_s']=max(matrix_lags) if matrix_lags else None
verdict['ready_notification_verified'] &= len(matrix_lags)==sum(x['pcm_sessions'] for x in pcm.values()) and bool(matrix_lags) and max(matrix_lags)<1
verdict['startup_comparison_evidence']=startup_scope
verdict['warm_startup_improved']=startup_conditions and all(s.get('native_restart_first_callback_s') and s.get('legacy_restart_first_callback_s') and s['native_restart_first_callback_s']['n']==5 and s['native_restart_first_callback_s']['median']<s['legacy_restart_first_callback_s']['median'] for s in startup)
verdict['playback_public_api_changed']=verdict.pop('public_api_changed')
verdict['phase57_experimental_interface_extended']=True
verdict['legacy_product_binaries_identical']=all(r['binary_identical'] for r in read('product_binary_comparison.json'))
verdict['startup_comparison_conditions_verified']=startup_conditions
verdict['startup_legacy_audio_diagnostics_pass']=legacy_startup_quality
verdict['all_161_speeds_supported_scope']='再生中の161段階変更を含む製品対応。固定速度の対応はfixed_all_161_speeds_pcm_verifiedを参照。'
verdict['callback_deadline_scope']='新経路の測定版160セッションと最終版88セッション。従来製品の計測FAILは別記。'
verdict['callback_deadline_verified'] &= len(native)==expected_native_sessions
verdict['targeted_fixed_lifecycle_pass'] &= verdict['notification_lifecycle_fix_verified']
aggregate=dict(pcm58=pcm,pcm57=reg57,deterministic=det,debug=debug,legacy_realtime=rt,legacy_native=legacy_native,protected_assets=dict(checked=protected['checked'],PASS=protected['PASS']),frozen_references_unchanged=frozen_ok,csv_audit=dict(sessions=csv_audit['sessions'],callbacks=csv_audit['callbacks'],PASS=csv_audit['PASS']),native_final=final_native,startup=startup,native_measurement_version=measurement_version,notification_fix_binary=read('notification_lifecycle_final/manifest.json')['binaries'])

lines=['# TimeStretchLab Phase 58：実時間増分再生の検証結果','',
'## 判定：B（条件付き成立）','',
'独立した固定速度の増分実時間経路を実装し、初回起動を実機で短縮できた。一方、通常負荷でもFIFO不足が再現しGate 1は未達。動的速度変更は実装・成功扱いへ進めず、製品既定経路とMerodoaは変更しない。音質・FIFO・閾値は緩めていない。','',
'## 1. 実装した機能','',
'解析workerとDSP workerを分離し、共有不変snapshotの最新1件、既存SPSC FIFO、AVAudioEngine/SourceNodeを接続した。世代/セッション/絶対PCM位置、背圧、真のEOS、失敗、取消、解放順を管理する。入力の全内容SHAと同時に非公開FDへ元WAVのバイト列を複製し、元パス監視を解析側へ限定した。callbackはFIFO取得・比較・事前確保した診断記録だけを行う。','',
'CandidateはFIFO容量/先行量/生成ブロック16,384/16,384/2,048、Baselineは16,384/12,288/2,048、出力ゲイン0.5。Baselineの蓄積上限も12,288へ制限する。','',
'## 2. 変更ファイルと既存経路','',
'新規実装は`src/prototype/Phase58RealtimePipeline.{h,cpp}`、`Phase58Diagnostics.h`、`Phase58Check.cpp`、`Phase58Native.mm`、`Phase58LegacyStartup.cpp`、`Phase58ProductReference.cpp`。テストは`tests/Phase58Tests.cpp`と`Phase58PcmSmoke.py`。実行・再現・監査スクリプトは`scripts/phase58_*.py`。設計資料は`docs/PHASE58_*.md`。CMakeへ独立ターゲットと決定論的2テストを追加した。','',
'既存ソースの拡張はPhase57の明示的な製品出力長指定と任意段階計測、Phase36内部の計測先ポインター設定2か所だけ。FFT/位相/OLA/FIRの算術は変更しない。Phase57の既定map終端長は保持する。PlaybackEngine/MacPlaybackEngineの公開APIと既定値は変更しない。','',
'Release全ビルド後の従来`phase54_native`と`phase39_reference`は、開始時に保存した各バイナリとSHA-256まで一致した（`product_binary_comparison.json`）。製品リンクにPhase58/Phase57の実験ライブラリは追加していない。','',
'### 出力長の契約差を発見','',
'MIX10秒・0.50倍ではPhase57のmap終端参照は881,380フレームだが、実際のPhase54製品は882,000フレームだった。新経路は製品式`llround(inputFrames * timeRatio)`を合成前に明示し、最終出力882,000・SHA `b92c90d1536ef125bf3359fd27f85c52029b11ff68d2013bfc455afb17e8f0c2`と一致した。`product_length_counterexample.log`と`product_smoke/`を保存。Phase57契約の初期実機結果を製品互換成功へ流用しない。','',
'## 3. 固定速度PCM一致','',
'独立参照はPhase57以前のPhase36ソース（ec087019、SHA `4ffec7c4db196f51e89bd4ebaf336020ae71d0969c31393a40752b4a37ed3899`）を優先リンクした`build/phase58_frozen/product_reference`。参照バイナリSHAは`3a3b04454f754c35afa4cac121a726fa31c44a6854761a7de5f71aa057f2a957`。Float32の全生ビット・出力長・raw SHAを比較し、許容誤差を使わない。','',
'| 試験 | 参照条件数 | 全PCMセッション | 結果 |','| --- | ---: | ---: | --- |']
for s,d in pcm.items():lines.append(f"| pcm58_{s} | {d['passed']+d['failed']} | {d['pcm_sessions']} | {'PASS' if d['PASS'] else 'FAIL'} |")
lines += ['',f"合計{verdict['fixed_pcm_sessions']:,}セッション。短尺は全8形式・境界/持続/連鎖・代表7速度・両preset・3チャンク。161速度は全8形式・両preset・2チャンク。長尺は3分境界/5分連鎖・代表7速度・両preset・2チャンク。`native_gate_product_final`の62条件には別途、同じ参照の全量FIFO一致確認がある。消費側が待つ試験を実時間成功には含めない。",'',
'## 4. 動的速度変更と5. 全161速度の範囲','',
'固定構築・全PCM一致は0.40〜2.00倍、0.01刻みの161速度を網羅した。再生中の変更は未実装で比較0件。固定map交換は行わず、Latest-Wins、要求ID/状態、L1/L2、safe-density、Phase50保護を緩めない。同じ論理出力位置・要求順・適用境界を再現する今後の比較設計は`docs/PHASE58_SPEED_TRANSITION.md`。既存製品の動的変更回帰と新経路の対応を混同しない。','',
'## 6. FIFO/Callback実時間試験','',
'環境はmacOS 26.6.2（25G83）arm64、Xcode 27.0（27A266a）、Apple Clang 21.0.0、Release。MacBookAir10,1、Apple M1、8コア、メモリ16GiB。内蔵スピーカー、device 72、48kHz/2ch/512フレーム。実機出力と重いビルド・DSP試験は直列。各manifestに入力・実行バイナリSHAを保存した。','',
f"新経路の実機{len(native)}セッション中、総合成功{final_native['passed']}、測定条件成立{final_native['measurement_valid']}、PCM prefix一致{final_native['pcm_prefix_exact']}、EOSまで全PCM一致{final_native['pcm_complete_exact']}。測定版160件は起動60・形式/30秒MIX 62・ライフサイクル/負荷34・長尺4。修正後はライフサイクル8件を実施し、最終起動再測定60件・同一不足条件20件は別版の結果として追加する。window再生は全PCM一致件数へ含めない。",'',
'最初の160セッションは固定した測定版（`native_measurement_version.json`）。その後、装置通知用フラグの所有権、Ready/Cancelのmutex同期、未完了統計のnull表示を修正した。音声callback・DSP合成の算術とFIFO設定は変えていない。現在版と測定版のバイナリSHAを区別し、160件を現在版の実測件数とは呼ばない。','',
'| 指標 | 測定版160＋通知修正版8セッション合計/最大 |','| --- | ---: |']
for k,v in totals.items():lines.append(f'| {k}（合計） | {v:,} |')
for k,v in maxima.items():lines.append(f'| {k}（最大） | {v} |')
lines += ['',f"callback CSVの独立再計算：{csv_audit['sessions']}セッション、{csv_audit['callbacks']:,}回、{'PASS' if csv_audit['PASS'] else 'FAIL'}。不足・連続不足・消費位置・最大/p95/p99・記録件数を再照合した。C++確保はTLS付きnew系で測定し、C malloc/OS内部全体を測ったものではない。",'',
'### 通常負荷の失敗は未解決','',
'`native_product`でPCM16 Stereo 48kHz、4秒境界素材、2.00倍Candidateに不足2,048フレームが発生。同じ入力の`reproduce_fifo`は旧固定製品5/5成功、新経路9/10成功（失敗1,024フレーム）。`reproduce_stages`は19/20成功（失敗24,576フレーム）。元パス監視を分離し入力を非公開複製しても`reproduce_private_input`で19/20成功、失敗時10,240フレーム/20 callback/最大連続6,656フレーム。いずれもraw PCMは末尾まで一致していた。','',
'非公開入力版の失敗ではDSP1ブロックの経過224.95ms、CPU27.92ms、その位相区間は経過201.70ms、CPU23.31ms。解析は最初のcallback前に完了。callback最大37,917ns、期限/HAL/時刻/形式/C++確保異常0でもFIFO不足が起きた。非CPU時間の内訳は未測定で、OS非実行や内部待ちを断定しない。最終版の再試験が成功しても未解決事象を取り消さない。','',
'初期の`native_gate_v2`はBaseline蓄積上限修正前、`native_gate_final`はPhase57 map終端長であり、中断結果とSCOPEを保持し最終製品互換件数へ合算しない。','',
'### 高負荷・長尺・ライフサイクルの限界','',
'CPU2 thread＋128MiB保持、30秒MIXの9固定速度を各3秒、無音/持続/連続attack/連鎖のEOS、両presetを試験した。Pause/Resume、EOS→新規Play、Stop→新規Play、安全停止の模擬を測定。長尺実機は3分境界Candidate0.40/Baseline2.00、5分連鎖Candidate2.00/Baseline1.00の4条件をEOSまで検証。全速度×全形式の長尺実時間保証ではない。OS全体のメモリ逼迫、物理装置・レート変更、速度変更中の停止/再開は未検証。','',
'3分境界0.40倍Candidateは約450秒の実機再生で19,845,000フレーム一致。最初のcallback約164msに対し解析完了約809msで、全曲解析前の正しい実機供給を確認した。一方、5分連鎖2.00倍Candidateは解析完了約937msまでMapが増えず、最初のcallback約1,006ms、EOS前公開0フレーム。特殊素材の待機を起動高速化の成功へ含めない。','',
'入力変化は単体試験で解析前/解析後の切詰め、削除、置換、権限変更、その後の新セッション復旧を確認する。解析待ち中の取消、FIFO背圧中の停止、同一入力の複数セッションも検証する。','',
'## 7. 起動時間の実測','',
'同一入力・preset・0.50倍・装置・Releaseで各5回。入力MIXは44.1kHz/Float32/Stereoの30/180/300秒。受付相当の開始から最初の有効PCM callbackまで。単位ms。各セルは中央値 / 最大 / 母標準偏差。ColdとStop→Playを分け、失敗を除去して集計しない。Phase57の約52msは290秒PCM16のオフライン先行量相当であり、直接比較しない。','',
'| 音源 | preset | 従来Cold | 新経路Cold | 従来Stop→Play | 新経路Stop→Play |','| --- | --- | ---: | ---: | ---: | ---: |']
for s in startup:
    vals=[]
    for k in ('legacy_cold_first_callback_s','native_cold_first_callback_s','legacy_restart_first_callback_s','native_restart_first_callback_s'):
        d=s[k];vals.append((' / '.join(f'{d[v]*1000:.2f}' for v in ('median','max','population_stddev'))+('' if d['n']==5 else f" (n={d['n']})")) if d else '未計測')
    lines.append(f"| {s['seconds']}秒MIX | {s['preset']} | "+' | '.join(vals)+' |')
lines += ['','Coldの中央値は6条件とも短縮したが、キャッシュhitの従来Stop→Playより新規解析する新経路の再開は遅い。解析キャッシュは新経路へ未統合。入力の全SHA・非公開コピーを新経路の時間から除外していない。参照PCMの事前読込みは検証器だけの作業で原点前。Mach/steady接続の不確かさも保存し、1ms以下を有効条件とした。','',
'Play→callbackの統計は`startup_final/statistics.json`、Readyや解析・各公開境界・資源の統計は`startup_final/stage_resource_statistics.json`。従来の段階情報は所要時間であり、最初の閉鎖eventの絶対時刻は未計測。新経路の各段階はsummaryへ保存する。callback到達は物理的な可聴開始ではない。ループバック未実施。Coldは新規プロセス・解析キャッシュmissを意味し、OSファイルキャッシュは消去しない。参照生成後に各回A→Bで測定し、装置・OS履歴への順序効果を独立評価していない。','',
'## 8. CPU・メモリ','',
'Cold準備と約1秒の実機再生を含むプロセスCPU時間とプロセス生存中Peak RSSの中央値。検証用の記録出力などの費用も含む。新経路の検証器は全参照PCM・記録領域を追加するため製品DSP単独のメモリ差ではない。','',
'| 音源/preset | 従来CPU秒 | 新経路CPU秒 | 従来RSS MiB | 新経路RSS MiB | 参照PCM MiB | 入力複製MiB |','| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
rows=read(startup_scope+'/rows.json')
for s in startup:
    group=[r for r in rows if r['seconds']==s['seconds'] and r['preset']==s['preset']]
    n=next((r['native'][0] for r in group if r['native'][0]),{})
    def median_cell(key,scale=1,digits=3):
        d=s.get(key);return f"{d['median']*scale:.{digits}f}" if d else '未計測'
    values=[median_cell('legacy_cold_process_cpu_s'),median_cell('native_cold_process_cpu_s'),median_cell('legacy_cold_peak_rss_bytes',1/1048576,1),median_cell('native_cold_peak_rss_bytes',1/1048576,1)]
    values += [f'{n[k]/1048576:.1f}' if n.get(k) is not None else '未計測' for k in ('reference_bytes','source_snapshot_bytes')]
    lines.append(f"| {s['seconds']}秒/{s['preset']} | "+' | '.join(values)+' |')
lines += ['','入力複製は一時ストレージとOSページキャッシュを消費する。上限512MiBで、曲長に比例する。伸縮済み全PCMディスクキャッシュは追加していない。解析CPU/監視込みthread CPU、DSP advance CPU/thread全CPU、待機・snapshot所有量は各summaryに保存する。従来側のpublished worker cycle CPUは公開ブロックの部分和であり、thread全量と比較しない。未計測の従来callback確保はnull。','',
'起動試験の5分MIXでは17セッションが解析完了前に停止した。raw summaryの`analysis_cpu_s`/snapshot統計は`analysis_done=false`時の初期値0であり、0 CPU/0 byteの実測ではない。`final_summary.json`ではnullへ正規化し、段階統計も解析完了した実行だけを母数にする（各nを保存）。原記録と初期集計を保持する。process/thread CPUは停止までの実測区間費用であり、未処理の残りを含む全曲総量ではない。','',
'## 9. ビルド・Golden・既存回帰','',
f"Release全ターゲット・別領域のarm64 Debug全ターゲットをビルドした。決定論的CTest {det['passed']}/{det['total']}、関連Debug CTest {debug['passed']}/{debug['total']}、Golden {verdict['golden_pass']}/25。Phase56増分解析、Phase54 cache/seek、既存動的計画・境界・densityのテストを含む。",'',
'| Phase57回帰 | 全PCMセッション | 一致拒否条件数 | 結果 |','| --- | ---: | ---: | --- |']
for s,d in reg57.items():lines.append(f"| {s} | {d['pcm_sessions']:,} | {d['matched_rejections']} | {'PASS' if d['PASS'] else 'FAIL'} |")
lines += ['',f"Phase57合計{verdict['phase57_pcm_regression_sessions']:,}全PCM回帰。元のmap終端契約の固定参照（SHA `461c26d10b0fd8a781cbffcbbab49072f501e02172e2a7c2f26e3e49a0253a1e`）を使い、製品長参照へ置き換えていない。",'',
f"従来製品の実機smoke（シーク・速度変更・Pause/Resume・Stop/Play）は{sum(v['VERDICT']=='PASS' for v in legacy_native)}/2。既存実時間CTestは{rt['passed']}/{rt['total']}、不合格{rt['failed']}。過去Phase54のphase44 FAIL（最大起床遅れ42.1952ms）はそのまま保存し、同一条件・閾値の今回ログを`legacy_realtime_ctest.log`へ保存。故障注入検出のテスト成功を通常再生成功とはしない。",'',
f"元HEAD `88d5394c3d48970b14807c2d5151e4a3a4f86a2b`、main、開始時clean。既存資産{protected['checked']:,}件のGit blob照合は{'PASS' if protected['PASS'] else 'FAIL'}。例外はCMake、Phase36内部ヘッダー、Phase57合成cpp/hのみ。Phase53〜57結果・Golden・旧参照を上書きしていない。固定参照ハッシュ再確認は{'PASS' if frozen_ok else 'FAIL'}。最終バイナリ・ビルド設定・製品link内容は`final_binaries.json`と`build_settings.json`。",'',
'## 10. リスク、11. 製品統合、12. 次Phase','',
'主な未達は通常負荷での供給停止、動的161段階変更と同一論理条件でのPCM比較、Latest-Wins、物理装置/レート変更、速度変更中のライフサイクル、キャッシュ共有、OS全体の資源圧迫。FIFO不足はraw PCM一致だけでは検出できず、最終版の成功例だけで安定性保証へ拡張できない。','',
'Gate 1未達、Gate 2未実装、Gate 3部分検証、Gate 4採用不可。公開API/既定製品経路/Merodoaは維持する。非同期準備API、状態・世代・通知・キャッシュ寿命の設計案と移行条件は`docs/PHASE58_PRODUCT_HANDOFF.md`。','',
'Phase58 Fixでは保存済み入力の2.00倍CandidateをAudio System Traceで調べ、非実行と内部待ちを切り分ける。通常pthreadのQoS指定だけでは足りていない。リアルタイムworker/Audio Workgroup、事前確保、有界同期、I/O分離を検証し、先行量や品質を緩めずGate 1を再評価する。その後に継続DSPへPhase39動的契約を接続し、要求の論理位置を固定した参照比較器・161速度網羅・実機負荷試験を進める。物理装置試験と公開API統合はその後とする。','',
'## 再現用コマンド例','',
'各`--output`には存在しない新規パスを指定する。ネイティブ再生と重い試験を同時実行しない。','',
'```sh',
'python3 scripts/phase58_study.py --suite all_speeds --output results/phase58/recheck_161',
'python3 scripts/phase58_reproduce.py --output results/phase58/recheck_underrun --repeats 20 --legacy-repeats 5',
'python3 scripts/phase58_native_validation.py --suite long --output results/phase58/recheck_native_long',
'```','',
'不足再現driverの終了コードだけで合格判定しない。各`rows.json`/`summary.json`とnative summaryのPASS・PCM・FIFO・時刻を参照する。保存済み結果は再実行先にしない。','']
lines=[s.replace('`startup_final/statistics.json`',f'`{startup_scope}/statistics.json`').replace('`startup_final/stage_resource_statistics.json`',f'`{startup_scope}/stage_resource_statistics.json`').replace('起動試験の5分MIXでは17セッション','初期起動試験の5分MIXでは17セッション').replace('| 指標 | 測定版160＋通知修正版8セッション合計/最大 |',f'| 指標 | 保存した実機{len(native)}セッション合計/最大 |').replace('Coldの中央値は6条件とも短縮したが、キャッシュhitの従来Stop→Playより新規解析する新経路の再開は遅い。','Coldの同一条件比較は'+('6条件とも中央値を短縮した。' if latency else '改善確認の条件を満たさなかった。')+'Stop→Playはキャッシュ条件が異なるため上表の各条件で比較する。') for s in lines]
lines += ['','従来Candidate実機のFAIL内訳：raw PCM/FIFO/処理期限はPASSだったが、callback 2でhost進行誤差12,069,728ns（約12.07ms）、sample進行誤差532フレームを検出した。`legacy_native_candidate_clock_analysis.json`に既存Phase46基準による再計算を保存。BaselineはPASS。今回の既存実時間CTest 2/2成功だけで、この実機FAILを取り消さない。','',
'## Ready通知の修正と最終版の追加確認','',
'修正前の速度行列では、準備は約17〜39msで完了しているのに約60秒待つケースを23件検出した。元のPCM比較PASSは通知期限の成功を意味しない。`ready_wait_counterexamples.json`、`pcm58_all_speeds_before_ready_fix`、当時のバイナリとソースを保持する。Ready/Cancelledの更新を条件変数の待機と同じmutexで保護し、predicate確認と待機開始の間の通知取りこぼしを防いだ。callbackのmutexや品質・FIFO設定は変更しない。','',
f"修正後の短尺EOS反復：{read('ready_stress/summary.json')['sessions']}セッション、PCM/通知 {'PASS' if read('ready_stress/summary.json')['PASS'] else 'FAIL'}、最大通知遅れ{read('ready_stress/summary.json')['notification_lag_max_s']*1000:.3f}ms。1秒の検出基準は60秒通知落ちを検出する機能試験であり、音声callbackの期限やPCM許容誤差ではない。",'',
'測定版160セッションの後、通知用フラグの所有権とReady/Cancel同期、未完了統計のnull表示を修正した。`notification_lifecycle_final`の8セッションはこの版で再確認した。最初の160件を現在のバイナリの計測へ読み替えない。','']
if startup_scope=='startup_after_ready_fix':
    lines += ['最終版の起動比較をさらに30組・新経路60セッションで再実行した。上の起動/CPU表はこの最終版の値を使用し、初期測定を`startup_final`へ保持する。同じ通常負荷不足条件を20回追加で再実行し、成功/失敗を`reproduce_after_ready_fix`へ全件保存した。','',
        f"最終版同条件再実行：{read('reproduce_after_ready_fix/summary.json')['progressive_pass']}/20成功。準備通知の修正だけでは、再生中の位相処理区間で生じた非CPU時間の原因を解消した証明にはならない。Gate 1と動的実装の保留は維持する。",'']
(base/'REPORT.md').write_text('\n'.join(lines))
(base/'final_summary.json').write_text(json.dumps(aggregate,ensure_ascii=False,indent=2)+'\n')
(base/'VERDICT.json').write_text(json.dumps(verdict,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:verdict[k] for k in ('verdict','fixed_pcm_sessions','phase57_pcm_regression_sessions','golden_pass','callback_deadline_verified','legacy_product_regression_passed')},ensure_ascii=False))
