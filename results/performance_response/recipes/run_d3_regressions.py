"""D3の待機分岐に対応する既存試験だけを最終ソースで直列実行する。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import source_manifest

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--build-record', type=Path, required=True)
p.add_argument('--extra-build-record', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
base = ROOT / 'build/progressive_adoption_20261023_01'
b, extra = common.load(a.build_record), common.load(a.extra_build_record)
source = source_manifest(ROOT)
assert b['status'] == extra['status'] == 'PASS' and b['source'] == extra['source'] == source['sha256']
build = Path(b['binaries']['phase62_adoption_review_native']['path']).parent
bins = {**b['binaries'], **extra['binaries']}
for item in bins.values():
    assert common.identity(item['path']) == item
compiler = subprocess.check_output(['/usr/bin/xcrun', 'clang++', '--version'], text=True)
provenance = out / 'BUILD_PROVENANCE.json'
common.save(provenance, dict(status='PASS', source_inventory_sha256=source['sha256'],
    compiler=compiler, architecture='arm64', configuration='Release',
    build_records=[common.identity(a.build_record), common.identity(a.extra_build_record)],
    binaries={k: v['sha256'] for k, v in bins.items()}))
jobs = []
def driver(key, script, args, timeout=1200):
    jobs.append(dict(id=key, kind='driver', command=[sys.executable, str(ROOT / script), *map(str, args)],
                     summary=str(out / key / 'SUMMARY.json'), timeout_s=timeout))
driver('preparation', 'results/performance_response/recipes/run_local.py',
       ['--build-record', a.build_record, '--input', base / 'inputs/mono48_16s.wav',
        '--suite', 'preparation', '--output', out / 'preparation'])
# Only this small, previously measured 41MiB retained suite uses the documented
# disk-floor argument. PCM, case counts, memory, and realtime budgets are intact.
driver('paused', 'scripts/phase62_dynamic_validation.py',
       ['--suite', 'paused', '--build', build, '--output', out / 'paused', '--minimum-free-gib', '.5'])
driver('review', 'results/progressive_adoption/recipes/run_measurements.py',
       ['--base', base, '--build-record', a.build_record, '--suite', 'review', '--output', out / 'review'])
mix = ROOT / 'results/phase31/input/mix.wav'
other = ROOT / 'build/phase62/run_01/step1_release/mix_repeat_36s.wav'
for suite in ('playing', 'paused-clear'):
    driver(suite, 'scripts/phase62_finish_validation.py',
           ['--suite', suite, '--build', build, '--input', mix, '--other-input', other,
            '--build-provenance', provenance, '--output', out / suite])
driver('control', 'scripts/phase62_finish_control_validation.py',
       ['--build', build, '--input', mix, '--output', out / 'control'])
sustained = ROOT / 'build/performance_response_20261023_01/dynamic161_final_01/dynamic_sustained_48000_mono_pcm16_9s.wav'
for preset in ('candidate', 'baseline'):
    key = 'race_' + preset
    jobs.append(dict(id=key, kind='native', expected=8, timeout_s=180,
        command=[bins['phase62_race_native']['path'], str(mix), preset, str(out / key), str(other)],
        summary=str(out / key / 'SUMMARY.json')))
    key = 'dynamic_controls_' + preset
    jobs.append(dict(id=key, kind='native', expected=3, timeout_s=240,
        command=[bins['phase62_dynamic_controls_native']['path'], str(sustained), preset, str(out / key)],
        summary=str(out / key / 'SUMMARY.json')))
    key = 'handoff_' + preset
    jobs.append(dict(id=key, kind='native', expected=1, timeout_s=240,
        command=[bins['phase62_dynamic_handoff_tests']['path'], str(sustained), '1000000', '750000', preset,
                 str(out / key), str(ROOT / 'build/phase59_frozen/captured_reference'),
                 str(ROOT / 'build/phase61/oracle_release_v1/phase61_frozen_reference'),
                 '64' if preset == 'candidate' else '4096'], summary=str(out / key / 'SUMMARY.json')))
common.save(out / 'EXPECTED.json', dict(source=source['sha256'], driver=common.identity(__file__),
    builds=[common.identity(a.build_record), common.identity(a.extra_build_record)],
    inputs=[common.identity(f) for f in (mix, other, sustained)],
    expected_drivers=len(jobs), all_expected_ids=[j['id'] for j in jobs], jobs=jobs,
    serial=True, disk_floor_gib_paused_only=.5,
    disk_floor_reason='bounded existing short suite; prior retained physical size 41MiB; no quality/resource criterion changed',
    RT_approval='individual native reports only; offline Handoff is not a realtime result', physical_audio=None))
rows = []
env = dict(os.environ, PATH='/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin')
for job in jobs:
    assert source_manifest(ROOT) == source
    log = out / (job['id'] + '.log')
    started, timed = time.monotonic(), False
    print('START', job['id'], flush=True)
    with log.open('w') as f:
        try:
            code = subprocess.run(job['command'], env=env, stdout=f, stderr=subprocess.STDOUT,
                                  timeout=job['timeout_s']).returncode
        except subprocess.TimeoutExpired:
            code, timed = None, True
    path = Path(job['summary'])
    result = common.load(path) if path.exists() else {}
    ok = code == 0 and not timed and bool(result)
    if job['kind'] == 'native':
        ok &= result.get('status') == 'PASS' and result.get('expected') == result.get('executed') == job['expected']
        if job['id'].startswith('race_'):
            ok &= result.get('PASS') == 8
    else:
        ok &= result.get('status') == 'PASS' or (job['id'] == 'paused' and result.get('selected_suite_pass') is True)
    rows.append(dict(id=job['id'], PASS=bool(ok), returncode=code, timeout=timed,
        wall_s=time.monotonic() - started, summary=result, log=common.identity(log),
        summary_identity=common.identity(path) if path.exists() else None))
    common.save(out / 'SUMMARY.json', dict(status='PASS' if len(rows) == len(jobs) and all(r['PASS'] for r in rows)
        else 'INCOMPLETE_OR_FAIL', run_complete=len(rows) == len(jobs), expected_drivers=len(jobs),
        executed_drivers=len(rows), rows=rows, source=source['sha256']))
    print('END', job['id'], code, bool(ok), flush=True)
assert source_manifest(ROOT) == source
sys.exit(0 if all(r['PASS'] for r in rows) else 2)
