"""Final evidence audit: exact bits, scopes, unchanged legacy sources, timings."""
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess
from phase55_study import ROOT

OUT = ROOT / 'results/phase56'
cases = json.loads((OUT / 'percent_exact/summary.json').read_text())
assert len(cases) == 78 and all(c['PASS'] and c['runs'] == 7 for c in cases)
frozen = ROOT / 'build/phase56_frozen/reference_percent'
frozen_sha = hashlib.sha256(frozen.read_bytes()).hexdigest()
assert frozen_sha == (OUT / 'frozen_percent_reference_sha256.txt').read_text().split()[0]
binary_sha = hashlib.sha256((ROOT / 'build/phase56_check').read_bytes()).hexdigest()
for c in cases:
    manifest = json.loads((OUT / 'percent_exact' / c['name'] / 'reference_manifest.json').read_text())
    assert manifest['binary_sha256'] == frozen_sha
    assert manifest['incremental_binary_sha256'] == binary_sha
    assert manifest['speed_micros'] == list(range(400000,2000001,10000))
    assert hashlib.sha256(Path(manifest['reference']).read_bytes()).hexdigest() == c['reference_sha256']
    assert all(r['PASS'] and r['speed_count'] == 161 and r['final_sha256'] == c['reference_sha256'] for r in c['measurements'])
golden = json.loads((OUT / 'golden/summary.json').read_text())
assert len(golden) == 25 and all(r['PASS'] for r in golden)
audit = json.loads((OUT / 'protected_percent_final.json').read_text())
assert audit['PASS']
performance = json.loads((OUT / 'percent_performance/summary.json').read_text())
assert len(performance) == 2 and all(c['runs'] == 35 and c['PASS'] and all(r['speed_count']==161 and r['PASS'] and r['final_sha256']==c['reference_sha256'] for r in c['measurements']) for c in performance)
ratios = []
for case in performance:
    manifest = json.loads((OUT / 'percent_performance' / case['name'] / 'reference_manifest.json').read_text())
    assert manifest['binary_sha256'] == frozen_sha and manifest['incremental_binary_sha256'] == binary_sha
    assert manifest['speed_micros'] == list(range(400000,2000001,10000))
    assert hashlib.sha256(Path(manifest['reference']).read_bytes()).hexdigest() == case['reference_sha256']
    full = json.loads((OUT / 'percent_performance' / case['name'] / 'full_runs.json').read_text())
    assert len(full) == 5 and all(r['speed_count'] == 161 for r in full)
    baseline = statistics.median(r['analysis_and_maps_cpu_seconds'] for r in full)
    for chunk in ('1024', '7168', '8192', '32768', '131072', 'irregular', '5003'):
        rows = [r for r in case['measurements'] if r['chunk'] == chunk]
        assert len(rows) == 5
        ratios.append(dict(input=case['name'], chunk=chunk, baseline_thread_cpu_median=baseline,
                           incremental_thread_cpu_median=statistics.median(r['thread_cpu_seconds'] for r in rows),
                           cpu_increase_percent=100 * (statistics.median(r['thread_cpu_seconds'] for r in rows) / baseline - 1)))
(OUT / 'cpu_comparison.json').write_text(json.dumps(ratios, indent=2) + '\n')
verdict = dict(verdict='A', scope='継続状態を持つ解析と、要求した固定速度TimeMap。製品統合とPCM継続合成は対象外。',
               inputs=78, chunk_modes=7, exact_sessions=546, speed_maps_per_session=161,
               exact_fixed_map_comparisons=87906, intermediate_and_final_exact=True,
               frozen_reference_sha256=frozen_sha, checked_binary_sha256=binary_sha,
               golden_pcm_passed=25, protected_files=audit['checked'], golden_files=audit['golden_checked'],
               performance_sessions=70, legacy_whole_runs=10,
               product_api_changed=False, production_incremental_integration=False, pcm_startup_improvement_proven=False,
               realtime_dsp_competition_verified=False, historical_realtime_failures_preserved=True,
               same_input_request_coalescing=False,
               fixed_speed_min=0.4, fixed_speed_max=2.0, fixed_speed_step=0.01,
               fixed_speed_values=[i / 100 for i in range(40, 201)], speed_micros=list(range(400000,2000001,10000)))
(OUT / 'VERDICT.json').write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + '\n')
files = [ROOT / 'CMakeLists.txt', *list((ROOT / 'src').rglob('*.*')),
         *list((ROOT / 'tests').glob('Phase56*')), *list((ROOT / 'scripts').glob('phase56_*.py'))]
bins = [ROOT / 'build' / name for name in ('phase56_check', 'phase56_tests', 'phase56_fixed_modes', 'phase54_core_probe')]
bins += [ROOT / 'build/phase56_frozen' / name for name in ('reference', 'reference_scope', 'reference_debug', 'reference_percent', 'reference_percent_debug', 'check_seven')]
env = dict(baseline='14d30be6a7a2dc164eead5a5d747c60fba806b49',
           head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
           branch=subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
           platform=platform.platform(), machine=platform.machine(), compiler=subprocess.check_output(['c++', '--version'], text=True),
           release_flags=(ROOT / 'build/CMakeFiles/phase56_incremental.dir/flags.make').read_text(),
           debug_flags=(ROOT / 'build/phase56_debug/CMakeFiles/phase56_incremental.dir/flags.make').read_text(),
           sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files) if p.is_file()},
           binaries={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in bins})
(OUT / 'environment.json').write_text(json.dumps(env, indent=2) + '\n')
print(json.dumps(verdict, ensure_ascii=False, indent=2))
