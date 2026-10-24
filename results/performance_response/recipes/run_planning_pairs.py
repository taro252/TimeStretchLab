"""C1計画clientの旧版/候補を独立process・各3反復で交互に比較する。

arm64 Pythonで使用する。例（このファイルを作成した時点では未実行）:
  run_planning_pairs.py --clients B/planning_clients_01/CLIENT.json --output B/planning_pairs_01
  --long-input B/fixtures/chain_600s.wav を付けた場合だけ600秒層を追加する。
既定は30/300秒×履歴0/4×両Preset×3反復×2版=48process、600秒付きは72。
全Map field/全ノードSHA/全決定field/全Pending経路を比較する。timeout/欠落はFAIL。
主指標はplanner.update+planのthread CPU/wall合計。解析append/copy/hash/JSONは除外。
confirmPlanは別計測。全process CPUはそれらを含むためPROCESS_COSTへ分離する。
page/index copy・materializedは各対象のみでPhase39全copy量ではない。
planning scratchは保守payload推定上限でRSS/allocator実測ではない。
座標専用fixture。PCM/実時間/音質/実アプリFの承認は行わない。
"""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
sys.path.insert(0, str(ROOT / 'results/performance_response/recipes'))
import run_pairs as common

STAT_KEYS = ('updates', 'fixed_event_visits', 'fixed_appended_nodes', 'dynamic_appended_nodes',
             'materialized_nodes', 'history_replays', 'diagnostic_replay_requests', 'diagnostic_comparisons',
             'prefix_proof_pages', 'prefix_proof_nodes', 'index_bytes_copied', 'fixed_cache_entries',
             'page_live_bytes', 'page_peak_bytes', 'page_copied_bytes', 'planning_scratch_estimated_peak_bytes')
ARTIFACTS = ('EXPECTED.json', 'SUMMARY.json', 'decisions.jsonl', 'attempts.jsonl', 'observations.jsonl', 'final_map.jsonl')
SEMANTIC_FILES = ('decisions.jsonl', 'attempts.jsonl', 'final_map.jsonl')
FINAL_MAP_KEYS = {'node_encoding', 'all_nodes_sha256', 'all_events_sha256', 'source_hop', 'node_count',
                  'certified_nodes', 'first_node', 'last_node', 'input_generation', 'version', 'base_version',
                  'first_changed_node', 'received_input', 'output_frames', 'final', 'has_transitions', 'density_modes'}
METRICS = ('update_thread_cpu_s', 'update_wall_s', 'plan_thread_cpu_s', 'plan_wall_s',
           'confirm_thread_cpu_s', 'confirm_wall_s', 'planner_update_plan_thread_cpu_s',
           'planner_update_plan_wall_s', 'planner_transaction_thread_cpu_s', 'planner_transaction_wall_s',
           'map_bytes_final', 'whole_process_cpu_s', 'whole_process_wall_s')
SCOPE = {
    'scope': 'C1 offline planning only; coordinate fixture with no actual DSP OLA/FIR history',
    'main_cpu': 'sum CLOCK_THREAD_CPUTIME_ID intervals around planner.update and planner.plan',
    'main_wall': 'sum steady_clock intervals around planner.update and planner.plan; not end-to-end latency',
    'excluded_from_main': ['analysis append/finish', 'input copy', 'file/node/event hashes', 'JSON', 'constructor/destructor', 'confirmPlan'],
    'confirm': 'separate intervals, also included in planner_transaction totals',
    'whole_process_cpu': 'wait4 per-child user+system; includes excluded work and all threads',
    'copy_statistics': 'page/index copy and materialized count cover named targets only; not every internal Phase39 copy',
    'planning_scratch': 'conservative payload estimate of Phase39 materialize/proposal/protection/history temporary peak; not RSS or allocator measurement',
    'map_bytes': 'planner accounting, including estimated planning scratch in candidate; old/new accounting definitions differ',
    'n3': 'descriptive statistics only; no causal significance, confidence interval, or adoption claim',
    'PCM_approval': False, 'realtime_approval': False, 'subjective_approval': False,
    'application_F_approval': False, 'performance_adoption_approval': False,
}


