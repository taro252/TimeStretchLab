import json,sys,statistics,xml.etree.ElementTree as ET,hashlib,subprocess,platform
from pathlib import Path
ROOT=Path.cwd();RUN=ROOT/'build/phase62_fix/run_01';FINAL=RUN/'final_v9';E=FINAL/'evidence';OUT=ROOT/'results/phase62_fix'
sys.path.insert(0,str(ROOT/'scripts'));from phase62_evidence import identity,source_manifest,aggregate

def load(p):return json.loads(p.read_text()) if p.is_file() else None
def jsonl(p):return [json.loads(line) for line in p.read_text().splitlines()] if p.is_file() else []
def range_of(values):
 values=sorted(values)
 if not values:return None
 def q(f):
  pos=(len(values)-1)*f;lo=int(pos);hi=min(lo+1,len(values)-1);return values[lo]+(values[hi]-values[lo])*(pos-lo)
 return dict(n=len(values),min=values[0],median=q(.5),p95=q(.95),max=values[-1],mean=statistics.mean(values))
def suites():
 result={}
 for folder in E.iterdir():
  if folder.is_dir() and (folder/'LEDGER.json').is_file():
   a=aggregate(folder);plan=load(folder/'EXPECTED.json');kinds={c['id']:c['kind'] for c in plan['cases']}
   result[folder.name]=dict(counts=a['counts'],expected=a['expected'],PASS=a['PASS'],gates=a['gates'],gate_coverage=a['gate_coverage'],source_sha256=plan['provenance']['source']['sha256'],ledger=identity(folder/'LEDGER.json'),by_kind={})
   for kind in set(kinds.values()):
    rows=[row for row in a['cases'] if kinds[row['id']]==kind];result[folder.name]['by_kind'][kind]={s:sum(row['status']==s for row in rows) for s in ('PASS','FAIL','NOT_RUN','INCOMPLETE')}
   result[folder.name]['exceptions']=[dict(id=r['id'],status=r['status'],gates=r['gates'],reasons=r.get('reasons'),log=str(folder/(r['id']+'.log'))) for r in a['cases'] if r['status']!='PASS']
 return result

def matrix(name):
 folder=E/name;plan=load(folder/'EXPECTED.json');data=load(folder/'LEDGER.json')
 if not plan or not data:return None
 actual={r['id']:r for r in data['cases']};rows=[]
 for case in plan['cases']:
  if case['kind']!='native':continue
  measured=load(folder/case['result']);row=dict(id=case['id'],status=actual[case['id']]['status'],gates=actual[case['id']]['gates'],result=measured)
  rows.append(row)
 return dict(expected=len(rows),functional_pass=sum(r['gates']['functional'] is True for r in rows),realtime_pass=sum(r['gates']['realtime'] is True for r in rows),cycles=sum(r['result']['cycles'] for r in rows if r['result']),rows=rows)

def ctest(config):
 p=E/(config+'_ctest')/'ctest.xml'
 if not p.is_file():return None
 rows=ET.parse(p).getroot().findall('.//testcase');return dict(total=len(rows),passed=sum(not any(r.find(t) is not None for t in ('failure','error','skipped')) for r in rows),names=[r.get('name') for r in rows])

def pcm(name):
 folder=E/name;data=load(folder/'LEDGER.json')
 if not data:return None
 return {group:dict(expected=len(rows),passed=sum(r['status']=='PASS' for r in rows),statuses={s:sum(r['status']==s for r in rows) for s in ('PASS','FAIL','NOT_RUN','INCOMPLETE')}) for group,rows in [('finite',[r for r in data['cases'] if r['id'].endswith(('_candidate','_baseline'))]),('reused',[r for r in data['cases'] if r['id'].endswith('_reuse')])]}

s=suites();matrices={name:matrix(name) for name in ('release_native','release_short','release_longA','release_clock','release_controls','release_long','release_step1','debug_native','debug_controls','debug_long')}
quality_files=sorted((E/'release_quality').glob('*/metrics.json'))
quality=[load(p) for p in quality_files];rms={}
for ms in (10,25,100):
 values=[v for r in quality for w in r['windows'] if w['milliseconds']==ms for v in w['rms_change_db'] if v is not None];rms[str(ms)]=range_of(values)
