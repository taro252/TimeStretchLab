"""Interactiveを48program/240casesの固定交互計画で直列実行する新規run専用recipe。

arm64 Python:
  run_interactive_pairs.py --client B/interactive_pair_clients_01/CLIENT.json --output B/interactive_pairs_01
旧v3 frozen02 / 候補v4 final04 source02b81。各childは同じ5位置だけを測る。
repeat0 old/new、repeat1 new/old、repeat2 old/new。timeoutは各120秒固定で失敗。
既存validatorのfield/時刻順序/誤差許容/分位式/counter表を再利用し、各版120IDを確認。
120件合算と8速度Preset群、2xCandidate15件のp50/p95/maxを分離する。
品質/物理/UI/採用承認を生成しない。旧120の結果を新240へ足さない。
"""
import argparse
import collections
import datetime
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys

import build_interactive_pair_clients as builder
import run_pairs as common
import run_seek_history as helpers
import run_paused_deep_pairs as paused

ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / 'results/progressive_adoption/recipes/audit_native_performance.py'
VALIDATOR_SHA = '0f535e0192f7c3df99812d7b98ea827da70b104f6466d1876d0fec134e944930'
SPEEDS = (400000, 500000, 1000000, 2000000)
POSITIONS = builder.POSITIONS
EXPECTED_KEYS = set(itertools.product(SPEEDS, (True, False), range(3), POSITIONS))
SCOPE = {
    'suite': 'same original Interactive120 keys per version; split 24 children/version, not a single native process',
    'insertion': 'one normal-thread speed/preset/repeat env selector; reverse reconstruction proves original bytes',
    'native_timing': 'timestamps/asserts/FIFO/callback/positions unchanged; accepted to FIFO Ready and first callback separate',
    'main_Ready_goal': 'each version all120 combined p95<=200ms, identical to original validator',
    'subgroups': '8 speed/Preset strata with 15 cases each; report every p95/max and explicit 2x Candidate without averaging it away',
    'original_validator': 'reuse constants, row_key, numeric tolerances, timestamp order, quantile, distribution and counter tables; original main() not executed',
    'execution': '48 actual per-child executions; no invented single-process EXECUTION or aggregate native launch',
    'process_watchdog_s': 120, 'timeout_allowed': False, 'serial_audio': True,
    'CPU': 'wait4 whole child process cost incl /usr/bin/env exec; separate from each native Ready interval',
    'n3': 'descriptive counterbalanced observations; no causal significance',
    'quality_status': 'UNMEASURED', 'quality_approval': False, 'public_approved': False,
    'physical_audio': None, 'application_F': None}


def strict(body):
    def pairs(values):
        result = {}
        for key, value in values:
            common.require(key not in result, 'duplicate JSON key ' + key)
            result[key] = value
        return result
    def reject(value):
        raise ValueError('nonfinite JSON ' + value)
    result = json.loads(body, object_pairs_hook=pairs, parse_constant=reject)
    def finite(value):
        if isinstance(value, dict):
            for child in value.values():
                finite(child)
        elif isinstance(value, list):
            for child in value:
                finite(child)
        elif type(value) is float:
            common.require(math.isfinite(value), 'nonfinite JSON number')
    finite(result)
    return result


def read(path, lines=False):
    body = Path(path).read_text()
    if not lines:
        return strict(body)
    rows = body.splitlines()
    common.require(all(line.strip() for line in rows), 'blank native JSONL row')
    values = [strict(line) for line in rows]
    common.require(all(isinstance(value, dict) for value in values), 'native JSONL row must be an object')
    return values


