"""同じArmed本文を固定5674 v3/final03 bfa v4へcompile/linkする。音声実行なし。

/usr/local/bin/python3 results/performance_response/recipes/build_armed_wait_clients.py \
  --output build/performance_response_20261023_01/armed_wait_clients_01
既定n3旧新6program/48checks。--repeats 1は探索2program/16checks。
runnerでもn3の保存clientから--repeats 1を選べる。CPU窓20秒/child timeout150秒。
旧9archive/probeの既知SHAと候補final_archive_03を照合する。
製品/既存recipe/CMakeへ書かず、新規build出力だけにcompileする。
"""
import argparse
import datetime
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

import build_frozen_client as frozen
import build_seek_history_client as shared
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
SOURCE = Path(__file__).with_name('armed_wait_native.cpp')
INPUT_SHA = '13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0'


CANDIDATE_SOURCE = 'bfa05533e0d5bef0f5543a09a40e5ee181111bf4e557ca066310ef8f779c7688'
CANDIDATE_BUILD_SHA = 'cf6e70aa6c9cf2c416d99286c03d3aef7b8ae01769c64b87647bf2921119ecde'
BASELINE_CLIENT_SHA = '45eca7d30805baea514d79eb2291ed359c2daa17f5c83d4269fea830a4447087'
CLIENT_SOURCE_SHA = 'd63fb6065be717ff878b7c5024f7d0182d9e33850e4c1fb90e620784f31fdfdc'
CHECK_IDS = (
    'D3A01_chain300_final_Ready', 'D3A02_first_A_PCM_and_old_join',
    'D3A03_accepted_075_identity', 'D3A04_fixed_B_Armed_precondition',
    'D3A05_full_20s_Armed_CPU_window', 'D3A06_B_adopts_075_PCM_and_old_join',
    'D3A07_Stop_terminal_and_owner_release', 'D3A08_callback_allocation_and_supply')


