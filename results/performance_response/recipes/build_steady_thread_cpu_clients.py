#!/usr/bin/env python3
"""旧5674/保存05へ同一の全thread CPU診断本文を個別linkする（実行しない）。

 --output B/steady_thread_cpu_clients_01
元PerformanceSteadyNativeの挿入部を除いた全byteを固定SHAへ照合する。
旧752/保存05の768 source台帳・9個の.a/probe・元hostを固定し、保存05の
live candidateディレクトリをリンクに使わない。生成物は新規build/だけ。
"""
import argparse
import datetime
import hashlib
import importlib.util
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
SOURCE = Path(__file__).with_name('steady_thread_cpu_native.cpp')
AUDIT_PATH = Path(__file__).with_name('run_mono2_ablation.py')
AUDIT_SHA = '19c63657c267937952ac9df076c92ce40ad500ee0abcae17f6a8bb6989aee4dd'
FROZEN_PATH = Path(__file__).with_name('build_frozen_client.py')
FROZEN_SHA = '36222a0b3040588332032b232cd5d482a57029a0ced9712a2b2be4829df902fb'
OLD_HOST_SHA = '7831a21cdd33b90cf22df0afae7669c93d099e7be53834142bfe4855dc349a21'
SAVED_HOST_SHA = 'd22445d7390f61ae560a9fd84e6b5fa87e87358096d4b19ab52e28a56151fa50'
LABELS = ('old5674', 'saved05')
SCOPE = {'classification': 'DIAGNOSTIC', 'automatic_CPU_adoption': False, 'quality': None,
         'physical_audio': None, 'normal_CPU_reexecution': False, 'callback_modified': False,
         'sampling': 'Two sequential task_threads snapshots on the existing normal control thread, outside a/b.',
         'thread_totals': 'New/gone thread interval CPU is unknown, never zero-filled. Matched sum is not task CPU.',
         'counters': 'Existing d0/d only; their interval includes sampling overhead, unlike process a/b.'}