def load_validator():
    common.require(common.identity(VALIDATOR)['sha256'] == VALIDATOR_SHA, 'original validator SHA changed')
    spec = importlib.util.spec_from_file_location('interactive_pairs_original_validator', VALIDATOR)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def jobs_for(client, plan, out):
    common.require(plan['schema'] == 'interactive-pairs-v1' and plan['status'] == 'NOT_RUN' and
                   plan['expected_programs'] == len(plan['jobs']) == 48 and plan['expected_cases'] == 240 and
                   plan['expected_cases_per_version'] == 120 and plan['process_timeout_s'] == 120 and
                   plan['timeout_allowed'] is False, 'fixed unstarted 48/240 plan and 120s watchdog')
    common.require(plan['positions'] == list(POSITIONS) and plan['speeds_micros'] == list(SPEEDS) and
                   plan['preset_names'] == ['candidate', 'baseline'] and plan['repeat_values'] == [0, 1, 2] and
                   plan['ready_target_p95_ms'] == 200, 'original fixed strata/positions/goal')
    common.require(plan['input'] == client['input'] and plan['original_source_sha256'] ==
                   client['source']['sha256'] == builder.SOURCE_SHA and plan['client_source_sha256'] ==
                   client['copied_source']['sha256'] == builder.DERIVED_SOURCE_SHA, 'common original/derived source and input')
    jobs = []
    for repeat in (0, 1, 2):
        for speed in SPEEDS:
            for preset in ('candidate', 'baseline'):
                pair = f's{speed}_{preset}_r{repeat}'
                for version in (('old', 'candidate') if repeat % 2 == 0 else ('candidate', 'old')):
                    entry, raw = client['clients'][version], plan['jobs'][len(jobs)]
                    values = {'id': pair + '_' + version, 'pair_id': pair, 'repeat': repeat, 'version': version,
                              'preset': preset, 'speed_micros': speed, 'expected_rows': 5}
                    env = dict(zip(builder.SELECTORS, (str(speed), preset, str(repeat))))
                    common.require(all(raw.get(k) == v for k, v in values.items()) and raw['environment'] == env,
                                   'exact program ID/order/selectors')
                    command = raw['command']
                    common.require(len(command) == 3 and command[:2] == [entry['binary']['path'], client['input']['path']],
                                   'unchanged native CLI')
                    actual = [*command[:2], str(out / values['id'])]
                    # /usr/bin/env execs the one child; native argv remains exactly the original 3 arguments.
                    launch = ['/usr/bin/env', *[key + '=' + env[key] for key in builder.SELECTORS], *actual]
                    keys = [[speed, preset == 'candidate', repeat, at] for at in POSITIONS]
                    jobs.append({**values, 'command': actual, 'launch_command': launch, 'environment': env,
                                 'expected_keys': keys, 'original_plan_command': command})
    common.require(plan['all_expected_ids'] == [j['id'] for j in jobs] and len({j['id'] for j in jobs}) == 48,
                   'fixed full program ID set')
    return jobs


