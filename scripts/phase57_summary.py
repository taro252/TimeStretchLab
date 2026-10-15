"""Audit completed evidence and emit the final Phase57 report/verdict."""
import csv,hashlib,json,platform,re,statistics as st,subprocess
from pathlib import Path
from phase55_study import ROOT
from phase57_study import CHUNKS,LONG_SPEEDS,REPRESENTATIVE,sha
OUT=ROOT/'results/phase57'
assert json.loads((OUT/'pipeline_status.json').read_text())['status']=='passed'
BINARY=sha(ROOT/'build/phase57_check');FROZEN=sha(ROOT/'build/phase57_frozen/reference')
assert FROZEN==(OUT/'frozen_reference_sha256.txt').read_text().split()[0]
all_rows=[];statistics=[];coverage=set();early=0;lead_early=0;non_eos=0;rejected_runs=0
for suite in ('stage1_final','stage2','long','natural','rejections'):
    directory=OUT/suite;manifest=json.loads((directory/'manifest.json').read_text());summary=json.loads((directory/'summary.json').read_text())
    assert summary['PASS'] and manifest['incremental_binary_sha256']==BINARY and manifest['reference_binary_sha256']==FROZEN
    sources={s['name']:s for s in manifest['inputs']}
    for s in sources.values():assert sha(s['path'])==s['input_sha256'],s['path']
    rows=[json.loads(line) for line in (directory/'rows.jsonl').read_text().splitlines()]
    assert len(rows)==len(sources)*len(manifest['speeds'])*2==summary['cases']
    seen=set();passed=0;rejected=0
    for case in rows:
        identity=(case['input'],case['speed_micros'],case['preset']);assert identity not in seen;seen.add(identity)
        expected=set(manifest['chunks'])
        if suite=='long' and case['input']=='boundary_180s' and case['speed_micros'] in (500000,1000000,2000000):expected|={'32768','5003'}
        if case.get('matched_rejection'):
            assert case['reference_exit']!=0 and all(r['matched'] and r['exit']!=0 for r in case['rejections'])
            assert {r['chunk'] for r in case['rejections']}==expected
            rejected+=1;rejected_runs+=len(case['rejections']);continue
        assert case['PASS'] and case['reference_exit']==0
        assert {m['chunk'] for m in case['measurements']}==expected
        source=sources[case['input']]
        for m in case['measurements']:
            assert m['PASS'] and not m['bench'] and m['output_frames']==case['reference']['output_frames'] and m['pcm_sha256']==case['reference']['pcm_sha256']
            passed+=1;non_eos+=m['non_eos_pcm_frames']>0
            early+=m['non_eos_pcm_frames']>0 and 0<=m['first_published_s']<m['analysis_done_s']
            lead_early+=m['non_eos_pcm_frames']>=(16384 if case['preset']=='candidate' else 12288) and 0<=m['lead_ready_s']<m['analysis_done_s']
            if suite=='stage2':coverage.add((source['encoding'],source['channels'],source['rate'],case['preset'],case['speed_micros']))
            if suite=='long' and case['input']=='chain_300s':assert m['non_eos_pcm_frames']==0 and m['first_published_s']>=m['analysis_done_s']
        all_rows.append((suite,case))
    assert passed==summary['pcm_sessions'] and rejected==summary['matched_rejections']
    statistics.append(dict(suite=suite,inputs=len(sources),reference_cases=len(rows),exact_pcm_sessions=passed,matched_rejection_cases=rejected))
assert len(coverage)==8*2*161
assert next(s for s in statistics if s['suite']=='stage1_final')['exact_pcm_sessions']==4704
stage2=next(s for s in statistics if s['suite']=='stage2');assert stage2['reference_cases']==15456 and stage2['exact_pcm_sessions']+stage2['matched_rejection_cases']*3==46368
assert early>0 and non_eos>0 and lead_early>0
for suite in ('legacy_equivalence','timing_equivalence'):
    x=json.loads((OUT/suite/'summary.json').read_text());assert x['PASS'] and x['cases']==112 and all(r['PASS'] for r in x['rows'])
