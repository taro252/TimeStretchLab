"""既存品質証拠の現SHAと再利用条件を監査する。音声/build/PCM数値再演算なし。"""
import argparse
import hashlib
import json
from pathlib import Path

FIXED_SHA = 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
COLD_IDS = [f'{side}_cold_A{at}' for side in ('before', 'after') for at in (0, 30, 270)]
WARM_IDS = [f'{side}_warm_{mode}' for side in ('before', 'after') for mode in ('serial', 'replace')]
PREFIX_IDS = ['prefix_baseline', 'prefix_candidate']
COLD_CHECKS = {'reference_identity', 'raw_all_bits', 'output_all_bits', 'interval_coordinates', 'rounds_and_cycles', 'static_cache_hit'}
WARM_CHECKS = {'independent_map', 'raw_all_bits', 'output_all_bits', 'coordinates', 'gain'}


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def need(ok, message):
    if not ok:
        raise ValueError(message)


class Audit:
    def __init__(self):
        self.cache, self.artifacts, self.checks = {}, {}, []

    def identity(self, path):
        path = Path(path).resolve()
        stat = path.stat()
        stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if self.cache.get(path, (None,))[0] != stamp:
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = path.stat()
            need(stamp == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), '監査中に変更: ' + str(path))
            self.cache[path] = stamp, dict(path=str(path), bytes=stat.st_size, sha256=digest)
        value = self.cache[path][1]
        self.artifacts[str(path)] = value
        return value

    def verify(self, saved, label):
        actual = self.identity(saved['path'])
        need(actual == saved, label + ': 現artifact identityが保存値と違う')
        return actual

    def case(self, label, operation):
        try:
            detail = operation()
            self.checks.append(dict(id=label, status='PASS', detail=detail))
        except Exception as error:
            self.checks.append(dict(id=label, status='FAIL', reason=str(error)))


def unique(rows, key='id'):
    result = {row[key]: row for row in rows}
    need(len(result) == len(rows), '重複ID: ' + key)
    return result


def complete(value, count):
    need(value['status'] == 'PASS' and value['run_complete'] is True, '未完了/失敗summary')
    need(value['expected'] == value['executed'] == count, '予定/実行件数が不一致')


def option(command, name):
    need(command.count(name) == 1, 'validator CLIの欠落/重複: ' + name)
    index = command.index(name)
    need(index + 1 < len(command), 'validator CLIの値欠落: ' + name)
    return command[index + 1]


