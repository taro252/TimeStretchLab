"""fresh ABの本試験: 48k Float32 mono/stereo、A30/270、.4/1/2、n3、旧新交互=72実行。

通常計測。独立PCM監査、RT、1000ms目標を別に保存する。入力は300秒、解析完了、
PlayingかつC<A。先行準備・warm・44.1k Interactiveの集合とは混ぜない。
音声試験やbuildと重ねない。既存run_pairsの凍結client・監査関数だけを再利用する。
"""
import argparse
import datetime
import os
from pathlib import Path
import platform
import sys
# BOUNDED_INSERT_BEGIN imports
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
# BOUNDED_INSERT_END imports

import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
# BOUNDED_INSERT_BEGIN implementation

# 同じ72 childの間だけ保守する。測定本体の行は挿入除去で全byte復元できる。
ORIGINAL_SHA = 'ad036a5f14c1ed0bac26c7a3111c197e27bbe0bfd11fdef357f5d5ad1f3e790e'
PREFIX_HELPER_SHA = 'e8a8cfe999117b280ccdc4c3e9e751309aef9dfd84e0fa69f9dc374b35bf831b'
INSERT_NAMES = ('imports', 'implementation', 'setup', 'before_child', 'between_batches', 'final_result')
MIB = 1024 * 1024
BASE = ROOT / 'build/performance_response_20261023_01'


class BoundedStorageBlocked(RuntimeError):
    pass