golden=json.loads((OUT/'golden/summary.json').read_text());assert len(golden)==25 and all(r['PASS'] for r in golden)
audit=json.loads((OUT/'protected_final.json').read_text());assert audit['PASS'] and audit['golden_checked']==30
release=(OUT/'ctest_deterministic.log').read_text();debug=(OUT/'ctest_debug.log').read_text()
assert '100% tests passed, 0 tests failed out of 82' in release
assert '100% tests passed, 0 tests failed out of 6' in debug
assert json.loads((OUT/'debug_smoke/summary.json').read_text())['PASS']
performance=[];perf_sessions=0;whole_runs=0;performance_validations=0;strict_early=0;strict_lead=0
for suite in ('performance','performance_chunks'):
    manifest=json.loads((OUT/suite/'manifest.json').read_text());assert manifest['incremental_binary_sha256']==BINARY
    assert manifest['reference_binary_sha256']==sha(ROOT/'build/phase57_frozen/reference_timing')
    assert json.loads((OUT/suite/'summary.json').read_text())['PASS']
    for source in manifest['inputs']:assert sha(source['path'])==source['input_sha256']
    for line in (OUT/suite/'rows.jsonl').read_text().splitlines():
        c=json.loads(line);assert c['PASS'] and len(c['full_runs'])==5
        whole_runs+=5
        validations=c['validation_measurements'];assert len(validations)==len(manifest['chunks'])
        for v in validations:assert v['PASS'] and not v['bench'] and v['output_frames']==c['reference']['output_frames'] and v['pcm_sha256']==c['reference']['pcm_sha256']
        performance_validations+=len(validations)
        for r in c['full_runs']:assert r['pcm_sha256']==c['reference']['pcm_sha256'] and r['output_frames']==c['reference']['output_frames']
        a={key:dict(median=st.median(r[key] for r in c['full_runs']),maximum=max(r[key] for r in c['full_runs']),population_stddev=st.pstdev(r[key] for r in c['full_runs'])) for key in c['full_runs'][0] if isinstance(c['full_runs'][0][key],(float,int)) and not isinstance(c['full_runs'][0][key],bool)}
        for chunk in manifest['chunks']:
            rows=[r for r in c['measurements'] if r['chunk']==chunk];assert len(rows)==5
            for r in rows:assert r['PASS'] and r['bench'] and r['pcm_sha256']==c['reference']['pcm_sha256'] and r['output_frames']==c['reference']['output_frames']
            perf_sessions+=len(rows)
            b={key:dict(median=st.median(r[key] for r in rows),maximum=max(r[key] for r in rows),population_stddev=st.pstdev(r[key] for r in rows)) for key in rows[0] if isinstance(rows[0][key],(int,float)) and not isinstance(rows[0][key],bool)}
            frontiers=[]
            for repeat in range(5):
                trace=OUT/suite/f"{c['input']}_{c['speed_micros']}_{c['preset']}_{repeat}_{chunk}.csv"
                checkpoints=list(csv.DictReader(trace.open()))
                first=next((r for r in checkpoints if int(r['pcm_published'])>0),None)
                goal=16384 if c['preset']=='candidate' else 12288
                first_lead=next((r for r in checkpoints if int(r['pcm_published'])>=goal),None)
                total=c['reference']['input_frames']
                prior=max((int(r['pcm_published']) for r in checkpoints if int(r['received'])<total),default=0)
                frontiers.append(dict(repeat=repeat,input_frames_at_first_pcm=int(first['received']) if first else total,input_frames_at_lead=int(first_lead['received']) if first_lead else total,pcm_before_all_input_received=prior))
                strict_early+=first is not None and int(first['received'])<total
                strict_lead+=first_lead is not None and int(first_lead['received'])<total
            performance.append(dict(suite=suite,input=c['input'],preset=c['preset'],chunk=chunk,n=5,whole=a,progressive=b,frontiers=frontiers,cpu_increase_percent=100*(b['cpu_s']['median']/a['cpu_s']['median']-1)))