def cold_origin(audit, case_id, row):
    """03→02のような多段再利用も、実際に音声を採取した行まで辿る。"""
    chain, seen = [], set()
    while row.get('reused_native_and_validation') is True:
        saved = row['source_record']
        audit.verify(saved, case_id + ' source_record')
        path = str(Path(saved['path']).resolve())
        need(path not in seen and len(chain) < 16, 'cold source_recordの循環/過剰段数')
        seen.add(path)
        parent = unique(read(path)['rows'])[case_id]
        for key in ('id', 'command', 'log', 'validator', 'validation', 'expected', 'executed', 'status', 'exit', 'timeout', 'source'):
            need(row[key] == parent[key], 'cold source_recordとの不一致: ' + key)
        need(parent['status'] == 'PASS' and parent['exit'] == 0 and not parent['timeout'] and parent['expected'] == parent['executed'] == 6,
             'cold source_recordの個別結果が未完了')
        chain.append(saved)
        row = parent
    command = row['validator']['command']
    capture = Path(option(command, '--capture')).resolve()
    folder = Path(option(command, '--output')).resolve()
    need(Path(row['command'][-1]).resolve() == capture and capture.name == case_id and folder.name == case_id + '_audit', 'cold実capture/auditのCLI対応不一致')
    need(Path(row['log']['path']).resolve() == capture.parent / (case_id + '.log'), 'cold native logの場所不一致')
    return row, capture, folder, chain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--previous', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--final-build', type=int, default=7)
    parser.add_argument('--cpu-build', type=int, default=4)
    parser.add_argument('--control-build', type=int, default=5)
    parser.add_argument('--cpu-run', type=Path, default=Path('cpu_after_01'))
    parser.add_argument('--control-run', type=Path, default=Path('control_regressions_01'))
    args = parser.parse_args()
    need(not args.output.exists(), '既存監査を上書きしない')
    base, current, previous = args.base.resolve(), args.current.resolve(), args.previous.resolve()
    audit = Audit()
    cs, ps = read(current / 'SUMMARY.json'), read(previous / 'SUMMARY.json')
    ce, pe = read(current / 'EXPECTED.json'), read(previous / 'EXPECTED.json')
    cr, pr = read(current / 'REFERENCES.json'), read(previous / 'REFERENCES.json')
    current_jobs, previous_jobs = unique(ce['jobs']), unique(pe['jobs'])
    current_rows, previous_rows = unique(cs['rows']), unique(ps['rows'])
    need(min(args.final_build, args.cpu_build, args.control_build) > 0, 'build番号は正の整数')
    builds = {n: read(base / f'candidate_build_{n:02}/BUILD.json') for n in {args.cpu_build, args.control_build, args.final_build}}
    cpu_run = args.cpu_run.resolve() if args.cpu_run.is_absolute() else base / args.cpu_run
    control_run = args.control_run.resolve() if args.control_run.is_absolute() else base / args.control_run
    inputs = {Path(row['path']).name: row for row in ce['inputs']}

    def root_ledger():
        need(cs['status'] == 'PASS' and cs['run_complete'] is True, 'currentが未完了')
        need(cs['expected_programs'] == cs['executed_programs'] == len(current_rows) == 12, 'current program件数')
        need(cs['expected_checks'] == cs['executed_checks'] == sum(row['executed'] for row in current_rows.values()) == 88, 'current check件数')
        need(set(current_jobs) == set(current_rows) == set(COLD_IDS + WARM_IDS + PREFIX_IDS), 'current予定ID集合')
        need(all(row['status'] == 'PASS' and row['exit'] == 0 and not row['timeout'] for row in current_rows.values()), 'current個別失敗/時間切れ')
        need(ce['source']['sha256'] == builds[args.final_build]['source'], '最終sourceとの不一致')
        for key in ('baseline_build', 'candidate_build', 'reference_binary'):
            audit.verify(ce[key], 'current ' + key)
        need(Path(ce['candidate_build']['path']).resolve() == (base / f'candidate_build_{args.final_build:02}/BUILD.json').resolve(), '選択した最終BUILDとのlink不一致')
        audit.verify(ce['driver'], 'current集計recipe')
        need(ce['reference_binary']['sha256'] == FIXED_SHA, '固定参照binary不一致')
        for item in ce['inputs']:
            audit.verify(item, 'current input')
        for path in (current / 'EXPECTED.json', current / 'SUMMARY.json', current / 'REFERENCES.json',
                     previous / 'EXPECTED.json', previous / 'SUMMARY.json', previous / 'REFERENCES.json'):
            audit.identity(path)
        return dict(programs=12, checks=88, current_source=builds[args.final_build]['source'], independent_pcm_recomputed=False)
    audit.case('root.complete_' + current.name.removeprefix('ab_quality_'), root_ledger)

    def old_failures():
        first = read(base / 'ab_quality_01/SUMMARY.json')
        second = read(base / 'ab_quality_02/SUMMARY.json')
        need(first['status'] != 'PASS' and second['status'] != 'PASS', '旧collector失敗の全体結果を書換えた')
        need(not first['run_complete'] and not second['run_complete'], '旧collector失敗を全体完了へ変更')
        audit.identity(base / 'ab_quality_01/SUMMARY.json')
        audit.identity(base / 'ab_quality_02/SUMMARY.json')
        return dict(quality01=first['status'], quality02=second['status'], old_full_summaries_reused_as_GO=False,
                    reused_scope=[key for key in COLD_IDS if current_rows[key].get('reused_native_and_validation') is True], public_go=False)
    audit.case('root.old_failures_preserved', old_failures)

    for ref_id in ('prefix_baseline', 'prefix_candidate', 'warm', 'cold'):
        def reference(ref_id=ref_id):
            need(ce['reference_groups'] == pe['reference_groups'], '旧/現 reference groups不一致')
            group = next(row for row in ce['reference_groups'] if row['id'] == ref_id)
            row, old = cr[ref_id], pr[ref_id]
            for key in ('command', 'exit', 'timeout', 'meta', 'raw', 'input', 'log'):
                need(row[key] == old[key], '旧/現 reference条件不一致: ' + key)
            need(row['exit'] == 0 and row['timeout'] is False, '参照生成が未完了')
            for key in ('raw', 'input', 'log'):
                audit.verify(row[key], ref_id + ' ' + key)
            need(read(row['log']['path']) == row['meta'], '参照metaとSHA固定した生成logが違う')
            need(row['meta']['sha256'] == row['raw']['sha256'] and row['meta']['output_frames'] * row['meta']['channels'] * 4 == row['raw']['bytes'], '参照RAWのSHA/全長不一致')
            command = list(map(str, row['command']))
            need(command[0] == ce['reference_binary']['path'] and command[1] == str(group['input']) and command[2:4] == ['1000000', group['preset']] and
                 command[4] == row['raw']['path'] and command[5:] == list(map(str, group['positions'])), '参照CLI/preset/入力座標が不一致')
            return dict(raw_sha256=row['raw']['sha256'], input_sha256=row['input']['sha256'], positions=row['meta']['positions'], frozen_binary_sha256=FIXED_SHA)
        audit.case('reference.' + ref_id, reference)

    for case_id in COLD_IDS:
        def cold(case_id=case_id):
            job, oldjob = current_jobs[case_id], previous_jobs[case_id]
            row, previous_row = current_rows[case_id], previous_rows[case_id]
            reused = row.get('reused_native_and_validation') is True
            for key in ('id', 'kind', 'ref', 'indices', 'expected'):
                need(job[key] == oldjob[key], '旧/現cold job不一致: ' + key)
            if reused:
                need(job['binary'] == oldjob['binary'] and job['command'][:-1] == oldjob['command'][:-1], '再利用coldのbinary/CLI/preset/speed/range不一致')
                need(Path(row['source_record']['path']).resolve() == previous / 'SUMMARY.json', '再利用元が指定previousでない')
                need(row['validation'] == previous_row['validation'], 'previousから再利用した品質判定を変更')
            else:
                need(row['command'] == job['command'] and row['source'] == job['source'] and 'source_record' not in row, '新実行coldのCLI/source不一致')
            oldrow, capture, folder, chain = cold_origin(audit, case_id, row)
            need(oldrow['command'][:-1] == job['command'][:-1], '実採取coldのbinary/CLI/preset/speed/range不一致')
            for value in (row, oldrow):
                need(value['status'] == 'PASS' and value['exit'] == 0 and not value['timeout'] and value['expected'] == value['executed'] == 6, 'cold再利用元が未完了')
            need(row['validation'] == oldrow['validation'], '再利用した品質判定を変更')
            audit.verify(oldrow['log'], 'cold native log')
            audit.verify(oldrow['validator']['log'], 'cold validator log')
            need(oldrow['validator']['exit'] == 0 and not oldrow['validator']['timeout'], '旧validator失敗')
            expected, result = read(folder / 'EXPECTED.json'), read(folder / 'SUMMARY.json')
            complete(result, 6)
            need(result == oldrow['validation'] and result['passed'] == 6 and set(result['checks']) == COLD_CHECKS and
                 all(value['status'] == 'PASS' for value in result['checks'].values()), '旧audit全6checks不一致')
            need(expected['case_id'] == case_id and expected['expected'] == 6 and set(expected['expected_ids']) == COLD_CHECKS and expected['expected_rounds'] == 2 and
                 expected['minimum_cycles'] == 3 and expected['preset'] == 'candidate' and expected['speed_micros'] == 1000000 and expected['expected_cache_mode'] == 'raw', '旧audit条件不一致')
            artifacts = expected['input_and_artifacts']
            need(set(artifacts) == {'input', 'reference_raw', 'reference_map', 'reference_binary', 'host_binary', 'driver', 'EXPECTED.json', 'SUMMARY.json',
                                    'measurements.jsonl', 'raw_records.jsonl', 'spans.jsonl', 'raw.f32', 'output_before_gain.f32'}, '旧audit必須artifact集合不一致')
            for name, identity in artifacts.items():
                audit.verify(identity, case_id + ' ' + name)
            for name in ('EXPECTED.json', 'SUMMARY.json', 'measurements.jsonl', 'raw_records.jsonl', 'spans.jsonl', 'raw.f32', 'output_before_gain.f32'):
                need(Path(artifacts[name]['path']).resolve() == capture / name, 'cold CLIとaudit captureの場所不一致: ' + name)
            validation_command = oldrow['validator']['command']
            need(option(validation_command, '--case-id') == case_id and option(validation_command, '--preset') == 'candidate' and
                 option(validation_command, '--speed-micros') == '1000000' and option(validation_command, '--expected-rounds') == '2' and
                 option(validation_command, '--min-cycles') == '3' and option(validation_command, '--expected-cache-mode') == 'raw' and
                 validation_command.count('--require-cache-hit') == 1, 'cold実validator CLIの条件不一致')
            for argument, name in (('--input', 'input'), ('--host-binary', 'host_binary'), ('--reference-binary', 'reference_binary'),
                                   ('--reference-raw', 'reference_raw'), ('--reference-map', 'reference_map')):
                need(Path(option(validation_command, argument)).resolve() == Path(artifacts[name]['path']).resolve(), 'cold実validator CLIとartifact不一致: ' + argument)
            audit.identity(folder / 'EXPECTED.json'); audit.identity(folder / 'SUMMARY.json')
            need(artifacts['input'] == inputs['artificial_300s.wav'] and artifacts['reference_binary'] == ce['reference_binary'] and
                 artifacts['reference_raw'] == cr['cold']['raw'] and artifacts['host_binary'] == job['binary'], '旧captureのinput/reference/binaryが最終候補と違う')
            need(read(artifacts['reference_map']['path']) == read(current / (case_id + '_map.json')), '旧/現cold Map内容不一致')
            native = read(artifacts['SUMMARY.json']['path']); complete(native, 2)
            measurements = lines(artifacts['measurements.jsonl']['path'])
            rounds = result['checks']['rounds_and_cycles']['rounds']
            need(len(measurements) == len(rounds) == 2 and [x['round'] for x in measurements] == [0, 1] and [x['round'] for x in rounds] == [0, 1], '2round集合不一致')
            need(result['checks']['rounds_and_cycles']['minimum_cycles'] == 3 and result['checks']['static_cache_hit']['checked_rounds'] == [1], '3周期/cache-hit対象不一致')
            for observed, checked in zip(measurements, rounds):
                need(observed['cycles'] == checked['completed_periods'] >= 3 and observed['missing'] == observed['callback_new'] == 0 and
                     observed['checkpoint_start'] + observed['cold_discarded_frames'] == result['result']['independent_OA'], 'round品質/座標不一致')
            warm = measurements[1]
            need(warm['cold_discarded_frames'] < 2048 and (warm['checkpoint_start'] > 0 or
                 (result['result']['independent_OA'] == 0 and warm.get('initial_checkpoint_hit') == 1 and warm['checkpoint_start'] == warm['cold_discarded_frames'] == 0)), 'OA=0専用hit/保存点不一致')
            need(native['owners_peak'] <= 2 and native['owners_alive'] == 0, 'cold owner cap')
            need(len(lines(artifacts['raw_records.jsonl']['path'])) == native['raw_records'] and len(lines(artifacts['spans.jsonl']['path'])) == native['output_spans'], 'cold records/spans件数不一致')
            return dict(checks=6, rounds=2, minimum_cycles=3, raw_sha256=artifacts['raw.f32']['sha256'],
                        output_sha256=artifacts['output_before_gain.f32']['sha256'], host_sha256=job['binary']['sha256'],
                        execution_source=oldrow['source'], final_job_source=job['source'], reused_native_and_validation=reused,
                        source_record_chain=chain, capture=str(capture), audit=str(folder), same_binary_allows_source_manifest_alias=reused)
        audit.case('reuse.' + case_id, cold)

    for case_id in WARM_IDS:
        def warm(case_id=case_id):
            job, row = current_jobs[case_id], current_rows[case_id]
            folder = current / case_id
            native, ex = read(folder / 'SUMMARY.json'), read(folder / 'EXPECTED.json')
            complete(native, 1)
            result, expected = read(current / (case_id + '_audit/SUMMARY.json')), read(current / (case_id + '_audit/EXPECTED.json'))
            complete(result, 5)
            need(result['passed'] == 5 and set(result['checks']) == WARM_CHECKS and all(value == 'PASS' for value in result['checks'].values()), 'warm全5checks不一致')
            need(row['validation'] == result and row['validator']['exit'] == 0 and not row['validator']['timeout'], 'warm validator link')
            for name in ('input', 'reference_binary', 'reference_raw', 'reference_map', 'equations', 'driver'):
                audit.verify(expected[name], case_id + ' ' + name)
            for name in ('EXPECTED.json', 'SUMMARY.json', 'raw_records.jsonl', 'spans.jsonl', 'raw.f32', 'output_before_gain.f32'):
                audit.identity(folder / name)
            audit.verify(job['binary'], 'warm実行binary'); audit.verify(row['log'], 'warm log'); audit.verify(row['validator']['log'], 'warm validator log')
            need(expected['reference_raw'] == cr['warm']['raw'] and expected['input'] == inputs['artificial_240s.wav'] and
                 native['mode'] == ex['mode'] == job['command'][2] and ex['A'] == 1440000 and ex['B'] == 1536000 and ex['preset'] == 'candidate' and ex['speed'] == 1, 'warm条件/参照不一致')
            records, spans = lines(folder / 'raw_records.jsonl'), lines(folder / 'spans.jsonl')
            epochs, next_at = {}, {}
            for item in records:
                epoch, session, at = item['epoch'], item['session'], item['at']
                need(epoch > 0 and session > 0 and (epoch not in epochs or (epochs[epoch] == session and next_at[epoch] == at)), 'warm epoch/session/RAW連続性不一致')
                epochs[epoch], next_at[epoch] = session, at + item['frames']
            oa, ob = read(expected['reference_map']['path'])['positions']; period, width = ob - oa, 240
            loop_sessions = {native['old_session'], native['first_A_session']}
            first_epoch = {}
            for item in records:
                if item['session'] in loop_sessions:
                    first_epoch.setdefault(item['session'], item['epoch'])
            need(set(first_epoch) == loop_sessions and native['first_A_at'] == oa, 'warm新旧Loopの初回epoch/A欠落')
            natural, periodic_spans, clear_exit_spans = 0, 0, 0
            for span in spans:
                for prefix, frames, at, epoch in [('', span['frames'], span['new_at'], span['new_epoch']),
                                                   ('old_', span['mixed'], span['old_at'], span['old_epoch'])]:
                    if not frames:
                        continue
                    need(epoch in epochs, 'warm spanのepochがRAWにない')
                    if epochs[epoch] not in loop_sessions:
                        continue
                    # ClearのB継続への退出は自然周回ではない。通常ownerがBから
                    # 開始し、旧末尾を5ms混合するこの1区間は周期補正を行わない。
                    # 製品flagだけで除外せず、新旧ownerと独立OB/幅で限定する。
                    clear_exit = (prefix == 'old_' and epochs[epoch] == native['old_session'] and
                                  epochs[span['new_epoch']] not in loop_sessions and span['new_at'] == ob and
                                  at == ob - width and frames == span['frames'] == span['new_received'] ==
                                  span['old_received'] == width and span['transition_offset'] == 0 and
                                  span['transition_length'] == width)
                    if clear_exit:
                        need(span['periodic'] == span['old_periodic'] == span['old_head'] == span['old_tail'] ==
                             span['head'] == span['tail'] == span['correction_before_mix'] == 0, 'Clear出口の周期補正/順序が不一致')
                        clear_exit_spans += 1
                        continue
                    need(span[prefix + 'periodic'] == 1 and span[prefix + 'period_frames'] == period and span[prefix + 'boundary_frames'] == width and
                         span[prefix + 'period_offset'] == at - oa and oa <= at < at + frames <= ob, 'warm独立周期/境界位置')
                    head = epoch != first_epoch[epochs[epoch]] and at < oa + width
                    tail = at >= ob - width
                    need(bool(span[prefix + 'head']) == head and bool(span[prefix + 'tail']) == tail, 'warm独立位置/周回によるhead/tailが製品flagと違う')
                    need(at + frames <= (oa + width if head else ob if tail else ob - width), 'warm補正窓をspanが跨ぐ')
                    periodic_spans += 1
                    if not prefix and epochs[epoch] == native['first_A_session'] and at + frames == ob:
                        natural += 1
            need(natural == native['final_cycles'] == native['natural_boundary_spans'] >= 2 and native['adoption_cycles'] <= native['final_cycles'], 'warm自然B/採用時cycleの分離不一致')
            need(native['owner_peak'] <= 2 and native['checkpoint_peak'] <= 2 and native['worker_new'] == native['worker_deadlines'] == 0, 'warm資源/worker品質不一致')
            return dict(native_checks=1, independent_checks=5, metadata_only_extra_boundary_check=True, periodic_spans=periodic_spans,
                        natural_B_spans=natural, final_cycles=native['final_cycles'], clear_exit_spans=clear_exit_spans, pcm_recomputed=False)
        audit.case('warm.' + case_id, warm)

    for case_id in PREFIX_IDS:
        def prefix(case_id=case_id):
            folder = current / case_id
            expected, result, checks = read(folder / 'EXPECTED.json'), read(folder / 'SUMMARY.json'), lines(folder / 'checks.jsonl')
            complete(result, 16)
            need(result['passed'] == 16 and len(checks) == 16 and len(unique(checks)) == 16 and set(unique(checks)) == set(expected['required_ids']) and
                 len(expected['required_ids']) == len(set(expected['required_ids'])) == 16 and all(item['pass'] is True for item in checks), 'prefix重複なし完全集合/件数不一致')
            need(expected['binary_sha256'] == current_jobs[case_id]['binary']['sha256'] and expected['reference_raw_sha256'] == cr[case_id]['raw']['sha256'] and
                 expected['reference_binary_sha256'] == FIXED_SHA, 'prefix binary/reference不一致')
            need(expected['input_sha256'] == inputs['artificial_12s.wav']['sha256'] and expected['preset'] == current_jobs[case_id]['preset'] and
                 expected['reference_positions'] == cr[case_id]['meta']['positions'], 'prefix入力/preset/独立Map座標不一致')
            audit.verify(current_jobs[case_id]['binary'], 'prefix binary')
            for name in ('EXPECTED.json', 'SUMMARY.json', 'checks.jsonl', 'audit.jsonl'):
                audit.identity(folder / name)
            return dict(checks=16, unique_ids=16, comparison='complete unordered set', native_deadlines='NOT_ASSESSED')
        audit.case('prefix.' + case_id, prefix)

    for binary, previous_build in [('phase62_control_cpu_native', args.cpu_build), ('phase62_control_summary_tests', args.control_build),
                                    ('phase62_input_watch_tests', args.control_build), ('phase62_clear_reenable_native', args.control_build)]:
        def binary_alias(binary=binary, previous_build=previous_build):
            old, final = builds[previous_build]['binaries'][binary], builds[args.final_build]['binaries'][binary]
            need(builds[previous_build]['status'] == builds[args.final_build]['status'] == 'PASS' and old['bytes'] == final['bytes'] and old['sha256'] == final['sha256'], '実測buildと最終buildのbinary不一致')
            audit.verify(final, '最終binary')
            audit.identity(base / f'candidate_build_{previous_build:02}/BUILD.json'); audit.identity(base / f'candidate_build_{args.final_build:02}/BUILD.json')
            if binary == 'phase62_control_cpu_native':
                cpu = read(cpu_run / 'EXPECTED.json')
                need(cpu['binary'] == old, 'CPU実行binaryとのlink不一致')
                audit.verify(cpu['build_record'], 'CPU BUILD link')
                need(Path(cpu['build_record']['path']).resolve() == (base / f'candidate_build_{args.cpu_build:02}/BUILD.json').resolve(), 'CPU実行BUILDが指定と違う')
                audit.identity(cpu_run / 'EXPECTED.json')
            else:
                control = read(control_run / 'EXPECTED.json')
                audit.verify(control['build'], 'control BUILD link')
                need(Path(control['build']['path']).resolve() == (base / f'candidate_build_{args.control_build:02}/BUILD.json').resolve(), 'control実行BUILDが指定と違う')
                audit.identity(control_run / 'EXPECTED.json')
            return dict(binary=binary, previous_build=previous_build, final_build=args.final_build, bytes=final['bytes'], sha256=final['sha256'])
        audit.case('binary.' + binary, binary_alias)

    expected_count = 22
    need(len(audit.checks) == expected_count, '監査予定件数の実装不一致')
    result = dict(suite='phase62_quality_reuse_independent_audit', status='PASS' if all(row['status'] == 'PASS' for row in audit.checks) else 'FAIL',
                  run_complete=True, expected=expected_count, executed=len(audit.checks), passed=sum(row['status'] == 'PASS' for row in audit.checks),
                  recipe=audit.identity(Path(__file__)), current=str(current), previous=str(previous), checks=audit.checks,
                  selection=dict(final_build=args.final_build, cpu_build=args.cpu_build, control_build=args.control_build,
                                 cpu_run=str(cpu_run), control_run=str(control_run)),
                  artifact_count=len(audit.artifacts), artifacts=list(audit.artifacts.values()), build=False, audio=False,
                  pcm_numerical_recalculation=False, public_go=False, realtime_deadlines='NOT_ASSESSED',
                  limitations=['既存独立PCM判定はartifact全SHAを結合して再利用する', 'warm補正窓はJSON座標だけを追加監査しPCMを再演算しない',
                               '選択した実測buildと最終buildは対象実行binaryの同一性を検査し、全source manifest同一とは主張しない'])
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: result[key] for key in ('status', 'expected', 'executed', 'passed', 'artifact_count')}, ensure_ascii=False))
    for row in audit.checks:
        if row['status'] != 'PASS':
            print(row['id'] + ': ' + row['reason'])
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
