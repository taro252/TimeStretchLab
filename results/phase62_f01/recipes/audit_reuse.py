"""F01差分に依存しない旧検証だけを、実include/link閉包とSHAで限定接続する。

ビルド・PCM比較・実音声は実行しない。旧runと旧実行体を変更しない。
"""
import argparse
import ast
import csv
import hashlib
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from functools import lru_cache

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import source_manifest

OLD = ROOT / 'build/phase62_e5_review_20261021_01'
NEW = ROOT / 'build/phase62_f01_20261021_01'
OUT = ROOT / 'results/phase62_f01/REUSE_AUDIT.json'
CF = 'cefdb1294e89cb5280ad8f6df401eac59825212334e4110f958ca6f0d7c0199c'
DF = 'dfcd0562c0ddf4dad1b7a1c181895544f4ea119e995f2d2f7c993619fd9e8b54'
LEGACY = '795dd66a101c68f6f0f3cbd994365b62bef29400271c76318355802011375a44'
ALLOWED_DELTA = {'src/platform/macos/ProgressiveMacPlaybackEngine.h',
                 'src/platform/macos/ProgressiveMacPlaybackEngine.mm',
                 'tests/Phase62AdoptionReviewNative.cpp'}
TARGETS = ['phase62_dynamic_pcm_tests', 'phase61_seek_check', 'phase54_core_probe',
           'phase62_loop_tests', 'phase62_fix_reuse_tests',
           'phase62_worker_transaction_tests', 'phase62_cache_focus_tests']
EXCLUDED = ['phase62_render_tests', 'phase62_fix_safety_tests', 'phase62_fix_render_tests',
            'phase62_dynamic_boundary_tests', 'phase62_dynamic_handoff_tests']
ERRORS = []
VERIFIED = {}


def require(value, reason):
    if not value:
        ERRORS.append(reason)
    return bool(value)


def read(path):
    return json.loads(Path(path).read_text())


def ident(path):
    p = Path(path).resolve()
    with p.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(path=str(p), bytes=p.stat().st_size, sha256=digest)


def check_identity(item, label):
    p = Path(item['path'])
    if not p.is_absolute():
        p = ROOT / p
    actual = ident(p)
    require(actual['sha256'] == item['sha256'], label + ': SHA mismatch ' + str(p))
    if 'bytes' in item:
        require(actual['bytes'] == item['bytes'], label + ': byte count mismatch ' + str(p))
    key = actual['path']
    if key in VERIFIED:
        require(VERIFIED[key]['sha256'] == actual['sha256'], label + ': changed during audit ' + key)
    VERIFIED[key] = actual
    return actual


def identities(value, label):
    """明示保存された絶対path/SHA/bytesだけを検査。相対source一覧は別に扱う。"""
    if isinstance(value, dict):
        if {'path', 'sha256', 'bytes'} <= value.keys() and Path(value['path']).is_absolute():
            check_identity(value, label)
        for k, v in value.items():
            if k not in ('source', 'files') or not isinstance(v, list):
                identities(v, label + '.' + k)
            elif k == 'files':
                for row in v:
                    identities(row, label + '.files')
    elif isinstance(value, list):
        for row in value:
            identities(row, label)


def index(manifest):
    return {x['path']: x['sha256'] for x in manifest['files']}


@lru_cache(maxsize=None)
def dependencies(path):
    text = path.read_text().replace('\\\n', ' ')
    # SDK全pathへresolve/lstatを繰り返さない。必要なのはproject依存閉包。
    tokens = shlex.split(text.partition(':')[2])
    return {Path(x).resolve() for x in tokens if x.startswith(str(ROOT) + '/')}


def closure(build, target):
    """link.txtのarchive/dylibを再帰し、実.o.dに記録されたproject依存を収集。"""
    todo, seen, files, targets = [target], set(), set(), {}
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        directory = build / 'CMakeFiles' / (name + '.dir')
        link, flags = directory / 'link.txt', directory / 'flags.make'
        ds = sorted(directory.rglob('*.o.d'))
        require(bool(ds), target + ': no compiled dependency file for ' + name)
        linked = set()
        for token in shlex.split(link.read_text()):
            m = re.fullmatch(r'lib(.+)\.(a|dylib)', Path(token).name)
            if m and m[1] != name and (build / 'CMakeFiles' / (m[1] + '.dir')).exists():
                linked.add(m[1])
        for dep in ds:
            files |= {p for p in dependencies(dep) if p.is_relative_to(ROOT)
                      and p.relative_to(ROOT).parts[0] in ('src', 'tests')}
        targets[name] = dict(link=ident(link), flags=ident(flags),
                             flags_text=flags.read_text(),
                             dependency_files=[ident(p) for p in ds], linked_targets=sorted(linked))
        todo.extend(linked - seen)
    files.add(ROOT / 'CMakeLists.txt')
    return targets, {str(p.relative_to(ROOT)) for p in files}


