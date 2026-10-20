"""Phase62動的Loopの分離した検証台帳。既存証拠や実行体を上書きしない。"""
import argparse
from collections import Counter
import csv
import json
import math
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from phase57_study import fixture
from phase59_native_validation import wav_info
from phase62_evidence import Ledger, identity, sha, source_manifest

ROOT = Path(__file__).resolve().parents[1]
ORACLE_SHA = 'de70db5fbc4284fd13f3f9a7cf257cbca1d8d9a5755859067c7cfb234d1d5748'
CAPTURED_SHA = '1c860210fb6ea4a2075c5f2fdc9c1fd1afa97adb175413994be676a131d97818'
CAPTURED_BASE = 'bb22efcbd27f999e8ffe85bbe3f03e20895be3f2'
DYNAMIC_PRIORITY = ((400000, 2000000), (2000000, 400000),
                    (490000, 500000), (500000, 490000), (500000, 510000), (510000, 500000),
                    (990000, 1000000), (1000000, 990000), (1000000, 1010000), (1010000, 1000000))
SPEEDS = (400000, 1000000, 2000000)
PRESETS = ('candidate', 'baseline')
UNMEASURED = {
    'playing_independent_dynamic': '現在周期適用の独立Phase59 planner・実測Frontier・動的RAW比較はこのドライバーの対象外',
    'dynamic_B_and_different_speed_boundary': '採用動的MapのB・次固定周期・異速度最終PCMの統合照合は別ゲート',
    'latest_wins_clear_lifecycle': '動的Loopの全取消・Clear・入力世代競合は別ゲート',
    'seek_all_modes_and_formats': '本boundaryは100ms Exact代表入力。長Loop・全形式・Interactive/FastLocalは別ゲート',
    'resources_and_realtime': 'オフライン境界の成功は最大2所有者・callback確保・実機期限の成功を意味しない',
    'subjective_acoustic_merodoa_public': '試聴・物理loopback・Merodoa実統合・公開承認は実施しない',
}


def json_lines(path):
    result = []
    for line in path.read_text().splitlines():
        if line.startswith('{'):
            result.append(json.loads(line))
    return result


def validate_row(ledger, key, predicate, details):
    row = ledger.rows[key]
    row['verification'] = details
    if row['status'] == 'PASS' and not predicate:
        row['status'] = 'FAIL'
        row['gates']['functional'] = False
        row.setdefault('reasons', []).append('件数・最終統計・独立参照の検査が不一致')
    ledger.save()
    return row['status'] == 'PASS'


def oracle_result(ledger, key, raw, expected_positions, source):
    rows = json_lines(ledger.root/(key+'.log'))
    if len(rows) != 1:
        raise ValueError('oracleの最終JSONが欠落または重複')
    result = rows[0]
    meta = wav_info(source)
    finite = True
    with raw.open('rb') as stream:
        while block := stream.read(1 << 20):
            finite &= len(block) % 4 == 0 and all(math.isfinite(x[0]) for x in struct.iter_unpack('<f', block))
    valid = (len(result.get('positions', [])) == expected_positions and
             result.get('channels') == meta['channels'] and result.get('rate') == meta['rate'] and
             result.get('input_frames') == meta['frames'] and
             raw.stat().st_size == result.get('output_frames', -1)*meta['channels']*4 and
             sha(raw) == result.get('sha256') and finite)
    if not validate_row(ledger, key, valid, dict(final=result, finite=finite, expected_positions=expected_positions)):
        raise ValueError('oracleのSHA・長さ・finite・Map位置が不一致')
    return result


