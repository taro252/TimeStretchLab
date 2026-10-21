"""全必須runの完走後だけ、今回の限定局所判定と小さい証拠を発行する。"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity, source_manifest
from phase62_aggregation import strict_gates, exact_ids
from phase62_review_validation import verify
from run_f01 import reproduce


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    assert not path.exists(), '確定済み証拠を上書きしない: ' + str(path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--base', type=Path, required=True)
    args = parser.parse_args()
    base = args.base.resolve()
    out = ROOT / 'results/phase62_f01'
    src = source_manifest(ROOT)
    initial = read(base / 'INITIAL.json')
    build = read(base / 'BUILD_CANDIDATE_01.json')
    old = read(base / 'baseline_repro_01/SUMMARY.json')
    fixed = read(base / 'f01_fixed_01/SUMMARY.json')
    regression = read(base / 'regressions_01/SUMMARY.json')
    strict = read(base / 'strict_01/SUMMARY.json')
    renderer = read(base / 'renderer_01/SUMMARY.json')
    native = read(base / 'native_01/SUMMARY.json')
    refs = read(base / 'REFERENCE_VERIFIED_01.json')
    reuse = read(out / 'REUSE_AUDIT.json')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    assert head == initial['head'] == 'b0352c6f4c22f100f161297769b26561dc07701b'
    assert initial['status'] == '' and initial['branch'] == 'main'
    assert build['status'] == 'PASS' and build['build_exit'] == 0
    assert build['source_inventory_sha256'] == src['sha256']
    for record in [old, fixed, regression, strict, renderer, native, refs, reuse]:
        assert record['status'] == 'PASS' and record.get('run_complete') is True
    for directory, record in [('baseline_repro_01', old), ('f01_fixed_01', fixed), ('regressions_01', regression)]:
        spec = read(base / directory / 'EXPECTED.json')
        exact_ids(spec['required_ids'], [r['id'] for r in record['rows']], directory + ' program IDs')
        expected_rows = spec['expected_programs'] if directory != 'regressions_01' else len(spec['jobs'])
        assert len(record['rows']) == expected_rows
        jobs = {r['id']:r for r in spec['jobs']}
        for row in record['rows']:
            job = jobs[row['id']]
            assert row['timed_out'] is False
            child = base / directory / row['id']
            if directory == 'baseline_repro_01':
                reproduce(child, row['exit'], row['timed_out'])
            elif directory == 'f01_fixed_01':
                summary, reasons = verify(job, child, row['exit'], row['timed_out'])
                assert not reasons and summary == row['summary'] and row['status'] == 'PASS'
                exact_ids(job['required_checks'], read(child/'EXPECTED.json')['checks'], 'F01 check IDs')
            else:
                assert row['status'] == 'PASS' and row['exit'] == 0
                assert row['programs'] == job['programs'] and row['checks'] == job['checks']
                assert identity(child/'SUMMARY.json') == row['summary'] and read(child/'SUMMARY.json') == row['result']
                result = row['result']
                assert result['status'] == 'PASS'
                if not row['id'].startswith('race_'):
                    assert result['run_complete'] is True
                    assert all(r['status'] == 'PASS' and r['exit'] == 0 for r in result['rows'])
        if directory == 'regressions_01':
            assert sum(r['programs'] for r in record['rows']) == 75 and sum(r['checks'] for r in record['rows']) == 326
    assert old['expected_programs'] == old['executed_programs'] == 4
    assert all(r['status'] == 'EXPECTED_FAILURE_REPRODUCED' and r['exit'] == 1 and r['executed'] == 4 for r in old['rows'])
    assert fixed['expected_programs'] == fixed['executed_programs'] == 10
    assert fixed['expected_checks'] == fixed['executed_checks'] == 64 and fixed['source'] == src['sha256']
    assert regression['expected_programs'] == regression['executed_programs'] == 75
    assert regression['expected_checks'] == regression['executed_checks'] == 326
    strict_gates(base / 'strict_01')
    assert strict['executed_stage_count'] == 6
    assert renderer['expected'] == renderer['executed'] == 4
    rc = {r['id']:r['certificate'] for r in renderer['rows']}
    assert rc['final_boundary_strict_v8']['measured']['cases_expected'] == rc['final_boundary_strict_v8']['measured']['cases_executed'] == 184
    extra = rc['final_extra']['measurements']
    assert sum(r['count'] for r in extra if r['id'].startswith('boundary_')) == 368
    handoff = [r for r in extra if r['id'].startswith('handoff_')]
    assert len(handoff) == 6 and all(r['count'] == 1 for r in handoff)
    assert rc['final_uncached_boundary']['measured_totals_by_unit']['checks'] == 128
    assert rc['final_min512_v9']['measured_totals_by_unit']['checks'] == 192
    assert native['expected'] == native['executed'] == 5
    assert sum(r['certificate']['executed_programs'] for r in native['rows']) == 41
    rt = [v for r in native['rows'] for v in r['certificate'].get('realtime', [])]
    assert len(rt) == 8 and len({r['id'] for r in rt}) == 8 and all(r['status'] == 'PASS' for r in rt)
    normal_rows = [r for group in native['rows'] for r in group['certificate'].get('rows', []) if r.get('realtime_gate') == 'PASS']
    assert len(normal_rows) == 8
    zero_fields = ['output_affected_frames', 'failure_padding_frames', 'raw_mix_errors', 'nonfinite',
                   'zero_source_or_output_frames', 'safety_stop_frames', 'missing_frames', 'underrun_calls',
                   'worker_deadlines', 'worker_new', 'workgroup_errors', 'final_worker_deadlines',
                   'final_worker_new', 'final_workgroup_errors', 'final_missing_frames', 'callback_deadlines',
                   'callback_new', 'callback_heap_calls', 'callback_frees', 'warm_fft_plans']
    for row in normal_rows:
        value = row['result']
        assert value['functional_pass'] is True and all(value[k] == 0 for k in zero_fields)
        assert value['cycles'] == (4100 if row['id'].startswith('stress_') else 4)
        assert value['workers_created'] == 2
    assert all(r['exit'] == 0 and not r['timed_out'] and r['status'] == 'PASS' for r in renderer['rows'] + native['rows'])
    assert all(s['source_inventory_sha256'] == src['sha256'] for s in [regression, strict, renderer, native])
    for path in ['REGRESSION_DEVICE_GUARD_01.json', 'NATIVE_DEVICE_GUARD_01.json']:
        assert read(base / path)['PASS'] is True
    assert refs['expected'] == refs['executed'] == refs['passed'] == 10
    assert reuse['applicable_to_source'] == src['sha256'] and reuse['old_results_relabelled'] is False
    race_spec = read(base/'RACE_EXPECTED_01.json')
    assert race_spec['before_both_race_runs'] is True and race_spec['source'] == src['sha256']
    assert identity(Path(race_spec['binary']['path'])) == race_spec['binary']
    assert race_spec['binary']['sha256'] == build['binaries']['phase62_race_native']
    race_proof = []
    for job in race_spec['jobs']:
        child = base/'regressions_01'/job['id']
        summary = read(child/'SUMMARY.json')
        rows = [json.loads(line) for line in (child/'observations.jsonl').read_text().splitlines()]
        exact_ids(race_spec['required_case_ids'], [r['case'] for r in rows], job['id'] + ' case IDs')
        assert all(r['status'] == 'PASS' for r in rows)
        assert summary['status'] == 'PASS' and summary['expected'] == summary['executed'] == summary['PASS'] == 8
        assert summary['FAIL'] == summary['INCOMPLETE'] == summary['REPRODUCED'] == 0
        race_proof.append(dict(id=job['id'], expected=8, executed=8, status='PASS', observations=identity(child/'observations.jsonl')))
    observations = []
    for kind, parent in [('old', old), ('fixed', fixed)]:
        folder = base / ('baseline_repro_01' if kind == 'old' else 'f01_fixed_01')
        for row in parent['rows']:
            child = folder / row['id']
            main_mode = row['id'].startswith(('f01_dsp_done_', 'f01_checkpoint_'))
            files = [child/'F01_selected_window.json', child/('F01_actual_adoption.json' if main_mode else 'F01_action_cleanup.json')]
            assert all(p.is_file() for p in files), row['id'] + ' 必須観測の欠落'
            close = child/'final_close_ledger.jsonl'
            close_data = None
            if kind == 'fixed' and not main_mode:
                rows = [json.loads(line) for line in close.read_text().splitlines()]
                assert len(rows) == 4 and rows[0]['record'] == 'audit_delivery'
                assert rows[0]['calls'] == 1 and rows[0]['copied_count'] == 3
                assert rows[0]['workers_joined'] is True and rows[0]['retirement_complete'] is True
                receipts = [json.loads(line) for line in (child/'receipts.jsonl').read_text().splitlines()]
                accepted = [r['id'] for r in receipts if r['accepted'] and not r['duplicate']]
                exact_ids(list(map(str, accepted)), [str(r['id']) for r in rows[1:]], 'F01 close receipt IDs')
                by_id = {r['id']:r for r in rows[1:]}
                states = ['Failed' if row['id'].startswith('f01_selected_failure_') else 'Cancelled', 'Cancelled', 'Completed']
                assert [by_id[i]['state'] for i in accepted] == states
                for i in accepted[:2]:
                    value = by_id[i]
                    assert value['reason'] and value['output_started'] is False
                    assert value['first_PCM_observed_ns'] == value['completed_ns'] == 0
                assert by_id[accepted[2]]['output_started'] is True and by_id[accepted[2]]['first_PCM_observed_ns'] > 0
                close_data = rows
            observations.append(dict(kind=kind, id=row['id'], status=row['status'], exit=row['exit'],
                                     expected=row['expected'], executed=row['executed'],
                                     records=[dict(file=identity(p), data=read(p)) for p in files],
                                     final_close_ledger=identity(close) if close.exists() else None,
                                     final_close_data=close_data))
    prior = {r['path']: r['sha256'] for r in initial['source']['files']}
    delta = [dict(path=r['path'], old_sha256=prior.get(r['path']), new_sha256=r['sha256'])
             for r in src['files'] if prior.get(r['path']) != r['sha256']]
    assert {r['path'] for r in delta} == {'src/platform/macos/ProgressiveMacPlaybackEngine.h',
                                         'src/platform/macos/ProgressiveMacPlaybackEngine.mm',
                                         'tests/Phase62AdoptionReviewNative.cpp'}
    save(out / 'SOURCE_MANIFEST.json', src)
    save(out / 'SOURCE_DELTA.json', dict(base_head=head, initial_source=initial['source']['sha256'], final_source=src['sha256'], files=delta))
    save(out / 'BUILD_PROVENANCE.json', dict(candidate=build, observed_baseline=read(base/'baseline_01/BUILD.json'),
         observed_baseline_plan=identity(base/'baseline_01/EXPECTED.json'), strict=identity(base/'strict_01/SUMMARY.json')))
    save(out / 'F01_CERTIFICATE.json', dict(status='PASS', meaning='旧4本は実不一致を検出したFAILを保持。修正版10本64checks PASS。',
         source=src['sha256'], observations=observations, old_summary=identity(base/'baseline_repro_01/SUMMARY.json'),
         fixed_summary=identity(base/'f01_fixed_01/SUMMARY.json'), RT_deadline_approval='NOT_ASSESSED'))
    seek_observations = []
    for name in ['candidate_normal', 'candidate_R0', 'baseline_normal', 'baseline_R0']:
        path = base/'native_01/final_seek_api_v10'/name/'SUMMARY.json'
        value = read(path)
        assert value['status'] == 'PASS' and value['expected'] == value['executed']
        assert value['RT_deadline_approval'] == 'NOT_ASSESSED'
        seek_observations.append(dict(id=name, source=src['sha256'], summary=identity(path),
             expected=value['expected'], executed=value['executed'], functional_status='PASS',
             worker_deadlines_observed=value['worker_deadlines_observed'],
             callback_deadlines_observed=value['callback_deadlines_observed'], RT_deadline_approval='NOT_ASSESSED'))
    save(out/'FUNCTIONAL_DEADLINE_OBSERVATION.json', dict(scope='seek機能PASSと期限観測を分離。正常RT8本へ合算しない。',
         source=src['sha256'], current=seek_observations,
         previous=identity(ROOT/'results/phase62_e5_review/FUNCTIONAL_DEADLINE_OBSERVATION.json'),
         cause='NOT_DETERMINED', next_gate='case/session/epoch/処理区間とworker時刻・FIFO影響の対応による分類',
         physical_loopback='NOT_RUN'))
    save(out/'NATIVE_NORMAL_RT.json', dict(status='PASS', source=src['sha256'], expected=8, executed=8,
         parent=identity(base/'native_01/final_native_gates_v10/SUMMARY.json'),
         rows=[dict(id=r['id'], status='PASS', measurements=r['result']) for r in normal_rows],
         zero_fields=zero_fields, normal_only=True, physical_loopback='NOT_RUN', human_listening='NOT_RUN'))
    records = ['INITIAL.json', 'VALIDATION_PLAN.json', 'ENV_PREFLIGHT_RESULT.json', 'ENVIRONMENT_01.json', 'ENVIRONMENT_02.json', 'BUILD_CANDIDATE_01.json',
               'baseline_01/EXPECTED.json', 'baseline_01/BUILD.json', 'baseline_repro_01/EXPECTED.json',
               'baseline_repro_01/SUMMARY.json', 'f01_fixed_01/EXPECTED.json', 'f01_fixed_01/SUMMARY.json',
               'regressions_01/EXPECTED.json', 'regressions_01/SUMMARY.json', 'strict_01/EXPECTED.json',
               'strict_01/SUMMARY.json', 'renderer_01/EXPECTED.json', 'renderer_01/SUMMARY.json',
               'native_01/EXPECTED.json', 'native_01/SUMMARY.json', 'REFERENCE_VERIFIED_01.json',
               'REGRESSION_DEVICE_GUARD_01.json', 'NATIVE_DEVICE_GUARD_01.json', 'RACE_EXPECTED_01.json']
    save(out / 'GROUP_RESULTS.json', dict(status='PASS', source=src['sha256'],
         regression=regression, strict=identity(base/'strict_01/SUMMARY.json'), renderer=renderer, native=native,
         references=identity(base/'REFERENCE_VERIFIED_01.json'), limited_reuse=identity(out/'REUSE_AUDIT.json'),
         race_case_ID_supplement=race_proof, race_predeclared=identity(base/'RACE_EXPECTED_01.json')))
    diff = subprocess.check_output(['git', 'diff', '--binary', 'HEAD', '--', 'src', 'tests', 'scripts', 'CMakeLists.txt'], cwd=ROOT)
    save(out / 'MANIFEST.json', dict(schema=1, status='PASS', run_complete=True, local_verdict='PASS / GO（F01と本書の限定回帰）',
         public_verdict='NO-GO', merodoa_default_verdict='NO-GO', initial_head=head, final_head=head, branch='main',
         initial_working_tree_clean=True, committed=False, staged=False, pushed=False, source_inventory_sha256=src['sha256'],
         initial_source_inventory_sha256=initial['source']['sha256'], source_diff_sha256=hashlib.sha256(diff).hexdigest(),
         evidence_base=str(base), records=[identity(base/p) for p in records],
         new_counts=dict(F01_reproduction=4, F01_fixed_programs=10, F01_fixed_checks=64, regression_programs=75,
                         regression_checks=326, CTest_Release=20, CTest_Debug=20, evidence_unit_checks=75,
                         renderer_boundary_checks=872, renderer_independent_handoff_programs=6, native_programs=41,
                         normal_RT_subset_programs=8),
         limited_reuse_not_new_execution=dict(dynamic=640, priority=20, strata=54, Exact=896, Golden=25,
                                             fixed_finite=322, fixed_reuse=322, worker_programs=8, worker_checks=48, cache_checks=12),
         not_run=['physical_loopback', 'human_listening', 'Merodoa_TCC_security_scope_bookmark_UI_integration'],
         capabilities=dict(allowExperimentalLoops=False, publicLoopApproved=False, seek=False,
                           currentCycleSpeedChanges=False, publicSeekApproved=False),
         next_public_gates_document='REPORT.md', old_history_rewritten=False))
    print(json.dumps(dict(status='PASS', source=src['sha256'], local='PASS', public='NO-GO', Merodoa_default='NO-GO')))


if __name__ == '__main__':
    raise SystemExit(main())
