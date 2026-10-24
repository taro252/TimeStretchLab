"""固定clientの旧版/候補を交互に実行する。新規build/内の出力先のみ。

既定はCandidatePreset、各層3反復、反復順old/new→new/old→old/new。
steady: 2入力×4速度×3反復×2版=48件、各測定窓30秒。
ab: A30/A270×fresh/prewarm/early0/mid×3反復×2版=48件。
例: --baseline-client B/frozen_clients_01/CLIENT.json --candidate-build B/build_candidate_02/BUILD.json
    --suite ab --output B/ab_pairs_01 --only A270_mid_candidate
--onlyは層IDまたはpair IDを受け、片方の版だけを選択しない。
CPU、ON待ち時間、RT、独立PCM検証、実アプリ/F、音響の判定は別々に扱う。
親Pythonもarm64版を指定する（/usr/local/bin/python3はRosettaの場合がある）。
子native実行形式のarm64と親Pythonの実行形式は別々に記録する。
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import pathlib
import platform
import signal
import statistics
import struct
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[3]
TARGET = {'steady': 'performance_steady_native', 'ab': 'progressive_adoption_ab_native'}
SOURCE = {'steady': 'tests/PerformanceSteadyNative.cpp', 'ab': 'tests/ProgressiveAdoptionAbNative.cpp'}
OLD_COMMIT = '5674bd982d98caacaa3e87cdeae5bfc0b01c66ef'
CPU_FORMULA = '100 * (RUSAGE_SELF user_s + system_s delta) / steady_clock wall_s delta; 1 core = 100%'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(path):
    path = pathlib.Path(path).resolve()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def load(path):
    def reject_constant(text):
        raise ValueError('non-finite JSON: ' + text)
    return json.loads(path.read_text(), parse_constant=reject_constant)


def manifest_digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def current_source_digest(root):
    paths = [root / 'CMakeLists.txt']
    for directory in ('src', 'tests', 'scripts'):
        paths.extend(p for p in (root / directory).rglob('*') if p.is_file() and
                     p.suffix in ('.h', '.hpp', '.cpp', '.mm', '.py', '.c', '.m'))
    rows = [{'path': str(p.relative_to(root)), 'sha256': identity(p)['sha256']} for p in sorted(paths)]
    return manifest_digest(rows)


def wav_identity(path, rate, channels):
    """IEEE Float32 WAVを読み取り検証。Python waveはformat=3を扱えない。"""
    path = path.resolve()
    with path.open('rb') as stream:
        header = stream.read(12)
        require(len(header) == 12 and header[:4] == b'RIFF' and header[8:] == b'WAVE', 'RIFF WAV required')
        fmt, data_bytes = None, None
        while stream.tell() + 8 <= path.stat().st_size:
            kind, size = struct.unpack('<4sI', stream.read(8))
            require(stream.tell() + size <= path.stat().st_size, 'WAV chunk outside file')
            if kind == b'fmt ':
                require(16 <= size <= 4096, 'WAV fmt chunk size')
                fmt = stream.read(size)
            elif kind == b'data':
                require(data_bytes is None, 'multiple WAV data chunks')
                data_bytes = size
                stream.seek(size, 1)
            else:
                stream.seek(size, 1)
            if size & 1:
                stream.seek(1, 1)
    require(fmt is not None and data_bytes is not None, 'WAV fmt/data missing')
    tag, actual_channels, actual_rate, byte_rate, align, bits = struct.unpack('<HHIIHH', fmt[:16])
    floating = tag == 3 or (tag == 0xfffe and len(fmt) >= 40 and
                          fmt[24:40] == bytes.fromhex('0300000000001000800000aa00389b71'))
    require(floating and bits == 32, 'Float32 input required')
    require((actual_rate, actual_channels) == (rate, channels), 'wrong WAV rate/channels')
    require(align == channels * 4 and byte_rate == rate * align and data_bytes % align == 0, 'WAV frame format')
    frames = data_bytes // align
    require(frames == rate * 300, '300-second input required')
    return {**identity(path), 'sample_format': 'Float32', 'rate': rate, 'channels': channels,
            'frames': frames, 'duration_s': frames / rate, 'data_bytes': data_bytes}


def environment():
    values = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'platform': platform.platform(), 'machine': platform.machine(),
              'python': sys.version, 'load_average': list(os.getloadavg()),
              'inherited': {key: os.environ.get(key) for key in
                            ('SDKROOT', 'MACOSX_DEPLOYMENT_TARGET', 'DEVELOPER_DIR', 'DYLD_LIBRARY_PATH',
                             'DYLD_INSERT_LIBRARIES', 'OMP_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}}
    for key, command in {
        'os': ['/usr/bin/sw_vers'],
        'cpu': ['/usr/sbin/sysctl', 'hw.model', 'hw.memsize', 'hw.ncpu', 'hw.physicalcpu', 'hw.logicalcpu'],
        'audio_devices': ['/usr/sbin/system_profiler', 'SPAudioDataType'],
        'power': ['/usr/bin/pmset', '-g', 'batt'],
        'thermal': ['/usr/bin/pmset', '-g', 'therm'],
    }.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            values[key] = {'argv': command, 'returncode': result.returncode,
                           'stdout': result.stdout, 'stderr': result.stderr}
        except (OSError, subprocess.TimeoutExpired) as error:
            values[key] = {'argv': command, 'error': str(error)}
    return values


def execute(command, log, timeout):
    """wait4でこの子だけの全process CPUを回収する。測定窓CPUとは混ぜない。"""
    begin, usage, status, timed_out, interrupted = time.monotonic(), None, None, False, False
    with log.open('w') as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while True:
                pid, status, usage = os.wait4(child.pid, os.WNOHANG)
                if pid:
                    break
                if time.monotonic() - begin >= timeout:
                    timed_out = True
                    os.killpg(child.pid, signal.SIGTERM)
                    deadline = time.monotonic() + 5
                    while True:
                        pid, status, usage = os.wait4(child.pid, os.WNOHANG)
                        if pid:
                            break
                        if time.monotonic() >= deadline:
                            os.killpg(child.pid, signal.SIGKILL)
                            _, status, usage = os.wait4(child.pid, 0)
                            break
                        time.sleep(.05)
                    break
                time.sleep(.05)
        except KeyboardInterrupt:
            interrupted = True
        finally:
            if usage is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
    return {'returncode': child.returncode, 'timeout': timed_out, 'interrupted': interrupted,
            'wall_s': time.monotonic() - begin,
            'process_user_s': usage.ru_utime, 'process_system_s': usage.ru_stime,
            'whole_process_cpu_s': usage.ru_utime + usage.ru_stime,
            'max_rss_native_units': usage.ru_maxrss, 'max_rss_units': 'bytes on macOS; KiB on Linux',
            'voluntary_context_switches': usage.ru_nvcsw, 'involuntary_context_switches': usage.ru_nivcsw,
            'log': identity(log)}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def percentile(values, q=.95):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def dispersion(values):
    mean = statistics.mean(values) if values else None
    stdev = statistics.stdev(values) if len(values) > 1 else None
    return {'min': min(values) if values else None, 'max': max(values) if values else None,
            'sample_stdev': stdev, 'coefficient_of_variation_percent':
            100 * stdev / abs(mean) if stdev is not None and mean else None}


def assess(suite, job, summary, cost, execution, input_info, seconds, device_rate, device_buffer):
    errors = []
    def check(condition, text):
        if not condition:
            errors.append(text)
    check(not execution['timeout'] and not execution['interrupted'], 'process timeout/interruption')
    check(isinstance(summary.get('rt_pass'), bool), 'missing RT result')
    rt = summary.get('rt_pass') is True
    # 2はhostが明示的に報告したRT違反。欠落/例外の1とは分離して記録する。
    check(execution['returncode'] == (0 if rt else 2), 'exit/RT result mismatch')
    check(summary.get('input_sha256') == input_info['sha256'], 'input SHA mismatch')
    check(summary.get('source_rate') == input_info['rate'], 'source rate mismatch')
    check(summary.get('device_rate') == device_rate and summary.get('device_buffer') == device_buffer,
          'device rate/buffer differs from fixed condition')
    check(finite(summary.get('owners_peak')) and summary['owners_peak'] <= 2, 'execution owner bound')
    if suite == 'steady':
        check(summary.get('complete') is True, 'incomplete steady window')
        cpu, wall = summary.get('cpu_s'), summary.get('wall_s')
        check(finite(cpu) and cpu >= 0 and finite(wall) and wall >= seconds and wall <= seconds + 2,
              'invalid steady CPU/window')
        if finite(cpu) and finite(wall) and wall > 0:
            expected = 100 * cpu / wall
            check(finite(summary.get('cpu_percent')) and math.isclose(summary['cpu_percent'], expected, rel_tol=1e-9, abs_tol=1e-8), 'CPU formula mismatch')
        check(finite(summary.get('polls')) and summary['polls'] >= seconds * 4, 'control polling count')
        check(summary.get('quality') is None and summary.get('physical_audio') is None, 'unexpected quality/physical approval')
    else:
        check(summary.get('run_complete') is True and summary.get('functional') is True, 'AB functional/incomplete')
        check(summary.get('performance_exercised') is True, 'Playing native measurement not exercised')
        check(summary.get('channels') == input_info['channels'], 'AB input channels')
        check(summary.get('C_before_A') is True, 'initial C is not before A')
        check(finite(summary.get('accepted_to_first_A_ms')) and summary['accepted_to_first_A_ms'] >= 0, 'AB first A timestamp')
        check(finite(summary.get('checkpoint_peak')) and summary['checkpoint_peak'] <= 2, 'checkpoint bound')
        check(bool(cost), 'host PROCESS_COST.json missing')
        for key in ('pre_on_wall_ms', 'on_to_first_A_observed_wall_ms', 'pre_on_process_cpu_s',
                    'on_to_first_A_observed_process_cpu_s', 'total_process_cpu_s'):
            check(finite(cost.get(key)) and cost[key] >= 0, 'invalid process cost ' + key)
        if all(finite(cost.get(key)) for key in ('pre_on_process_cpu_s', 'on_to_first_A_observed_process_cpu_s', 'total_process_cpu_s')):
            check(math.isclose(cost['total_process_cpu_s'], cost['pre_on_process_cpu_s'] + cost['on_to_first_A_observed_process_cpu_s'], rel_tol=1e-9, abs_tol=1e-8), 'total ON process CPU formula')
        check(cost.get('prewarm_lead_ms') == job['lead_ms'], 'prewarm lead mismatch')
        check(finite(cost.get('C_at_on')) and 0 <= cost['C_at_on'] < job['A_seconds'] * input_info['rate'], 'C at ON is not before A')
        if job['mode'] == 'fresh':
            check(summary.get('initial_checkpoint_hit') is False, 'fresh unexpectedly used a checkpoint')
            check(cost.get('preparing_at_on') is False, 'fresh unexpectedly had preparation')
        elif job['mode'] == 'prewarm':
            check(summary.get('initial_checkpoint_hit') is True and summary.get('preparation_joined') is True,
                  'completed prewarm was not reused/joined')
            check(cost.get('preparing_at_on') is False, 'completed prewarm still preparing at ON')
        else:
            # 先に完了した測定を「途中引継ぎ」へ無断で分類しない。
            check(cost.get('preparing_at_on') is True, 'early0/mid preparation completed before ON')
        target = 250 if job['mode'] == 'prewarm' else 1000
        if finite(summary.get('accepted_to_first_A_ms')):
            check(summary.get('performance_pass') is (summary['accepted_to_first_A_ms'] <= target), 'host latency target mismatch')
    return {'integrity_pass': not errors, 'errors': errors, 'rt_pass': rt,
            'latency_target_ms': (250 if job.get('mode') == 'prewarm' else 1000) if suite == 'ab' else None,
            'latency_sample_pass': summary.get('performance_pass') if suite == 'ab' else None}


def aggregate(rows, jobs, suite, repeats):
    groups = []
    for stratum in dict.fromkeys(job['stratum'] for job in jobs):
        versions = {}
        expected_repeats = sorted({job['repeat'] for job in jobs if job['stratum'] == stratum})
        expected_count = len(expected_repeats)
        for version in ('old', 'candidate'):
            selected = [row for row in rows if row['stratum'] == stratum and row['version'] == version]
            valid = [row for row in selected if row.get('integrity_pass')]
            metric = 'cpu_percent' if suite == 'steady' else 'accepted_to_first_A_ms'
            values = [row['summary'][metric] for row in valid]
            rt_values = [row['summary'][metric] for row in valid if row.get('rt_pass')]
            target = selected[0].get('latency_target_ms') if selected else None
            p95 = percentile(values)
            versions[version] = {'expected': expected_count, 'executed': len(selected), 'valid': len(valid),
                                 'samples': values, 'mean': sum(values) / len(values) if values else None,
                                 'median': percentile(values, .5), 'p95': p95,
                                 **dispersion(values), 'rt_clean_samples': rt_values,
                                 'rt_clean_mean': statistics.mean(rt_values) if rt_values else None,
                                 'rt_all_pass': len(selected) == expected_count and all(row.get('rt_pass') for row in selected),
                                 'latency_target_ms': target,
                                 'latency_p95_pass': len(values) == expected_count and p95 <= target if target is not None else None}
        paired = []
        for repeat in expected_repeats:
            match = {row['version']: row for row in rows if row['stratum'] == stratum and row['repeat'] == repeat}
            if set(match) == {'old', 'candidate'} and all(row.get('integrity_pass') for row in match.values()):
                key = 'cpu_percent' if suite == 'steady' else 'accepted_to_first_A_ms'
                old, candidate = (match[v]['summary'][key] for v in ('old', 'candidate'))
                paired.append({'repeat': repeat, 'old': old, 'candidate': candidate,
                               'candidate_over_old': candidate / old if old else None,
                               'reduction_percent': 100 * (old - candidate) / old if old else None})
        reductions = [pair['reduction_percent'] for pair in paired if pair['reduction_percent'] is not None]
        ranges = [versions[version] for version in ('old', 'candidate')]
        overlap = (max(group['min'] for group in ranges) <= min(group['max'] for group in ranges)) if all(group['min'] is not None for group in ranges) else None
        groups.append({'stratum': stratum, 'metric': metric, 'versions': versions, 'pairs': paired,
                       'paired_reduction_mean_percent': statistics.mean(reductions) if reductions else None,
                       'paired_reduction_spread': dispersion(reductions), 'sample_ranges_overlap': overlap,
                       'statistical_significance': 'NOT_ASSESSED; n=3 descriptive statistics only'})
    return groups


def main():
    def interrupted(signum, frame):
        raise KeyboardInterrupt('signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-client', type=pathlib.Path, required=True)
    parser.add_argument('--candidate-build', type=pathlib.Path, required=True)
    parser.add_argument('--suite', choices=TARGET, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--mono-input', type=pathlib.Path, default=ROOT / 'results/phase56/long/chain_300s.wav')
    parser.add_argument('--stereo-input', type=pathlib.Path, default=ROOT / 'build/phase61_fast_seek/music_300s.wav')
    parser.add_argument('--presets', nargs='+', choices=('candidate', 'baseline'), default=['candidate'])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--device-rate', type=int, default=48000)
    parser.add_argument('--device-buffer', type=int, default=512)
    parser.add_argument('--only', nargs='+', help='stratum ID or pair ID; both versions are retained')
    args = parser.parse_args()
    require(args.repeats > 0 and 5 <= args.seconds <= 60 and args.timeout > args.seconds, 'invalid finite run bounds')
    require(len(args.presets) == len(set(args.presets)), 'duplicate presets')
    out = args.output.resolve()
    require(out.is_relative_to(ROOT / 'build'), 'large evidence must be written under build/')
    out.mkdir(parents=True, exist_ok=False)
    rows, errors, jobs = [], [], []
    try:
        baseline, candidate = load(args.baseline_client), load(args.candidate_build)
        require(baseline['status'] == candidate['status'] == 'PASS', 'build/client record is not PASS')
        require(baseline['schema'] == 'performance-frozen-client-v1' and baseline['contract_version'] == 3,
                'baseline must be the old-header frozen client')
        require(baseline['baseline_commit'] == OLD_COMMIT, 'wrong baseline commit')
        require(candidate['architecture'] == 'arm64' and candidate['configuration'] == 'Release', 'candidate configuration')
        require(manifest_digest(candidate['source_manifest']['files']) == candidate['source'] == candidate['source_manifest']['sha256'], 'candidate manifest SHA')
        candidate_root = pathlib.Path(candidate['source_root']).resolve()
        require(current_source_digest(candidate_root) == candidate['source'], 'candidate source changed after build')
        source_map = {row['path']: row['sha256'] for row in candidate['source_manifest']['files']}
        client = baseline['clients'][args.suite]
        require(client['source_relative'] == SOURCE[args.suite] and client['contract_version'] == 3, 'client suite/ABI mismatch')
        source_sha = client['copied_source']['sha256']
        require(source_map[SOURCE[args.suite]] == source_sha == client['source']['sha256'], 'old/candidate client source is not identical')
        require(identity(client['copied_source']['path']) == client['copied_source'], 'copied old client changed')
        hosts = {'old': client['binary'], 'candidate': candidate['binaries'][TARGET[args.suite]]}
        record_ids = {'baseline_client': identity(args.baseline_client), 'candidate_build': identity(args.candidate_build)}
        def verify_frozen():
            require(identity(args.baseline_client) == record_ids['baseline_client'] and
                    identity(args.candidate_build) == record_ids['candidate_build'], 'build record changed')
            for host in hosts.values():
                require(identity(host['path']) == host, 'binary SHA changed')
            for item in baseline['link_inputs'].values():
                require(identity(item['path']) == item, 'old link input SHA changed')
        verify_frozen()
        require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS required')
        # 外部ライブラリ差し替えで旧/新の実行内容が変わることを避ける。
        require(not os.environ.get('DYLD_LIBRARY_PATH') and not os.environ.get('DYLD_INSERT_LIBRARIES'), 'ambient DYLD override')
        inputs = {'mono48chain300s': wav_identity(args.mono_input, 48000, 1)}
        if args.suite == 'steady':
            inputs['stereo441music300s'] = wav_identity(args.stereo_input, 44100, 2)
        pairs = []
        for repeat in range(1, args.repeats + 1):
            for preset in args.presets:
                if args.suite == 'steady':
                    configs = [(label, speed) for label in inputs for speed in (40, 50, 100, 200)]
                    for label, speed in configs:
                        stratum = f'{label}_s{speed:03d}_{preset}'
                        pairs.append({'id': f'{stratum}_r{repeat:02d}', 'stratum': stratum, 'repeat': repeat,
                                      'preset': preset, 'input': label, 'speed': speed / 100})
                else:
                    for at in (30, 270):
                        for mode in ('fresh', 'prewarm', 'early0', 'mid'):
                            stratum = f'A{at}_{mode}_{preset}'
                            pairs.append({'id': f'{stratum}_r{repeat:02d}', 'stratum': stratum, 'repeat': repeat,
                                          'preset': preset, 'input': 'mono48chain300s', 'A_seconds': at,
                                          'mode': mode, 'lead_ms': (500 if at == 30 else 2500) if mode == 'mid' else 0})
        if args.only:
            known = {pair[key] for pair in pairs for key in ('id', 'stratum')}
            require(set(args.only) <= known, 'unknown --only ID: ' + str(set(args.only) - known))
            pairs = [pair for pair in pairs if pair['id'] in args.only or pair['stratum'] in args.only]
        for pair in pairs:
            order = ('old', 'candidate') if pair['repeat'] % 2 else ('candidate', 'old')
            for version in order:
                job = {**pair, 'pair_id': pair['id'], 'id': pair['id'] + '_' + version, 'version': version}
                output = out / job['id']
                host, inp = hosts[version]['path'], inputs[job['input']]['path']
                if args.suite == 'steady':
                    command = [host, inp, job['preset'], str(job['speed']), str(args.seconds), str(output)]
                else:
                    mode = job['mode'] if job['mode'] in ('fresh', 'prewarm') else 'early_on'
                    command = [host, inp, job['preset'], str(job['A_seconds']), '.1', '1', mode, 'Playing', '0', str(output), str(job['lead_ms'])]
                jobs.append({**job, 'command': command})
        require(jobs, 'empty selection')
        required_matrix = not args.only and args.repeats == 3 and args.seconds == 30 and args.presets == ['candidate']
        save(out / 'EXPECTED.json', {'schema': 'performance-pairs-v1', 'suite': args.suite,
             'baseline_commit': OLD_COMMIT, 'baseline_source': baseline['baseline_source'],
             'candidate_source': candidate['source'], 'client_source_sha256': source_sha,
             'records': record_ids, 'hosts': hosts, 'driver': identity(__file__), 'inputs': inputs,
             'expected_programs': len(jobs), 'expected_pairs': len(pairs),
             'all_expected_ids': [job['id'] for job in jobs], 'jobs': jobs,
             'required_matrix': required_matrix, 'repeats': args.repeats, 'seconds': args.seconds,
             'only': args.only, 'order': 'odd repeat old/candidate; even repeat candidate/old',
             'cpu_formula': CPU_FORMULA, 'p95_formula': '(N-1)*0.95 linear interpolation; n=3 is a measured sample, not broad approval',
             'cold_target_p95_ms': 1000, 'warm_target_p95_ms': 250,
             'device_condition': {'rate': args.device_rate, 'buffer_frames': args.device_buffer},
             'callback_gate': False, 'quality_approval': False, 'realtime_approval': False,
             'formal_approval': False, 'independent_pcm': 'ROOT_SEPARATE_AUDIT', 'physical_audio': None, 'application_F': None})
        save(out / 'ENVIRONMENT_BEFORE.json', environment())
        previous_device = None
        for job in jobs:
            verify_frozen()
            row = {key: job[key] for key in ('id', 'stratum', 'pair_id', 'repeat', 'version', 'preset', 'input')}
            row['load_average_before'] = list(os.getloadavg())
            execution = execute(job['command'], out / (job['id'] + '.log'), args.timeout)
            row['execution'] = execution
            directory = out / job['id']
            summary_path, cost_path = directory / 'SUMMARY.json', directory / 'PROCESS_COST.json'
            try:
                summary = load(summary_path) if summary_path.exists() else {}
                cost = load(cost_path) if cost_path.exists() else {}
                result = assess(args.suite, job, summary, cost, execution, inputs[job['input']],
                                args.seconds, args.device_rate, args.device_buffer)
                device = summary.get('device')
                if device is not None:
                    if previous_device is None:
                        previous_device = device
                    elif previous_device != device:
                        result['errors'].append('audio device ID changed within comparison')
                        result['integrity_pass'] = False
                row.update(result, summary=summary, host_process_cost=cost)
            except (ValueError, TypeError, KeyError, OSError) as error:
                row.update(integrity_pass=False, rt_pass=False, errors=[str(error)], summary={}, host_process_cost={})
            row['artifacts'] = [identity(path) for path in sorted(directory.rglob('*')) if path.is_file()] if directory.exists() else []
            row['load_average_after'] = list(os.getloadavg())
            rows.append(row)
            save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_programs': len(jobs),
                                       'executed_programs': len(rows), 'all_expected_ids': [j['id'] for j in jobs], 'rows': rows})
            save(out / 'PROCESS_COST.json', {'schema': 'performance-process-cost-v1',
                 'note': 'whole_process_cpu_sは起動/初期prepare/先行準備/ON/後続周回/停止を含む。host内ON前後費用・steady窓とは別。',
                 'expected_programs': len(jobs), 'executed_programs': len(rows),
                 'rows': [{'id': r['id'], 'whole_process': r['execution'], 'host_on_cost': r['host_process_cost']} for r in rows],
                 'physical_audio': None})
            print(job['id'], execution['returncode'], 'integrity', row['integrity_pass'], 'RT', row['rt_pass'], flush=True)
            if execution['interrupted']:
                raise KeyboardInterrupt('native child interrupted; joined and accounted')
        verify_frozen()
        require(current_source_digest(candidate_root) == candidate['source'], 'candidate source changed during run')
        for inp in inputs.values():
            require(identity(inp['path'])['sha256'] == inp['sha256'], 'input changed during run')
        save(out / 'ENVIRONMENT_AFTER.json', environment())
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    complete = len(rows) == len(jobs) and bool(jobs) and not errors
    integrity = complete and all(row.get('integrity_pass') for row in rows)
    rt = complete and all(row.get('rt_pass') for row in rows)
    groups = aggregate(rows, jobs, args.suite, args.repeats)
    candidate_latency = (integrity and all(group['versions']['candidate']['latency_p95_pass'] for group in groups)) if args.suite == 'ab' else None
    # 旧版の既知期限未達を途中終了理由にせず、全pairを保存して候補の判定と分ける。
    final = {'schema': 'performance-pairs-v1', 'status': 'PASS' if integrity and rt and candidate_latency is not False else 'INCOMPLETE_OR_FAIL',
             'complete': complete, 'integrity_pass': integrity, 'rt_all_versions_pass': rt,
             'candidate_latency_p95_pass': candidate_latency, 'expected_programs': len(jobs),
             'executed_programs': len(rows), 'all_expected_ids': [job['id'] for job in jobs],
             'errors': errors, 'groups': groups, 'rows': rows, 'cpu_formula': CPU_FORMULA,
             'quality_approval': False, 'formal_approval': False, 'independent_pcm': 'ROOT_SEPARATE_AUDIT',
             'physical_audio': None, 'application_F': None}
    save(out / 'SUMMARY.json', final)
    return 0 if final['status'] == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