def boundary_expectations(positions, rate):
    # Probeと別に、旧oracleの全整数入力Mapから実現可能な条件を先に確定する。
    import bisect
    oa, ob = positions[0], positions[-1]
    cases = []
    unavailable = []
    for remaining, label in ((0, 'R0'), (rate//200-1, 'R_N_minus_1'),
                             (rate//200, 'R_N'), (rate//200+1, 'R_N_plus_1')):
        target = ob-remaining
        low = bisect.bisect_left(positions, target)
        if low < len(positions)-1 and positions[low] == target:
            cases.append((label, 17+low, target, remaining))
        else:
            unavailable.append(label)
            if low:
                cases.append((label+'_below_input', 16+low, positions[low-1], remaining))
            if low < len(positions)-1:
                cases.append((label+'_above_input', 17+low, positions[low], remaining))
    cases += [('B_minus_1', 17+len(positions)-2, positions[-2], 0),
              ('A', 17, oa, 0),
              ('midpoint', 17+(len(positions)-1)//2, positions[(len(positions)-1)//2], 0)]
    return cases, unavailable


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--suite', choices=('boundary', 'regression', 'paused', 'dynamic-priority', 'dynamic161'), required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--configuration', choices=('Release', 'Debug'), default='Release')
    parser.add_argument('--input', type=Path, default=ROOT/'results/phase31/input/mix.wav')
    parser.add_argument('--oracle', type=Path, default=ROOT/'build/phase61/oracle_release_v1/phase61_frozen_reference')
    parser.add_argument('--captured-reference', type=Path, default=ROOT/'build/phase59_frozen/captured_reference')
    parser.add_argument('--minimum-free-gib', type=float, default=2.)
    args = parser.parse_args()
    if not math.isfinite(args.minimum_free_gib) or args.minimum_free_gib < 0:
        parser.error('minimum-free-gibは0以上の有限値を指定してください')
    build, out, oracle, source = (p.resolve() for p in (args.build, args.output, args.oracle, args.input))
    dynamic_suite = args.suite in ('dynamic-priority', 'dynamic161')
    if dynamic_suite:
        oracle = args.captured_reference.resolve()
        source = out/'dynamic_sustained_48000_mono_pcm16_9s.wav'
    oracle_expected_sha = CAPTURED_SHA if dynamic_suite else ORACLE_SHA
    reference_manifest = ROOT/('results/phase59/CAPTURED_REFERENCE.json' if dynamic_suite else 'results/phase62_fix/recipes/oracle_manifest.json')
    unmeasured = dict(UNMEASURED)
    if dynamic_suite:
        # このsuiteのケース自身がcycle 0の独立動的比較を担当する。
        unmeasured.pop('playing_independent_dynamic')
    if out.exists():
        parser.error('outputには存在しない新規ディレクトリを指定してください')
    if not out.is_relative_to(ROOT/'build'):
        parser.error('PCMと実行ログのoutputはGit管理外のbuild/以下へ指定してください')
    common = ['phase62_loop_tests']
    targets = {'boundary': ['phase62_dynamic_boundary_tests'],
               'regression': ['phase61_seek_check', 'phase54_core_probe', 'phase62_fix_reuse_tests'],
               'paused': ['paused_speed_loop_tests', 'paused_speed_native_tests', 'paused_speed_pipeline_tests'],
               'dynamic-priority': ['phase62_dynamic_pcm_tests'],
               'dynamic161': ['phase62_dynamic_pcm_tests']}[args.suite]
    cases = [dict(id=k, kind='exit') for k in ('oracle_identity', 'configure', 'build', 'architecture')]
    cases.append(dict(id='ctest', kind='ctest', required=['ctest.xml', 'CTEST_EXPECTED.json'],
                      result='ctest.xml', test_names_file='CTEST_EXPECTED.json'))
    jobs = []

    def plan(key, command, **spec):
        cases.append(dict(id=key, kind=spec.pop('kind', 'exit'), **spec))
        jobs.append((key, command))

    if dynamic_suite:
        if args.suite == 'dynamic161':
            forward = [(speed, speed+10000) for speed in range(400000, 2000000, 10000)]
            pairs = [*forward, *((target, initial) for initial, target in forward)]
        else:
            pairs = DYNAMIC_PRIORITY
        for initial, target in pairs:
            for preset in PRESETS:
                key = f'dynamic_{initial}_{target}_{preset}'
                case_dir = out/key
                required = [key+'/'+name for name in ('SUMMARY.json', 'EXPECTED.json', 'actual.f32', 'reference.f32',
                    'reference.json', 'reference.plans.csv', 'dynamic_map.nodes.bin', 'reference.nodes.bin',
                    'speeds.csv', 'plans.csv', 'plan_frontiers.csv', 'REFERENCE_COMMAND.json')]
                plan(key, [build/'phase62_dynamic_pcm_tests', source, initial, target, preset, case_dir, oracle],
                     required=required, expected_count=1, initial=initial, target=target, preset=preset,
                     result=key+'/SUMMARY.json', strict_dynamic=True)
    elif args.suite == 'boundary':
        rate = wav_info(source)['rate']
        for speed in SPEEDS:
            for preset in PRESETS:
                key = f'boundary_{speed}_{preset}'
                raw = out/(key+'.f32')
                # 全整数位置をoracleへ渡す。製品Mapを期待値として採用しない。
                plan(key+'_oracle', [oracle, source, speed, preset, raw, *range(17, 18+rate//10)],
                     required=[raw.name], positions=rate//10+1)
                plan(key, [build/'phase62_dynamic_boundary_tests', source, speed, preset, raw, 'OA', 'OB'],
                     expected_callbacks=[64, 128, 512, 4096], reference_case=key+'_oracle')
    elif args.suite == 'regression':
        plan('exact896', [sys.executable, '-B', ROOT/'tests/Phase61SeekSmoke.py', build/'phase61_seek_check', oracle,
                         '--full', '--output', out/'exact'], kind='exact', required=['exact/summary.json', 'exact/rows.jsonl'],
             result='exact/summary.json', expected_count=896)
        plan('golden25', [sys.executable, '-B', ROOT/'tests/Phase61Golden.py', '--probe', build/'phase54_core_probe', '--output', out/'golden'],
             kind='golden', required=['golden/summary.json'], result='golden/summary.json', expected_count=25)
        source = out/'fixed_48000_stereo_float32.wav'
        for speed in range(400000, 2000001, 10000):
            for preset in PRESETS:
                key = f'fixed_{speed}_{preset}'
                raw = out/(key+'.f32')
                plan(key+'_oracle', [oracle, source, speed, preset, raw, 1023, 49025], required=[raw.name], positions=2)
                for suffix, binary in (('finite', 'phase62_loop_tests'), ('reuse', 'phase62_fix_reuse_tests')):
                    plan(key+'_'+suffix, [build/binary, source, speed, preset, 1023, 49025, raw, 'OA', 'OB'],
                         kind='pcm', reference_case=key+'_oracle', expected_count=1)
    else:
        for preset in PRESETS:
            plan('paused_loop_'+preset, [build/'paused_speed_loop_tests', source, preset], expected_count=1, expected_case_count=10)
        for rate, channels in ((48000, 2), (44100, 1)):
            wav = out/f'paused_{rate}_{channels}.wav'
            for preset in PRESETS:
                refs = out/f'paused_{rate}_{channels}_{preset}_refs'
                stem = f'paused_{rate}_{channels}_{preset}'
                for speed in (750000, 1250000, 400000, 2000000, 490000, 500000, 990000, 1000000, 1010000):
                    raw = refs/f'{speed}_{preset}.f32'
                    plan(stem+'_oracle_'+str(speed), [oracle, wav, speed, preset, raw, rate], required=[str(raw.relative_to(out))], positions=1)
                plan(stem+'_pcm', [build/'paused_speed_native_tests', wav, refs, preset, 'representative'], expected_count=9)
                plan(stem+'_controls', [build/'paused_speed_native_tests', wav, refs, preset, 'controls'], expected_count=21)
    for key, reason in unmeasured.items():
        cases.append(dict(id=key, kind='exit', reason=reason))
    frozen = source_manifest(ROOT)
    provenance = dict(source=frozen, driver=identity(__file__), base_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                      working_tree=subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=ROOT, text=True).splitlines(),
                      suite=args.suite, configuration=args.configuration, architecture='arm64', host=platform.platform(),
                      oracle_expected_sha256=oracle_expected_sha, independent_oracle_manifest=identity(reference_manifest),
                      reference_scope='旧Phase59動的planner/Phase36 DSP' if dynamic_suite else '旧固定Exact DSP',
                      minimum_free_bytes=int(args.minimum_free_gib*1024**3),
                      serial_audio=True, public_go=False)
    ledger = Ledger(out, cases, provenance)
    for key, reason in unmeasured.items():
        ledger.rows[key]['reasons'] = [reason]
    ledger.save()
    verified_oracles = {}
    interruption = None
    try:
        actual = identity(oracle)
        expected_manifest = json.loads(reference_manifest.read_text())
        valid = actual['sha256'] == oracle_expected_sha and expected_manifest.get('binary_sha256') == oracle_expected_sha
        if dynamic_suite:
            frozen_manifest = json.loads((ROOT/'results/phase59/FROZEN_REFERENCE.json').read_text())
            valid &= expected_manifest.get('baseline_head') == frozen_manifest.get('baseline_head') == CAPTURED_BASE
            valid &= expected_manifest.get('library_sha256') == frozen_manifest.get('library_sha256')
            driver_folder = ROOT/'results/phase59/reference_driver_sources'
            valid &= all(sha(driver_folder/name) == value for name, value in frozen_manifest['frozen_driver_sha256'].items())
            valid &= sha(driver_folder/'Phase59CapturedReference.cpp') == expected_manifest.get('driver_source_sha256')
        ledger.rows['oracle_identity'].update(status='PASS' if valid else 'FAIL', reference=actual,
            expected_sha256=oracle_expected_sha, manifest=identity(reference_manifest),
            gates={**ledger.rows['oracle_identity']['gates'], 'functional': valid})
        ledger.save()
        if not valid:
            raise ValueError('旧独立oracleのSHA不一致。変更後DSPからの再生成で代替しない')
        if dynamic_suite:
            fixture(source, 48000, 1, 1, 'sustained', 9.)
            metadata = wav_info(source)
            if metadata['frames']/2 <= 96000 or metadata['frames'] != 432000:
                raise ValueError('動的fixtureの最速固定出力が96,000以下、または9秒ではない')
            recipe = dict(input=identity(source), metadata=metadata, generator=identity(ROOT/'scripts/phase57_study.py'),
                driver=identity(__file__), recipe="phase57_study.fixture(path, 48000, 1, 1, 'sustained', 9.0)",
                source_kind='既存の決定的sustained生成関数。元WAVの代用品ではなく、このsuite専用の事前宣言fixture。',
                parameters=dict(rate=48000, channels=1, encoding='PCM16', seconds=9, frames=432000),
                fastest_fixed_output_frames=216000, minimum_required_output_exclusive=96000,
                all_initial_speeds_exceed_limit=True, preset_count=2)
            (out/'INPUT_RECIPE.json').write_text(json.dumps(recipe, ensure_ascii=False, indent=2)+'\n')
        if args.suite == 'regression':
            fixture(source, 48000, 2, 3, 'boundary', 1.5)
        if args.suite == 'paused':
            for rate, channels in ((48000, 2), (44100, 1)):
                fixture(out/f'paused_{rate}_{channels}.wav', rate, channels, 1, 'boundary', 3.)
                for preset in PRESETS:
                    (out/f'paused_{rate}_{channels}_{preset}_refs').mkdir()
        setup = [('configure', ['cmake', '-S', ROOT, '-B', build, '-DCMAKE_BUILD_TYPE='+args.configuration, '-DCMAKE_OSX_ARCHITECTURES=arm64', '-DBUILD_TESTING=ON']),
                 ('build', ['cmake', '--build', build, '--target', *dict.fromkeys(common+targets), '-j2']),
                 ('architecture', [sys.executable, '-B', ROOT/'scripts/phase62_evidence.py', oracle, *(build/t for t in dict.fromkeys(common+targets))])]
        for key, command in setup:
            if not ledger.run(key, command, cwd=ROOT, timeout=1800):
                raise ValueError(key+'失敗。旧binaryは使用しない')
        pattern = '^(phase62_loop|paused_speed_pipeline)$' if args.suite == 'paused' else '^phase62_loop$'
        selection = subprocess.run(['ctest', '--test-dir', str(build), '-R', pattern, '--show-only=json-v1'], capture_output=True, text=True)
        if selection.returncode:
            raise ValueError('CTest期待一覧の取得失敗')
        names = [test['name'] for test in json.loads(selection.stdout)['tests']]
        if not names:
            raise ValueError('CTest対象が0件')
        (out/'CTEST_EXPECTED.json').write_text(json.dumps(names)+'\n')
        # CTEST_EXPECTEDは生成済みの入力。run()の古い生成物検出対象から外す。
        next(c for c in cases if c['id'] == 'ctest')['required'] = ['ctest.xml']
        if not ledger.run('ctest', ['ctest', '--test-dir', build, '-R', pattern, '--output-on-failure', '--output-junit', out/'ctest.xml', '-j1'],
                          cwd=ROOT, timeout=1200, inputs=[out/'CTEST_EXPECTED.json']):
            raise ValueError('CTest失敗')
        for job_index, (key, command) in enumerate(jobs):
            if shutil.disk_usage(ROOT).free < int(args.minimum_free_gib*1024**3):
                raise ValueError('空き容量下限に達したため残りはNOT_RUN。既存証拠は削除しない')
            if (dynamic_suite or job_index % 32 == 0) and source_manifest(ROOT)['sha256'] != frozen['sha256']:
                raise ValueError('実行中にソースが変更された')
            spec = next(c for c in cases if c['id'] == key)
            if 'reference_case' in spec:
                ref = verified_oracles.get(spec['reference_case'])
                if ref is None:
                    ledger.rows[key]['reasons'] = ['独立参照が未完了']
                    continue
                command = [ref['positions'][0] if value == 'OA' else ref['positions'][-1] if value == 'OB' else value for value in command]
                if args.suite == 'boundary':
                    expected, unavailable = boundary_expectations(ref['positions'], wav_info(source)['rate'])
                    spec.update(expected_count=len(expected)*4, expected_cases=expected, not_representable=unavailable,
                                independent_output_end=ref['positions'][-1], independent_mix_frames=wav_info(source)['rate']//200)
                    (out/'EXPECTED.json').write_text(json.dumps(ledger.plan, ensure_ascii=False, indent=2)+'\n')
            inputs = [Path(str(v)) for v in command[1:] if Path(str(v)).is_file() and Path(str(v)).suffix in ('.wav', '.f32')]
            ok = ledger.run(key, command, cwd=ROOT, timeout=1800, inputs=[oracle, *inputs])
            if dynamic_suite and source_manifest(ROOT)['sha256'] != frozen['sha256']:
                raise ValueError('動的case実行前後でソースSHAが変化した。旧binaryの結果を採用しない')
            if not ok:
                continue
            if dynamic_suite:
                final = json.loads((out/spec['result']).read_text())
                with (out/key/'speeds.csv').open() as stream:
                    operations = list(csv.DictReader(stream))
                applied = [op for op in operations if int(op['target_micros']) == spec['target'] and float(op['applied_s']) >= 0]
                valid = (final.get('suite') == 'phase62_dynamic_pcm' and final.get('status') == 'PASS' and
                    final.get('expected') == final.get('executed') == spec['expected_count'] == 1 and
                    final.get('initial_micros') == spec['initial'] and final.get('target_micros') == spec['target'] and
                    final.get('cycle') == 0 and final.get('frames', 0) == final.get('dynamic_B') and
                    final.get('oracle_exit') == 0 and final.get('reference_sha256') == oracle_expected_sha and
                    final.get('independent_planner') is True and final.get('independent_DSP_RAW') is True and
                    final.get('map_bit_exact') is True and final.get('nonfinite') == 0 and final.get('realtime') is False and
                    len(applied) == 1 and int(applied[0]['id']) == final.get('operation_id') and
                    int(applied[0]['applied_output']) == final.get('applied_output') and
                    int(applied[0]['completion_output']) == final.get('completion_output') and
                    0 < final.get('applied_output', 0) <= final.get('completion_output', 0) < final.get('dynamic_B', 0) and
                    sha(out/key/'actual.f32') == sha(out/key/'reference.f32') == final.get('pcm_sha256') and
                    (out/key/'dynamic_map.nodes.bin').read_bytes() == (out/key/'reference.nodes.bin').read_bytes())
                validate_row(ledger, key, valid, dict(expected=1, executed=final.get('executed', 0), final=final,
                    strict_verified=valid, actual_applied_operations=len(applied), input=identity(source), reference=identity(oracle)))
            elif key.endswith('_oracle') or '_oracle_' in key:
                raw = Path(str(command[4]))
                verified_oracles[key] = oracle_result(ledger, key, raw, spec['positions'], Path(str(command[1])))
            elif args.suite == 'boundary':
                rows = json_lines(out/(key+'.log'))
                final = rows[-1] if rows else {}
                measured = [row for row in rows if row.get('status') == 'PASS' and 'callback' in row]
                expected_pairs = Counter((label, position, spec['independent_output_end']-output,
                                          spec['independent_mix_frames'], callback, False)
                                         for label, position, output, _ in spec['expected_cases'] for callback in spec['expected_callbacks'])
                actual_pairs = Counter((row['case'], row['input'], row['R'], row['N'], row['callback'], row['old_near_B']) for row in measured)
                valid = (final.get('suite') == 'phase62_dynamic_boundary' and final.get('status') == 'PASS' and
                         final.get('expected') == final.get('executed') == len(measured) == spec['expected_count'] and
                         final.get('independent_DSP_RAW') is True and final.get('realtime') is False and expected_pairs == actual_pairs and
                         all(row.get('independent_DSP_RAW') is True for row in measured))
                validate_row(ledger, key, valid, dict(expected=spec['expected_count'], executed=len(measured), final=final))
            elif args.suite == 'paused':
                rows = json_lines(out/(key+'.log'))
                expected = spec['expected_count']
                if key.startswith('paused_loop_'):
                    final = rows[-1] if rows else {}
                    valid = (final.get('suite') == 'paused_speed_loop' and final.get('status') == 'PASS' and
                             final.get('expected') == spec['expected_case_count'] and
                             final.get('executed') == spec['expected_case_count'])
                    measured = 1 if valid else 0
                else:
                    measured = sum(row.get('PASS') is True for row in rows)
                    valid = measured == len(rows) == expected
                validate_row(ledger, key, valid, dict(expected=expected, executed=measured, final=rows[-1] if rows else None))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        interruption = str(error)
        (out/'INTERRUPTION.json').write_text(json.dumps(dict(status='INCOMPLETE', reason=str(error)), ensure_ascii=False, indent=2)+'\n')
    finally:
        for spec in cases:
            row=ledger.rows[spec['id']]
            if spec.get('strict_dynamic') and row['status']=='PASS' and row.get('verification',{}).get('strict_verified') is not True:
                row.update(status='INCOMPLETE')
                row.setdefault('reasons',[]).append('子実行は終了したが独立参照・最終統計の検査が完了していない')
        final_source = source_manifest(ROOT)
        changed = final_source['sha256'] != frozen['sha256']
        if changed:
            for row in ledger.rows.values():
                if row['status'] == 'PASS':
                    row.update(status='INCOMPLETE', source_changed_during_run=True)
        summary = ledger.save()
        selected = [row for key, row in ledger.rows.items() if key not in unmeasured]
        passed = {key for key, row in ledger.rows.items() if row['status'] == 'PASS'}
        measurements = {}
        if dynamic_suite:
            dynamic_specs = [spec for spec in cases if spec.get('strict_dynamic')]
            applied_specs = [spec for spec in dynamic_specs if spec['id'] in passed and
                ledger.rows[spec['id']].get('verification', {}).get('strict_verified') is True and
                ledger.rows[spec['id']].get('verification', {}).get('actual_applied_operations') == 1]
            initial_values = sorted({spec['initial'] for spec in applied_specs})
            target_values = sorted({spec['target'] for spec in applied_specs})
            measurements = dict(programs_expected=640 if args.suite == 'dynamic161' else 20,
                programs_executed=sum(ledger.rows[spec['id']].get('exit') is not None for spec in dynamic_specs),
                independent_pcm_planner_map_passed=len(applied_specs),
                initial_speed_values_applied=initial_values, target_speed_values_applied=target_values,
                initial_speed_count=len(initial_values), target_speed_count=len(target_values),
                actual_applied_operations=sum(ledger.rows[spec['id']].get('verification', {}).get('actual_applied_operations', 0) for spec in applied_specs),
                coverage_by_preset={preset: dict(programs=sum(spec['preset'] == preset for spec in applied_specs),
                    initial_values=sorted({spec['initial'] for spec in applied_specs if spec['preset'] == preset}),
                    target_values=sorted({spec['target'] for spec in applied_specs if spec['preset'] == preset})) for preset in PRESETS},
                all161_actually_applied_and_independent_pcm_passed=args.suite == 'dynamic161' and len(applied_specs) == 640 and
                    initial_values == target_values == list(range(400000, 2000001, 10000)))
        elif args.suite == 'boundary':
            probes = [row for key, row in ledger.rows.items() if key.startswith('boundary_') and not key.endswith('_oracle')]
            measurements = dict(programs_expected=6, programs_passed=sum(row['status'] == 'PASS' for row in probes),
                cases_expected=sum(row.get('verification', {}).get('expected', 0) for row in probes),
                cases_executed=sum(row.get('verification', {}).get('executed', 0) for row in probes),
                counts_fully_resolved=all('verification' in row for row in probes))
        elif args.suite == 'regression':
            measurements = dict(exact_expected=896, exact_passed=896 if 'exact896' in passed else 0,
                golden_expected=25, golden_passed=25 if 'golden25' in passed else 0,
                fixed_finite_expected=322, fixed_finite_passed=sum(key.endswith('_finite') for key in passed),
                fixed_reuse_expected=322, fixed_reuse_passed=sum(key.endswith('_reuse') for key in passed),
                fixed_speed_values_expected=161,
                fixed_speed_values_passed=sorted(speed for speed in range(400000, 2000001, 10000)
                    if all(f'fixed_{speed}_{preset}_{mode}' in passed for preset in PRESETS for mode in ('finite', 'reuse'))))
        else:
            measurements = dict(loop_programs_expected=2, loop_programs_passed=sum(key.startswith('paused_loop_') for key in passed),
                ordinary_pcm_expected=36, ordinary_pcm_passed=sum(ledger.rows[key].get('verification', {}).get('executed', 0) for key in passed if key.endswith('_pcm')),
                ordinary_controls_expected=84, ordinary_controls_passed=sum(ledger.rows[key].get('verification', {}).get('executed', 0) for key in passed if key.endswith('_controls')))
        summary.update(selected_suite=args.suite, selected_suite_pass=not interruption and bool(selected) and all(row['status'] == 'PASS' for row in selected),
                       source_before=frozen['sha256'], source_after=final_source['sha256'], public_go=False,
                       local_overall_go=False, source_changed=changed, final_statistics_present=True, measurements=measurements,
                       interruption=interruption,
                       input_recipe=identity(out/'INPUT_RECIPE.json') if (out/'INPUT_RECIPE.json').is_file() else None,
                       binaries=[identity(build/t) for t in dict.fromkeys(common+targets) if (build/t).is_file()])
        (out/'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps({key: summary[key] for key in ('selected_suite', 'selected_suite_pass', 'expected', 'counts', 'local_overall_go')}, ensure_ascii=False), flush=True)
    return 0 if summary['selected_suite_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
