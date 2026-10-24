"""最終実行体のC1単体52項目、DSP凍結スカラー156項目、checkpoint全suffix2実行。"""
import argparse
from pathlib import Path
import subprocess
import sys
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import source_manifest

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--build-record', type=Path, required=True)
p.add_argument('--base', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
p.add_argument('--only', nargs='+')
a = p.parse_args()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
b = common.load(a.build_record)
common.require(b['status'] == 'PASS' and source_manifest(ROOT)['sha256'] == b['source'], 'frozen build/source')
jobs = []
for preset in ('candidate', 'baseline'):
    target = b['binaries']['performance_planner_tests']
    jobs.append({'id': 'planner_' + preset, 'binary': target, 'kind': 'planner', 'expected_checks': 26,
                 'command': [target['path'], str((a.base / 'inputs/mono48_16s.wav').resolve()), preset, str(out / ('planner_' + preset)), b['source']]})
for fixture, inp in (('mix', ROOT / 'results/phase31/input/mix.wav'),
                     ('stereo441_16s', a.base / 'inputs/stereo441_16s.wav')):
    target = b['binaries']['phase61_checkpoint_tests']
    jobs.append({'id': 'checkpoint_' + fixture, 'binary': target, 'kind': 'checkpoint', 'expected_checks': None,
                 'command': [target['path'], str(inp.resolve())]})
target = b['binaries']['performance_dsp_equivalence_tests']
jobs.append({'id': 'dsp', 'binary': target, 'kind': 'dsp', 'expected_checks': 156, 'command': [target['path']]})
if a.only:
    common.require(set(a.only) <= {x['id'] for x in jobs}, 'unknown --only ID')
    jobs = [x for x in jobs if x['id'] in a.only]
for j in jobs:
    common.require(common.identity(j['binary']['path']) == j['binary'], 'binary changed')
common.save(out / 'EXPECTED.json', {'source': b['source'], 'build': common.identity(a.build_record),
            'driver': common.identity(__file__), 'helper': common.identity(common.__file__), 'jobs': jobs,
            'expected_programs': len(jobs), 'planner_checks': sum(x.get('expected_checks') or 0 for x in jobs if x['kind'] == 'planner'),
            'dsp_checks': 156 if any(x['kind'] == 'dsp' for x in jobs) else 0,
            'checkpoint_programs': sum(x['kind'] == 'checkpoint' for x in jobs), 'selection': a.only,
            'inputs': [common.identity(a.base / ('inputs/' + x + '.wav')) for x in ('mono48_16s', 'stereo441_16s')] + [common.identity(ROOT / 'results/phase31/input/mix.wav')],
            'additional_mono_fixture': 'units_final_01 kept FAIL; checkpoint_fixture_repro_02 shows identical NoSafeInterval before/after. Original CTest mix is the positive contract fixture.',
            'checkpoint_scope': 'fixed and two dynamic target states, complete suffix phase/OLA/FIR bits and post-restore Map/Plan; checkpoint oracle is separate live instance',
            'PCM_quality_approval': False, 'realtime_approval': False})
rows = []
for j in jobs:
    log = out / (j['id'] + '.log')
    with log.open('w') as f:
        r = subprocess.run(j['command'], stdout=f, stderr=subprocess.STDOUT, timeout=180)
    ok, result = r.returncode == 0, None
    if j['kind'] == 'planner':
        result = common.load(out / j['id'] / 'SUMMARY.json')
        expected = common.load(out / j['id'] / 'EXPECTED.json')
        import json
        checks = [json.loads(x) for x in (out / j['id'] / 'checks.jsonl').read_text().splitlines()]
        ok = (ok and result['status'] == 'PASS' and result['run_complete']
              and result['expected'] == result['executed'] == len(checks) == 26
              and [x['id'] for x in checks] == expected['required_ids']
              and all(x['pass'] is True for x in checks))
    elif j['kind'] == 'dsp':
        lines = [x[len('SUMMARY '):] for x in log.read_text().splitlines() if x.startswith('SUMMARY ')]
        common.require(len(lines) == 1, 'one final DSP summary')
        import json
        result = json.loads(lines[0])
        ok = ok and result['status'] == 'PASS' and result['run_complete'] and result['passed'] == result['expected'] == 156 and result['failed'] == 0
    else:
        ok = ok and log.read_text().startswith('PASS fixed/dynamic checkpoint full suffix')
    rows.append({'id': j['id'], 'PASS': bool(ok), 'returncode': r.returncode, 'result': result, 'log': common.identity(log)})
    common.save(out / 'SUMMARY.json', {'status': 'PASS' if len(rows) == len(jobs) and all(x['PASS'] for x in rows) else 'INCOMPLETE_OR_FAIL', 'expected_programs': len(jobs), 'executed_programs': len(rows), 'rows': rows})
    print(j['id'], ok, flush=True)
common.require(source_manifest(ROOT)['sha256'] == b['source'], 'source changed')
for j in jobs:
    common.require(common.identity(j['binary']['path']) == j['binary'], 'binary changed')
sys.exit(0 if all(x['PASS'] for x in rows) else 2)