q=dict(cases_measured=len(quality),passed=sum(r['PASS'] for r in quality),bit_exact=sum(r['bit_exact'] for r in quality),finite=sum(r['finite'] for r in quality),rms_change_db=rms,peak_gain05=max((r['output_peak_gain05'] for r in quality),default=None),unexpected_zero_frames=sum(r['unexpected_zero_frames'] for r in quality),subjective_listening=None,acoustic_loopback=None,real_recorded_piano=None)
old=load(RUN/'baseline_long/cycles_1000/result.json');new=load(E/'release_long/cycles_1000/result.json')
comparison=dict(old=old,new=new,normal_incremental=None,n_per_condition=1)
if old and new:
 comparison.update(old_cpu_percent=old['process_cpu_s']/old['wall_s']*100,new_cpu_percent=new['process_cpu_s']/new['wall_s']*100,cpu_seconds_reduction_percent=(1-new['process_cpu_s']/old['process_cpu_s'])*100,old_preparations=old['preparations'],new_preparations=new['preparations'])
 samples=jsonl(E/'release_long/cycles_1000/rss_samples.jsonl');interval=[]
 for a,b in zip(samples,samples[1:]):
  if b['wall_s']>a['wall_s']:interval.append((b['cpu_s']-a['cpu_s'])/(b['wall_s']-a['wall_s'])*100)
 comparison['new_100_cycle_interval_cpu_percent']=range_of(interval);comparison['new_thread_samples']=[r.get('threads') for r in samples];comparison['distribution_unit']='100周期ごとの区間。1周ごとの分布ではない。n=1走行。'
clock=[]
for p in E.rglob('clock_recomputed.json'):
 r=load(p);clock.append(dict(path=str(p.relative_to(ROOT)),**r))
summary=dict(schema=1,base_head='d25433c88a1bae83b89168a26f1c6c9d8053a644',source_sha256=source_manifest(ROOT)['sha256'],frozen_source_sha256=load(FINAL/'FROZEN_SOURCE.json')['sha256'],source_unchanged=source_manifest(ROOT)['sha256']==load(FINAL/'FROZEN_SOURCE.json')['sha256'],public_go=False,committed=False,pushed=False,suites=s,ctest=dict(release=ctest('release'),debug=ctest('debug')),exact=load(E/'release_exact/exact/summary.json'),golden=load(E/'release_golden/golden/summary.json'),bounded=pcm('release_pcm'),all_161=pcm('release_pcm161'),native_matrices=matrices,quality=q,comparison_1000=comparison,independent_clock=dict(traces=len(clock),passed=sum(r['PASS'] for r in clock),callbacks=sum(r['callbacks'] for r in clock),pairs=sum(r['checked_pairs'] for r in clock),exceptions=[r for r in clock if not r['PASS']]),historical_unresolved=dict(release_host_sample_each=1,debug_whole_dsp_deadlines=121,fast_local_quality_failures=78,fast_local_quality_total=1080,stereo_ready_p95_200ms=False),gates=[dict(id=1,name='固定・動的PCM',verdict='PENDING'),dict(id=2,name='境界・周期長',verdict='PENDING'),dict(id=3,name='操作・同期・寿命',verdict='NO-GO',reason='B直前手動seek等の一般対応を未承認'),dict(id=4,name='100ms・長いA・速度応答',verdict='NO-GO',reason='現在周期の途中の動的速度応答が未実装'),dict(id=5,name='Release実時間',verdict='PENDING'),dict(id=6,name='Debug機能・実時間',verdict='PENDING'),dict(id=7,name='主観音質・実音響',verdict='未検証'),dict(id=8,name='Sandbox・TCC・bookmark・FD・実アプリ',verdict='未検証'),dict(id=9,name='一般公開・Merodoa既定採用',verdict='NO-GO')])
summary['extra_evidence']={}
for name in ('deep_independent','deep_long_seed','exact_finite','paired_1000','sandbox_evidence','waveform_analysis','post_clear_clock','fd_lifetime','listening_pack','piano_quality','piano_waveform','piano_listening_pack','clock_startup_extended','preserved_clock_audit','inside_seek','boundary_methods','figure_repair'):
 folder=FINAL/name
 if (folder/'SUMMARY.json').is_file():
  value=aggregate(folder);summary['extra_evidence'][name]=dict(PASS=value['PASS'],counts=value['counts'],gates=value['gates'],summary=identity(folder/'SUMMARY.json'))
