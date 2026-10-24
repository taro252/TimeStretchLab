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

import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]


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
    common.save(out / 'SUMMARY.json', result)
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    sys.exit(main())
