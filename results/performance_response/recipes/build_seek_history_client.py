"""D3の単独clientを固定旧/候補header・archiveへcompile/linkする（実行しない）。

--baseline-client B/frozen_clients_01/CLIENT.json --candidate-build B/build_candidate_03/BUILD.json
--output B/seek_history_clients_01 [--input 300s.wav --seconds 5 --repeats 3]
出力RUN_PLAN.jsonの各commandは別途直列実行する。既定は5層×3反復×2版=30件。
製品/試験/CMakeへの編集や、履歴上限の変更は行わない。
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import sys

import build_frozen_client as frozen


ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE = pathlib.Path(__file__).with_name('seek_history_native.cpp')


def source_digest(root):
    paths = [root / 'CMakeLists.txt']
    for directory in ('src', 'tests', 'scripts'):
        paths.extend(p for p in (root / directory).rglob('*') if p.is_file() and
                     p.suffix in ('.h', '.hpp', '.cpp', '.mm', '.py', '.c', '.m'))
    return digest([{'path': str(p.relative_to(root)), 'sha256': frozen.identity(p)['sha256']} for p in sorted(paths)])


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-client', type=pathlib.Path, required=True)
    parser.add_argument('--candidate-build', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--input', type=pathlib.Path, default=ROOT / 'results/phase56/long/chain_300s.wav')
    parser.add_argument('--seconds', type=float, default=5)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--presets', nargs='+', choices=('candidate', 'baseline'), default=['candidate'])
    args = parser.parse_args()
    frozen.require(args.repeats > 0 and 5 <= args.seconds <= 30, 'bounded D3 run plan')
    frozen.require(len(args.presets) == len(set(args.presets)), 'duplicate presets')
    out = args.output.resolve()
    frozen.require(out.is_relative_to(ROOT / 'build'), 'generated files belong under build/')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'performance-seek-history-client-v1', 'status': 'INCOMPLETE', 'compile_only': True,
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'driver': frozen.identity(__file__), 'compile_helper': frozen.identity(frozen.__file__),
              'clients': {}, 'commands': []}
    try:
        baseline = json.loads(args.baseline_client.read_text())
        candidate = json.loads(args.candidate_build.read_text())
        frozen.require(baseline['status'] == candidate['status'] == 'PASS', 'records must be PASS')
        frozen.require(baseline['contract_version'] == 3 and baseline['baseline_source'] == frozen.OLD_SOURCE_SHA,
                       'wrong old client provenance')
        frozen.require(candidate['configuration'] == 'Release' and candidate['architecture'] == 'arm64', 'candidate configuration')
        old_build_record = baseline['baseline_build_record']
        frozen.require(frozen.identity(old_build_record['path']) == old_build_record, 'old BUILD record changed')
        old = json.loads(pathlib.Path(old_build_record['path']).read_text())
        source_id = frozen.identity(SOURCE)
        source = out / 'client.cpp'
        shutil.copyfile(SOURCE, source)
        frozen.require(frozen.identity(source)['sha256'] == source_id['sha256'], 'client source copy mismatch')
        record.update(source=source_id, copied_source=frozen.identity(source),
                      baseline_client=frozen.identity(args.baseline_client), candidate_build=frozen.identity(args.candidate_build),
                      input=frozen.identity(args.input), real_seek_limit=4096, history_strata=[0, 1, 100, 1000, 4095])
        frozen.require(not any(os.environ.get(key) for key in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'LIBRARY_PATH')), 'ambient include/library override')
        for version, build in (('old', old), ('candidate', candidate)):
            root = pathlib.Path(build['source_root']).resolve()
            source_sha = build['source']
            frozen.require(digest(build['source_manifest']['files']) == source_sha == build['source_manifest']['sha256'], 'source manifest content')
            if version == 'candidate':
                frozen.require(source_digest(root) == source_sha, 'candidate source changed after build')
            source_map = {row['path']: row['sha256'] for row in build['source_manifest']['files']}
            build_dir = (pathlib.Path(baseline['baseline_build']) if version == 'old' else
                         pathlib.Path(build['binaries']['phase62_control_cpu_native']['path']).parent).resolve()
            template_file = build_dir / 'CMakeFiles/phase62_control_cpu_native.dir/link.txt'
            flags_file = build_dir / 'CMakeFiles/phase62_control_cpu_native.dir/flags.make'
            template = shlex.split(template_file.read_text())
            object_indices = [i for i, token in enumerate(template) if token.endswith('.o')]
            output_indices = [i for i, token in enumerate(template) if token == '-o']
            frozen.require(len(object_indices) == len(output_indices) == 1, 'one link object/output required')
            compiler, flags = template[0], frozen.flags_from_make(flags_file)
            frozen.require(pathlib.Path(compiler).is_absolute() and flags['CXX_INCLUDES'] == ['-I' + str(root / 'src')], 'compiler/include search path')
            libraries = []
            for token in template[1:]:
                if token.endswith(('.a', '.dylib')):
                    item = frozen.identity(build_dir / token)
                    if version == 'old':
                        frozen.require(baseline['link_inputs'].get(pathlib.Path(token).name) == item and
                                       item['sha256'] == frozen.OLD_LINK_SHA.get(pathlib.Path(token).name), 'old archive SHA')
                    libraries.append(item)
            frozen.require(len(libraries) == len(frozen.OLD_LINK_SHA), 'link library count')
            directory = out / version
            directory.mkdir()
            obj, dep, binary = directory / 'client.o', directory / 'client.d', directory / 'seek_history_native'
            diagnostics = version == 'candidate'
            compile_command = [compiler, *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], '-I' + str(root / 'tests'),
                               *flags['CXX_FLAGS'], '-DTS_SEEK_HISTORY_LATCH_DIAGNOSTICS=' + ('1' if diagnostics else '0'),
                               '-MD', '-MT', str(obj), '-MF', str(dep), '-o', str(obj), '-c', str(source)]
            record['commands'].append(frozen.run(compile_command, build_dir, directory / 'compile.log'))
            dependencies = []
            for token in frozen.make_dependencies(dep):
                path = (build_dir / token).resolve()
                item = frozen.identity(path)
                if path == source:
                    item['origin'] = 'same_client_source'
                elif path.is_relative_to(root):
                    relative = str(path.relative_to(root))
                    frozen.require(source_map.get(relative) == item['sha256'], 'source dependency SHA: ' + relative)
                    item.update(origin=version + '_source_manifest', source_path=relative)
                else:
                    forbidden = {ROOT.resolve(), pathlib.Path(old['source_root']).resolve(), pathlib.Path(candidate['source_root']).resolve()}
                    frozen.require(not any(path.is_relative_to(other) for other in forbidden), 'mixed old/candidate source dependency')
                    item['origin'] = 'toolchain_or_system'
                dependencies.append(item)
            frozen.require(any(row.get('source_path') == 'tests/ProgressiveAdoptionLimitNative.cpp' for row in dependencies), 'expected existing helper absent')
            symbols = subprocess.check_output(['/usr/bin/nm', '-u', str(obj)], text=True)
            tag = 'ContractV3Tag' if version == 'old' else 'ContractV4Tag'
            frozen.require(any('prepare' in line and tag in line for line in symbols.splitlines()), 'prepare ABI mismatch')
            (directory / 'undefined_symbols.txt').write_text(symbols)
            link_command = template.copy()
            link_command[object_indices[0]] = str(obj)
            link_command[output_indices[0] + 1] = str(binary)
            frozen.require(sum(a != b for a, b in zip(template, link_command)) == 2, 'link changed beyond object/output')
            record['commands'].append(frozen.run(link_command, build_dir, directory / 'link.log'))
            arches = subprocess.check_output(['/usr/bin/lipo', '-archs', str(binary)], text=True).split()
            frozen.require(arches == ['arm64'], 'arm64 native client required')
            for item in dependencies + libraries:
                frozen.require(frozen.identity(item['path'])['sha256'] == item['sha256'], 'build dependency changed')
            frozen.require(frozen.identity(SOURCE) == source_id, 'client source changed during compile')
            record['clients'][version] = {'source': source_sha, 'source_root': str(root), 'build': str(build_dir),
                'binary': frozen.identity(binary), 'object': frozen.identity(obj), 'depfile': frozen.identity(dep),
                'dependencies': dependencies, 'libraries': libraries, 'compiler': frozen.identity(compiler),
                'flags': flags, 'flags_file': frozen.identity(flags_file), 'link_template': frozen.identity(template_file),
                'undefined_symbols': frozen.identity(directory / 'undefined_symbols.txt'),
                'compile_command': compile_command, 'link_command': link_command,
                'latch_diagnostics_compiled': diagnostics, 'prepare_ABI': tag}
            frozen.save(out / 'CLIENT.json', record)
        frozen.require(source_digest(pathlib.Path(candidate['source_root']).resolve()) == candidate['source'], 'candidate changed during compile')
        jobs = []
        for repeat in range(1, args.repeats + 1):
            for preset in args.presets:
                for count in (0, 1, 100, 1000, 4095):
                    pair = f'N{count}_{preset}_r{repeat:02d}'
                    order = ('old', 'candidate') if repeat % 2 else ('candidate', 'old')
                    for version in order:
                        key = pair + '_' + version
                        client = record['clients'][version]
                        jobs.append({'id': key, 'pair_id': pair, 'history_N': count, 'Accepted_ID': count + 1,
                            'checks': 10, 'final_audit_IDs': '1..' + str(count + 1),
                            'command': [client['binary']['path'], str(args.input.resolve()), preset, str(count), str(args.seconds),
                                        str(out / 'run_not_started' / key), client['source'], version]})
        frozen.save(out / 'RUN_PLAN.json', {'schema': 'seek-history-pairs-v1', 'status': 'NOT_RUN',
            'expected_programs': len(jobs), 'expected_checks': len(jobs) * 10, 'jobs': jobs,
            'all_expected_ids': [job['id'] for job in jobs], 'input': record['input'], 'client_source_sha256': source_id['sha256'],
            'cpu_window_s': args.seconds, 'cpu_formula': '100*(RUSAGE_SELF user+system delta)/steady_clock wall delta',
            'order': 'odd old/candidate, even candidate/old', 'callback_gate': False,
            'latch_internal_diagnostics': 'candidate only; old field access compiled out',
            'quality_approval': False, 'realtime_approval': False, 'physical_audio': None})
        record.update(status='PASS', run_plan=frozen.identity(out / 'RUN_PLAN.json'))
        frozen.save(out / 'CLIENT.json', record)
        print(out / 'CLIENT.json')
        return 0
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__ + ': ' + str(error))
        frozen.save(out / 'CLIENT.json', record)
        raise


if __name__ == '__main__':
    sys.exit(main())