def python_closure(seeds, historical):
    """静的import＋明示subprocess script。動的import対策に全Python sourceも照合。"""
    todo, seen, rows = list(seeds), set(), []
    while todo:
        p = Path(todo.pop()).resolve()
        if p in seen or not p.exists():
            continue
        seen.add(p)
        record = ident(p)
        if p.is_relative_to(ROOT):
            rel = str(p.relative_to(ROOT))
            if rel in historical:
                require(record['sha256'] == historical[rel], 'Python closure changed: ' + rel)
        rows.append(record)
        tree = ast.parse(p.read_text(), filename=str(p))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules += [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        for module in modules:
            rel = Path(*module.split('.')).with_suffix('.py')
            for directory in (p.parent, ROOT / 'scripts', ROOT / 'tests'):
                candidate = directory / rel
                if candidate.exists():
                    todo.append(candidate)
                    break
    return sorted(rows, key=lambda r: r['path'])


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--previous-audit-dir', type=Path)
    args = parser.parse_args()
    history = None
    if OUT.exists():
        if not args.previous_audit_dir:
            raise RuntimeError('output already exists; preserve previous audit')
        directory = args.previous_audit_dir.resolve()
        saved = read(directory / 'INDEX.json')
        for row in saved['files']:
            actual = ident(row['saved_path'])
            require(actual['sha256'] == row['sha256'] and actual['bytes'] == row['bytes'], 'saved audit history changed')
        first = next(r for r in saved['files'] if Path(r['original_path']) == OUT)
        require(ident(OUT)['sha256'] == first['sha256'], 'existing output differs from preserved first audit')
        if ERRORS:
            raise RuntimeError('; '.join(ERRORS))
        history = dict(index=ident(directory / 'INDEX.json'), files=saved['files'],
                       reason='前回監査・recipeを全byte保存して追補。旧製品runは変更しない')
    current = source_manifest(ROOT)
    old_manifest = read(ROOT / 'results/phase62_e5_review/SOURCE_MANIFEST.json')
    cf, now = index(old_manifest), index(current)
    require(old_manifest['sha256'] == CF, 'old final source inventory differs')
    delta = [dict(path=p, old_sha256=cf.get(p), new_sha256=now.get(p))
             for p in sorted(set(cf) | set(now)) if cf.get(p) != now.get(p)]
    require({r['path'] for r in delta} == ALLOWED_DELTA, 'F01 source delta is not exactly the three scoped files')
    new_build = read(NEW / 'BUILD_CANDIDATE_01.json')
    old_build = read(OLD / 'BUILD_REVIEW_07.json')
    worker_build = read(OLD / 'BUILD_REVIEW_06.json')
    cache_build = read(OLD / 'BUILD_REVIEW_04.json')
    for label, build, source in [('new', new_build, current['sha256']), ('old', old_build, CF),
                                 ('worker', worker_build, DF), ('cache', cache_build, LEGACY)]:
        require(build['status'] == 'PASS' and build['build_exit'] == 0, label + ': build unsuccessful')
        require(build['source_inventory_sha256'] == build['source_inventory_before_build'] ==
                build['source_inventory_after_build'] == source, label + ': build/source not stable')
        require(build['configuration'] == 'Release' and build['architecture'] == 'arm64', label + ': configuration changed')
        require(build['compiler'] == new_build['compiler'] and build['compiler_path'] == new_build['compiler_path'], label + ': compiler changed')
    worker_expected = read(OLD / 'review_functional_final_v2/EXPECTED.json')
    cache_manifest = read(OLD / 'focused_final_v1/cache/SOURCE.json')
    require(worker_expected['source']['sha256'] == DF and cache_manifest['sha256'] == LEGACY, 'execution source identity missing')
    indexes = {CF: cf, DF: index(worker_expected['source']), LEGACY: index(cache_manifest)}
    targets, project = {}, {}
    for target in TARGETS:
        before, bfiles = closure(OLD / 'candidate_build', target)
        after, afiles = closure(NEW / 'candidate_build', target)
        require(bfiles == afiles, target + ': dependency set changed')
        require(set(before) == set(after), target + ': linked target set changed')
        source = DF if target == 'phase62_worker_transaction_tests' else LEGACY if target == 'phase62_cache_focus_tests' else CF
        h = indexes[source]
        for rel in bfiles | afiles:
            actual = ident(ROOT / rel)
            require(rel in h and actual['sha256'] == h.get(rel), target + ': project dependency changed ' + rel)
            project[rel] = dict(path=rel, sha256=actual['sha256'], bytes=actual['bytes'])
        engine_hits = sorted(p for p in bfiles | afiles if 'ProgressiveMacPlaybackEngine' in p)
        require(not engine_hits, target + ': Engine included in reuse target')
        for name in before:
            require(before[name]['flags_text'] == after[name]['flags_text'], target + ': flags changed ' + name)
            before[name].pop('flags_text');after[name].pop('flags_text')
        old_binary, new_binary = ident(OLD / 'candidate_build' / target), ident(NEW / 'candidate_build' / target)
        require(old_binary['sha256'] == old_build['binaries'][target], target + ': old stored binary changed')
        require(new_binary['sha256'] == new_build['binaries'][target], target + ': new binary not bound to build')
        require(old_binary['sha256'] == (worker_build if source == DF else cache_build if source == LEGACY else old_build)['binaries'][target], target + ': old execution build chain mismatch')
        targets[target] = dict(status='PASS', execution_source=source, applicable_to_source=current['sha256'],
                               project_dependencies=sorted(bfiles), engine_dependencies=engine_hits,
                               old_closure=before, new_closure=after, old_binary=old_binary, new_binary=new_binary,
                               binary_identical=old_binary['sha256'] == new_binary['sha256'],
                               basis='実include/link閉包・依存source・flags・compiler不変。旧実行sourceは保持')
    excluded = []
    for target in EXCLUDED:
        directory = OLD / 'candidate_build/CMakeFiles' / (target + '.dir')
        ds = sorted(directory.rglob('*.o.d'))
        hits = sorted({str(p.relative_to(ROOT)) for d in ds for p in dependencies(d)
                       if p.is_relative_to(ROOT) and 'ProgressiveMacPlaybackEngine' in p.name})
        require(any(p.endswith('.mm') for p in hits), target + ': direct Engine include not confirmed')
        excluded.append(dict(target=target, status='EXCLUDED_FROM_REUSE', actual_engine_includes=hits,
                             evidence=[ident(p) for p in ds], link=ident(directory / 'link.txt'),
                             reason='libEngine非リンクでもEngine.mm直接include。rootの新CTest／renderer再実行対象'))
    offline_expected = read(OLD / 'offline_final/EXPECTED.json')
    offline_summary = read(OLD / 'offline_final/SUMMARY.json')
    require(offline_summary['status'] == 'PASS' and offline_summary['run_complete'] is True, 'old offline parent incomplete')
    accepted_offline = ['final_dynamic161', 'final_priority', 'final_regression',
                        'final_dynamic_strata', 'final_dynamic_remaining_formats']
    groups, seeds = [], [ROOT / 'scripts/phase62_review_validation.py', ROOT / 'scripts/phase62_finish_validation.py',
                         ROOT / 'tests/Phase61SeekSmoke.py', ROOT / 'tests/Phase61Golden.py']
    for name in accepted_offline:
        folder = OLD / 'offline_final' / name
        expected, summary = read(folder / 'EXPECTED.json'), read(folder / 'SUMMARY.json')
        parent = next(r for r in offline_summary['rows'] if r['id'] == name)
        require(parent['status'] == 'PASS' and parent['exit'] == 0 and parent['timed_out'] is False, name + ': parent exit/timeout failure')
        require((expected.get('source') or expected.get('provenance', {}).get('source'))['sha256'] == CF, name + ': source mismatch')
        identities(expected, name + '.expected')
        if summary.get('input_recipe'):
            check_identity(summary['input_recipe'], name + '.input_recipe')
            identities(read(summary['input_recipe']['path']), name + '.fixture')
        identities(summary.get('binaries', []), name + '.binaries')
        # suiteの入力WAVは各caseで同一物を反復使用する。保存SHAを一意に集約して照合。
        wavs = {}
        for case in summary.get('cases', []):
            for item in case.get('inputs', []):
                if Path(item['path']).suffix.lower() == '.wav':
                    if item['path'] in wavs:
                        require(wavs[item['path']]['sha256'] == item['sha256'], name + ': inconsistent input identity')
                    wavs[item['path']] = item
        identities(list(wavs.values()), name + '.case_input_WAV')
        measurements = parent['certificate'].get('measured', parent['certificate'].get('measured_totals_by_unit'))
        if name in ('final_dynamic161', 'final_priority', 'final_regression'):
            require(summary['selected_suite_pass'] is True and summary['final_statistics_present'] is True and
                    summary['source_before'] == summary['source_after'] == CF and summary['source_changed'] is False and
                    not summary.get('interruption'), name + ': selected suite incomplete')
            require(all(c['status'] in ('PASS', 'NOT_RUN') for c in summary['cases']), name + ': failed case')
            ids = [c['id'] for c in expected['cases']]
            require(len(ids) == len(set(ids)) == len(summary['cases']) and set(ids) == {c['id'] for c in summary['cases']}, name + ': case ID set mismatch')
            measurements = summary['measurements']
        else:
            wanted = [c['id'] for c in expected['commands']]
            actual = [r['id'] for r in summary['rows']]
            require(len(wanted) == len(set(wanted)) == len(actual) == len(set(actual)) and set(wanted) == set(actual), name + ': program ID set mismatch')
            require(summary['expected'] == summary['executed'] == len(wanted) and all(r['status'] == 'PASS' and r['exit'] == 0 for r in summary['rows']), name + ': incomplete/failed row')
        job = next(j for j in offline_expected['jobs'] if j['id'] == name)
        identities(job, name + '.driver')
        seeds += [Path(a) for a in job['command'] if str(a).endswith('.py')]
        groups.append(dict(id=name, status='PASS', evidence_reused=True, newly_executed=False,
                           execution_source=CF, applicable_to_source=current['sha256'],
                           expected=ident(folder / 'EXPECTED.json'), summary=ident(folder / 'SUMMARY.json'),
                           parent_result=ident(OLD / 'offline_final/SUMMARY.json'), measurements=measurements))
    d161 = read(OLD / 'offline_final/final_dynamic161/SUMMARY.json')['measurements']
    require(d161['programs_executed'] == d161['independent_pcm_planner_map_passed'] == d161['actual_applied_operations'] == 640 and d161['all161_actually_applied_and_independent_pcm_passed'] is True, 'dynamic640/full161 coverage missing')
    require(read(OLD / 'offline_final/final_priority/SUMMARY.json')['measurements']['programs_executed'] == 20, 'priority20 missing')
    reg = read(OLD / 'offline_final/final_regression/SUMMARY.json')['measurements']
    for name, count in [('exact',896),('golden',25),('fixed_finite',322),('fixed_reuse',322)]:
        require(reg[name + '_expected'] == reg[name + '_passed'] == count, name + ': count mismatch')
    for name, count in [('final_dynamic_strata',46),('final_dynamic_remaining_formats',8)]:
        require(read(OLD / 'offline_final' / name / 'SUMMARY.json')['executed'] == count, name + ': count mismatch')
    regression = OLD / 'offline_final/final_regression'
    exact_summary = read(regression / 'exact/summary.json')
    exact_manifest = read(regression / 'exact/manifest.json')
    check_identity(dict(path=str(regression / 'exact/manifest.json'), sha256=exact_summary['manifest_sha256']), 'Exact input manifest')
    require(exact_summary['PASS'] is True and exact_summary['expected'] == exact_summary['passed'] == 896 and
            exact_summary['failed'] == 0 and len(exact_manifest['inputs']) == 8, 'Exact896 fixture/result incomplete')
    for row in exact_manifest['inputs']:
        check_identity(row, 'Exact fixture')
    require(exact_manifest['check_sha256'] == old_build['binaries']['phase61_seek_check'], 'Exact executed binary mismatch')
    check_identity(dict(path=exact_manifest['reference'], sha256=exact_manifest['reference_sha256']), 'Exact reference')
    check_identity(dict(path=str(ROOT / 'tests/Phase61SeekSmoke.py'), sha256=exact_manifest['driver_sha256']), 'Exact driver')
    exact_rows = [json.loads(line) for line in (regression / 'exact/rows.jsonl').read_text().splitlines()]
    require(len(exact_rows) == 896 and all(r['exit'] == 0 and r['result']['PASS'] is True and
            r['result']['output_start'] == r['output_start'] for r in exact_rows), 'Exact rows/result mismatch')
    exact_reference_logs = []
    for name in sorted({r['name'] for r in exact_rows}):
        rows = [r for r in exact_rows if r['name'] == name]
        path = regression / 'exact' / name / 'reference.log'
        reference = read(path);exact_reference_logs.append(ident(path))
        inputs = [0, reference['input_frames']//2 + 17, reference['input_frames'] - 1, reference['input_frames']]
        output_at_input = dict(zip(inputs, reference['positions']))
        require(len(rows) == 8 and len({(r['input_frame'],r['mode']) for r in rows}) == 8,
                'Exact group ID set mismatch ' + name)
        for row in rows:
            result = row['result']
            require(row['reference_pcm_sha256'] == reference['sha256'] and
                    output_at_input.get(row['input_frame']) == row['output_start'] and
                    result['suffix_frames'] == reference['output_frames'] - row['output_start'] and
                    re.fullmatch('[0-9a-f]{64}', result['sha256']) is not None,
                    'Exact reference coordinate/hash mismatch ' + name)
            # result SHAはseek位置以後のsuffix。全曲RAW SHAとの等値は原点だけ。
            if row['output_start'] == 0:
                require(result['sha256'] == reference['sha256'], 'Exact origin SHA mismatch ' + name)
            if result['suffix_frames'] == 0:
                require(result['sha256'] == hashlib.sha256(b'').hexdigest(), 'Exact EOF suffix SHA mismatch ' + name)
        for frame in {r['input_frame'] for r in rows}:
            pair = [r['result']['sha256'] for r in rows if r['input_frame'] == frame]
            require(len(pair) == 2 and pair[0] == pair[1], 'Exact standard/workgroup suffix differ ' + name)
    golden_summary = read(regression / 'golden/summary.json')
    require(golden_summary['PASS'] is True and golden_summary['passed'] == golden_summary['total'] == 25 and
            golden_summary['probe_sha256'] == old_build['binaries']['phase54_core_probe'], 'Golden25 result/binary incomplete')
    golden_inputs, golden_refs, golden_manifests, golden_rows = {}, {}, [], []
    for phase in ('phase12', 'phase28'):
        path = ROOT / 'results' / phase / 'golden/manifest.csv'
        original = subprocess.check_output(['git', 'show', 'e5dc91675723b7163b10cc3ea2323710033caeaa:' + str(path.relative_to(ROOT))], cwd=ROOT)
        require(hashlib.sha256(original).hexdigest() == ident(path)['sha256'], 'Golden historical CSV changed ' + phase)
        golden_manifests.append(ident(path))
        with path.open() as stream:
            golden_rows += [r for r in csv.DictReader(stream) if r['speed'] in ('0.50','0.60','0.70','0.75','0.80')]
    require(len(golden_rows) == 25, 'Golden manifest count mismatch')
    for row in golden_rows:
        result = [r for r in golden_summary['results'] if r['name'] == row['name'] and r['speed'] == row['speed']]
        require(len(result) == 1 and result[0]['PASS'] is True and result[0]['exit'] == 0 and
                result[0]['golden_sha256'] == row['output_sha256'], 'Golden source/reference binding mismatch')
        ip, rp = ROOT / row['input_path'], ROOT / row['output_path']
        golden_inputs[str(ip)] = dict(path=str(ip), sha256=row['input_sha256'])
        golden_refs[str(rp)] = dict(path=str(rp), sha256=row['output_sha256'])
    for item in golden_inputs.values():
        check_identity(item, 'Golden input WAV')
    for item in golden_refs.values():
        check_identity(item, 'Golden frozen WAV')
    regression_inputs = dict(exact=dict(summary=ident(regression / 'exact/summary.json'),
                                       manifest=ident(regression / 'exact/manifest.json'),
                                       rows=ident(regression / 'exact/rows.jsonl'), inputs_verified=8, rows_verified=896,
                                       full_reference_logs=exact_reference_logs,
                                       SHA_semantics='reference_pcm_sha256は全曲、result.sha256はseek以後suffix。当時の全bit比較PASSを保持し、今回RAW再生成はしない。',
                                       audit_erratum='history_02の監査FAILは全曲/suffix SHAを誤って全行等値比較したため。製品Exact896のFAILではない。'),
                             golden=dict(summary=ident(regression / 'golden/summary.json'),
                                         historical_manifest_commit='e5dc91675723b7163b10cc3ea2323710033caeaa',
                                         manifests=golden_manifests, inputs_verified=len(golden_inputs),
                                         reference_WAVs_verified=len(golden_refs), results_verified=25),
                             scope='既存入力・参照WAVの保存SHAを読み取り照合。PCM再生成・新しい比較件数への付替えなし')
    # workerはレビュー36本全体のうち対象8本だけを接続する。
    review = read(ROOT / 'results/phase62_e5_review/REVIEW_CERTIFICATE.json')
    prefixes = ('applying_cancel_', 'planner_cancel_', 'proposal_cancel_', 'cache_old_new_')
    worker_rows = [r for r in review['review_functional']['rows'] if r['id'].startswith(prefixes)]
    require(len(worker_rows) == 8 and len({r['id'] for r in worker_rows}) == 8 and
            sum(r['executed'] for r in worker_rows) == 48, 'worker 8/48 count mismatch')
    for row in worker_rows:
        require(row['status'] == 'PASS' and row['exit'] == 0 and row['timeout'] is False and
                row['actual_run_source'] == DF and row['expected'] == row['executed'] == 6, 'worker failed/incomplete ' + row['id'])
        check_identity(row['log'], 'worker log')
    # 同じEXPECTED内の他28本（特に後で変更されたpartial binary）を
    # この8本の証明へ混ぜない。
    identities(worker_expected['driver'], 'worker driver')
    identities(worker_expected['build_provenance'], 'worker build')
    identities([b for b in worker_expected['binaries']
                if Path(b['path']).name == 'phase62_worker_transaction_tests'], 'worker binary')
    identities(worker_expected['inputs'], 'worker input identities')
    groups.append(dict(id='worker_transaction', status='PASS', evidence_reused=True, newly_executed=False,
                       execution_source=DF, applicable_to_source=current['sha256'], programs=8, checks=48,
                       required_ids=[r['id'] for r in worker_rows],
                       expected=ident(OLD / 'review_functional_final_v2/EXPECTED.json'),
                       original_summary=ident(OLD / 'review_functional_final_v2/SUMMARY.json'),
                       certificate=ident(ROOT / 'results/phase62_e5_review/REVIEW_CERTIFICATE.json'),
                       scope='36本の全reviewを再利用せず、Engine非依存の8 worker programだけ'))
    cache_folder = OLD / 'focused_final_v1/cache'
    cache_expected, cache = read(cache_folder / 'EXPECTED.json'), read(cache_folder / 'SUMMARY.json')
    require(cache['status'] == 'PASS' and cache['run_complete'] is True and cache['source_inventory_sha256'] == LEGACY and
            cache['expected_programs'] == cache['executed_programs'] == cache['expected_checks'] == cache['executed_checks'] == 12,
            'cache 12 complete result missing')
    wanted, actual = cache_expected['required_ids'], [r['id'] for r in cache['rows']]
    require(len(wanted) == len(set(wanted)) == len(actual) == len(set(actual)) == 12 and set(wanted) == set(actual) and
            all(r['status'] == 'PASS' and r['exit'] == 0 and r['timed_out'] is False for r in cache['rows']), 'cache IDs/result mismatch')
    identities(cache_expected, 'cache expected');identities(read(cache_folder / 'INPUT_RECIPE.json'), 'cache fixture')
    native_chain = read(OLD / 'NATIVE_EQUIVALENCE_AFTER_VALIDATOR.json')
    require(native_chain['status'] == 'PASS' and native_chain['actual_run_source'] == LEGACY, 'cache old provenance chain missing')
    identities(native_chain['python_runtime_closure'], 'old runtime closure')
    groups.append(dict(id='cache_focus', status='PASS', evidence_reused=True, newly_executed=False,
                       execution_source=LEGACY, applicable_to_source=current['sha256'], programs=12, checks=12,
                       required_ids=wanted, expected=ident(cache_folder / 'EXPECTED.json'), summary=ident(cache_folder / 'SUMMARY.json'),
                       intermediate_chain=[ident(OLD / 'BUILD_REVIEW_04.json'), ident(OLD / 'NATIVE_EQUIVALENCE_AFTER_VALIDATOR.json'),
                                           ident(ROOT / 'results/phase62_e5_review/REVIEW_CERTIFICATE.json'), ident(OLD / 'BUILD_REVIEW_07.json')],
                       scope='旧親focusedはINCOMPLETEのまま。成功cache子だけを限定接続'))
    # 検証器/fixture generator/subprocess scriptを含む全Python sourceはcfから不変。
    python_sources = []
    for rel, old_sha in cf.items():
        if rel.endswith('.py'):
            actual = ident(ROOT / rel)
            require(actual['sha256'] == old_sha, 'Python source changed ' + rel)
            python_sources.append(dict(path=rel, sha256=actual['sha256']))
    runtime = python_closure(seeds, cf)
    # 凍結素材を現在の製品DSPから再生成せず、保存byteを再照合する。
    reference_path = ROOT / 'results/phase62_e5_review/REFERENCE_VERIFIED.json'
    reference = read(reference_path)
    require(reference['status'] == 'PASS' and reference['run_complete'] is True and
            reference['expected'] == reference['executed'] == reference['passed'] == 10, 'old reference audit incomplete')
    identities(reference['details'], 'frozen reference')
    frozen = reference['details']['dynamic_523_sources_git_and_sha']
    frozen_files = read(frozen['recorded_inventory']['path'])
    require(len(frozen_files) == 523, 'frozen source count mismatch')
    for row in frozen_files:
        p = Path(frozen['source_root']) / row['path'];data = p.read_bytes()
        git_blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(hashlib.sha256(data).hexdigest() == row['sha256'] and git_blob == row['git_blob'] == row['actual_git_blob'], 'frozen source changed ' + row['path'])
    final_source = source_manifest(ROOT)
    require(final_source['sha256'] == current['sha256'], 'source changed during read-only audit')
    report = dict(schema=1, suite='phase62_f01_limited_evidence_reuse',
                  created_utc=datetime.now(timezone.utc).isoformat(), status='PASS' if not ERRORS else 'FAIL',
                  run_complete=True, execution_source_preserved=True, old_results_relabelled=False,
                  applicable_to_source=current['sha256'], source_before_audit=current['sha256'], source_after_audit=final_source['sha256'],
                  source_delta=delta, allowed_reuse_groups=[r['id'] for r in groups], groups=groups,
                  preserved_initial_audit=history, regression_input_reference_audit=regression_inputs,
                  target_audits=targets, project_dependency_files=sorted(project.values(), key=lambda r:r['path']),
                  excluded_engine_include_targets=excluded,
                  build_provenance=[ident(NEW / 'BUILD_CANDIDATE_01.json'), ident(OLD / 'BUILD_REVIEW_07.json'),
                                    ident(OLD / 'BUILD_REVIEW_06.json'), ident(OLD / 'BUILD_REVIEW_04.json')],
                  compiler=new_build['compiler'], configuration='Release', architecture='arm64',
                  python_source_superset=python_sources, runtime_driver_import_closure=runtime,
                  frozen_reference=dict(previous_audit=ident(reference_path), dynamic_source_files_verified=523,
                                        dynamic_commit=reference['dynamic_commit'], fixed_commit=reference['fixed_commit'],
                                        product_DSP_used_to_rebuild_reference=False),
                  verified_identity_files=sorted(VERIFIED.values(), key=lambda r:r['path']),
                  evidence_scope='既存の完了PCM/planner/Map比較結果の限定再利用。今回PCM/音声の新実行は0。正常RT/native/rendererの新PASSには数えない。',
                  system_headers='SDK/system header全byteの歴史的同一性は別証明にしない。compiler/flagsと保存済み実行体SHAを比較。',
                  errors=ERRORS, recipe=ident(__file__), new_PCM_cases=0, audio_executed=False,
                  completion_marker='PHASE62_F01_REUSE_AUDIT_COMPLETE', local_overall_go=False)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(status=report['status'], groups=len(groups), targets=len(targets),
                          binary_identical=sum(r['binary_identical'] for r in targets.values()),
                          excluded=len(excluded), errors=ERRORS), ensure_ascii=False))
    return 0 if not ERRORS else 2


if __name__ == '__main__':
    raise SystemExit(main())
