"""Summarize measured scopes without promoting partial or absent evidence."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase55'
summaries = {}
for suite in ('short', 'special', 'long'):
    cases = json.loads((OUT / suite / 'summary.json').read_text())
    if not cases or not all(c['PASS'] for c in cases):
        raise SystemExit(f'{suite}: complete successful evidence is required')
    rows = []
    for case in cases:
        rows.extend(json.loads(line) for line in (OUT / suite / case['name'] / 'rows.jsonl').read_text().splitlines())
    pcm = suite != 'long'
    summaries[suite] = dict(cases=len(cases), snapshot_speed_preset_rows=len(rows),
                            unique_analysis_snapshots=len(cases) * (5 if suite == 'long' else 4),
                            PASS=all(c['PASS'] for c in cases),
                            naive_map_counterexamples=sum(r['first_map_difference'] >= 0 for r in rows),
                            measured_pcm=pcm,
                            pcm_comparisons=len(rows) if pcm else 0,
                            partial_pcm_counterexamples=sum(r['first_pcm_interleaved_sample'] >= 0 for r in rows) if pcm else None,
                            nonempty_sealed_pcm_matches=sum(r['sealed_pcm_frames'] > 0 and not r['eof']
                                                           and r['expected_sealed_sha256'] == r['actual_sealed_sha256'] for r in rows) if pcm else None,
                            eof_snapshot_rows=sum(bool(r['eof']) for r in rows))
verdict = dict(verdict='B', product_adoption=False, progressive_product_path_changed=False,
               scopes=summaries, live_incremental_render_verified=False,
               unique_map_comparisons=sum(s['unique_analysis_snapshots'] * 7 for s in summaries.values()),
               pcm_comparisons=sum(s['pcm_comparisons'] for s in summaries.values()),
               long_track_pcm_verified=False, progressive_speed_change_verified=False,
               progressive_realtime_verified=False,
               historical_phase54_realtime_failure_preserved=True,
               reason='閉鎖イベントまでのmapと非空の保守的PCM切り戻し領域は試験範囲で完全一致。固定長部分再生には反例があり、増分処理の全ライフサイクルは未検証。')
golden = json.loads((OUT / 'golden/summary.json').read_text())
verdict['golden_pcm_passed'] = sum(bool(r['PASS']) for r in golden)
verdict['golden_pcm_total'] = len(golden)
audit = json.loads((OUT / 'protected_final.json').read_text())
verdict['protected_audit_passed'] = audit['PASS']
verdict['current_realtime_ctest_exit'] = json.loads((OUT / 'realtime_execution.json').read_text())['ctest_realtime']['exit']
(OUT / 'VERDICT.json').write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + '\n')

sources = sorted([ROOT / 'CMakeLists.txt', *list((ROOT / 'src').rglob('*.*')),
                  *list((ROOT / 'tests').glob('*55*')), *list((ROOT / 'scripts').glob('phase55_*.py'))])
bins = [ROOT / 'build' / name for name in ('phase55_analysis_probe', 'phase55_startup_study',
        'phase55_dependency_tests', 'phase54_core_probe', 'phase54_startup_probe')]
environment = dict(baseline='039592e59cc1a525b495e38d3cedeb6c050792b1',
                   head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                   platform=platform.platform(), machine=platform.machine(),
                   compiler=subprocess.check_output(['c++', '--version'], text=True),
                   cmake_cache_lines=[line for line in (ROOT / 'build/CMakeCache.txt').read_text().splitlines()
                                      if line.startswith(('CMAKE_BUILD_TYPE:', 'CMAKE_OSX_ARCHITECTURES:',
                                                          'CMAKE_CXX_FLAGS_RELEASE:', 'TIMESTRETCH_ENABLE_REALTIME_TESTS:'))],
                   sources={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()},
                   binaries={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in bins})
(OUT / 'environment.json').write_text(json.dumps(environment, indent=2) + '\n')
print(json.dumps(verdict, indent=2, ensure_ascii=False))
