"""ABの旧新共通本文を、同じ有限180秒/65536観測領域でbuildする。
候補 --candidate-build と --source-sha は必須。live source/全依存SHAを前後固定する。
5674旧版は凍結のまま、製品DSP/期限/設定は変えずcompile/linkのみ。
"""
import argparse
import datetime
import difflib
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
# 候補は必須CLI SHAと完全source台帳で固定する。
BODY = 'tests/ProgressiveAdoptionAbNative.cpp'
CAPTURE = 'tests/Phase62InitialLoopNative.cpp'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-client', type=Path, default=BASE / 'frozen_clients_02/CLIENT.json')
    parser.add_argument('--candidate-build', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new clients belong under build/')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'performance-ab-observation-clients-v1', 'status': 'INCOMPLETE', 'compile_only': True,
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'driver': common.identity(__file__), 'helpers': [common.identity(m.__file__) for m in (frozen, shared, common)],
              'clients': {}, 'commands': []}
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS Python required')
        common.require(not any(os.environ.get(k) for k in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH',
                       'LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES')), 'ambient include/library override')
        baseline, candidate = common.load(args.baseline_client), common.load(args.candidate_build)
        common.require(baseline['schema'] == 'performance-frozen-client-v1' and baseline['status'] == candidate['status'] == 'PASS', 'PASS build records required')
        common.require(baseline['baseline_commit'] == frozen.OLD_COMMIT and baseline['baseline_source'] == frozen.OLD_SOURCE_SHA and baseline['contract_version'] == 3, '5674 v3 frozen baseline required')
        common.require(candidate['source'] == args.source_sha and len(args.source_sha) == 64, 'explicit frozen candidate SHA required')
        common.require(common.identity(baseline['baseline_build_record']['path']) == baseline['baseline_build_record'], 'old BUILD changed')
        old = common.load(Path(baseline['baseline_build_record']['path']))
        common.require(old['source'] == baseline['baseline_source'] and set(baseline['link_inputs']) == set(frozen.OLD_LINK_SHA), 'old source/link set')
        for name, item in baseline['link_inputs'].items():
            common.require(common.identity(item['path']) == item and item['sha256'] == frozen.OLD_LINK_SHA[name], 'old archive/probe SHA')
        roots = {v: Path(b['source_root']).resolve() for v, b in (('old', old), ('candidate', candidate))}
        for version, build in (('old', old), ('candidate', candidate)):
            common.require(build['status'] == 'PASS' and build['configuration'] == 'Release' and build['architecture'] == 'arm64', 'Release arm64 build')
            common.require(shared.digest(build['source_manifest']['files']) == build['source'] == build['source_manifest']['sha256'], 'source manifest contents')
            common.require(shared.source_digest(roots[version]) == build['source'], version + ' source not frozen')
        maps = {v: {x['path']: x['sha256'] for x in b['source_manifest']['files']} for v, b in (('old', old), ('candidate', candidate))}
        body_source, capture_source = roots['candidate'] / BODY, roots['candidate'] / CAPTURE
        body_id, capture_id = common.identity(body_source), common.identity(capture_source)
        common.require(maps['candidate'][BODY] == body_id['sha256'] and maps['candidate'][CAPTURE] == capture_id['sha256'], 'candidate source-file SHA')
        common.require(maps['old'][CAPTURE] == capture_id['sha256'], 'both versions must share the same original InitialCapture source')
        body, capture = out / Path(BODY).name, out / Path(CAPTURE).name
        shutil.copyfile(body_source, body)
        original = capture_source.read_bytes()
        changed = original
        replacements = ((b'rate*40', b'rate*180', 2), (b'rawRecords(8192)', b'rawRecords(65536)', 1),
                        (b'spans(8192)', b'spans(65536)', 1))
        for before, after, count in replacements:
            common.require(changed.count(before) == count and changed.count(after) == 0, 'unexpected observation replacement count')
            changed = changed.replace(before, after)
            common.require(changed.count(after) == count, 'observation replacement incomplete')
        capture.write_bytes(changed)
        common.require(common.identity(body)['sha256'] == body_id['sha256'], 'AB client body changed')
        restored = changed
        for before, after, count in reversed(replacements):
            common.require(restored.count(after) == count, 'reverse replacement count')
            restored = restored.replace(after, before)
        common.require(restored == original, 'changes beyond four finite-observation substitutions')
        patch = out / 'CAPTURE_OBSERVATION.patch'
        patch.write_text(''.join(difflib.unified_diff(original.decode().splitlines(keepends=True), changed.decode().splitlines(keepends=True),
                              fromfile=CAPTURE + '.original', tofile=Path(CAPTURE).name + '.common180s')))
        record.update(common_client=common.identity(body), common_capture_source=common.identity(capture),
                      client_source_original=body_id, capture_source_original=capture_id, observation_diff=common.identity(patch),
                      baseline_client=common.identity(args.baseline_client), baseline_build_record=baseline['baseline_build_record'],
                      baseline_link_inputs=list(baseline['link_inputs'].values()), candidate_build=common.identity(args.candidate_build),
                      baseline_commit=frozen.OLD_COMMIT, baseline_source=frozen.OLD_SOURCE_SHA, candidate_source=candidate['source'],
                      transformation={'replacements': [{'before': a.decode(), 'after': z.decode(), 'count': n} for a, z, n in replacements],
                                      'AB_body_byte_identical': True, 'reverse_reconstruction_byte_identical': True,
                                      'product_source_modified': False, 'product_libraries_modified': False,
                                      'DSP_modified': False, 'deadline_or_options_modified': False},
                      observation_capacity={'raw_PCM_seconds': 180, 'output_PCM_seconds': 180, 'raw_records': 65536, 'output_spans': 65536,
                                            'scope': 'host-owned finite observation memory; identical old/new; no callback allocation'},
                      measurement_policy={'required_full_matrix_programs': 72, 'previous_40s_attempt': str(BASE / 'ab_main_pairs_final_01'),
                                          'reuse_previous_18_successful_cases': False,
                                          'instruction': 'all 72 main comparison programs must use this one common observation condition'},
                      quality_approval=False, realtime_approval=False, physical_audio=None, application_F=None)
        for version, build in (('old', old), ('candidate', candidate)):
            root = roots[version]
            build_dir = (Path(baseline['baseline_build']) if version == 'old' else Path(build['binaries']['phase62_control_cpu_native']['path']).parent).resolve()
            template_path = build_dir / 'CMakeFiles/phase62_control_cpu_native.dir/link.txt'
            flags_path = build_dir / 'CMakeFiles/phase62_control_cpu_native.dir/flags.make'
            template, flags = shlex.split(template_path.read_text()), frozen.flags_from_make(flags_path)
            if version == 'old':
                common.require(common.identity(template_path) == baseline['link_template'] and common.identity(flags_path) == baseline['flags_file'], 'old flags/link template SHA')
            else:
                common.require(common.identity(build['binaries']['phase62_control_cpu_native']['path']) == build['binaries']['phase62_control_cpu_native'], 'candidate anchor binary SHA')
            objects = [i for i, token in enumerate(template) if token.endswith('.o')]
            outputs = [i for i, token in enumerate(template) if token == '-o']
            common.require(len(objects) == len(outputs) == 1 and outputs[0] + 1 < len(template), 'one object/output')
            compiler = template[0]
            common.require(Path(compiler).is_absolute() and flags['CXX_INCLUDES'] == ['-I' + str(root / 'src')], 'compiler/include path')
            common.require(not flags['CXX_DEFINES'] and '-std=c++20' in flags['CXX_FLAGS'] and '-O3' in flags['CXX_FLAGS'], 'Release C++20 flags')
            libraries = []
            for token in template[1:]:
                if token.endswith(('.a', '.dylib')):
                    item = common.identity(build_dir / token)
                    if version == 'old':
                        common.require(baseline['link_inputs'].get(Path(token).name) == item, 'old link dependency SHA')
                    libraries.append(item)
            common.require(len(libraries) == 10 and sum(i['path'].endswith('.a') for i in libraries) == 9 and
                           sum(i['path'].endswith('.dylib') for i in libraries) == 1, '9 archives and heap probe')
            directory = out / version
            directory.mkdir()
            obj, dep, binary = directory / 'client.o', directory / 'client.d', directory / 'progressive_adoption_ab_native'
            compile_command = [compiler, *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], '-I' + str(root / 'tests'),
                               *flags['CXX_FLAGS'], '-MD', '-MT', str(obj), '-MF', str(dep), '-o', str(obj), '-c', str(body)]
            record['commands'].append(frozen.run(compile_command, build_dir, directory / 'compile.log'))
            dependencies = []
            for token in frozen.make_dependencies(dep):
                path = (build_dir / token).resolve()
                item = common.identity(path)
                if path == body:
                    common.require(item == record['common_client'], 'common AB body dependency SHA')
                    item['origin'] = 'common_AB_body'
                elif path == capture:
                    common.require(item == record['common_capture_source'], 'common capture dependency SHA')
                    item['origin'] = 'common_180s_65536_observation_source'
                elif path.is_relative_to(root):
                    relative = str(path.relative_to(root))
                    common.require(maps[version].get(relative) == item['sha256'], 'frozen dependency SHA: ' + relative)
                    item.update(origin=version + '_source_manifest', source_path=relative)
                else:
                    common.require(not any(path.is_relative_to(r) for r in roots.values()), 'mixed old/candidate header')
                    item['origin'] = 'toolchain_or_system'
                dependencies.append(item)
            common.require(sum(x['origin'] == 'common_AB_body' for x in dependencies) == 1 and
                           sum(x['origin'] == 'common_180s_65536_observation_source' for x in dependencies) == 1, 'common source pair missing')
            common.require(not any(x.get('source_path') in (BODY, CAPTURE) for x in dependencies), 'original 40s helper/body leaked into compile')
            common.require(any(x.get('source_path') == 'tests/Phase62NativeTests.cpp' for x in dependencies), 'remaining helper must come from matching old/new source')
            symbols = subprocess.check_output(['/usr/bin/nm', '-u', str(obj)], text=True)
            tag, other = ('ContractV3Tag', 'ContractV4Tag') if version == 'old' else ('ContractV4Tag', 'ContractV3Tag')
            prepare = [line for line in symbols.splitlines() if 'ProgressiveMacPlaybackEngine' in line and 'prepare' in line]
            common.require(any(tag in x for x in prepare) and not any(other in x for x in prepare), 'prepare ABI mismatch')
            (directory / 'undefined_symbols.txt').write_text(symbols)
            link_command = template.copy()
            link_command[objects[0]] = str(obj)
            link_command[outputs[0] + 1] = str(binary)
            common.require(sum(a != z for a, z in zip(template, link_command)) == 2, 'link changes beyond object/output')
            record['commands'].append(frozen.run(link_command, build_dir, directory / 'link.log'))
            architectures = subprocess.check_output(['/usr/bin/lipo', '-archs', str(binary)], text=True).split()
            common.require(architectures == ['arm64'], 'native arm64 binary')
            for item in dependencies + libraries:
                common.require(common.identity(item['path'])['sha256'] == item['sha256'], 'dependency changed during compile')
            record['clients'][version] = {'binary': common.identity(binary), 'source': build['source'],
                'contract_version': 3 if version == 'old' else 4, 'prepare_ABI': tag, 'architectures': architectures,
                'source_root': str(root), 'build': str(build_dir), 'object': common.identity(obj), 'depfile': common.identity(dep),
                'dependencies': dependencies, 'libraries': libraries, 'compiler': common.identity(compiler),
                'compiler_version': subprocess.check_output([compiler, '--version'], text=True),
                'flags': flags, 'flags_file': common.identity(flags_path), 'link_template': common.identity(template_path),
                'undefined_symbols': common.identity(directory / 'undefined_symbols.txt'),
                'common_client_sha256': record['common_client']['sha256'], 'common_capture_source_sha256': record['common_capture_source']['sha256'],
                'compile_command': compile_command, 'link_command': link_command}
            common.save(out / 'CLIENT.json', record)
        for version, build in (('old', old), ('candidate', candidate)):
            common.require(shared.source_digest(roots[version]) == build['source'], version + ' source changed during compile')
            compiled = record['clients'][version]
            for key in ('binary', 'object', 'depfile', 'compiler', 'flags_file', 'link_template', 'undefined_symbols'):
                common.require(common.identity(compiled[key]['path']) == compiled[key], 'final compiled artifact/template SHA')
            for item in compiled['dependencies'] + compiled['libraries']:
                common.require(common.identity(item['path'])['sha256'] == item['sha256'], 'final dependency SHA')
        for item in (record['common_client'], record['common_capture_source'], record['observation_diff'], record['client_source_original'],
                     record['capture_source_original'], record['baseline_client'], record['baseline_build_record'], record['candidate_build'], record['driver'], *record['helpers']):
            common.require(common.identity(item['path']) == item, 'source/recipe/manifest changed during compile')
        record['status'] = 'PASS'
        common.save(out / 'CLIENT.json', record)
        print(out / 'CLIENT.json')
        return 0
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__ + ': ' + str(error))
        common.save(out / 'CLIENT.json', record)
        raise


if __name__ == '__main__':
    sys.exit(main())