def jobs_for(client, out, repeats):
    common.require(repeats in (1, 3), 'exploratory n1 or descriptive n3 only')
    jobs = []
    for repeat in range(1, repeats + 1):
        pair = f'Armed20_{client["preset"]}_r{repeat:02d}'
        for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
            entry, key = client['clients'][version], pair + '_' + version
            jobs.append({'id': key, 'pair_id': pair, 'repeat': repeat, 'version': version,
                'preset': client['preset'], 'checks': 8, 'check_ids': list(CHECK_IDS),
                'command': [entry['binary']['path'], client['input']['path'], client['preset'], '20',
                            str(out / key), entry['source'], version]})
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-client', type=Path, default=BASE / 'frozen_clients_02/CLIENT.json')
    parser.add_argument('--candidate-build', type=Path, default=BASE / 'build_final_03/BUILD.json')
    parser.add_argument('--candidate-archive', type=Path, default=BASE / 'final_archive_03/ARCHIVE.json')
    parser.add_argument('--repeats', type=int, choices=(1, 3), default=3)
    parser.add_argument('--input', type=Path, default=ROOT / 'results/phase56/long/chain_300s.wav')
    parser.add_argument('--preset', choices=('candidate', 'baseline'), default='candidate')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'generated clients belong under build/')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'performance-armed-wait-clients-v1', 'status': 'INCOMPLETE', 'compile_only': True,
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'driver': common.identity(__file__), 'helpers': [common.identity(m.__file__) for m in (frozen, shared, common)],
              'clients': {}, 'commands': []}
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS Python required')
        common.require(not any(os.environ.get(k) for k in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH',
                       'OBJC_INCLUDE_PATH', 'LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES')), 'ambient include/library override')
        common.require(common.identity(args.baseline_client)['sha256'] == BASELINE_CLIENT_SHA, 'fixed frozen_clients_02 record required')
        common.require(common.identity(args.candidate_build)['sha256'] == CANDIDATE_BUILD_SHA, 'fixed final03 BUILD record required')
        baseline = common.load(args.baseline_client)
        candidate = common.load(args.candidate_build)
        archive = common.load(args.candidate_archive)
        common.require(candidate['source'] == CANDIDATE_SOURCE and archive['source'] == CANDIDATE_SOURCE, 'fixed bfa final03 source')
        common.require(archive['build'] == common.identity(args.candidate_build), 'archive/build identity')
        common.require(archive.get('product_src_all_identical') is True and len(archive['files']) == 54, 'final03 archive contract')
        archive_files = {}
        for row in archive['files']:
            original, archived = row['original'], row['archived']
            common.require(original['bytes'] == archived['bytes'] and original['sha256'] == archived['sha256'], 'archive original/copy identity')
            common.require(original['path'] not in archive_files, 'duplicate archive original')
            archive_files[original['path']] = row
        used_archives = []
        def archive_match(item):
            row = archive_files.get(item['path'])
            common.require(row is not None and row['original'] == item, 'candidate link/anchor absent from final archive: ' + item['path'])
            common.require(common.identity(row['archived']['path']) == row['archived'], 'candidate archived bytes changed')
            if row not in used_archives:
                used_archives.append(row)

        common.require(baseline['schema'] == 'performance-frozen-client-v1' and baseline['status'] == candidate['status'] == 'PASS', 'PASS build records required')
        common.require(baseline['baseline_commit'] == frozen.OLD_COMMIT and baseline['baseline_source'] == frozen.OLD_SOURCE_SHA and baseline['contract_version'] == 3, 'fixed 5674 v3 baseline required')
        common.require(common.identity(baseline['baseline_build_record']['path']) == baseline['baseline_build_record'], 'baseline BUILD changed')
        old = common.load(Path(baseline['baseline_build_record']['path']))
        common.require(old['source'] == baseline['baseline_source'], 'baseline source mismatch')
        common.require(set(baseline['link_inputs']) == set(frozen.OLD_LINK_SHA), 'baseline link-input set')
        common.require(sum(n.endswith('.a') for n in baseline['link_inputs']) == 9 and sum(n.endswith('.dylib') for n in baseline['link_inputs']) == 1, 'nine archives and one heap probe required')
        for name, item in baseline['link_inputs'].items():
            common.require(common.identity(item['path']) == item and item['sha256'] == frozen.OLD_LINK_SHA[name], 'baseline archive/probe SHA: ' + name)
        input_info = common.wav_identity(args.input, 48000, 1)
        common.require(input_info['sha256'] == INPUT_SHA, 'fixed chain300 input SHA required')
        source_id = common.identity(SOURCE)
        common.require(source_id['sha256'] == CLIENT_SOURCE_SHA, 'fixed Armed client body SHA')
        source = out / 'client.cpp'
        shutil.copyfile(SOURCE, source)
        common.require(common.identity(source)['sha256'] == source_id['sha256'], 'same client source copy')
        record.update(source=source_id, copied_source=common.identity(source),
                      baseline_client=common.identity(args.baseline_client), baseline_build=baseline['baseline_build_record'],
                      baseline_link_inputs=list(baseline['link_inputs'].values()), candidate_build=common.identity(args.candidate_build),
                      input={k: input_info[k] for k in ('path', 'bytes', 'sha256')}, input_format=input_info,
                      candidate_archive=common.identity(args.candidate_archive), candidate_archive_files=used_archives,
                      repeats=args.repeats, cpu_window_s=20, child_timeout_s=150,
                      preset=args.preset, baseline_commit=frozen.OLD_COMMIT, baseline_source=frozen.OLD_SOURCE_SHA)
        for version, build in (('old', old), ('candidate', candidate)):
            root = Path(build['source_root']).resolve()
            common.require(build['status'] == 'PASS' and build['architecture'] == 'arm64' and build['configuration'] == 'Release', 'Release arm64 build required')
            common.require(shared.digest(build['source_manifest']['files']) == build['source'] == build['source_manifest']['sha256'], 'manifest content SHA')
            common.require(shared.source_digest(root) == build['source'], version + ' source changed after build')
            source_map = {row['path']: row['sha256'] for row in build['source_manifest']['files']}
            build_dir = (Path(baseline['baseline_build']) if version == 'old' else Path(build['binaries']['phase62_control_cpu_native']['path']).parent).resolve()
            template_path = build_dir / 'CMakeFiles/phase62_control_cpu_native.dir/link.txt'
            flags_path = build_dir / 'CMakeFiles/phase62_control_cpu_native.dir/flags.make'
            template, flags = shlex.split(template_path.read_text()), frozen.flags_from_make(flags_path)
            if version == 'old':
                common.require(common.identity(template_path) == baseline['link_template'] and common.identity(flags_path) == baseline['flags_file'], 'baseline compile/link template SHA')
            else:
                anchor = build['binaries']['phase62_control_cpu_native']
                common.require(common.identity(anchor['path']) == anchor, 'candidate anchor binary SHA')
                archive_match(anchor)
            objects = [i for i, token in enumerate(template) if token.endswith('.o')]
            outputs = [i for i, token in enumerate(template) if token == '-o']
            common.require(len(objects) == len(outputs) == 1 and outputs[0] + 1 < len(template), 'one link object/output')
            compiler = template[0]
            common.require(Path(compiler).is_absolute() and flags['CXX_INCLUDES'] == ['-I' + str(root / 'src')], 'compiler/include path')
            common.require(not flags['CXX_DEFINES'] and '-std=c++20' in flags['CXX_FLAGS'] and '-O3' in flags['CXX_FLAGS'], 'Release C++20 flags')
            libraries = []
            for token in template[1:]:
                if token.endswith(('.a', '.dylib')):
                    item = common.identity(build_dir / token)
                    if version == 'old':
                        common.require(baseline['link_inputs'].get(Path(token).name) == item, 'old link dependency differs from frozen client')
                    else:
                        archive_match(item)
                    libraries.append(item)
            common.require(len(libraries) == 10 and sum(i['path'].endswith('.a') for i in libraries) == 9 and sum(i['path'].endswith('.dylib') for i in libraries) == 1, 'nine archives plus one dylib')
            directory = out / version
            directory.mkdir()
            obj, dep, binary = directory / 'client.o', directory / 'client.d', directory / 'armed_wait_native'
            compile_command = [compiler, *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], '-I' + str(root / 'tests'),
                               *flags['CXX_FLAGS'], '-MD', '-MT', str(obj), '-MF', str(dep), '-o', str(obj), '-c', str(source)]
            record['commands'].append(frozen.run(compile_command, build_dir, directory / 'compile.log'))
            dependencies = []
            for token in frozen.make_dependencies(dep):
                path = (build_dir / token).resolve()
                item = common.identity(path)
                if path == source:
                    item['origin'] = 'same_client_source'
                elif path.is_relative_to(root):
                    relative = str(path.relative_to(root))
                    common.require(source_map.get(relative) == item['sha256'], 'source/header dependency SHA: ' + relative)
                    item.update(origin=version + '_source_manifest', source_path=relative)
                else:
                    common.require(not any(path.is_relative_to(Path(b['source_root']).resolve()) for b in (old, candidate)), 'mixed old/candidate source')
                    item['origin'] = 'toolchain_or_system'
                dependencies.append(item)
            for needed in ('tests/ProgressiveAdoptionLimitNative.cpp', 'tests/Phase61NativeTests.cpp', 'tests/Phase61CallbackMallocProbe.h', 'src/platform/macos/ProgressiveMacPlaybackEngine.h', 'src/playback/ProgressiveFeatureContract.h'):
                common.require(any(d.get('source_path') == needed for d in dependencies), 'missing common helper/header ' + needed)
            symbols = subprocess.check_output(['/usr/bin/nm', '-u', str(obj)], text=True)
            tag = 'ContractV3Tag' if version == 'old' else 'ContractV4Tag'
            other = 'ContractV4Tag' if version == 'old' else 'ContractV3Tag'
            prepare = [line for line in symbols.splitlines() if 'ProgressiveMacPlaybackEngine' in line and 'prepare' in line]
            common.require(any(tag in line for line in prepare) and not any(other in line for line in prepare), 'prepare ABI mismatch')
            (directory / 'undefined_symbols.txt').write_text(symbols)
            link_command = template.copy()
            link_command[objects[0]] = str(obj)
            link_command[outputs[0] + 1] = str(binary)
            common.require(sum(a != b for a, b in zip(template, link_command)) == 2, 'link changes beyond object/output')
            record['commands'].append(frozen.run(link_command, build_dir, directory / 'link.log'))
            architectures = subprocess.check_output(['/usr/bin/lipo', '-archs', str(binary)], text=True).split()
            common.require(architectures == ['arm64'], 'arm64 client required')
            for item in dependencies + libraries:
                common.require(common.identity(item['path'])['sha256'] == item['sha256'], 'dependency changed during compile')
            record['clients'][version] = {'source': build['source'], 'source_root': str(root), 'build': str(build_dir),
                'binary': common.identity(binary), 'object': common.identity(obj), 'depfile': common.identity(dep),
                'dependencies': dependencies, 'libraries': libraries, 'compiler': common.identity(compiler),
                'compiler_version': subprocess.check_output([compiler, '--version'], text=True),
                'flags': flags, 'flags_file': common.identity(flags_path), 'link_template': common.identity(template_path),
                'undefined_symbols': common.identity(directory / 'undefined_symbols.txt'), 'prepare_ABI': tag,
                'contract_version': 3 if version == 'old' else 4, 'architectures': architectures,
                'compile_command': compile_command, 'link_command': link_command}
            common.save(out / 'CLIENT.json', record)
        for version, build in (('old', old), ('candidate', candidate)):
            common.require(shared.source_digest(Path(build['source_root']).resolve()) == build['source'], version + ' source changed during compile')
            for item in record['clients'][version]['dependencies'] + record['clients'][version]['libraries']:
                common.require(common.identity(item['path'])['sha256'] == item['sha256'], 'final dependency SHA')
        common.require(common.identity(SOURCE) == source_id and common.identity(args.baseline_client) == record['baseline_client'] and common.identity(args.candidate_build) == record['candidate_build'] and common.identity(args.candidate_archive) == record['candidate_archive'], 'source/build record changed')
        for row in used_archives:
            common.require(common.identity(row['original']['path']) == row['original'] and common.identity(row['archived']['path']) == row['archived'], 'final archive check')
        for item in record['helpers'] + [record['driver']]:
            common.require(common.identity(item['path']) == item, 'recipe/helper changed during compile')
        jobs = jobs_for(record, out / 'run_not_started', args.repeats)
        common.save(out / 'RUN_PLAN.json', {'schema': 'armed-wait-pairs-v1', 'status': 'NOT_RUN',
            'expected_programs': len(jobs), 'expected_checks': len(jobs) * 8, 'jobs': jobs,
            'all_expected_ids': [j['id'] for j in jobs], 'required_check_ids': list(CHECK_IDS),
            'input': record['input'], 'client_source_sha256': source_id['sha256'], 'preset': args.preset,
            'repeats_per_version': args.repeats, 'cpu_window_s': 20, 'child_timeout_s': 150,
            'A_input_frame': 0, 'B_input_frame': 1440000, 'initial_speed_micros': 1000000,
            'target_speed_micros': 750000, 'order': 'odd old/candidate; even candidate/old',
            'phase_observation': 'public Armed/fixed-B facts and nonblocking normal hook; private phase inferred',
            'performance_goal': 'CONTRIBUTION_MEASUREMENT_ONLY', 'callback_gate': False,
            'performance_improvement_approval': False, 'quality_approval': False, 'RT_approval': False,
            'physical_audio': None, 'application_F': None})
        record.update(status='PASS', run_plan=common.identity(out / 'RUN_PLAN.json'))
        common.save(out / 'CLIENT.json', record)
        print(out / 'CLIENT.json')
        return 0
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__ + ': ' + str(error))
        common.save(out / 'CLIENT.json', record)
        raise


if __name__ == '__main__':
    sys.exit(main())