def jsonl(path):
    def reject(value):
        raise ValueError('nonfinite JSONL: ' + value)
    lines = path.read_text().splitlines()
    common.require(all(line.strip() for line in lines), 'empty JSONL line: ' + str(path))
    return [json.loads(line, parse_constant=reject) for line in lines]


def wav(path, duration):
    """RIFF Float32 mono48kの専用計画負荷入力。chunk位置も保存する。"""
    path = path.resolve()
    size = path.stat().st_size
    with path.open('rb') as stream:
        header = stream.read(12)
        common.require(len(header) == 12 and header[:4] == b'RIFF' and header[8:] == b'WAVE', 'RIFF WAV required')
        common.require(struct.unpack('<I', header[4:8])[0] + 8 == size, 'RIFF file length')
        fmt, data = None, None
        while stream.tell() < size:
            part = stream.read(8)
            common.require(len(part) == 8, 'truncated WAV chunk')
            kind, count = struct.unpack('<4sI', part)
            common.require(stream.tell() + count + (count & 1) <= size, 'WAV chunk outside file')
            if kind == b'fmt ':
                common.require(fmt is None and 16 <= count <= 4096, 'WAV fmt')
                fmt = stream.read(count)
            elif kind == b'data':
                common.require(data is None, 'multiple data chunks')
                data = {'data_offset': stream.tell(), 'data_bytes': count}
                stream.seek(count, 1)
            else:
                stream.seek(count, 1)
            stream.seek(count & 1, 1)
    common.require(fmt is not None and data is not None, 'missing fmt/data')
    tag, channels, rate, byte_rate, align, bits = struct.unpack('<HHIIHH', fmt[:16])
    floating = tag == 3 or (tag == 0xfffe and len(fmt) >= 40 and fmt[24:40] == bytes.fromhex('0300000000001000800000aa00389b71'))
    common.require(floating and bits == 32 and channels == 1 and rate == 48000 and align == 4 and byte_rate == 192000, 'Float32 mono48k required')
    common.require(data['data_bytes'] == duration * rate * align, 'wrong dedicated WAV duration')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        stream.seek(data['data_offset'])
        remain = data['data_bytes']
        while remain:
            block = stream.read(min(remain, 1024 * 1024))
            common.require(block, 'truncated PCM payload')
            digest.update(block)
            remain -= len(block)
    return {**common.identity(path), **data, 'sample_format': 'Float32', 'rate': rate, 'channels': channels,
            'frames': duration * rate, 'duration_s': duration, 'pcm_payload_sha256': digest.hexdigest(),
            'purpose': 'C1 Map planning load only; not a replacement for quality or realtime reference'}


def confirm_double_pcm(short, long):
    """600秒は元300秒PCMの順序/bitを保った2回連結か確認する。"""
    with Path(short['path']).open('rb') as left, Path(long['path']).open('rb') as right:
        right.seek(long['data_offset'])
        for _ in range(2):
            left.seek(short['data_offset'])
            remain = short['data_bytes']
            while remain:
                size = min(remain, 1024 * 1024)
                common.require(left.read(size) == right.read(size), '600s PCM is not exact 300s payload repeated twice')
                remain -= size
    return {'status': 'PASS', 'base_sha256': short['sha256'], 'derived_sha256': long['sha256'],
            'recipe': 'copy original Float32 mono48k WAV PCM data twice in order; retain rate/channels/Float32; write corrected RIFF/data lengths',
            'verification': 'stream byte comparison of each half against the full original PCM payload',
            'reference_substitute': False}


def inventory(client, client_path):
    values = {}
    def add(value):
        if not isinstance(value, dict) or not {'path', 'bytes', 'sha256'} <= value.keys():
            return
        item = {k: value[k] for k in ('path', 'bytes', 'sha256')}
        common.require(item['path'] not in values or values[item['path']] == item, 'contradictory compile SHA')
        values[item['path']] = item
    add(common.identity(client_path))
    for key in ('driver', 'source', 'copied_source', 'old_archive', 'old_build', 'candidate_build', 'compiler', 'template', 'flags_file'):
        add(client[key])
    for value in client['helpers'] + client['old_archive_files']:
        add(value)
    for command in client['commands']:
        add(command['log'])
    for value in client['clients'].values():
        for key in ('binary', 'object', 'depfile'):
            add(value[key])
        for item in value['dependencies'] + value['libraries']:
            add(item)
    return [values[key] for key in sorted(values)]