assert strict_early>0 and strict_lead>0
(OUT/'performance_statistics.json').write_text(json.dumps(performance,indent=2)+'\n')
verdict=dict(verdict='A',progressive_pcm_exact=True,all_161_speeds_verified=True,all_8_formats_verified=True,candidate_verified=True,baseline_verified=True,long_track_pcm_verified=True,non_eos_pcm_produced=non_eos>0,early_pcm_before_full_analysis=early>0,product_path_modified=True,product_api_modified=False,shared_legacy_dsp_refactored=True,production_progressive_integration=False,realtime_verified=False,phase58_ready=True,long_all_161_speeds_verified=False,long_all_8_formats_verified=False,long_speed_micros=LONG_SPEEDS,exact_pcm_sessions=sum(s['exact_pcm_sessions'] for s in statistics),matched_rejection_cases=sum(s['matched_rejection_cases'] for s in statistics),matched_rejection_runs=rejected_runs,non_eos_pcm_sessions=non_eos,early_pcm_sessions=early,early_lead_sessions=lead_early,golden_pcm_passed=25,protected_files=audit['checked'],golden_files=audit['golden_checked'],performance_sessions=perf_sessions,performance_full_bit_validation_sessions=performance_validations,whole_performance_runs=whole_runs,early_pcm_before_all_input_received=True,performance_early_pcm_runs=strict_early,performance_early_lead_runs=strict_lead,verification_build='Release',debug_verification_scope='Phase13/56/57関連6CTestと、独立した変更前Debug DSPによる36 PCMセッション',reference_binary_sha256=FROZEN,incremental_binary_sha256=BINARY,historical_realtime_failures_preserved=True,product_path_modified_detail='Phase36内部の共通化のみ。公開API・品質算術・FIFO・ゲインは維持。増分経路の製品接続なし。',matrix=statistics)
(OUT/'VERDICT.json').write_text(json.dumps(verdict,ensure_ascii=False,indent=2)+'\n')
files=[ROOT/'CMakeLists.txt',ROOT/'src/prototype/Phase36StreamingSpeedEngine.cpp',ROOT/'src/prototype/Phase36SynthesisCore.h',*list((ROOT/'src/prototype').glob('Phase57*')),*list((ROOT/'tests').glob('Phase57*')),*list((ROOT/'scripts').glob('phase57_*'))]
bins=[ROOT/'build'/n for n in ('phase57_check','phase57_tests','phase57_reference','phase54_core_probe')]+[ROOT/'build/phase57_frozen'/n for n in ('reference','reference_timing','reference_debug')]+[ROOT/'build/phase57_debug'/n for n in ('phase57_check','phase57_tests')]
links={}
for name in ('playback_demo','phase54_core_probe'):
    text=(ROOT/f'build/CMakeFiles/{name}.dir/link.txt').read_text();assert 'phase57_synthesis' not in text and 'phase56_incremental' not in text;links[name]=text
status=subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)
env=dict(baseline='ec087019626d9ff0d9f157245729b74ddb6847d7',head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),status=status,platform=platform.platform(),machine=platform.machine(),compiler=subprocess.check_output(['c++','--version'],text=True),release_flags=(ROOT/'build/CMakeFiles/phase57_synthesis.dir/flags.make').read_text(),debug_flags=(ROOT/'build/phase57_debug/CMakeFiles/phase57_synthesis.dir/flags.make').read_text(),sources={str(p.relative_to(ROOT)):sha(p) for p in files if p.is_file()},binaries={str(p.relative_to(ROOT)):sha(p) for p in bins},product_link_commands=links)
(OUT/'environment.json').write_text(json.dumps(env,ensure_ascii=False,indent=2)+'\n')
(OUT/'matrix_summary.json').write_text(json.dumps(statistics,indent=2)+'\n')
print(json.dumps(verdict,ensure_ascii=False,indent=2))