def load_helper(path, sha, name):
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError('Frozen helper changed: ' + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helpers():
    audit = load_helper(AUDIT_PATH, AUDIT_SHA, 'thread_cpu_ablation_helper')
    frozen = load_helper(FROZEN_PATH, FROZEN_SHA, 'thread_cpu_compile_helper')
    return audit, frozen, audit.load_common()


def strip_diagnostic(text):
    pattern = r'/\* THREAD_CPU_([A-Z_]+)_BEGIN \*/.*?/\* THREAD_CPU_\1_END \*/'
    matches = list(re.finditer(pattern, text, flags=re.S))
    if [m.group(1) for m in matches] != ['HEADERS', 'HELPERS', 'PRE', 'POST', 'WRITE']:
        raise ValueError('Exact five diagnostic insertion blocks required')
    return re.sub(pattern, '', text, flags=re.S)


def freeze(plan, common):
    """元source全台帳とcompile/linkに実際に用いた全依存を再確認する。"""
    errors = []
    for item in plan['inventory']:
        try:
            actual = common.identity(item['path'])
            if any(actual[k] != item[k] for k in ('path', 'bytes', 'sha256')):
                errors.append('Changed identity: ' + item['path'])
        except OSError as error:
            errors.append(str(error))
    for row in plan['roots']:
        if common.current_source_digest(Path(row['root'])) != row['source']:
            errors.append('Changed source ledger: ' + row['label'])
    return {'status': 'PASS' if not errors else 'FAIL', 'files': len(plan['inventory']),
            'source_counts': {r['label']: r['count'] for r in plan['roots']}, 'errors': errors}


def provenance(audit, common):
    need = audit.need
    need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native arm64 macOS Python required')
    need(not any(os.environ.get(k) for k in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH',
             'OBJC_INCLUDE_PATH', 'LIBRARY_PATH')), 'Ambient include/library override forbidden')
    need(not any(k.startswith('DYLD_') and v for k, v in os.environ.items()), 'Ambient dyld override forbidden')
    base_id, base = audit.pinned(common, BASE / 'frozen_clients_02/CLIENT.json', audit.CLIENT_SHA)
    arc_id, arc = audit.pinned(common, BASE / 'timer_archive_05/ARCHIVE.json', audit.ARCHIVE_SHA)
    snap_id, snap = audit.pinned(common, BASE / 'timer_source_05/SOURCE.json', audit.SNAPSHOT_SHA)
    build05_id, build05 = audit.pinned(common, Path(arc['build']['path']), audit.BUILD05_SHA)
    old_build_id = audit.checked(common, base['baseline_build_record'])
    old_build = audit.read(old_build_id['path'])
    need(base['status'] == old_build['status'] == build05['status'] == 'PASS'
         and base['baseline_source'] == audit.OLD_SOURCE and base['baseline_commit'] == common.OLD_COMMIT
         and base['contract_version'] == 3, 'Pinned baseline provenance')
    need(all(x['architecture'] == 'arm64' and x['configuration'] == 'Release' for x in (old_build, build05)),
         'Release arm64 builds only')
    maps = {'old5674': audit.source_map(common, old_build, audit.OLD_SOURCE),
            'saved05': audit.source_map(common, snap, audit.SAVED_SOURCE)}
    need(audit.source_map(common, build05, audit.SAVED_SOURCE) == maps['saved05']
         and arc['source'] == audit.SAVED_SOURCE and arc['build'] == build05_id and arc['source_snapshot'] == snap_id,
         'Archive05 binds exact BUILD and source snapshot')
    roots = [{'label': 'old5674', 'root': str(Path(base['old_source_root']).resolve()),
              'source': audit.OLD_SOURCE, 'count': 752},
             {'label': 'saved05', 'root': str((BASE / 'timer_source_05').resolve()),
              'source': audit.SAVED_SOURCE, 'count': 768}]
    body = audit.checked(common, base['clients']['steady']['copied_source'])
    need(body['sha256'] == audit.BODY_SHA == maps['saved05'][audit.BODY], 'Original common body identity')
    source = common.identity(SOURCE)
    original = strip_diagnostic(SOURCE.read_text()).encode()
    need(hashlib.sha256(original).hexdigest() == audit.BODY_SHA and len(original) == body['bytes'],
         'Diagnostic removals must restore all original body bytes, options and callback')
    need(SOURCE.read_text().count('threadCpuSnapshot();') == 2, 'Exactly two snapshots, no in-window sampling')
    need(len(arc['files']) == 54, 'Canonical archive05 has 54 members')
    members = {}
    for row in arc['files']:
        a, b = row['original'], row['archived']; name = Path(b['path']).name
        need(name not in members and all(a[k] == b[k] for k in ('bytes', 'sha256'))
             and Path(b['path']).resolve().parent == BASE / 'timer_archive_05', 'Unique archive05 identity')
        members[name] = b
    libraries = {'old5674': list(base['link_inputs'].values()),
                 'saved05': [members[name] for name in base['link_inputs']]}
    old_host = base['clients']['steady']['binary']; saved_host = members['performance_steady_native']
    need(old_host['sha256'] == OLD_HOST_SHA and saved_host['sha256'] == SAVED_HOST_SHA
         and all(saved_host[k] == build05['binaries']['performance_steady_native'][k] for k in ('bytes', 'sha256')),
         'Canonical normal hosts, not overwritten live candidate')
    flags = base['compile_flags']
    need(flags == {'CXX_DEFINES': [], 'CXX_INCLUDES': ['-I' + str(Path(roots[0]['root']) / 'src')],
                   'CXX_FLAGS': ['-O3', '-DNDEBUG', '-std=c++20', '-arch', 'arm64']}, 'Original common flags')
    compiler = audit.checked(common, base['compiler'])
    input_id = common.wav_identity(ROOT / 'results/phase56/long/chain_300s.wav', 48000, 1)
    need(input_id['sha256'] == audit.INPUT_SHA and input_id['frames'] == 14400000, 'Fixed chain300 mono Float32')
    inventory = [base_id, arc_id, snap_id, build05_id, old_build_id, body, source, compiler,
                 common.identity(__file__), common.identity(AUDIT_PATH), common.identity(FROZEN_PATH),
                 common.identity(audit.COMMON), old_host, saved_host,
                 {k: input_id[k] for k in ('path', 'bytes', 'sha256')}]
    for item in (base['clients']['steady']['object'], base['clients']['steady']['depfile'],
                 base['link_template'], base['flags_file']):
        inventory.append(audit.checked(common, item))
    for label in LABELS:
        need(len(libraries[label]) == 10 and len({Path(v['path']).name for v in libraries[label]}) == 10,
             'Nine static libraries and heap probe required')
        inventory.extend(libraries[label])
    plan = {'roots': roots, 'source_maps': maps, 'inventory': inventory, 'libraries': libraries,
            'input': input_id, 'source': source, 'original_body': body, 'compiler': compiler, 'flags': flags,
            'base': base, 'normal_hosts': {'old5674': old_host, 'saved05': saved_host},
            'source_provenance': 'old752 plus external fixed common host; saved05 uses full768 immutable snapshot.',
            'old_archive_pin_provenance': base['archive_pin_provenance']}
    check = freeze(plan, common);need(check['status'] == 'PASS', str(check));plan['initial_freeze'] = check
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    audit, frozen, common = helpers();need = audit.need
    out = args.output.resolve()
    need(out.is_relative_to(ROOT / 'build'), 'New output must be under build/')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'steady-thread-cpu-clients-v1', 'status': 'INCOMPLETE', 'compile_only': True,
              'classification': 'DIAGNOSTIC', 'scope': SCOPE, 'clients': {}, 'commands': [],
              'driver': common.identity(__file__), 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        plan = provenance(audit, common)
        copied = out / 'client.cpp';shutil.copyfile(SOURCE, copied)
        need(common.identity(copied)['sha256'] == plan['source']['sha256'], 'Same copied diagnostic body')
        plan['inventory'].append(common.identity(copied))
        record.update(provenance=plan, copied_source=common.identity(copied))
        common.save(out / 'CLIENT.json', record)
        template = plan['base']['clients']['steady']['link_command']
        objects = [i for i, t in enumerate(template) if t.endswith('.o')]
        outputs = [i for i, t in enumerate(template) if t == '-o']
        rpaths = [i for i, t in enumerate(template) if t.startswith('-Wl,-rpath,')]
        need(len(objects) == len(outputs) == len(rpaths) == 1, 'Single frozen link object/output/rpath')
        for root in plan['roots']:
            label, source_root = root['label'], Path(root['root'])
            directory = out / label;directory.mkdir()
            obj, dep, binary = directory / 'client.o', directory / 'client.d', directory / 'steady_thread_cpu_native'
            shared = label == 'saved05';tag = 'ContractV4Tag' if shared else 'ContractV3Tag'
            compiler = plan['compiler']['path'];flags = plan['flags']
            cmd = [compiler, *flags['CXX_DEFINES'], '-I' + str(source_root / 'src'), '-I' + str(source_root / 'tests'),
                   *flags['CXX_FLAGS'], '-DTS_THREAD_CPU_SHARED_PRODUCER=' + str(int(shared)),
                   '-MD', '-MT', str(obj), '-MF', str(dep), '-o', str(obj), '-c', str(copied)]
            record['commands'].append(frozen.run(cmd, directory, directory / 'compile.log'))
            dependencies = []
            for token in frozen.make_dependencies(dep):
                path = (directory / token).resolve();item = common.identity(path)
                if path == copied:
                    item['origin'] = 'same_diagnostic_body'
                elif path.is_relative_to(source_root):
                    relative = str(path.relative_to(source_root))
                    need(plan['source_maps'][label].get(relative) == item['sha256'], 'Frozen header/source differs: ' + relative)
                    item.update(origin=label + '_frozen_source', source_path=relative)
                else:
                    forbidden = [ROOT, *[Path(r['root']) for r in plan['roots']]]
                    need(not any(path.is_relative_to(p) for p in forbidden), 'Mixed source/helper: ' + str(path))
                    item['origin'] = 'toolchain_or_system'
                dependencies.append(item)
            for expected in ('tests/Phase62InitialLoopNative.cpp', 'src/platform/macos/ProgressiveMacPlaybackEngine.h',
                             'src/prototype/Phase58RealtimePipeline.h'):
                need(any(d.get('source_path') == expected for d in dependencies), 'Required frozen dependency: ' + expected)
            symbols = subprocess.check_output(['/usr/bin/nm', '-u', str(obj)], text=True)
            need(any('prepare' in line and tag in line for line in symbols.splitlines()), 'Expected prepare ABI')
            need(not any('prepare' in line and ('ContractV3Tag' if shared else 'ContractV4Tag') in line
                         for line in symbols.splitlines()), 'Opposite ABI leaked')
            (directory / 'undefined_symbols.txt').write_text(symbols)
            by_name = {Path(v['path']).name: v for v in plan['libraries'][label]}
            link = template.copy();link[objects[0]] = str(obj);link[outputs[0] + 1] = str(binary)
            link[rpaths[0]] = '-Wl,-rpath,' + str(Path(by_name[audit.PROBE]['path']).parent)
            for i, token in enumerate(link):
                if token.endswith(('.a', '.dylib')):
                    need(Path(token).name in by_name, 'Unexpected frozen link library')
                    link[i] = by_name[Path(token).name]['path']
            allowed = set(objects + [outputs[0] + 1] + rpaths +
                          [i for i, t in enumerate(template) if t.endswith(('.a', '.dylib'))])
            need(all(a == b or i in allowed for i, (a, b) in enumerate(zip(template, link))), 'Link flags changed')
            record['commands'].append(frozen.run(link, directory, directory / 'link.log'))
            binary_id = common.identity(binary)
            runtime = audit.linkage(common, binary_id, by_name[audit.PROBE])
            client = {'source': root['source'], 'source_root': root['root'], 'contract_version': 4 if shared else 3,
                      'binary': binary_id, 'object': common.identity(obj), 'depfile': common.identity(dep),
                      'dependencies': dependencies, 'libraries': plan['libraries'][label],
                      'compile_command': cmd, 'link_command': link, 'prepare_ABI': tag,
                      'shared_producer_extra_fields': shared, 'runtime_linkage': runtime,
                      'undefined_symbols': common.identity(directory / 'undefined_symbols.txt')}
            record['clients'][label] = client
            plan['inventory'].extend([*dependencies, client['binary'], client['object'], client['depfile'],
                                      client['undefined_symbols'], runtime['resolved_probe']])
            common.save(out / 'CLIENT.json', record)
        final = freeze(plan, common);need(final['status'] == 'PASS', str(final))
        record.update(status='PASS', final_freeze=final)
        common.save(out / 'CLIENT.json', record)
        print(out / 'CLIENT.json')
        return 0
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__ + ': ' + str(error))
        common.save(out / 'CLIENT.json', record)
        raise


if __name__ == '__main__':
    sys.exit(main())