def frozen(rows, roots):
    errors = []
    for item in rows:
        try:
            common.require(common.identity(item['path']) == item, 'SHA/bytes differs')
        except Exception as error:
            errors.append({'path': item['path'], 'error': str(error)})
    sources = {}
    for version, info in roots.items():
        try:
            digest = common.current_source_digest(Path(info['path']))
            sources[version] = {'expected': info['source'], 'actual': digest, 'same': digest == info['source']}
            common.require(digest == info['source'], 'source inventory changed')
        except Exception as error:
            errors.append({'source_root': info['path'], 'error': str(error)})
    return {'status': 'PASS' if not errors else 'FAIL', 'errors': errors, 'source_manifests': sources,
            'source_scope': 'CMakeLists and source files in src/tests/scripts; docs/results/build additions are permitted',
            'checked_files': len(rows)}


def host_environment():
    value = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'machine': platform.machine(),
             'platform': platform.platform(), 'python': sys.version, 'python_executable': common.identity(sys.executable),
             'load_average': list(os.getloadavg()), 'audio_device': 'NOT_USED (offline planner)',
             'inherited': {k: os.environ.get(k) for k in ('SDKROOT', 'MACOSX_DEPLOYMENT_TARGET', 'DEVELOPER_DIR',
                            'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}}
    for name, command in {'os': ['/usr/bin/sw_vers'], 'cpu': ['/usr/sbin/sysctl', 'hw.model', 'hw.memsize', 'hw.ncpu', 'hw.physicalcpu', 'hw.logicalcpu'],
                          'power': ['/usr/bin/pmset', '-g', 'batt'], 'thermal': ['/usr/bin/pmset', '-g', 'therm']}.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            value[name] = {'argv': command, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}
        except (OSError, subprocess.TimeoutExpired) as error:
            value[name] = {'argv': command, 'error': str(error)}
    return value


def matrix(seconds):
    jobs = []
    for duration in seconds:
        for history in (0, 4):
            for preset in ('candidate', 'baseline'):
                layer = f'S{duration}_H{history}_{preset}'
                for repetition in range(1, 4):
                    pair = f'{layer}_r{repetition:02d}'
                    for version in (('old', 'candidate') if repetition % 2 else ('candidate', 'old')):
                        jobs.append({'id': pair + '_' + version, 'pair': pair, 'layer': layer, 'version': version,
                                     'preset': preset, 'history': history, 'seconds': duration, 'repetition': repetition})
    return jobs


def assess(job, directory, execution, info, binary):
    errors, outputs, rows = [], {}, {}
    def check(value, message):
        if not value:
            errors.append(message)
    check(execution.get('returncode') == 0 and not execution.get('timeout') and not execution.get('interrupted'), 'process failure/timeout/interruption')
    for key in ('wall_s', 'process_user_s', 'process_system_s', 'whole_process_cpu_s'):
        check(common.finite(execution.get(key)) and execution[key] >= 0, 'invalid whole-process clock: ' + key)
    check(common.finite(execution.get('wall_s')) and execution['wall_s'] > 0, 'zero process duration')
    try:
        output = common.load(directory / 'ARTIFACTS.json')
        check({item['path'] for item in output['files']} == set(ARTIFACTS), 'artifact ID set')
        check(len(output['files']) == len(ARTIFACTS), 'duplicate artifact ID')
        for item in output['files']:
            check(item['path'] in ARTIFACTS, 'unexpected output path')
            if item['path'] not in ARTIFACTS:
                continue
            path = directory / item['path']
            observed = common.identity(path)
            check(observed['sha256'] == item['sha256'] and observed['bytes'] == item['bytes'], 'artifact hash ' + item['path'])
            outputs[item['path']] = observed
        outputs['ARTIFACTS.json'] = common.identity(directory / 'ARTIFACTS.json')
        s, expected = common.load(directory / 'SUMMARY.json'), common.load(directory / 'EXPECTED.json')
        for name in ('decisions.jsonl', 'attempts.jsonl', 'observations.jsonl', 'final_map.jsonl'):
            rows[name] = jsonl(directory / name)
        check(s.get('status') == 'PASS' and s.get('run_complete') is True, 'host incomplete/FAIL')
        for key, value in {'source': binary['source'], 'preset': job['preset'], 'prefix_seconds': job['seconds'],
                           'metrics_compiled': job['version'] == 'candidate', 'diagnostic_replay': False,
                           'input_sha256': info['sha256'], 'binary_sha256': binary['binary']['sha256'],
                           'source_rate': info['rate'], 'channels': info['channels'], 'input_frames': info['rate'] * job['seconds'],
                           'received_frames': info['rate'] * job['seconds'], 'chunk_frames': 32768,
                           'expected_history': job['history'], 'applied_history': job['history']}.items():
            check(s.get(key) == value, 'summary identity: ' + key)
        request_ids = list(range(1, job['history'] + 1))
        requests = [{'id': i + 1, 'target_micros': target, 'progress_percent': progress,
                     'due_input_frames': (s['input_frames'] * progress + 99) // 100}
                    for i, (target, progress) in enumerate(zip((500000, 750000, 1500000, 2000000), (10, 30, 50, 70)))] if job['history'] else []
        check(expected.get('requests') == requests and expected.get('source') == binary['source'] and expected.get('preset') == job['preset'], 'expected request set')
        check(expected.get('input_file_sha256') == info['sha256'] and expected.get('prefix_seconds') == job['seconds'], 'expected input')
        decisions, attempts, observations, final_map = (rows[name] for name in ('decisions.jsonl', 'attempts.jsonl', 'observations.jsonl', 'final_map.jsonl'))
        check([r.get('id') for r in decisions] == request_ids, 'all accepted decision IDs')
        check([r.get('after_request_id') for r in observations] == request_ids, 'all applied observation IDs')
        check({r.get('id') for r in attempts} == set(request_ids), 'attempt ID set')
        check(len(final_map) == 1 and final_map[0].get('final') is True and final_map[0].get('received_input') == s['input_frames'], 'final Map completeness')
        if len(final_map) == 1:
            check(set(final_map[0]) == FINAL_MAP_KEYS, 'complete final Map field set')
            check(final_map[0].get('certified_nodes') == final_map[0].get('node_count'), 'all certified nodes recorded')
        check(len(attempts) == s['plan']['calls'], 'all plan attempts recorded')
        check(len(decisions) == s['confirm']['calls'] == job['history'], 'all confirmations recorded')
        check(sum(r.get('pending_attempts', 0) for r in decisions) == s['pending_attempts'], 'all pending attempts')
        check(s['append_calls'] == math.ceil(s['input_frames'] / 32768), 'append count')
        check(s['update']['calls'] == s['append_calls'] + 1, 'all updates counted')
        check(s['plan']['calls'] == job['history'] + s['pending_attempts'], 'plan count')
        check(job['history'] == 0 or (s['nonfinal_applied'] > 0 and s['updates_with_committed_history'] > 0), 'nonfinal history not exercised')
        for phase in ('update', 'plan', 'confirm'):
            check(type(s[phase]['calls']) is int and s[phase]['calls'] >= 0, phase + ' calls')
            for field in ('thread_cpu_s', 'wall_s', 'max_thread_cpu_s', 'max_wall_s'):
                check(common.finite(s[phase][field]) and s[phase][field] >= 0, phase + ' invalid ' + field)
            check(s[phase]['max_thread_cpu_s'] <= s[phase]['thread_cpu_s'] + 1e-12 and s[phase]['max_wall_s'] <= s[phase]['wall_s'] + 1e-12, phase + ' maxima')
        for field, phases in (('planner_update_plan', ('update', 'plan')), ('planner_transaction', ('update', 'plan', 'confirm'))):
            for suffix in ('thread_cpu_s', 'wall_s'):
                check(common.finite(s.get(field + '_' + suffix)) and math.isclose(s[field + '_' + suffix], sum(s[p][suffix] for p in phases), rel_tol=1e-9, abs_tol=1e-12), field + ' formula')
        check(common.finite(s.get('map_bytes_final')) and s['map_bytes_final'] >= 0, 'map accounting')
        check(all(s.get(k) is False for k in ('analysis_append_cpu_included', 'hash_json_cpu_included', 'constructor_destructor_cpu_included',
                                            'clock_overhead_subtracted', 'PCM_approval', 'realtime_approval', 'subjective_approval', 'application_F_approval')), 'scope/approval flags')
        stats = s['statistics']
        check(set(stats) == {'available', *STAT_KEYS}, 'statistics schema')
        if job['version'] == 'candidate':
            check(stats.get('available') is True and all(type(stats.get(k)) is int and stats[k] >= 0 for k in STAT_KEYS), 'candidate statistics unavailable/invalid')
            check(stats['updates'] == s['update']['calls'], 'statistics update count')
            check(all(stats[k] == 0 for k in ('history_replays', 'diagnostic_replay_requests', 'diagnostic_comparisons')), 'normal path replayed history')
            check(stats['fixed_cache_entries'] <= 5, 'fixed cache >5')
            check(stats['page_live_bytes'] <= stats['page_peak_bytes'], 'page high-water mark')
            check(stats['page_peak_bytes'] <= 4 * 1024 * 1024, 'planner immutable-page budget >4MiB')
        else:
            check(stats.get('available') is False and all(stats.get(k) is None for k in STAT_KEYS), 'old statistics must be null, not zero')
        values = {f'{phase}_{field}': s[phase][field] for phase in ('update', 'plan', 'confirm') for field in ('thread_cpu_s', 'wall_s')}
        values.update({k: s[k] for k in METRICS if k in s})
        values.update(whole_process_cpu_s=execution['whole_process_cpu_s'], whole_process_wall_s=execution['wall_s'])
        return {'status': 'PASS' if not errors else 'FAIL', 'errors': errors, 'metrics': values, 'statistics': stats,
                'outputs': outputs, 'planned_request_ids': request_ids, 'decision_count': len(decisions), 'attempt_count': len(attempts)}, rows
    except Exception as error:
        errors.append(type(error).__name__ + ': ' + str(error))
        return {'status': 'FAIL', 'errors': errors, 'outputs': outputs}, rows


def statistics_for(values):
    return {'n': len(values), 'values': values, 'mean': statistics.mean(values) if values else None,
            'median': statistics.median(values) if values else None, 'p95_interpolated': common.percentile(values),
            **common.dispersion(values)}


def compare(jobs, results):
    pairs = {}
    for job in jobs:
        pairs.setdefault(job['pair'], {})[job['version']] = job
    comparisons = []
    for name, versions in pairs.items():
        old, candidate = (results.get(versions[v]['id'], {}) for v in ('old', 'candidate'))
        errors, files = [], {}
        for filename in SEMANTIC_FILES:
            try:
                left, right = (Path(results[versions[v]['id']]['output']) / filename for v in ('old', 'candidate'))
                byte_same = common.identity(left)['sha256'] == common.identity(right)['sha256']
                same = jsonl(left) == jsonl(right) and byte_same
                files[filename] = {'same_all_fields': same, 'byte_identical': byte_same,
                                   'old': common.identity(left), 'candidate': common.identity(right)}
                if not same:
                    errors.append(filename + ' differs')
            except Exception as error:
                errors.append(filename + ': ' + str(error))
        if old.get('assessment', {}).get('status') != 'PASS' or candidate.get('assessment', {}).get('status') != 'PASS':
            errors.append('one or both programs failed validation')
        comparisons.append({'pair': name, 'layer': versions['old']['layer'], 'status': 'PASS' if not errors else 'FAIL', 'errors': errors, 'files': files})
    return comparisons


def aggregate(jobs, results, comparisons):
    groups = []
    for layer in dict.fromkeys(j['layer'] for j in jobs):
        group = {'layer': layer, 'scope': SCOPE, 'versions': {}, 'paired_candidate_reduction_percent': {},
                 'semantic_pairs_passed': sum(c['layer'] == layer and c['status'] == 'PASS' for c in comparisons), 'expected_pairs': 3}
        for version in ('old', 'candidate'):
            selected = [results[j['id']]['assessment'] for j in jobs if j['layer'] == layer and j['version'] == version and j['id'] in results]
            valid = [s for s in selected if s['status'] == 'PASS']
            group['versions'][version] = {'expected_programs': 3, 'valid_programs': len(valid),
                'metrics': {k: statistics_for([s['metrics'][k] for s in valid]) for k in METRICS},
                'statistics': {k: (statistics_for([s['statistics'][k] for s in valid]) if version == 'candidate' else None) for k in STAT_KEYS},
                'statistics_available': version == 'candidate'}
        group['semantically_comparable'] = group['semantic_pairs_passed'] == 3 and all(v['valid_programs'] == 3 for v in group['versions'].values())
        for metric in ('planner_update_plan_thread_cpu_s', 'planner_update_plan_wall_s', 'planner_transaction_thread_cpu_s', 'whole_process_cpu_s'):
            reductions = []
            for repetition in range(1, 4):
                pair_jobs = {j['version']: j for j in jobs if j['layer'] == layer and j['repetition'] == repetition}
                pair_results = {v: results.get(j['id'], {}).get('assessment', {}) for v, j in pair_jobs.items()}
                pair_name = f'{layer}_r{repetition:02d}'
                semantic_pass = any(c['pair'] == pair_name and c['status'] == 'PASS' for c in comparisons)
                if semantic_pass and all(s.get('status') == 'PASS' for s in pair_results.values()):
                    left, right = (pair_results[v]['metrics'][metric] for v in ('old', 'candidate'))
                    if left > 0:
                        reductions.append(100 * (left - right) / left)
            group['paired_candidate_reduction_percent'][metric] = statistics_for(reductions)
        groups.append(group)
    return groups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clients', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--input', type=Path, default=ROOT / 'results/phase56/long/chain_300s.wav')
    parser.add_argument('--long-input', type=Path)
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new evidence output belongs under build/')
    out.mkdir(parents=True, exist_ok=False)
    summary = {'schema': 'c1-planning-pairs-v1', 'status': 'INCOMPLETE', 'driver': common.identity(__file__),
               'helpers': [common.identity(common.__file__)], 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'scope': SCOPE, 'results': [], 'groups': [], 'long600': {'status': 'NOT_RUN', 'reason': 'dedicated --long-input was not supplied'}}
    results, executions, jobs = {}, [], []
    try:
        common.require(platform.machine() == 'arm64', 'native arm64 Python required; use bundled runtime Python')
        common.require(common.finite(args.timeout) and args.timeout >= 30, 'finite timeout >=30s required')
        common.require(not any(os.environ.get(k) for k in ('DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'CPATH', 'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH')), 'ambient library/include override')
        client = common.load(args.clients)
        common.require(client['schema'] == 'c1-planning-clients-v1' and client['status'] == 'PASS', 'compiled client manifest must be PASS')
        common.require(set(client['clients']) == {'old', 'candidate'}, 'both versions required')
        common.require(client['source']['sha256'] == client['copied_source']['sha256'], 'one common client source required')
        common.require(client['clients']['old']['incremental_metrics'] is False and client['clients']['candidate']['incremental_metrics'] is True, 'metrics macro identity')
        common.require(client['clients']['old']['constructor_arguments'] == 5 and client['clients']['candidate']['constructor_arguments'] == 6, 'constructor ABI identity')
        for entry in client['clients'].values():
            common.require(entry['architectures'] == ['arm64'] and entry['diagnostic_replay'] is False, 'arm64 normal client only')
        inputs = {300: wav(args.input, 300)}
        if args.long_input:
            inputs[600] = wav(args.long_input, 600)
            summary['long600'] = confirm_double_pcm(inputs[300], inputs[600])
        jobs = matrix([30, 300] + ([600] if args.long_input else []))
        common.require(len(jobs) == (72 if args.long_input else 48) and len({j['id'] for j in jobs}) == len(jobs), 'fixed matrix count')
        rows = inventory(client, args.clients) + [common.identity(__file__), common.identity(common.__file__)] + [{k: i[k] for k in ('path', 'bytes', 'sha256')} for i in inputs.values()]
        roots = {v: {'path': i['source_root'], 'source': i['source']} for v, i in client['clients'].items()}
        common.save(out / 'COMPILE_INVENTORY.json', rows)
        before = frozen(rows, roots)
        common.save(out / 'FROZEN_BEFORE.json', before)
        common.require(before['status'] == 'PASS', 'compile/source inventory is not frozen')
        common.save(out / 'ENVIRONMENT_BEFORE.json', host_environment())
        summary.update(clients=common.identity(args.clients), expected_programs=len(jobs), expected_pairs=len(jobs) // 2,
                       expected_decision_rows=sum(j['history'] for j in jobs), expected_final_map_rows=len(jobs),
                       expected_ids=[j['id'] for j in jobs], inputs=list(inputs.values()), compile_inventory=common.identity(out / 'COMPILE_INVENTORY.json'),
                       CPU_formula='sum thread CPU intervals for update+plan; one core=100%; no wall interval includes analysis append',
                       timeout_s=args.timeout)
        common.save(out / 'EXPECTED.json', {'jobs': jobs, 'expected_programs': len(jobs), 'expected_pairs': len(jobs) // 2,
                    'expected_decision_rows': summary['expected_decision_rows'], 'expected_final_map_rows': len(jobs),
                    'scope': SCOPE, 'inputs': list(inputs.values()), 'long600': summary['long600']})
        common.save(out / 'SUMMARY.json', summary)
        for job in jobs:
            info = inputs[600 if job['seconds'] == 600 else 300]
            entry = client['clients'][job['version']]
            command = [entry['binary']['path'], info['path'], job['preset'], str(job['history']), str(job['seconds']), str(out / job['id']), entry['source']]
            row = {**job, 'argv': command, 'output': str(out / job['id'])}
            try:
                common.require(common.identity(args.clients) == summary['clients'], 'CLIENT manifest changed during run')
                common.require(common.identity(entry['binary']['path']) == entry['binary'], 'binary changed before run')
                execution = common.execute(command, out / (job['id'] + '.log'), args.timeout)
                executions.append({**job, **execution})
                assessment, _ = assess(job, out / job['id'], execution, info, entry)
                row.update(execution=execution, assessment=assessment)
            except Exception as error:
                row.update(assessment={'status': 'FAIL', 'errors': [type(error).__name__ + ': ' + str(error)]})
            results[job['id']] = row
            common.save(out / 'PROCESS_COST.json', {'scope': 'whole process cost including analysis/IO/hash/JSON; not main planner-only measurement', 'rows': executions})
            summary.update(results=list(results.values()), completed_programs=len(executions),
                           validated_programs=sum(r['assessment']['status'] == 'PASS' for r in results.values()))
            common.save(out / 'SUMMARY.json', summary)
        after = frozen(rows, roots)
        common.save(out / 'FROZEN_AFTER.json', after)
        common.save(out / 'ENVIRONMENT_AFTER.json', host_environment())
        comparisons = compare(jobs, results)
        common.save(out / 'COMPARISONS.json', comparisons)
        groups = aggregate(jobs, results, comparisons)
        summary.update(groups=groups, comparisons=common.identity(out / 'COMPARISONS.json'),
                       actual_decision_rows=sum(r['assessment'].get('decision_count', 0) for r in results.values()),
                       semantic_pairs_passed=sum(r['status'] == 'PASS' for r in comparisons),
                       frozen_before=before, frozen_after=after,
                       functional_pass=all(r['assessment']['status'] == 'PASS' for r in results.values()) and len(results) == len(jobs),
                       semantic_pass=all(r['status'] == 'PASS' for r in comparisons),
                       all_programs_finished=len(executions) == len(jobs) and all(e['returncode'] == 0 and not e['timeout'] and not e['interrupted'] for e in executions))
        summary['status'] = 'PASS' if summary['functional_pass'] and summary['semantic_pass'] and summary['all_programs_finished'] and after['status'] == 'PASS' and summary['actual_decision_rows'] == summary['expected_decision_rows'] else 'FAIL'
        common.save(out / 'SUMMARY.json', summary)
        print(out / 'SUMMARY.json')
        return 0 if summary['status'] == 'PASS' else 1
    except BaseException as error:
        summary.update(status='FAIL', error=type(error).__name__ + ': ' + str(error), results=list(results.values()),
                       completed_programs=len(executions), expected_programs=len(jobs) if jobs else None)
        common.save(out / 'SUMMARY.json', summary)
        raise


if __name__ == '__main__':
    sys.exit(main())
