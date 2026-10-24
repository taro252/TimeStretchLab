"""warm再ONの同一本文を凍結5674 v3と明示候補v4へbuildする。
候補 --candidate-build と --source-sha は必須、live sourceと全リンクSHAを固定。
n3交互×A30/A270=12program/144checks。compile/linkのみ。
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
SOURCE = Path(__file__).with_name('warm_ab_native_v2.cpp')
SOURCE_SHA = '1d36e487a17a8b6a63a57846a9a625f2210d72a4064caaeac364fa1fbcdc98ac'
# 候補sourceは必須CLIで固定。
INPUT_SHA = '13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-client', type=Path, default=BASE / 'frozen_clients_02/CLIENT.json')
    parser.add_argument('--candidate-build', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--input', type=Path, default=ROOT / 'results/phase56/long/chain_300s.wav')
    parser.add_argument('--preset', choices=('candidate', 'baseline'), default='candidate')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'generated clients belong under build/')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'performance-warm-ab-clients-v1', 'status': 'INCOMPLETE', 'compile_only': True,
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'driver': common.identity(__file__), 'helpers': [common.identity(m.__file__) for m in (frozen, shared, common)],
              'clients': {}, 'commands': [], 'host_revision': 2,
              'reservation_probe': 'separate engine prepare Ready Stop close after primary cost boundary'}
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS Python required')
        common.require(not any(os.environ.get(k) for k in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH',
                       'OBJC_INCLUDE_PATH', 'LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES')), 'ambient include/library override')
        baseline = common.load(args.baseline_client)
        candidate = common.load(args.candidate_build)
        common.require(args.baseline_client.resolve() == (BASE / 'frozen_clients_02/CLIENT.json').resolve(), 'fixed frozen02 baseline path')
        common.require(candidate['source'] == args.source_sha and len(args.source_sha) == 64, 'explicit frozen candidate SHA required')
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
        common.require(source_id['sha256'] == SOURCE_SHA, 'fixed warm client source SHA required')
        source = out / 'client.cpp'
        shutil.copyfile(SOURCE, source)
        common.require(common.identity(source)['sha256'] == source_id['sha256'], 'same client source copy')
        record.update(source=source_id, copied_source=common.identity(source),
                      baseline_client=common.identity(args.baseline_client), baseline_build=baseline['baseline_build_record'],
                      baseline_link_inputs=list(baseline['link_inputs'].values()), candidate_build=common.identity(args.candidate_build),
                      input={k: input_info[k] for k in ('path', 'bytes', 'sha256')}, input_format=input_info,
                      preset=args.preset, baseline_commit=frozen.OLD_COMMIT, baseline_source=frozen.OLD_SOURCE_SHA,
                      candidate_source=args.source_sha, expected_programs=12, expected_checks=144,
                      quality_approval=False, realtime_approval=False, public_approved=False)
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
                    libraries.append(item)
            common.require(len(libraries) == 10 and sum(i['path'].endswith('.a') for i in libraries) == 9 and sum(i['path'].endswith('.dylib') for i in libraries) == 1, 'nine archives plus one dylib')
            directory = out / version
            directory.mkdir()
            obj, dep, binary = directory / 'client.o', directory / 'client.d', directory / 'warm_ab_native'
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
            for needed in ('tests/Phase62InitialLoopNative.cpp', 'tests/Phase61CallbackMallocProbe.h', 'src/platform/macos/ProgressiveMacPlaybackEngine.h'):
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
        common.require(common.identity(SOURCE) == source_id and common.identity(source) == record['copied_source'] and
                       common.identity(args.baseline_client) == record['baseline_client'] and
                       common.identity(args.candidate_build) == record['candidate_build'], 'source/build record changed')
        common.require(common.identity(input_info['path']) == record['input'], 'fixed input changed during compile')
        for item in record['helpers'] + [record['driver']]:
            common.require(common.identity(item['path']) == item, 'recipe/helper changed during compile')
        helper_ids = [next(d for d in record['clients'][v]['dependencies']
                           if d.get('source_path') == 'tests/Phase62InitialLoopNative.cpp') for v in ('old', 'candidate')]
        common.require(helper_ids[0]['sha256'] == helper_ids[1]['sha256'], 'common frozen InitialCapture helper differs')
        record['capture_helper'] = {'old': helper_ids[0], 'candidate': helper_ids[1],
            'common_sha256': helper_ids[0]['sha256'], 'original_helper_modified': False,
            'host_only_capacity': 'same client normal constructor sets 180 seconds / 65536 preallocated records'}
        jobs = []
        for repeat in (1, 2, 3):
            for at in (30, 270):
                pair = f'A{at}_{args.preset}_r{repeat:02d}'
                for version in (('old', 'candidate') if repeat % 2 else ('candidate', 'old')):
                    entry, key = record['clients'][version], pair + '_' + version
                    jobs.append({'id': key, 'pair_id': pair, 'repeat': repeat, 'version': version,
                        'preset': args.preset, 'A_seconds': at, 'checks': 12,
                        'command': [entry['binary']['path'], input_info['path'], args.preset, str(at),
                                    str(out / 'run_not_started' / key), entry['source'], version]})
        common.require(len(jobs) == len({j['id'] for j in jobs}) == 12, 'fixed complete 12-program plan')
        common.save(out / 'RUN_PLAN.json', {'schema': 'warm-ab-pairs-v1', 'status': 'NOT_RUN',
            'expected_programs': 12, 'expected_checks': 144, 'jobs': jobs,
            'all_expected_ids': [j['id'] for j in jobs], 'input': record['input'],
            'client_source_sha256': source_id['sha256'], 'preset': args.preset,
            'speed_micros': 1000000, 'A_seconds': [30, 270], 'loop_duration_ms': 100,
            'unique_Loop_IDs_per_program': [1, 2],
            'accepted_receipts_per_program': [{'action': 'initial_ON', 'id': 1},
                {'action': 'Playing_Clear', 'id': 1}, {'action': 'warm_reON', 'id': 2}],
            'order': 'repeat1 old/candidate; repeat2 candidate/old; repeat3 old/candidate; A30 then A270',
            'warm_target_p95_ms': 250, 'hit_required': 'initialCheckpointHit actual true',
            'miss': 'NOT_EXERCISED; never silently relabel fresh',
            'cost_scope': 'initial setup, capture save/reset, normal Play, reON and whole process separate',
            'physical_audio': None, 'application_F': None, 'quality_approval': False,
            'RT_deadline_approval': False, 'public_approved': False, 'callback_gate': False})
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