class BoundedMaintenance:
    def __init__(self, out, driver):
        self.out, self.driver = out, driver
        self.original = Path(__file__).with_name('run_ab_main_pairs.py')
        self.helper = Path(__file__).with_name('share_capture_prefixes.py')
        self.self_identity = common.identity(driver)
        self.pins = [(self.original, ORIGINAL_SHA), (self.helper, PREFIX_HELPER_SHA)]
        self.operations, self.space_checks = [], []
        self.verify_sources()
        data = Path(driver).read_bytes()
        names = tuple(x.decode() for x in re.findall(rb'(?m)^[ \t]*# BOUNDED_INSERT_BEGIN ([a-z_]+)\n', data))
        restored = re.sub(rb'(?ms)^[ \t]*# BOUNDED_INSERT_BEGIN [a-z_]+\n.*?^[ \t]*# BOUNDED_INSERT_END [a-z_]+\n', b'', data)
        common.require(names == INSERT_NAMES and restored == self.original.read_bytes(), 'bounded reverse reconstruction differs from complete original body')
        common.require(out.is_relative_to(BASE), 'prefix helper accepts this B only')
        self.provenance = {'original': common.identity(self.original), 'prefix_helper': common.identity(self.helper),
                           'derived': self.self_identity, 'insertions': list(names), 'reverse_original_body_bytes_identical': True,
                           'reverse_original_sha256': hashlib.sha256(restored).hexdigest()}
        self.plan = {'schema': 'ab-bounded-maintenance-v1', 'after_completed_jobs': [24, 48], 'fixed_programs': 72,
                     'managed_queue_exclusive_required': True, 'native_child_wait4_collected_before_maintenance': True,
                     'roots': [str(out)], 'roots_scope': 'this fresh run only; completed children, future job folders absent',
                     'capacity_rule': 'max(512MiB, largest completed raw/output *2 +16MiB +largest input +256MiB) on output volume; native input +256MiB on every configured temp volume',
                     'scope': 'normal-thread evidence storage only, outside native child wait4/process/Ready/CPU windows',
                     'native_aggregate_statistics_unchanged': True, 'extra_native_trials': 0,
                     'PCM_bytes_paths_and_full_SHA_preserved': True, 'old_evidence_roots_modified': False}
        self.save()

    def verify_sources(self):
        common.require(common.identity(self.driver) == self.self_identity, 'bounded driver changed')
        for path, expected in self.pins:
            common.require(common.identity(path)['sha256'] == expected, 'pinned original/prefix helper changed: '+str(path))

    def save(self):
        common.save(self.out / 'BOUNDED_STORAGE.json', {'plan': self.plan, 'provenance': self.provenance,
                    'space_checks': self.space_checks, 'operations': self.operations})

    def capacity(self, inputs, stage, largest=0):
        largest_input = max(x['bytes'] for x in inputs.values())
        native = largest_input + 256 * MIB
        temporary = 2 * largest + 16 * MIB if largest else 0
        paths = {str(Path(tempfile.gettempdir()).resolve()), str(Path('/tmp').resolve())}
        for name in ('TMPDIR', 'TMP', 'TEMP', 'TEMPDIR'):
            if os.environ.get(name):
                path = Path(os.environ[name]).resolve()
                common.require(path.is_dir(), 'configured native temp directory unavailable: '+name)
                paths.add(str(path))
        table = [{'role': 'output', 'path': str(self.out), 'free_bytes': shutil.disk_usage(self.out).free,
                  'required_bytes': max(512 * MIB, native + temporary)}]
        table += [{'role': 'native_temp', 'path': path, 'free_bytes': shutil.disk_usage(path).free,
                   'required_bytes': native} for path in sorted(paths)]
        check = {'stage': stage, 'largest_completed_PCM_bytes': largest, 'largest_input_bytes': largest_input,
                 'native_input_reserve_bytes': 256 * MIB, 'maintenance_extra_bytes': temporary,
                 'checks': table, 'pass': all(x['free_bytes'] >= x['required_bytes'] for x in table)}
        self.space_checks.append(check)
        self.save()
        if not check['pass']:
            raise BoundedStorageBlocked('fixed native/output/maintenance free-space guard: '+stage)

    def no_native_process(self, hosts):
        # args文字列を検索しない。read-only shellのrecipe名等をnativeと誤認しない。
        result = subprocess.run(['/bin/ps', '-axo', 'pid=,comm='], capture_output=True, text=True, timeout=30)
        common.require(result.returncode == 0 and not result.stderr.strip(), 'cannot establish process quiescence')
        wanted = {Path(x['path']).name for x in hosts.values()}
        conflicts = []
        for line in result.stdout.splitlines():
            fields = line.strip().split(None, 1)
            common.require(len(fields) == 2 and fields[0].isdigit(), 'unexpected ps comm row')
            pid, comm = int(fields[0]), fields[1]
            name = Path(comm).name
            managed = comm.startswith(str(ROOT / 'build') + '/') or name in wanted
            native = ('native' in name.lower() or name.startswith(('paused_speed_', 'performance_')))
            if pid != os.getpid() and (managed or native):
                conflicts.append({'pid': pid, 'comm': comm})
        common.require(not conflicts, 'managed/native executable still running: '+json.dumps(conflicts))
        return {'method': 'ps pid+comm; no command-argument matching', 'managed_native_conflicts': conflicts,
                'limitation': 'requires exclusive parent queue; not a physical audio silence measurement'}

    @staticmethod
    def no_open_files(paths):
        for at in range(0, len(paths), 64):
            result = subprocess.run(['/usr/sbin/lsof', '-t', '--', *map(str, paths[at:at+64])],
                                    capture_output=True, text=True, timeout=30)
            common.require(result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip(),
                           'open descriptor or lsof cannot establish quiescence')

    def after_batch(self, jobs, rows, inputs, hosts):
        completed = len(rows)
        common.require(completed in (24, 48) and [x['id'] for x in rows] == [x['id'] for x in jobs[:completed]], 'completed prefix/order changed')
        common.require(all(type(x['execution']['returncode']) is int for x in rows), 'child not wait4 collected')
        self.verify_sources()
        artifacts = {x['path']: x for row in rows for x in row['artifacts']}
        expected_dirs = {x['id'] for x in rows}
        for path in self.out.iterdir():
            if path.is_dir():
                common.require(path.name in expected_dirs, 'unexpected/future job directory in storage roots')
        for path, expected in artifacts.items():
            common.require(common.identity(path) == expected, 'completed artifact changed before maintenance')
        files = [Path(x) for x in artifacts]
        pcm = [Path(x) for x in artifacts if Path(x).name in ('raw.f32', 'output_before_gain.f32')]
        largest = max((x.stat().st_size for x in pcm), default=0)
        self.capacity(inputs, 'before_maintenance_'+str(completed), largest)
        process_check = self.no_native_process(hosts)
        self.no_open_files(files)
        tag = 'MAINTENANCE_after_'+str(completed).zfill(2)
        qpath, result_path, log = (self.out / (tag+suffix) for suffix in ('_QUIESCENCE.json', '_RESULT.json', '.log'))
        common.require(not any(x.exists() for x in (qpath, result_path, log)), 'maintenance output already exists')
        quiescence = {'status': 'WRITERS_QUIESCENT', 'native_measurement_in_progress': False,
                      'roots': [str(self.out)], 'completed_job_ids': [x['id'] for x in rows],
                      'remaining_expected_ids': [x['id'] for x in jobs[completed:]],
                      'wait4_collected_children': completed, 'normal_thread_exclusive_queue': True,
                      'all_completed_artifacts_lsof': 'NONE; completed without warnings', 'process_check': process_check,
                      'scope': 'all writers of this run retired/reaped; no future child starts until maintenance returns'}
        common.save(qpath, quiescence)
        command = [sys.executable, '-B', str(self.helper), '--roots', str(self.out), '--output', str(result_path), '--quiescence-record', str(qpath)]
        operation = {'after_completed_jobs': completed, 'status': 'IN_PROGRESS', 'command': command,
                     'quiescence': common.identity(qpath), 'largest_completed_PCM_bytes': largest,
                     'time_scope': 'maintenance only; excluded from each child wait4 and native PROCESS_COST/Ready/CPU'}
        self.operations.append(operation)
        self.save()
        begin = time.monotonic()
        try:
            execution = common.execute(command, log, 900)
            operation.update(execution=execution, wall_s=time.monotonic()-begin, log=execution['log'])
            common.require(not execution['timeout'] and not execution['interrupted'] and execution['returncode'] == 0,
                           'prefix storage helper failed/timeout; native results unchanged')
            audit = common.load(result_path)
            common.require(audit['status'] == 'PASS' and audit['driver']['sha256'] == PREFIX_HELPER_SHA and
                           audit['roots'] == [str(self.out)] and audit['quiescence'] == common.identity(qpath), 'prefix maintenance audit mismatch')
            for path, expected in artifacts.items():
                common.require(common.identity(path) == expected, 'completed bytes/path/SHA changed after maintenance')
            self.no_open_files(files)
            self.no_native_process(hosts)
            self.verify_sources()
            operation.update(status='PASS', result=common.identity(result_path), completed_artifact_count=len(artifacts),
                             every_original_artifact_SHA_identical=True)
            self.capacity(inputs, 'after_maintenance_'+str(completed), largest)
        except BaseException as error:
            operation.update(status='BLOCKED' if isinstance(error, BoundedStorageBlocked) else 'FAIL_SAFE',
                             error=type(error).__name__+': '+str(error), wall_s=time.monotonic()-begin)
            raise
        finally:
            self.save()

