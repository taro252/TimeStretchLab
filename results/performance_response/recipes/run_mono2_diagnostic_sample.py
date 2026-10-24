"""同一Steady本文の旧版/明示候補を各1回、own child PIDだけsampleする。
候補 --candidate-build と --source-sha と新規--output は必須。
固定mono48/2x/30秒、launch観測+10秒後にsample 5秒/1ms。
通常CPU比較と別集合。生stackをCPU秒へ換算せず、品質/RT/採用承認を行わない。
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import time

import build_frozen_client as frozen
import run_pairs as common
import run_seek_history as d3

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
SOURCE = 'tests/PerformanceSteadyNative.cpp'
# 候補sourceを明示CLIで固定する。
INPUT = ROOT / 'results/phase56/long/chain_300s.wav'
INPUT_SHA = '13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0'
SAMPLE = Path('/usr/bin/sample')
SCOPE = {
    'measurement_set': 'DIAGNOSTIC_SAMPLE_ONLY; never merged with normal steady48',
    'native_window_s': 30, 'preset': 'candidate', 'speed': 2,
    'sample_schedule': '10 seconds after this parent observes Popen launch; not an instrumented steady-window start',
    'steady_window_overlap': 'NOT_EXACTLY_INSTRUMENTED; native SUMMARY confirms its separate 30-second window',
    'sample_duration_s': 5, 'sample_interval_ms': 1,
    'stack_ratios_converted_to_process_CPU_seconds': False, 'old_stack_samples_compared': False,
    'sample_output_parsed_for_CPU_attribution': False, 'RT_failure_attributed_to_sampling': False,
    'raw_sample_semantic_validation': 'NOT_PERFORMED; root inspects raw stack output later',
    'normal_CPU_improvement_approval': False, 'quality_approval': False, 'realtime_approval': False,
    'public_approval': False, 'physical_audio': None, 'application_F': None}


class OwnedChild:
    """Popenで作った子だけをwait4/killpgする。reap後のPIDは操作しない。"""
    def __init__(self, command, log, role, version, registry):
        self.command, self.log, self.role, self.version = command, log, role, version
        self.spawn_begin = time.monotonic()
        self.stream = log.open('w')
        try:
            self.process = subprocess.Popen(command, stdout=self.stream, stderr=subprocess.STDOUT, start_new_session=True)
        except BaseException:
            self.stream.close()
            raise
        self.pid, self.reaped, self.usage = self.process.pid, False, None
        self.start = time.monotonic()
        self.exit_code, self.end, self.timeout, self.terminated = None, None, False, False
        registry.append(self)

    def poll(self, block=False):
        if self.reaped:
            return True
        while True:
            try:
                pid, status, usage = os.wait4(self.pid, 0 if block else os.WNOHANG)
                break
            except InterruptedError:
                if not block:
                    return False
        if not pid:
            return False
        self.reaped, self.usage = True, usage
        self.exit_code, self.end = os.waitstatus_to_exitcode(status), time.monotonic()
        self.process.returncode = self.exit_code
        self.stream.close()
        return True

    def stop_and_reap(self):
        if self.reaped:
            return
        self.terminated = True
        # 未reapのown child PID/PGIDだけ。sampleが終了する前に対象をreapしない。
        try:
            os.killpg(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.poll():
                return
            time.sleep(.05)
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.poll(block=True)

    def record(self):
        value = {'role': self.role, 'version': self.version, 'argv': self.command, 'pid': self.pid, 'process_group': self.pid,
                 'spawn_parent_pid': os.getpid(), 'started_monotonic_s': self.start, 'reap_observed_monotonic_s': self.end,
                 'spawn_call_begin_monotonic_s': self.spawn_begin, 'wall_origin': 'parent observed Popen return',
                 'returncode': self.exit_code, 'reaped': self.reaped, 'timeout': self.timeout, 'termination_requested_by_supervisor': self.terminated,
                 'wall_s': self.end - self.start if self.end is not None else None, 'log': common.identity(self.log)}
        value['wall_scope'] = 'Popen return to reap observation; target reap is deferred while sampler is active'
        if self.usage is not None:
            value.update(process_user_s=self.usage.ru_utime, process_system_s=self.usage.ru_stime,
                         whole_process_cpu_s=self.usage.ru_utime + self.usage.ru_stime,
                         max_rss_native_units=self.usage.ru_maxrss, max_rss_units='bytes on macOS',
                         voluntary_context_switches=self.usage.ru_nvcsw, involuntary_context_switches=self.usage.ru_nivcsw)
        return value


def collect(version, binary, out, registry, cancelled, timeout, publish):
    directory = out / version
    directory.mkdir()
    native_output = directory / 'native'
    command = [binary['path'], str(INPUT), 'candidate', '2', '30', str(native_output)]
    client, sampler = None, None
    sample_file = directory / 'sample.stacks.txt'
    sample_launch = None
    try:
        client = OwnedChild(command, directory / 'native.stdout-stderr.log', 'native_steady', version, registry)
        publish(f'{version}: native own child PID {client.pid} launched')
        while True:
            if cancelled['signal'] is not None:
                raise KeyboardInterrupt('signal ' + str(cancelled['signal']))
            now = time.monotonic()
            if sampler is not None and not sampler.reaped:
                # sampleがPIDへattachし終える前の対象終了/PID再利用を防ぐ。
                # sample終了まではclientをreapせず、zombieでもPIDを保持する。
                sampler.poll()
                if not sampler.reaped and now - sampler.start > 20:
                    sampler.timeout = True
                    sampler.stop_and_reap()
            else:
                client.poll()
            if client.reaped:
                break
            if sampler is None and now - client.start >= 10:
                common.require(not client.reaped and client in registry, 'sample target must be this own unreaped child')
                sample_command = [str(SAMPLE), str(client.pid), '5', '1', '-file', str(sample_file)]
                sampler = OwnedChild(sample_command, directory / 'sample.stdout-stderr.log', 'sample_tool', version, registry)
                sample_launch = sampler.start - client.start
                publish(f'{version}: sample own child PID {client.pid}, duration=5s interval=1ms')
            if now - client.start > timeout:
                client.timeout = True
                if sampler is not None and not sampler.reaped:
                    sampler.stop_and_reap()
                client.stop_and_reap()
                break
            time.sleep(.05)
    finally:
        # 対象PIDを保持するためsampler -> clientの順で停止・reapする。
        if sampler is not None:
            sampler.stop_and_reap()
        if client is not None:
            client.stop_and_reap()
    native_record = client.record()
    errors = []
    try:
        summary = common.load(native_output / 'SUMMARY.json') if (native_output / 'SUMMARY.json').exists() else {}
    except (OSError, ValueError) as error:
        summary = {}
        errors.append('native summary load: ' + str(error))
    execution = {**native_record, 'interrupted': False}
    try:
        info = common.wav_identity(INPUT, 48000, 1)
        assessed = common.assess('steady', {}, summary, {}, execution, info, 30, 48000, 512)
        errors.extend(assessed['errors'])
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        errors.append('native summary: ' + str(error))
    sample_record = sampler.record() if sampler is not None else None
    if sampler is None or sampler.exit_code != 0 or sampler.timeout:
        errors.append('sample did not complete normally')
    if not sample_file.is_file() or sample_file.stat().st_size == 0:
        errors.append('raw sample stack output missing/empty')
    if client.timeout or client.exit_code not in (0, 2) or not summary.get('complete'):
        errors.append('native incomplete/failure/timeout')
    return {'version': version, 'collection_status': 'COLLECTED' if not errors else 'INCOMPLETE_OR_FAIL',
            'errors': errors, 'native': native_record, 'sampler': sample_record, 'sample_launch_after_native_s': sample_launch,
            'raw_stack_file': common.identity(sample_file) if sample_file.is_file() else None,
            'native_summary': summary, 'native_summary_file': common.identity(native_output / 'SUMMARY.json') if summary else None,
            'RT_or_resource_audit_observed': summary.get('rt_pass'), 'RT_failure_cause': 'NOT_ATTRIBUTED',
            'scope': SCOPE}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-client', type=Path, default=BASE / 'frozen_clients_02/CLIENT.json')
    parser.add_argument('--candidate-build', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    common.require(common.finite(args.timeout) and 30 < args.timeout <= 300, 'finite process watchdog 30..300s')
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new diagnostic output belongs under build/')
    out.mkdir(parents=True, exist_ok=False)
    driver_log = (out / 'DRIVER.stdout.log').open('w')
    def publish(line):
        print(line, flush=True)
        driver_log.write(line + '\n')
        driver_log.flush()
    cancelled = {'signal': None}
    def cancel(signum, frame):
        # Popen作成中にも例外を投げず、registry登録後の通常loopで取消する。
        # 子へsignal maskを持ち越さず、作成と所有登録の間の取り逃しを防ぐ。
        if cancelled['signal'] is None:
            cancelled['signal'] = signum
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, cancel)
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    children, rows, errors, inventory, manifests = [], [], [], [], []
    frozen_after = None
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS Python required')
        common.require(not os.environ.get('DYLD_LIBRARY_PATH') and not os.environ.get('DYLD_INSERT_LIBRARIES'), 'ambient dynamic-library override')
        old_client, candidate = common.load(args.baseline_client), common.load(args.candidate_build)
        common.require(old_client['status'] == candidate['status'] == 'PASS' and old_client['contract_version'] == 3 and
                       old_client['baseline_source'] == frozen.OLD_SOURCE_SHA and old_client['baseline_commit'] == frozen.OLD_COMMIT, 'fixed 5674 v3 baseline')
        common.require(candidate['source'] == args.source_sha and len(args.source_sha) == 64 and candidate['configuration'] == 'Release' and candidate['architecture'] == 'arm64', 'explicit frozen Release arm64 candidate')
        common.require(common.identity(old_client['baseline_build_record']['path']) == old_client['baseline_build_record'], 'old BUILD SHA')
        old_build = common.load(Path(old_client['baseline_build_record']['path']))
        old = old_client['clients']['steady']
        candidate_root = Path(candidate['source_root']).resolve()
        map_new = {x['path']: x['sha256'] for x in candidate['source_manifest']['files']}
        common.require(old['source_relative'] == SOURCE and old['source']['sha256'] == old['copied_source']['sha256'] == map_new[SOURCE], 'same PerformanceSteadyNative source required')
        common.require(common.identity(old['copied_source']['path']) == old['copied_source'], 'frozen common client copy')
        shutil.copyfile(old['copied_source']['path'], out / 'common_client.cpp')
        build_dir = Path(candidate['binaries']['performance_steady_native']['path']).resolve().parent
        link_path = build_dir / 'CMakeFiles/performance_steady_native.dir/link.txt'
        flags_path = build_dir / 'CMakeFiles/performance_steady_native.dir/flags.make'
        object_path = build_dir / 'CMakeFiles/performance_steady_native.dir/tests/PerformanceSteadyNative.cpp.o'
        dep_path = object_path.with_suffix('.o.d')
        link = shlex.split(link_path.read_text())
        new_dependencies = []
        for token in frozen.make_dependencies(dep_path):
            path = (build_dir / token).resolve()
            item = common.identity(path)
            if path.is_relative_to(candidate_root):
                relative = str(path.relative_to(candidate_root))
                common.require(map_new.get(relative) == item['sha256'], 'candidate source/header SHA')
                item.update(origin='candidate_source_manifest', source_path=relative)
            else:
                common.require(not path.is_relative_to(Path(old_build['source_root']).resolve()), 'old header leaked into candidate')
                item['origin'] = 'toolchain_or_system'
            new_dependencies.append(item)
        common.require(any(x.get('source_path') == SOURCE for x in new_dependencies), 'candidate client dependency absent')
        libraries = [common.identity(build_dir / token) for token in link[1:] if token.endswith(('.a', '.dylib'))]
        common.require(len(libraries) == 10 and sum(x['path'].endswith('.a') for x in libraries) == 9, 'candidate 9 archives + heap probe')
        common.require(set(old_client['link_inputs']) == set(frozen.OLD_LINK_SHA), 'old link-input set')
        for name, item in old_client['link_inputs'].items():
            common.require(common.identity(item['path']) == item and item['sha256'] == frozen.OLD_LINK_SHA[name], 'old archive/probe SHA')
        identities = {}
        def add(item, role):
            value = {k: item[k] for k in ('path', 'bytes', 'sha256')}
            if value['path'] in identities:
                common.require(identities[value['path']]['identity'] == value, 'contradictory frozen SHA')
                identities[value['path']]['roles'].append(role)
            else:
                identities[value['path']] = {'identity': value, 'roles': [role]}
        for p in (args.baseline_client, args.candidate_build, Path(old_client['baseline_build_record']['path']), SAMPLE,
                  link_path, flags_path, object_path, dep_path, candidate_root / SOURCE, out / 'common_client.cpp', Path(__file__),
                  Path(frozen.__file__), Path(common.__file__), Path(d3.__file__)):
            add(common.identity(p), 'record/tool/source/helper')
        for key in ('copied_source', 'object', 'depfile', 'undefined_symbols', 'binary'):
            add(old[key], 'frozen_old_client:' + key)
        for key in ('compiler', 'flags_file', 'link_template', 'driver'):
            add(old_client[key], 'frozen_old_build:' + key)
        add(candidate['binaries']['performance_steady_native'], 'candidate_binary')
        for item in old['dependencies'] + list(old_client['link_inputs'].values()) + new_dependencies + libraries:
            add(item, 'dependency_or_library')
        info = common.wav_identity(INPUT, 48000, 1)
        common.require(info['sha256'] == INPUT_SHA, 'fixed mono48 chain300 input SHA')
        add(info, 'input')
        inventory = list(identities.values())
        common.save(out / 'COMPILE_INVENTORY.json', {'files': inventory, 'sha256': common.manifest_digest(inventory)})
        d3.verify_inventory(inventory, out / 'FROZEN_BEFORE.json')
        for label, build in (('old', old_build), ('candidate', candidate)):
            root = Path(build['source_root']).resolve()
            common.require(common.manifest_digest(build['source_manifest']['files']) == build['source'] == build['source_manifest']['sha256'] and
                           common.current_source_digest(root) == build['source'], label + ' source is not frozen')
            manifests.append({'version': label, 'root': str(root), 'sha256': build['source']})
        binaries = {'old': old['binary'], 'candidate': candidate['binaries']['performance_steady_native']}
        for version, binary in binaries.items():
            result = subprocess.run(['/usr/bin/lipo', '-archs', binary['path']], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
            (out / (version + '.architecture.log')).write_text(result.stdout)
            common.require(result.returncode == 0 and result.stdout.split() == ['arm64'], 'native arm64 binary required')
        common.save(out / 'ENVIRONMENT_BEFORE.json', common.environment())
        device = d3.output_device()
        common.require(device['buffer_frames'] == 512, 'fixed 512-frame default output buffer')
        common.save(out / 'DEVICE_BEFORE.json', device)
        common.save(out / 'EXPECTED.json', {'schema': 'performance-diagnostic-sample-v1', 'created_utc': started,
            'scope': SCOPE, 'input': info, 'common_client': common.identity(out / 'common_client.cpp'),
            'baseline_client': common.identity(args.baseline_client), 'candidate_build': common.identity(args.candidate_build),
            'source_manifests': manifests, 'binaries': binaries, 'order': ['old', 'candidate'], 'expected_native_programs': 2,
            'expected_sample_programs': 2, 'sample_binary': common.identity(SAMPLE), 'sample_target': 'PID from own Popen only; no supplied/discovered external PID',
            'sample_target_PID_retained_until_sampler_reaped': True, 'timeout_s': args.timeout,
            'old_compile_command': old['compile_command'], 'old_link_command': old['link_command'],
            'candidate_link_command': link, 'candidate_compile_flags': frozen.flags_from_make(flags_path),
            'libraries': {'old': list(old_client['link_inputs'].values()), 'candidate': libraries},
            'source_freeze_scope': 'src/tests/scripts/CMake; docs/results/build additions allowed'})
        for version in ('old', 'candidate'):
            if cancelled['signal'] is not None:
                raise KeyboardInterrupt('signal ' + str(cancelled['signal']))
            common.require(d3.output_device() == device, 'default output device changed before launch')
            common.require(common.identity(binaries[version]['path']) == binaries[version], 'binary changed before launch')
            try:
                row = collect(version, binaries[version], out, children, cancelled, args.timeout, publish)
            except Exception as error:
                row = {'version': version, 'collection_status': 'INCOMPLETE_OR_FAIL',
                       'errors': [type(error).__name__ + ': ' + str(error)], 'scope': SCOPE,
                       'RT_or_resource_audit_observed': None,
                       'owned_children': [c.record() for c in children if c.version == version]}
            rows.append(row)
            common.save(out / 'COLLECTION_PROGRESS.json', {'scope': SCOPE, 'rows': rows, 'children': [c.record() for c in children]})
            publish(version + ': ' + row['collection_status'] + '; native RT/resource audit=' + str(row['RT_or_resource_audit_observed']))
        common.require(d3.output_device() == device, 'default output device changed during collection')
        common.save(out / 'DEVICE_AFTER.json', d3.output_device())
    except BaseException as error:
        errors.append(type(error).__name__ + ': ' + str(error))
    finally:
        # reverse creation order always reaps sample before its target native.
        for child in reversed(children):
            try:
                child.stop_and_reap()
            except BaseException as error:
                errors.append('cleanup: ' + type(error).__name__ + ': ' + str(error))
        if inventory:
            try:
                frozen_after = d3.verify_inventory(inventory, out / 'FROZEN_AFTER.json')
                for item in manifests:
                    common.require(common.current_source_digest(Path(item['root'])) == item['sha256'], item['version'] + ' source changed')
            except BaseException as error:
                errors.append('final frozen audit: ' + type(error).__name__ + ': ' + str(error))
        try:
            common.save(out / 'ENVIRONMENT_AFTER.json', common.environment())
        except BaseException as error:
            errors.append('environment: ' + str(error))
    reaped = all(c.reaped for c in children)
    complete = len(rows) == 2 and [r['version'] for r in rows] == ['old', 'candidate'] and all(r['collection_status'] == 'COLLECTED' for r in rows)
    collected = complete and reaped and not errors and cancelled['signal'] is None and frozen_after is not None
    common.save(out / 'CHILDREN.json', {'created_only_by_this_process': True, 'parent_pid': os.getpid(),
                'all_reaped': reaped, 'cancel_signal': cancelled['signal'], 'children': [c.record() for c in children]})
    result = {'schema': 'performance-diagnostic-sample-v1', 'status': 'COLLECTED' if collected else 'INCOMPLETE_OR_FAIL',
              'scope': SCOPE, 'expected_native_programs': 2, 'completed_rows': len(rows),
              'native_programs_launched': sum(c.role == 'native_steady' for c in children),
              'sample_programs_launched': sum(c.role == 'sample_tool' for c in children),
              'all_children_reaped': reaped, 'cancel_signal': cancelled['signal'], 'errors': errors, 'rows': rows,
              'stack_CPU_seconds_estimated': False, 'cross_version_stack_comparison': 'NOT_PERFORMED',
              'RT_failures': 'preserved in native summaries; cause NOT_ATTRIBUTED',
              'normal_CPU_improvement_approval': False, 'quality_approval': False, 'realtime_approval': False, 'public_approval': False}
    common.save(out / 'SUMMARY.json', result)
    publish(str(out / 'SUMMARY.json') + ': ' + result['status'])
    driver_log.close()
    files = [common.identity(p) for p in sorted(out.rglob('*')) if p.is_file() and p != out / 'ARTIFACTS.json']
    common.save(out / 'ARTIFACTS.json', {'files': files, 'raw_sample_only': True})
    return 0 if collected else 2


if __name__ == '__main__':
    sys.exit(main())