def row_validation(rows, expected_keys, audit, device_id):
    """audit_native_performance.pyのper-row検査を同じ数式/許容誤差/順序で適用する。"""
    row_errors, valid, latency, devices = [], [], [], set()
    for index, row in enumerate(rows):
        errors = []
        key = audit.row_key(row)
        for field in audit.INTEGER_FIELDS:
            value = row.get(field)
            if type(value) is not int or not 0 <= value < 2**64:
                errors.append('missing/invalid integer ' + field)
        for field in audit.FLOAT_FIELDS:
            value = row.get(field)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                errors.append('missing/nonfinite measurement ' + field)
        errors.extend('nonfinite ' + key for key in audit.floating_errors(row))
        if row.get('analysis_complete_at_play') is not True:
            errors.append('analysis was not complete at play')
        if not errors:
            if row['rate'] != 44100 or row['channels'] != 2:
                errors.append('input shape differs')
            if row['epoch'] == 0 or row['peak_rss'] == 0 or any(row[t] == 0 for t in audit.TIME_FIELDS):
                errors.append('zero epoch/RSS/timestamp')
            if not (row['accepted_ns'] <= row['preparing_ns'] <= row['analysis_ready_ns'] <= row['fifo_ready_ns']
                    <= row['switch_ready_ns'] <= row['transition_begin_ns'] <= row['transition_end_ns']
                    and row['fifo_ready_ns'] <= row['first_pcm_ns'] <= row['hal_estimate_ns']
                    and row['switch_ns'] == row['transition_begin_ns']):
                errors.append('timestamp order')
            # 元validator同様、first_pcmは同じcallback内のtransition_beginより数us前を許す。
            ready = (row['fifo_ready_ns'] - row['accepted_ns']) / 1e6
            first = (row['first_pcm_ns'] - row['accepted_ns']) / 1e6
            if not math.isclose(row['ready_ms'], ready, rel_tol=1e-5, abs_tol=0.01):
                errors.append('reported ready_ms differs from timestamps')
            if not math.isclose(row['first_pcm_ms'], first, rel_tol=1e-5, abs_tol=0.01):
                errors.append('reported first_pcm_ms differs from timestamps')
            if row['device'] != device_id or row['device_buffer'] != 512 or not math.isclose(row['device_rate'], 48000, abs_tol=1e-6, rel_tol=0):
                errors.append('actual device values differ')
            devices.add((row['device'], row['device_rate'], row['device_buffer']))
            if key not in expected_keys:
                errors.append('invalid operation key')
            if row['speed'] not in SPEEDS:
                errors.append('unsupported/zero speed')
            elif row['output'] > (13230000 * 1000000 + row['speed'] // 2) // row['speed']:
                errors.append('output coordinate outside full track')
            if any(row['lifetime_' + suffix] < row['delta_' + suffix] for suffix in audit.ZERO_SUFFIXES):
                errors.append('operation delta exceeds lifetime counter')
        if errors:
            row_errors.append({'row': index + 1, 'key': list(key) if key is not None else None, 'errors': errors})
        else:
            valid.append(row)
            latency.append({'key': list(key), 'ready_ms': ready, 'first_pcm_ms': first})
    return row_errors, valid, latency, devices


def program_assessment(job, rows, execution, audit, device_id):
    wanted = {tuple(key) for key in job['expected_keys']}
    keys = [audit.row_key(row) for row in rows]
    counts = collections.Counter(key for key in keys if key is not None)
    missing, extra = wanted - set(counts), set(counts) - wanted
    duplicates = [key for key, count in counts.items() if count > 1]
    key_ok = len(rows) == 5 and all(k is not None for k in keys) and not missing and not extra and not duplicates
    errors, valid, latency, devices = row_validation(rows, wanted, audit, device_id)
    ordered = sorted(valid, key=lambda row: row['accepted_ns'])
    sequence_ok = len(ordered) == 5 and len({r['epoch'] for r in ordered}) == 5 and all(
        ordered[i]['epoch'] < ordered[i+1]['epoch'] and ordered[i]['accepted_ns'] < ordered[i+1]['accepted_ns'] for i in range(4))
    lifetime_ok = len(ordered) == 5 and all(all(ordered[i][field] <= ordered[i+1][field] for i in range(4))
                                           for field in audit.LIFETIME_FIELDS)
    tables = {'delta': audit.table(rows, audit.DELTA_FIELDS, False),
              'lifetime': audit.table(rows, audit.LIFETIME_FIELDS, True)}
    rt = all(item['all_zero'] for table in tables.values() for item in table)
    complete = key_ok and execution['returncode'] == 0 and not execution['timeout'] and not execution['interrupted']
    integrity = complete and not errors and sequence_ok and lifetime_ok and len(devices) == 1
    return {'native_rows': rows, 'observed_rows': len(rows), 'expected_rows': 5,
            'all_keys_exact': key_ok, 'missing_keys': [list(k) for k in sorted(missing)],
            'unexpected_keys': [list(k) for k in sorted(extra)], 'duplicate_keys': [list(k) for k in sorted(duplicates)],
            'row_errors': errors, 'valid_measurement_count': len(valid), 'latencies_from_timestamps': latency,
            'session_epoch_and_lifetime_order': sequence_ok and lifetime_ok, 'counter_tables': tables,
            'rt_pass': rt, 'functional_integrity_pass': integrity, 'execution_complete': complete,
            'ready': audit.distribution([r['ready_ms'] for r in latency]),
            'first_pcm': audit.distribution([r['first_pcm_ms'] for r in latency]),
            'quality_status': 'UNMEASURED', 'public_approved': False}


def version_assessment(version, programs, audit, device_id):
    selected = [p for p in programs if p['version'] == version]
    rows = [row for p in selected for row in p.get('native_rows', [])]
    keys = [audit.row_key(row) for row in rows]
    counts = collections.Counter(key for key in keys if key is not None)
    missing, extra = EXPECTED_KEYS - set(counts), set(counts) - EXPECTED_KEYS
    duplicates = [key for key, count in counts.items() if count > 1]
    errors, valid, latency, devices = row_validation(rows, EXPECTED_KEYS, audit, device_id)
    complete = len(selected) == 24 and len(rows) == 120 and not missing and not extra and not duplicates and all(
        p.get('execution_complete') is True for p in selected)
    integrity = complete and not errors and all(p.get('functional_integrity_pass') is True for p in selected) and len(devices) == 1
    tables = {'delta': audit.table(rows, audit.DELTA_FIELDS, False),
              'lifetime': audit.table(rows, audit.LIFETIME_FIELDS, True)}
    rt = integrity and all(item['all_zero'] for table in tables.values() for item in table)
    ready = audit.distribution([row['ready_ms'] for row in latency])
    first = audit.distribution([row['first_pcm_ms'] for row in latency])
    groups = []
    for kind in ('preset', 'speed', 'preset_speed'):
        groupkeys = sorted({('candidate' if row['candidate'] else 'baseline',) if kind == 'preset' else
                           (row['speed'],) if kind == 'speed' else
                           ('candidate' if row['candidate'] else 'baseline', row['speed']) for row in valid})
        for key in groupkeys:
            subset = [row for row in valid if (('candidate' if row['candidate'] else 'baseline',) if kind == 'preset' else
                      (row['speed'],) if kind == 'speed' else
                      ('candidate' if row['candidate'] else 'baseline', row['speed'])) == key]
            values = [(row['fifo_ready_ns']-row['accepted_ns'])/1e6 for row in subset]
            first_values = [(row['first_pcm_ns']-row['accepted_ns'])/1e6 for row in subset]
            groups.append({'group_by': kind, 'key': list(key), 'ready': audit.distribution(values),
                           'first_pcm': audit.distribution(first_values), 'ready_over_200ms': sum(v > 200 for v in values),
                           'p95_le_200ms_observation': audit.quantile(values, .95) <= 200})
    main_goal = integrity and ready['p95_ms'] is not None and ready['p95_ms'] <= 200
    two_x = next((g for g in groups if g['group_by'] == 'preset_speed' and g['key'] == ['candidate', 2000000]), None)
    return {'version': version, 'execution_complete': complete, 'audit_status': 'PASS' if integrity else 'FAIL_OR_INCOMPLETE',
            'observed_programs': len(selected), 'expected_programs': 24, 'observed_count': len(rows), 'expected_count': 120,
            'valid_measurement_count': len(valid), 'missing_keys': [list(k) for k in sorted(missing)],
            'unexpected_keys': [list(k) for k in sorted(extra)], 'duplicate_keys': [list(k) for k in sorted(duplicates)],
            'all_original_keys_equal': complete, 'row_errors': errors, 'counter_tables': tables,
            'functional_rt_status': 'PASS' if rt else 'FAIL',
            'latency_status_all120_original_goal': 'PASS' if main_goal else 'FAIL',
            'performance_status_all120_original_validator': 'PASS' if rt and main_goal else 'FAIL',
            'ready': ready, 'first_pcm': first, 'target_ready_p95_ms': 200,
            'goal_scope': 'original validator all120 combined FIFO Ready only',
            'groups': groups, 'Candidate2x_15cases': two_x,
            'all_preset_speed_p95_le_200ms_observation': integrity and all(
                g['p95_le_200ms_observation'] for g in groups if g['group_by'] == 'preset_speed'),
            'quality_status': 'UNMEASURED', 'public_approved': False}


def paired_statistics(programs, audit):
    result = []
    for speed in SPEEDS:
        for preset in ('candidate', 'baseline'):
            pairs = []
            for repeat in range(3):
                selected = {p['version']: p for p in programs if p['speed_micros'] == speed and
                            p['preset'] == preset and p['repeat'] == repeat}
                qualified = set(selected) == {'old', 'candidate'} and all(
                    p.get('functional_integrity_pass') is True for p in selected.values())
                cases = []
                if qualified:
                    maps = {version: {row['input']: row for row in selected[version].get('native_rows', [])}
                            for version in ('old', 'candidate')}
                    for at in POSITIONS:
                        values = {}
                        for version in ('old', 'candidate'):
                            row = maps[version].get(at, {})
                            values[version] = ((row['fifo_ready_ns']-row['accepted_ns'])/1e6
                                               if row and not audit.floating_errors(row) else None)
                        left, right = values['old'], values['candidate']
                        finite = qualified and common.finite(left) and common.finite(right)
                        cases.append({'input': at, 'ready_ms': values,
                            'candidate_minus_old_ms': right-left if finite else None,
                            'candidate_over_old': right/left if finite and left > 0 else None,
                            'qualified': qualified})
                pairs.append({'repeat': repeat, 'qualified_pair': qualified, 'positions': cases,
                              'causal_significance': 'NOT_ASSESSED'})
            result.append({'speed_micros': speed, 'preset': preset, 'expected_pairs': 3, 'pairs': pairs})
    return result


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new evidence belongs under build/')
    out.mkdir(parents=True, exist_ok=False)
    jobs, programs, errors, inventory, roots = [], [], [], [], []
    after_inventory, source_after = None, []
    audit, device = None, None
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 runtime Python required')
        common.require(not any(os.environ.get(k) for k in ('DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'CPATH',
                       'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH', 'LIBRARY_PATH')), 'ambient library/include override')
        common.require(not any(key in os.environ for key in builder.SELECTORS), 'parent selector env must be unset')
        client_id, client = common.identity(args.client), read(args.client)
        common.require(client['schema'] == 'performance-interactive-pair-clients-v1' and client['status'] == 'PASS' and
                       set(client['clients']) == {'old', 'candidate'}, 'PASS same-client compile manifest')
        common.require(client['candidate_source'] == client['clients']['candidate']['source'] == builder.CANDIDATE_SOURCE and
                       client['baseline_source'] == client['clients']['old']['source'] == builder.frozen.OLD_SOURCE_SHA and
                       client['baseline_commit'] == builder.frozen.OLD_COMMIT, 'fixed final04/source02b81 and old v3 provenance')
        common.require(Path(client['baseline_client']['path']).resolve() ==
                       (builder.BASE/'frozen_clients_02/CLIENT.json').resolve() and
                       Path(client['candidate_build']['path']).resolve() ==
                       (builder.BASE/'build_final_04/BUILD.json').resolve(), 'fixed build record paths')
        common.require(client['client_extra_defines'] == ['-DPHASE61_INTERACTIVE_CONTRACT=1'] and
                       client['transformation']['one_insertion'] is True and
                       client['transformation']['default_all120_preserved'] is True and
                       client['transformation']['removed_bytes_equal_original'] is True, 'one normal selector insertion')
        original = Path(client['original_copy']['path']).read_bytes()
        changed = Path(client['copied_source']['path']).read_bytes()
        common.require(common.identity(client['original_copy']['path']) == client['original_copy'] and
                       builder.derive_client(original) == changed and
                       common.identity(client['copied_source']['path']) == client['copied_source'] and
                       client['original_copy']['sha256'] == client['source']['sha256'] == builder.SOURCE_SHA,
                       'source reverse reconstruction byte proof')
        common.require(common.identity(client['run_plan']['path']) == client['run_plan'], 'RUN_PLAN SHA')
        jobs = jobs_for(client, read(client['run_plan']['path']), out)
        # 既存Paused builderの全headers/SDK/object/9archive/probe監査口を再利用する。
        inventory = paused.compile_inventory(client, args.client)
        for item, role in ((client['original_copy'], 'original_body_copy'), (client['selector_patch'], 'one_insertion_patch'),
                           (common.identity(__file__), 'interactive_runner'), (common.identity(builder.__file__), 'interactive_builder'),
                           (common.identity(paused.__file__), 'reused_compile_audit'), (common.identity(VALIDATOR), 'original_validator'),
                           (common.identity('/usr/bin/env'), 'ownchild_env_exec_launcher')):
            inventory.append({'identity': {k:item[k] for k in ('path','bytes','sha256')}, 'roles': [role]})
        for entry in client['clients'].values():
            common.require(entry['compile_command'].count('-DPHASE61_INTERACTIVE_CONTRACT=1') == 1,
                           'original contract branch explicitly compiled once')
            common.require(subprocess.check_output(['/usr/bin/lipo','-archs',entry['binary']['path']],text=True).split() ==
                           ['arm64'], 'native arm64 binary')
        common.save(out/'COMPILE_INVENTORY.json', {'files':inventory,'sha256':common.manifest_digest(inventory)})
        helpers.verify_inventory(inventory,out/'FROZEN_BEFORE.json')
        for key in ('baseline_build','candidate_build'):
            build = read(client[key]['path'])
            root = Path(build['source_root']).resolve()
            common.require(build['status']=='PASS' and build['configuration']=='Release' and build['architecture']=='arm64' and
                           common.manifest_digest(build['source_manifest']['files']) ==
                           build['source'] == build['source_manifest']['sha256'], 'frozen Release arm64 source inventory')
            common.require(common.current_source_digest(root)==build['source'],key+' current source changed')
            roots.append({'name':key,'root':str(root),'expected_sha256':build['source']})
        common.save(out/'SOURCE_BEFORE.json',{'status':'PASS','roots':roots,'scope':'src/tests/scripts/CMake; docs/results allowed'})
        inp=common.wav_identity(Path(client['input']['path']),44100,2)
        common.require(inp['sha256']==client['input']['sha256']==builder.INPUT_SHA,'fixed stereo441 music300 input')
        audit=load_validator()
        device=helpers.output_device()
        common.require(device['buffer_frames']==512,'fixed actual output buffer512')
        common.save(out/'DEVICE_BEFORE.json',device)
        common.save(out/'ENVIRONMENT_BEFORE.json',common.environment())
        declaration={'schema':'interactive-interleaved-run-v1','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'expected_programs':48,'expected_cases':240,'cases_per_version':120,'all_expected_program_ids':[j['id'] for j in jobs],
            'all_expected_case_keys_per_version':[list(k) for k in sorted(EXPECTED_KEYS)],
            'jobs':jobs,'client':client_id,'run_plan':client['run_plan'],'input':inp,'source_roots':roots,
            'driver':common.identity(__file__),'builder':common.identity(builder.__file__),
            'validator':common.identity(VALIDATOR),'validator_formula_reuse':'constants/row_key/numeric criteria/quantile/counter tables; main not executed',
            'process_timeout_s':120,'timeout_allowed':False,'parent_architecture':platform.machine(),
            'scope':SCOPE,'quality_approval':False,'public_approved':False}
        common.save(out/'EXPECTED.json',declaration)
        for job in jobs:
            entry=client['clients'][job['version']]
            common.require(common.identity(args.client)==client_id and
                           common.identity(entry['binary']['path'])==entry['binary'],'client/binary changed before run')
            common.require(helpers.output_device()==device,'default output device changed before run')
            common.save(out/(job['id']+'.EXPECTED.json'),job)
            execution=common.execute(job['launch_command'],out/(job['id']+'.log'),120)
            directory=out/job['id']
            program={k:job[k] for k in ('id','pair_id','repeat','version','preset','speed_micros')}
            program.update(command=job['command'],launch_command=job['launch_command'],environment=job['environment'],execution=execution)
            try:
                rows=read(directory/'rows.jsonl',True)
                program.update(program_assessment(job,rows,execution,audit,device['default_output_device']))
            except (OSError,RuntimeError,ValueError,TypeError,KeyError,OverflowError) as error:
                program.update(native_rows=[],observed_rows=0,expected_rows=5,functional_integrity_pass=False,
                               execution_complete=False,rt_pass=False,errors=[type(error).__name__+': '+str(error)])
            program['device_after']=helpers.output_device()
            if program['device_after']!=device:
                program['functional_integrity_pass']=False
                program.setdefault('errors',[]).append('default output device changed during process')
            if directory.is_dir():
                common.save(directory/'PROGRAM_AUDIT.json',program)
                program['artifacts']=[common.identity(p) for p in sorted(directory.rglob('*')) if p.is_file()]
            else:
                program['artifacts']=[]
            programs.append(program)
            common.save(out/'SUMMARY.json',{**declaration,'status':'IN_PROGRESS','executed_programs':len(programs),
                                          'observed_cases':sum(p['observed_rows'] for p in programs),'programs':programs})
            common.save(out/'PROCESS_COST.json',{'schema':'interactive-pair-process-cost-v1','scope':SCOPE,
                'expected_programs':48,'executed_programs':len(programs),
                'programs':[{'id':p['id'],'execution':p['execution']} for p in programs]})
            print(job['id'],execution['returncode'],'rows',program['observed_rows'],'integrity',
                  program['functional_integrity_pass'],'RT',program['rt_pass'],flush=True)
            if execution['interrupted']:
                raise KeyboardInterrupt('own child interrupted and reaped')
        after_inventory=helpers.verify_inventory(inventory,out/'FROZEN_AFTER.json')
        common.save(out/'ENVIRONMENT_AFTER.json',common.environment())
        final_device=helpers.output_device()
        common.save(out/'DEVICE_AFTER.json',final_device)
        common.require(final_device==device,'default output device changed after run')
    except BaseException as error:
        errors.append(type(error).__name__+': '+str(error))
    finally:
        if inventory and after_inventory is None:
            try:
                after_inventory=helpers.verify_inventory(inventory,out/'FROZEN_AFTER.json')
            except BaseException as error:
                errors.append('final inventory: '+type(error).__name__+': '+str(error))
        if roots:
            try:
                for item in roots:
                    actual=common.current_source_digest(Path(item['root']))
                    source_after.append({**item,'actual_sha256':actual,'unchanged':actual==item['expected_sha256']})
                common.save(out/'SOURCE_AFTER.json',{'status':'PASS' if all(v['unchanged'] for v in source_after) else 'FAIL',
                                                    'roots':source_after})
                common.require(all(v['unchanged'] for v in source_after),'source changed during run')
            except BaseException as error:
                errors.append('final source: '+type(error).__name__+': '+str(error))
    expected_ids,got_ids=[j['id'] for j in jobs],[p['id'] for p in programs]
    finished=len(jobs)==len(programs)==48 and got_ids==expected_ids and all(
        not p['execution']['timeout'] and not p['execution']['interrupted'] for p in programs)
    versions=({v:version_assessment(v,programs,audit,device['default_output_device']) for v in ('old','candidate')}
              if audit is not None and device is not None else {})
    collection=finished and not errors and after_inventory is not None and len(versions)==2 and all(
        v['audit_status']=='PASS' for v in versions.values())
    original_candidate_pass=collection and versions['candidate']['performance_status_all120_original_validator']=='PASS'
    subgroup_candidate_pass=collection and versions['candidate']['all_preset_speed_p95_le_200ms_observation']
    status=('FAIL_OR_INCOMPLETE' if not collection else 'PASS' if original_candidate_pass and subgroup_candidate_pass
            else 'COMPLETE_WITH_PERFORMANCE_FAILURE')
    result={'schema':'interactive-interleaved-run-v1','status':status,
        'status_scope':'collection plus candidate original120 Ready/RT and reported speed/Preset200ms observations; no formal approval',
        'collection_status':'PASS' if collection else 'FAIL_OR_INCOMPLETE','all_programs_finished':finished,
        'expected_programs':48,'executed_programs':len(programs),'expected_cases':240,
        'observed_cases':sum(p.get('observed_rows',0) for p in programs),'expected_cases_per_version':120,
        'all_expected_program_ids':expected_ids,'executed_program_ids':got_ids,
        'candidate_original120_goal_pass':original_candidate_pass,
        'candidate_all_preset_speed_p95_200ms_observation_pass':subgroup_candidate_pass,
        'baseline_source':builder.frozen.OLD_SOURCE_SHA,'candidate_source':builder.CANDIDATE_SOURCE,
        'client_compile_manifest':common.identity(args.client) if args.client.is_file() else None,
        'expected_manifest':common.identity(out/'EXPECTED.json') if (out/'EXPECTED.json').is_file() else None,
        'source_after':source_after,'versions':versions,
        'paired_differences':paired_statistics(programs,audit) if audit is not None else [],
        'errors':errors,'scope':SCOPE,'programs':programs,'quality_status':'UNMEASURED',
        'quality_approval':False,'public_approved':False,'physical_audio':None,'application_F':None}
    for version in ('old','candidate'):
        rows=[row for p in programs if p['version']==version for row in p.get('native_rows',[])]
        p=out/(version+'_rows.jsonl')
        with p.open('x') as f:
            for row in rows:
                f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
        result.setdefault('aggregate_rows',{})[version]=common.identity(p)
    common.save(out/'SUMMARY.json',result)
    return 0 if status=='PASS' else 2


if __name__=='__main__':
    sys.exit(main())