# BOUNDED_INSERT_END implementation


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-client', type=Path, required=True)
    p.add_argument('--candidate-build', type=Path, required=True)
    p.add_argument('--observation-clients', type=Path,
                   help='同一の有限180秒記録領域だけを拡張した旧新client manifest')
    p.add_argument('--mono-input', type=Path, required=True)
    p.add_argument('--stereo-input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    out = a.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'large evidence belongs under build/')
    out.mkdir(parents=True, exist_ok=False)
    rows, jobs, errors = [], [], []
    record = {'schema': 'performance-ab-main-v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'driver': common.identity(__file__), 'helper': common.identity(common.__file__),
              'expected_programs': 72, 'expected_pairs': 36, 'preset': 'candidate',
              'cold_target_p95_ms': 1000, 'serial_audio': True, 'callback_gate': False,
              'independent_pcm': 'SEPARATE_AUDIT_REQUIRED', 'physical_audio': None,
              'application_F': None, 'formal_approval': False}
    try:
        # BOUNDED_INSERT_BEGIN setup
        bounded = BoundedMaintenance(out, __file__)
        record.update(bounded_maintenance_plan=bounded.plan, bounded_derivation=bounded.provenance)
        # BOUNDED_INSERT_END setup
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'arm64 macOS required')
        common.require(not any(os.environ.get(k) for k in ('DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'CPATH', 'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH')), 'ambient library override')
        old, new = common.load(a.baseline_client), common.load(a.candidate_build)
        common.require(old['status'] == new['status'] == 'PASS', 'build status')
        common.require(old['schema'] == 'performance-frozen-client-v1' and old['contract_version'] == 3 and old['baseline_commit'] == common.OLD_COMMIT, 'old provenance')
        common.require(new['architecture'] == 'arm64' and new['configuration'] == 'Release', 'candidate Release arm64')
        common.require(common.manifest_digest(new['source_manifest']['files']) == new['source'] == new['source_manifest']['sha256'], 'manifest contents')
        root = Path(new['source_root'])
        common.require(common.current_source_digest(root) == new['source'], 'candidate source changed')
        client = old['clients']['ab']
        source_map = {x['path']: x['sha256'] for x in new['source_manifest']['files']}
        common.require(client['source_relative'] == common.SOURCE['ab'] and client['contract_version'] == 3, 'client identity')
        common.require(source_map[common.SOURCE['ab']] == client['source']['sha256'] == client['copied_source']['sha256'], 'same client source')
        hosts = {'old': client['binary'], 'candidate': new['binaries'][common.TARGET['ab']]}
        extra_inventory = []
        if a.observation_clients:
            obs = common.load(a.observation_clients)
            common.require(obs['schema'] == 'performance-ab-observation-clients-v1' and obs['status'] == 'PASS', 'observation client build')
            common.require(set(obs['clients']) == {'old', 'candidate'}, 'both observation clients required')
            for version, source, contract in (('old', old['baseline_source'], 3), ('candidate', new['source'], 4)):
                item = obs['clients'][version]
                common.require(item['source'] == source and item['contract_version'] == contract, 'observation ABI/source')
                hosts[version] = item['binary']
            extra_inventory = [common.identity(a.observation_clients), obs['common_client'], obs['common_capture_source']]
            for item in obs['clients'].values():
                extra_inventory.extend(item['libraries'])
            record['observation_clients'] = common.identity(a.observation_clients)
            record['observation_scope'] = '180 seconds / 65536 records, same preallocated host-only capture for old and candidate; product deadline/resources unchanged'
        inputs = {'mono48': common.wav_identity(a.mono_input, 48000, 1), 'stereo48': common.wav_identity(a.stereo_input, 48000, 2)}
        ids = {'baseline_client': common.identity(a.baseline_client), 'candidate_build': common.identity(a.candidate_build)}
        def frozen():
            for path, expected in ((a.baseline_client, ids['baseline_client']), (a.candidate_build, ids['candidate_build'])):
                common.require(common.identity(path) == expected, 'record changed')
            for x in [*hosts.values(), *old['link_inputs'].values(), client['copied_source'], *extra_inventory]:
                common.require(common.identity(x['path']) == x, 'binary/library/client changed')
        frozen()
        for repeat in range(1, 4):
            for label in inputs:
                for at in (30, 270):
                    for speed in (40, 100, 200):
                        layer = f'{label}_A{at}_s{speed:03d}_candidate'
                        pair = f'{layer}_r{repeat:02d}'
                        for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
                            name = pair + '_' + version
                            job = {'id': name, 'pair_id': pair, 'stratum': layer, 'repeat': repeat, 'version': version,
                                   'preset': 'candidate', 'input': label, 'A_seconds': at, 'speed': speed / 100,
                                   'mode': 'fresh', 'lead_ms': 0}
                            job['command'] = [hosts[version]['path'], inputs[label]['path'], 'candidate', str(at), '.1', str(speed / 100), 'fresh', 'Playing', '0', str(out / name), '0']
                            jobs.append(job)
        common.require(len(jobs) == 72 and len({x['id'] for x in jobs}) == 72, 'fixed expected set')
        record.update(baseline_commit=common.OLD_COMMIT, baseline_source=old['baseline_source'], candidate_source=new['source'],
                      records=ids, hosts=hosts, inputs=inputs, jobs=jobs, all_expected_ids=[x['id'] for x in jobs],
                      process_timeout_s=180, prepare_timeout='native unchanged', p95_formula='(N-1)*.95 linear interpolation',
                      scope='native accepted to first A PCM; no UI/service/HAL/physical time substitution')
        common.save(out / 'EXPECTED.json', record)
        common.save(out / 'ENVIRONMENT_BEFORE.json', common.environment())
        device = None
        for job in jobs:
            frozen()
            # BOUNDED_INSERT_BEGIN before_child
            bounded.verify_sources()
            bounded.capacity(inputs, 'before_child_'+str(len(rows)+1))
            # BOUNDED_INSERT_END before_child
            execution = common.execute(job['command'], out / (job['id'] + '.log'), 180)
            directory = out / job['id']
            row = {**job, 'execution': execution}
            try:
                s = common.load(directory / 'SUMMARY.json')
                cost = common.load(directory / 'PROCESS_COST.json')
                row.update(common.assess('ab', job, s, cost, execution, inputs[job['input']], 30, 48000, 512), summary=s, host_process_cost=cost)
                common.require(s.get('channels') == inputs[job['input']]['channels'], 'actual channel count')
                if device is None:
                    device = s['device']
                common.require(s['device'] == device, 'device changed within comparison')
            except (ValueError, TypeError, KeyError, OSError, RuntimeError) as e:
                row.update(integrity_pass=False, rt_pass=False, errors=[str(e)], summary=row.get('summary', {}), host_process_cost=row.get('host_process_cost', {}))
            row['artifacts'] = [common.identity(x) for x in sorted(directory.rglob('*')) if x.is_file()] if directory.exists() else []
            rows.append(row)
            common.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_programs': 72, 'executed_programs': len(rows), 'rows': rows})
            print(job['id'], execution['returncode'], 'integrity', row['integrity_pass'], 'RT', row['rt_pass'], flush=True)
            if execution['interrupted']:
                raise KeyboardInterrupt('native child interrupted and collected')
            # BOUNDED_INSERT_BEGIN between_batches
            if len(rows) in (24, 48):
                bounded.after_batch(jobs, rows, inputs, hosts)
            # BOUNDED_INSERT_END between_batches
        frozen()
        common.require(common.current_source_digest(root) == new['source'], 'source changed during run')
        for x in inputs.values():
            common.require(common.identity(x['path'])['sha256'] == x['sha256'], 'input changed')
        common.save(out / 'ENVIRONMENT_AFTER.json', common.environment())
    except BaseException as e:
        errors.append(type(e).__name__ + ': ' + str(e))
    complete = len(rows) == 72 and not errors
    integrity = complete and all(x.get('integrity_pass') for x in rows)
    groups = common.aggregate(rows, jobs, 'ab', 3)
    candidate_rt = complete and all(x.get('rt_pass') for x in rows if x['version'] == 'candidate')
    candidate_latency = integrity and all(g['versions']['candidate']['latency_p95_pass'] for g in groups)
    result = {**record, 'status': 'PASS' if integrity and candidate_rt and candidate_latency else 'INCOMPLETE_OR_FAIL',
              'complete': complete, 'integrity_pass': integrity, 'candidate_rt_pass': candidate_rt,
              'candidate_latency_p95_pass': candidate_latency, 'executed_programs': len(rows), 'rows': rows,
              'groups': groups, 'errors': errors, 'independent_pcm': 'SEPARATE_AUDIT_REQUIRED'}
    # BOUNDED_INSERT_BEGIN final_result
    try:
        if 'bounded' in locals():
            bounded.verify_sources()
    except BaseException as error:
        errors.append(type(error).__name__+': '+str(error))
        result.update(status='INCOMPLETE_OR_FAIL', complete=False, integrity_pass=False,
                      candidate_rt_pass=False, candidate_latency_p95_pass=False)
    storage_blocked = any(x.startswith('BoundedStorageBlocked:') for x in errors)
    result.update(bounded_storage_status='BLOCKED' if storage_blocked else ('COMPLETE' if complete and not errors else 'INCOMPLETE'),
                  remaining_expected_ids=[x['id'] for x in jobs[len(rows):]],
                  completed_native_programs_preserved=len(rows), new_native_programs_added_by_maintenance=0,
                  maintenance_scope='outside all native child windows; no PCM/threshold/ID changes')
    if 'bounded' in locals():
        result.update(bounded_storage_record=common.identity(out / 'BOUNDED_STORAGE.json'),
                      maintenance_operations=bounded.operations)
    # BOUNDED_INSERT_END final_result
    common.save(out / 'SUMMARY.json', result)
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
