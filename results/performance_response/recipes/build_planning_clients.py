"""同一C1計画clientをB04旧archiveと指定候補buildへcompile/linkする。実行しない。

arm64 Python:
  build_planning_clients.py --candidate-build B/build_final/BUILD.json --output B/planning_clients_01
旧source=B/stage_b04_source、旧archive=B/stage_b04_archive/ARCHIVE.json。
archive全ファイルと旧source全manifestを前後照合する。生成物は新規build/出力のみ。
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
sys.path.insert(0, str(ROOT / 'results/performance_response/recipes'))
import build_frozen_client as frozen
import run_pairs as common


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate-build', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--old-source', type=Path, default=BASE / 'stage_b04_source')
    p.add_argument('--old-archive', type=Path, default=BASE / 'stage_b04_archive/ARCHIVE.json')
    p.add_argument('--source', type=Path, default=ROOT / 'tests/PerformancePlanningBench.cpp')
    a = p.parse_args()
    out = a.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'generated clients belong under build/')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'c1-planning-clients-v1', 'status': 'INCOMPLETE', 'compile_only': True,
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'driver': common.identity(__file__), 'helpers': [common.identity(frozen.__file__), common.identity(common.__file__)],
              'clients': {}, 'commands': []}
    try:
        common.require(platform.machine() == 'arm64', 'native arm64 Python required (use bundled runtime Python)')
        archive = common.load(a.old_archive)
        old_record = Path(archive['build_record']).resolve()
        old = common.load(old_record)
        candidate = common.load(a.candidate_build)
        common.require(old['status'] == candidate['status'] == 'PASS', 'build records must be PASS')
        common.require(archive['build_source'] == old['source'] == '5c3166fe78dbf410d32d06590e334cf77f21e8d032078b1261d0725cbc613928', 'old must be B04')
        for b in (old, candidate):
            common.require(b['configuration'] == 'Release' and b['architecture'] == 'arm64', 'Release arm64 required')
            common.require(common.manifest_digest(b['source_manifest']['files']) == b['source'] == b['source_manifest']['sha256'], 'build manifest contents')
        roots = {'old': a.old_source.resolve(), 'candidate': Path(candidate['source_root']).resolve()}
        for version, b in (('old', old), ('candidate', candidate)):
            common.require(common.current_source_digest(roots[version]) == b['source'], version + ' source is not frozen')
        archived = {}
        for item in archive['files']:
            expected = {'path': str(Path(item['archived']).resolve()), 'bytes': item['bytes'], 'sha256': item['sha256']}
            common.require(common.identity(expected['path']) == expected, 'old archive SHA: ' + expected['path'])
            name = Path(expected['path']).name
            common.require(name not in archived, 'duplicate archive member')
            archived[name] = expected
        source_id = common.identity(a.source)
        source = out / 'client.cpp'
        shutil.copyfile(a.source, source)
        common.require(common.identity(source)['sha256'] == source_id['sha256'], 'same source copy')
        build_dir = Path(candidate['binaries']['phase59_progressive_replay']['path']).resolve().parent
        common.require(common.identity(candidate['binaries']['phase59_progressive_replay']['path']) == candidate['binaries']['phase59_progressive_replay'], 'candidate anchor binary SHA')
        template_file = build_dir / 'CMakeFiles/phase59_progressive_replay.dir/link.txt'
        flags_file = build_dir / 'CMakeFiles/phase59_progressive_replay.dir/flags.make'
        template = shlex.split(template_file.read_text())
        flags = frozen.flags_from_make(flags_file)
        common.require(flags['CXX_INCLUDES'] == ['-I' + str(roots['candidate'] / 'src')], 'unexpected compiler include path')
        common.require(not flags['CXX_DEFINES'] and '-std=c++20' in flags['CXX_FLAGS'] and '-O3' in flags['CXX_FLAGS'], 'unexpected compiler flags')
        common.require(not any(os.environ.get(k) for k in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH', 'LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES')), 'ambient include/library override')
        objects = [i for i, token in enumerate(template) if token.endswith('.o')]
        outputs = [i for i, token in enumerate(template) if token == '-o']
        common.require(len(objects) == len(outputs) == 1, 'one object/output link template required')
        compiler = template[0]
        common.require(Path(compiler).is_absolute(), 'compiler must be absolute')
        record.update(source=source_id, copied_source=common.identity(source), old_archive=common.identity(a.old_archive),
                      old_build=common.identity(old_record), candidate_build=common.identity(a.candidate_build),
                      old_archive_files=list(archived.values()), compiler=common.identity(compiler),
                      compiler_version=subprocess.check_output([compiler, '--version'], text=True),
                      template=common.identity(template_file), flags_file=common.identity(flags_file), flags=flags,
                      environment={'machine': platform.machine(), 'platform': platform.platform(), 'python': sys.version,
                                   'inherited': {k: os.environ.get(k) for k in ('SDKROOT', 'MACOSX_DEPLOYMENT_TARGET', 'DEVELOPER_DIR')}},
                      flags_provenance='候補phase59_progressive_replayのRelease arm64/c++20設定を両clientへ共通使用。旧include/archiveだけB04へ置換。')
        for version, b in (('old', old), ('candidate', candidate)):
            root = roots[version]
            source_map = {row['path']: row['sha256'] for row in b['source_manifest']['files']}
            directory = out / version
            directory.mkdir()
            obj, dep, binary = directory / 'client.o', directory / 'client.d', directory / 'planning_bench'
            macro = '1' if version == 'candidate' else '0'
            compile_command = [compiler, '-I' + str(root / 'src'), *flags['CXX_FLAGS'],
                '-DTS_INCREMENTAL_PLANNER_METRICS=' + macro, '-MD', '-MT', str(obj), '-MF', str(dep), '-o', str(obj), '-c', str(source)]
            record['commands'].append(frozen.run(compile_command, build_dir, directory / 'compile.log'))
            deps = []
            for token in frozen.make_dependencies(dep):
                path = (build_dir / token).resolve()
                item = common.identity(path)
                if path == source:
                    item['origin'] = 'same_client_source'
                elif path.is_relative_to(root):
                    relative = str(path.relative_to(root))
                    common.require(source_map.get(relative) == item['sha256'], 'frozen dependency SHA: ' + relative)
                    item.update(origin=version + '_source_manifest', source_path=relative)
                else:
                    common.require(not any(path.is_relative_to(other) for other in roots.values()), 'mixed source dependency')
                    item['origin'] = 'toolchain_or_system'
                deps.append(item)
            common.require(any(x.get('source_path') == 'src/prototype/Phase59ProgressiveTransition.h' for x in deps), 'planner header missing')
            link_command = template.copy()
            link_command[objects[0]] = str(obj)
            link_command[outputs[0] + 1] = str(binary)
            libraries = []
            for i, token in enumerate(template):
                if token.endswith(('.a', '.dylib')):
                    item = archived.get(Path(token).name) if version == 'old' else common.identity(build_dir / token)
                    common.require(item is not None, 'old archive lacks link dependency ' + token)
                    link_command[i] = item['path']
                    libraries.append(item)
            common.require(libraries, 'no libraries linked')
            record['commands'].append(frozen.run(link_command, build_dir, directory / 'link.log'))
            arches = subprocess.check_output(['/usr/bin/lipo', '-archs', str(binary)], text=True).split()
            common.require(arches == ['arm64'], 'native arm64 client required')
            for item in deps + libraries:
                common.require(common.identity(item['path'])['sha256'] == item['sha256'], 'dependency changed during compile')
            record['clients'][version] = {'source': b['source'], 'source_root': str(root), 'binary': common.identity(binary),
                'object': common.identity(obj), 'depfile': common.identity(dep), 'dependencies': deps, 'libraries': libraries,
                'compile_command': compile_command, 'link_command': link_command, 'architectures': arches,
                'incremental_metrics': version == 'candidate', 'constructor_arguments': 6 if version == 'candidate' else 5,
                'diagnostic_replay': False}
            common.save(out / 'CLIENT.json', record)
        for item in archived.values():
            common.require(common.identity(item['path']) == item, 'old archive changed during compile')
        for version, b in (('old', old), ('candidate', candidate)):
            common.require(common.current_source_digest(roots[version]) == b['source'], 'source changed during compile')
        common.require(common.identity(a.source) == source_id, 'client source changed')
        common.require(common.identity(template_file) == record['template'] and common.identity(flags_file) == record['flags_file'], 'compile template changed')
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