summary['source_dependency_audit']=load(E/'dependency_audit.json')
summary['source_dependency_audit_after_main']=load(E/'dependency_audit_after_main.json')
summary['source_dependency_audit_after_sandbox']=load(E/'dependency_audit_after_sandbox.json')
summary['gate_semantics']={'quality_suite_PASS':'RAW/formula/finite/case-condition verification only; not subjective quality or unchanged volume approval','independent_clock_PASS':'diagnostic recomputation agrees with recorded flags; count fields may still contain real clock anomalies','overall_public_approval':False}
summary['environment']=load(FINAL/'ENVIRONMENT.json')
summary['device_identity']=load(FINAL/'DEVICE_IDENTITY.json')
summary['clear_results']={name:dict(cases=len(rows),self_repeats=sum(r['self_repeats_while_preparing'] for r in rows),max_self_repeats=max((r['self_repeats_while_preparing'] for r in rows),default=None),padding=sum(r['failure_padding_frames'] for r in rows),output_affected=sum(r['output_affected_frames'] for r in rows)) for name in s for rows in [[load(p) for p in (E/name).glob('*/clear_result.json')]] if rows}
summary['piano_quality']={"measured":len(list((FINAL/'piano_quality').glob('*/metrics.json'))),"passed":sum(load(p)['PASS'] for p in (FINAL/'piano_quality').glob('*/metrics.json')),"source":"results/phase2/real/stems/audition/piano_original.wav","recording_method_verified":False,"subjective_listening":None}
summary['preserved_clock_independent_analysis']=load(FINAL/'preserved_clock_audit/ANALYSIS.json')
summary['extended_startups']={p.parent.name:load(p) for p in (FINAL/'clock_startup_extended').glob('*/summary.json')}
summary['normal_startups']={p.parent.name:load(p) for p in (E/'release_clock').glob('normal_startup_*/summary.json')}
summary['paired_comparison']=load(FINAL/'paired_1000/PAIR_COMPARISON.json')
summary['preserved_clock_failure_unchanged_clock_code']=load(RUN/'final_v5/CLOCK_STARTUP_ANALYSIS.json')
summary['production_source_relation']=load(FINAL/'PRODUCTION_SOURCE_UNCHANGED.json')

comparison['evidence_scope']='Historical successful old run versus final new run, each n=1, same recorded input/range/speed/rate/buffer. Old run has no before/after device-ID trace; not the controlled paired experiment and not a causal speedup estimate.'
if 'cpu_seconds_reduction_percent' in comparison:comparison['descriptive_cpu_seconds_difference_percent']=comparison.pop('cpu_seconds_reduction_percent')
summary['paired_failure_analysis']=load(FINAL/'paired_1000/FAILURE_ANALYSIS.json')
summary['gates']=[
 dict(id=1,name='固定・動的PCM',verdict='NO-GO',scope='固定PCMはGO、Phase59既存回帰はPASS',reason='Phase62現在周期内の動的Mapと同一要求履歴の独立PCM照合は未実装'),
 dict(id=2,name='境界・周期長',verdict='未検証',scope='固定同速度のLと累積ΣLはGO',reason='異速度境界の独立最終キャプチャは未実施'),
 dict(id=3,name='操作・同期・寿命',verdict='NO-GO',scope='Pause競合、供給不足、Clear、FD、検証済み中点seekはGO',reason='B直前手動seekの一般対応は未承認'),
 dict(id=4,name='100ms・長いA・速度応答',verdict='NO-GO',scope='固定100ms・複数境界・A270秒再利用はGO',reason='長い現在周期を待たない速度応答が未実装'),
 dict(id=5,name='Release実時間',verdict='NO-GO',scope='最終固定主行列・長期・短区間・長いAの観測はGO',reason='保存した開始時host/sample不連続の根本原因未確定。再現0の走行で消さない'),
 dict(id=6,name='Debug機能・実時間',verdict='NO-GO',scope='CTest33/33、主行列53機能・RAW・周期はGO',reason='最終Debug主行列DSP期限超過34件、操作試験2件。旧x86_64全曲121件とも区別'),
 dict(id=7,name='主観音質・実音響',verdict='未検証',scope='RAW・加工数式・非有限値・比較用WAVと波形を技術検証',reason='試聴・物理ループバックなし。RMS最大+13.14dBを音質承認にしない'),
 dict(id=8,name='Sandbox・TCC・bookmark・FD・実アプリ',verdict='未検証',scope='TimeStretchLab実Sandbox・scope・範囲外拒否・FD寿命はGO',reason='Merodoaの実TCC拒否・期限切れbookmark・実アプリ統合は未実施'),
 dict(id=9,name='一般公開・Merodoa既定採用',verdict='NO-GO',reason='上記未達があるため既定フラグ維持。Step3は明示opt-in研究接続と検証済み固定条件のみ')]
summary['plot_dependencies']=load(FINAL/'PLOT_DEPENDENCIES.json')
summary['original_phase62_audit']=load(FINAL/'ORIGINAL_PHASE62_AUDIT.json')
summary['final_driver']=load(FINAL/'FINAL_AGGREGATE.json')
summary['prior_driver_interruption']=load(ROOT/'build/phase62_fix/run_01/final_v8/FINAL_AGGREGATE.json')
OUT.joinpath('SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
OUT.joinpath('SOURCE_MANIFEST.json').write_text(json.dumps(load(FINAL/'FROZEN_SOURCE.json'),indent=2)+'\n')
print({k:summary[k] for k in ('source_unchanged','ctest','bounded','all_161','quality','comparison_1000')})
