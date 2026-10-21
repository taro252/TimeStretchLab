"""最終focused実測を再検査して縮約する。既知のclose未観測は未完のまま残す。"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity, source_manifest
from phase62_aggregation import exact_ids, file_record, need

FINAL_SOURCE = 'fa2b6f4fea83e06b4d31433478ae01cae5d98c3465267c990625d4a30a171c8a'
FOCUSED_IDS = ['control', 'cache', 'playing', 'api', 'race_candidate', 'race_baseline']
RACE_IDS = ['latest_requests_before_B', 'paused_latest_ready_without_resume',
            'paused_audible_output_and_cycles_stationary', 'clear_enabled_off_and_supply_window',
            'stop_cancels_old_loop', 'input_reprepare_and_stale_identity_no_resurrection',
            'KeepPosition_initial_current_cycle_application', 'observed_output_finite_and_no_affected_frames']


def read(path):
    return json.loads(Path(path).read_text())


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def integer(value, label):
    need(type(value) is int and value >= 0, label + ': integer missing')
    return value


def checked_records(records):
    for record in records:
        file_record(record)


def checks(folder, expected_ids, allowed_missing=()):
    rows = jsonl(folder / 'checks.jsonl')
    exact_ids(expected_ids, [r['id'] for r in rows], str(folder) + ' check IDs')
    missing = [r['id'] for r in rows if r.get('status') == 'NOT_OBSERVABLE']
    exact = set(missing) == set(allowed_missing)
    need(exact and all(r['status'] == 'PASS' or r['id'] in allowed_missing and
                      r['status'] == 'NOT_OBSERVABLE' for r in rows), 'non-PASS checks')
    return dict(actual_check_ids=[r['id'] for r in rows],
                check_status={r['id']: r['status'] for r in rows},
                checks=identity(folder / 'checks.jsonl'),
                measured_passed=sum(r['status'] == 'PASS' for r in rows),
                unobservable_ids=missing)


def compact_suite(folder, suite):
    expected, summary = read(folder / 'EXPECTED.json'), read(folder / 'SUMMARY.json')
    jobs = expected.get('jobs', expected.get('commands'))
    need(isinstance(jobs, list) and jobs, 'missing focused plan')
    wanted = [j['id'] for j in jobs]
    exact_ids(wanted, [r['id'] for r in summary['rows']], suite)
    source = expected.get('source_inventory_sha256', expected.get('source', {}).get('sha256'))
    need(source == FINAL_SOURCE and summary.get('run_complete') is True, 'focused source/completion mismatch')
    if suite != 'control':
        need(summary.get('source_inventory_sha256') == source, 'child source mismatch')
        exact_ids(wanted, summary['executed_ids'], 'child executed IDs')
        exact_ids(wanted, summary['required_ids'], 'child required IDs')
    total_expected = sum(integer(j.get('expected', j.get('count')), 'planned check count') for j in jobs)
    need(expected['expected_programs'] == summary['expected_programs'] ==
         summary['executed_programs'] == len(jobs), 'program count mismatch')
    need(expected['expected_checks'] == summary['expected_checks'] == total_expected, 'expected checks mismatch')
    checked_records(expected.get('binaries', expected.get('binary', [])))
    checked_records([expected['input']] + ([expected['other_input']] if expected.get('other_input') else []))
    compact, passed = [], 0
    for row in summary['rows']:
        plan = next(j for j in jobs if j['id'] == row['id'])
        count = plan.get('expected', plan.get('count'))
        need(not row.get('timed_out') and row.get('source_and_binary_unchanged', True) is True, 'timed out/stale binary')
        file_record(row['log'])
        item = {k: row[k] for k in ('id', 'status', 'exit', 'expected', 'executed', 'seconds') if k in row}
        if suite == 'control' and row['id'] == 'unit4096':
            result = read(Path(row['log']['path']))
            need(result.get('PASS') is True and result['expected'] == result['executed'] == count, 'unit result incomplete')
            observed = result['executed']
        else:
            child = folder / row['id']
            result = read(child / 'SUMMARY.json')
            item['final_statistics'] = result
            item['child_summary'] = identity(child / 'SUMMARY.json')
            if suite in ('control', 'playing', 'paused-clear'):
                ids = expected['native_case_ids'] if suite == 'control' else read(child / 'EXPECTED.json')['expected_IDs']
                allowed = ['post_close_all_IDs_terminal_public_query'] if suite == 'playing' and row['id'].startswith('limit_close_') else []
                evidence = checks(child, ids, allowed)
                item.update(evidence)
                observed = evidence['measured_passed']
            else:
                observed = integer(result.get('executed'), 'child executed checks')
            need(result.get('run_complete') is True and result.get('expected') == count and
                 result.get('executed') == observed, 'child final count/completion mismatch')
            if row.get('result') is not None:
                need(row['result'] == result, 'parent cached result differs from child')
            if suite == 'api':
                need(all(result.get(k) is True for k in ('independent_planner', 'whole_Map_bit_exact',
                     'dynamic_RAW_all_frames_bit_exact', 'next_fixed_RAW_bit_exact', 'final_callback_PCM_bit_exact')),
                     'independent API proof missing')
        incomplete = suite == 'playing' and row['id'].startswith('limit_close_')
        if incomplete:
            need(row['status'] == result['status'] == 'INCOMPLETE' and type(row['exit']) is int and
                 row['exit'] == 3 and count == 6 and observed == 5, 'unexpected close incomplete scope')
        else:
            need(row['status'] == 'PASS' and result.get('status', 'PASS' if result.get('PASS') is True else '') == 'PASS' and
                 type(row['exit']) is int and row['exit'] == 0 and observed == count, 'non-PASS focused program')
        need(row['expected'] == count and integer(row['executed'], 'row executed') == observed, 'cached count mismatch')
        # Gitだけでも座標・要求と全RAWのhashを追える小さい原本を保持する。
        if not (suite == 'control' and row['id'] == 'unit4096'):
            names = {'EXPECTED.json', 'COMMIT.json', 'OPERATION.json', 'HOST_SUMMARY.json',
                     'ADMISSION.json', 'REQUEST.json', 'METRICS.json', 'BEFORE_REQUEST.json',
                     'ARTIFACTS.json', 'REFERENCES.json', 'COMMANDS.json', 'SEEK.json',
                     'receipts.jsonl', 'terminal_ledger.jsonl', 'after_Clear_ledger.jsonl',
                     'external_requests.json'}
            evidence = []
            for evidence_path in sorted(child.rglob('*')):
                if evidence_path.is_file() and evidence_path.name in names:
                    record = dict(file=identity(evidence_path))
                    if evidence_path.stat().st_size <= 65536:
                        record['content'] = jsonl(evidence_path) if evidence_path.suffix == '.jsonl' else read(evidence_path)
                    evidence.append(record)
            item['evidence'] = evidence
        passed += observed
        compact.append(item)
    need(summary['executed_checks'] == passed, 'suite measured count mismatch')
    status = 'INCOMPLETE' if suite == 'playing' else 'PASS'
    need(summary['status'] == status, 'suite status inconsistent')
    return dict(id=suite, status=status, run_complete=True, source_inventory_sha256=source,
                expected_programs=len(jobs), executed_programs=len(compact),
                expected_checks=total_expected, executed_checks=passed, required_program_ids=wanted,
                actual_program_ids=[r['id'] for r in compact], expected=identity(folder / 'EXPECTED.json'),
                summary=identity(folder / 'SUMMARY.json'), planned_programs=jobs, rows=compact,
                binaries=expected.get('binaries', expected.get('binary')), input=expected['input'])


def build_compact(base):
    need(source_manifest(ROOT)['sha256'] == FINAL_SOURCE, 'final source changed')
    folder = base / 'focused_final_v3'
    expected, summary = read(folder / 'EXPECTED.json'), read(folder / 'SUMMARY.json')
    exact_ids(FOCUSED_IDS, expected['required_ids'], 'focused planned groups')
    exact_ids(FOCUSED_IDS, [r['id'] for r in summary['rows']], 'focused executed groups')
    need(expected['source']['sha256'] == summary['source_inventory_sha256'] == FINAL_SOURCE and
         summary.get('run_complete') is True and summary['expected'] == summary['executed'] == len(FOCUSED_IDS),
         'focused parent incomplete/source mismatch')
    provenance = read(file_record(expected['build_provenance']))
    need(provenance.get('status') == 'PASS' and provenance.get('source_inventory_sha256') == FINAL_SOURCE,
         'focused build source mismatch')
    rows = []
    for parent in summary['rows']:
        need(parent.get('timed_out') is False, 'focused timeout')
        file_record(parent['summary'])
        file_record(parent['log'])
        if parent['id'].startswith('race_'):
            plan = next(j for j in expected['jobs'] if j['id'] == parent['id'])
            binary = Path(plan['command'][0])
            need(identity(binary)['sha256'] == provenance['binaries'][binary.name], 'race binary/build mismatch')
            child = folder / parent['id']
            stat = read(child / 'SUMMARY.json')
            observations = jsonl(child / 'observations.jsonl')
            exact_ids(RACE_IDS, [r['case'] for r in observations], 'race IDs')
            need(all(r['status'] == 'PASS' for r in observations) and stat['status'] == parent['status'] == 'PASS' and
                 stat['expected'] == stat['executed'] == stat['PASS'] == len(observations) == 8 and
                 parent['result'] == stat and type(parent['exit']) is int and parent['exit'] == 0, 'race incomplete')
            rows.append(dict(id=parent['id'], status='PASS', run_complete=True, source_inventory_sha256=FINAL_SOURCE,
                             expected_checks=8, executed_checks=len(observations), expected_programs=1,
                             executed_programs=1, summary=identity(child / 'SUMMARY.json'),
                             observations=identity(child / 'observations.jsonl'), results=observations, final_statistics=stat))
        else:
            child = compact_suite(folder / parent['id'], parent['id'])
            need(parent['result'] == read(folder / parent['id'] / 'SUMMARY.json') and
                 parent['status'] == child['status'] and parent['expected_checks'] == child['expected_checks'] and
                 parent['expected_programs'] == child['expected_programs'], 'focused parent/child mismatch')
            expected_exit = 2 if parent['id'] == 'playing' else 0
            need(type(parent['exit']) is int and parent['exit'] == expected_exit, 'focused driver exit mismatch')
            rows.append(child)
    need(summary['status'] == 'INCOMPLETE', 'known close gap was incorrectly closed')
    paused = compact_suite(base / 'paused_clear_final_v4', 'paused-clear')
    need(paused['expected_programs'] == 12 and paused['expected_checks'] == 24, 'paused Clear plan changed')
    rows.append(paused)
    return dict(schema=2, run_complete=True, status='INCOMPLETE', source_inventory_sha256=FINAL_SOURCE,
                focused_expected=identity(folder / 'EXPECTED.json'), focused_summary=identity(folder / 'SUMMARY.json'),
                rows=rows, close_unobservable_checks=2, local_overall_go=False)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build_compact(args.base.resolve())
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(status=result['status'], source=result['source_inventory_sha256'], local_overall_go=False)))


if __name__ == '__main__':
    main()
