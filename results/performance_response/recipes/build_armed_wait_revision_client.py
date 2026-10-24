"""D3待機分岐だけの前後clientを保存する。beforeは再compile/relinkしない。

/usr/local/bin/python3 results/performance_response/recipes/build_armed_wait_revision_client.py \
  --output build/performance_response_20261023_01/armed_wait_revision_clients_01
before=既存bfa V4 client/object、after=同本文/flags/headersのfinal04 V4 compile。
旧libraryの現pathは更新済みなのでarchive03の対応保存物で当時のSHAを検証する。
既定RUN_PLANはn3 before/after交互6program/48checks、20秒窓、150秒期限。
このrecipeはcompile/linkだけ。PCM/音声実行・製品/既存recipe編集はしない。
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
import build_armed_wait_clients as original
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
BEFORE_SOURCE = original.CANDIDATE_SOURCE
AFTER_SOURCE = '02b81c089a78155232a5fa4428586f1a6f81c53de90b1a319924fa9a4b04ac4b'
AFTER_BUILD_SHA = '60032980fe438dec504aee8a034279a49e55d7dabf5e44955a4e06f51e039eed'
BEFORE_CLIENT_SHA = '87c94ef724912bf3c7ae699da866d81bd7fa56db2e9ab257a3d619e95ad24f9d'
BEFORE_ARCHIVE_SHA = '80dfdba60ab872f797d36443e3d778f8658a45cb8591ff842327bfe2bc83574d'
AFTER_ARCHIVE_SHA = 'ddd288f9313b0c1f8b432a7a22dc03be5a24ca41d827b060bc1ddd3bb4f139a3'
BEFORE_SNAPSHOT_SHA = '181affd84a5649e983d3380fd585cf8f76e3c19247c290329617603913bbb372'
AFTER_SNAPSHOT_SHA = '82860ddccc5468402f62aef1927b894154de7e188f4d18539464489b2b86be0c'
PATCH_SHA = '99b2235819a5492f58e450c4a9dd4ebb9362e43852dfe4ed4b2486f2082b7420'
NATIVE_SOURCE = 'src/platform/macos/ProgressiveMacPlaybackEngine.mm'
NATIVE_LIBRARY = 'libmacos_progressive_playback_engine.a'
LABELS = ('before_wait', 'after_wait')


def fixed_record(path, expected):
    actual = common.identity(path)
    common.require(actual['sha256'] == expected, 'fixed record SHA: ' + str(path))
    return actual, common.load(path)


def verify_snapshot(path, source, expected_record_sha):
    identity, value = fixed_record(path, expected_record_sha)
    rows = value['files'] if 'files' in value else value['source_manifest']['files']
    common.require(value['source'] == source and len(rows) == 768
                   and common.manifest_digest(rows) == source, '768-file source ledger/content SHA')
    relative = [r['path'] for r in rows]
    common.require(len(set(relative)) == 768, 'unique snapshot file set')
    root = path.resolve().parent
    common.require(common.current_source_digest(root) == source, 'saved full source bytes differ')
    files = []
    for row in rows:
        p = (root / row['path']).resolve()
        common.require(p.is_relative_to(root), 'snapshot path escaped root')
        item = common.identity(p)
        common.require(item['sha256'] == row['sha256'], 'saved source byte SHA: ' + row['path'])
        files.append({**item, 'source_path': row['path']})
    return {'record': identity, 'root': str(root), 'source': source, 'files': files}, rows


def verify_archive(path, source, expected_sha, build_identity, verify_original):
    identity, value = fixed_record(path, expected_sha)
    common.require(value['source'] == source and value['build'] == build_identity
                   and len(value['files']) == 54, 'fixed archive source/build/54 files')
    entries, result = {}, []
    for row in value['files']:
        historical, archived = row['original'], row['archived']
        name = Path(historical['path']).name
        common.require(name not in entries and Path(archived['path']).name == name, 'unique archive file names')
        common.require(historical['sha256'] == archived['sha256'] and historical['bytes'] == archived['bytes'],
                       'archive original/copy declared byte identity')
        common.require(common.identity(archived['path']) == archived, 'archived actual byte SHA: ' + name)
        if verify_original:
            common.require(common.identity(historical['path']) == historical, 'current final04 actual bytes: ' + name)
        entries[name] = row
        result.append({'name': name, 'archived': archived,
                       **({'current_original': historical} if verify_original else {}),
                       'historical_original_path': historical['path'],
                       'historical_original_sha256': historical['sha256'],
                       'historical_original_bytes': historical['bytes']})
    return identity, entries, result


def dependency_key(item):
    if item.get('origin') == 'same_client_source':
        return ('same_client_source', 'armed_wait_native.cpp')
    if item.get('source_path'):
        return ('source', item['source_path'])
    return ('system', item['path'])


def dependency_signature(items):
    # clang lists pthread/sched.h twice through SDK include aliases. Compare
    # the complete multiset, preserving multiplicity and byte identities.
    return sorted((dependency_key(item), item['bytes'], item['sha256']) for item in items)


def jobs_for(client, out):
    jobs = []
    for repeat in (1, 2, 3):
        pair = f'Armed20_revision_{client["preset"]}_r{repeat:02d}'
        for label in (LABELS if repeat % 2 else tuple(reversed(LABELS))):
            entry, key = client['clients'][label], pair + '_' + label
            jobs.append({'id': key, 'pair_id': pair, 'repeat': repeat, 'label': label,
                'version': 'candidate', 'preset': client['preset'], 'checks': 8,
                'check_ids': list(original.CHECK_IDS),
                'command': [entry['binary']['path'], client['input']['path'], client['preset'], '20',
                            str(out / key), entry['source'], 'candidate']})
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before-client', type=Path, default=BASE / 'armed_wait_clients_final_01/CLIENT.json')
    parser.add_argument('--before-source', type=Path, default=BASE / 'final_source_03/SOURCE.json')
    parser.add_argument('--before-archive', type=Path, default=BASE / 'final_archive_03/ARCHIVE.json')
    parser.add_argument('--after-build', type=Path, default=BASE / 'build_final_04/BUILD.json')
    parser.add_argument('--after-source', type=Path, default=BASE / 'final_source_04/SOURCE.json')
    parser.add_argument('--after-archive', type=Path, default=BASE / 'final_archive_04/ARCHIVE.json')
    parser.add_argument('--patch', type=Path, default=BASE / 'D3_WAIT_PATCH.diff')
    parser.add_argument('--input', type=Path, default=ROOT / 'results/phase56/long/chain_300s.wav')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'new generated output under build/')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'armed-wait-revision-client-v1', 'status': 'INCOMPLETE', 'compile_only': True,
        'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'clients': {}, 'commands': [],
        'driver': common.identity(__file__), 'helpers': [common.identity(m.__file__) for m in (common, frozen, original)],
        'before_relinked': False, 'native_version_both': 'candidate', 'exploration_reused_as_new_count': False}
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS Python')
        common.require(not any(os.environ.get(k) for k in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH',
            'OBJC_INCLUDE_PATH', 'LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES')), 'ambient include/library override')
        before_id, saved = fixed_record(args.before_client, BEFORE_CLIENT_SHA)
        after_id, build = fixed_record(args.after_build, AFTER_BUILD_SHA)
        common.require(saved['schema'] == 'performance-armed-wait-clients-v1' and saved['status'] == 'PASS'
                       and saved['source']['sha256'] == saved['copied_source']['sha256'] == original.CLIENT_SOURCE_SHA,
                       'existing PASS identical-body Armed client')
        common.require(saved['candidate_build']['sha256'] == original.CANDIDATE_BUILD_SHA
                       and saved['preset'] in ('candidate', 'baseline'), 'historical final03/preset')
        common.require(common.identity(saved['candidate_build']['path']) == saved['candidate_build'], 'historical BUILD record')
        common.require(build['status'] == 'PASS' and build['source'] == AFTER_SOURCE
                       and build['configuration'] == 'Release' and build['architecture'] == 'arm64'
                       and common.manifest_digest(build['source_manifest']['files']) == AFTER_SOURCE
                       and build['source_manifest']['sha256'] == AFTER_SOURCE, 'final04 Release arm64 source ledger')
        source_root = Path(build['source_root']).resolve()
        common.require(common.current_source_digest(source_root) == AFTER_SOURCE, 'current final04 source bytes')
        snap03, rows03 = verify_snapshot(args.before_source, BEFORE_SOURCE, BEFORE_SNAPSHOT_SHA)
        snap04, rows04 = verify_snapshot(args.after_source, AFTER_SOURCE, AFTER_SNAPSHOT_SHA)
        m03, m04 = ({r['path']: r['sha256'] for r in rows} for rows in (rows03, rows04))
        common.require(set(m03) == set(m04), 'same complete source set')
        common.require(rows04 == build['source_manifest']['files'], 'saved04/current BUILD ledger')
        changed = [p for p in m03 if m03[p] != m04[p]]
        common.require(changed == [NATIVE_SOURCE], 'only D3 native .mm differs in all 768 files')
        patch_id, patch = common.identity(args.patch), args.patch.read_text()
        common.require(patch_id['sha256'] == PATCH_SHA, 'fixed D3 patch SHA')
        actual_patch = ''.join(difflib.unified_diff((Path(snap03['root']) / NATIVE_SOURCE).read_text().splitlines(keepends=True),
            (Path(snap04['root']) / NATIVE_SOURCE).read_text().splitlines(keepends=True),
            fromfile='bfa/' + NATIVE_SOURCE, tofile='02b81/' + NATIVE_SOURCE))
        common.require(patch == actual_patch, 'saved D3 patch exactly matches snapshot bytes')
        arc03_id, arc03, archive03 = verify_archive(args.before_archive, BEFORE_SOURCE, BEFORE_ARCHIVE_SHA,
                                                   saved['candidate_build'], False)
        arc04_id, arc04, archive04 = verify_archive(args.after_archive, AFTER_SOURCE, AFTER_ARCHIVE_SHA, after_id, True)
        common.require(set(arc03) == set(arc04), 'same 54 archived target names')
        changed_targets = sorted(n for n in arc03 if arc03[n]['archived']['sha256'] != arc04[n]['archived']['sha256'])
        common.require(len(changed_targets) == 15 and len(arc03) - len(changed_targets) == 39, '39 identical/15 changed archive targets')
        changed_libraries = [n for n in changed_targets if n.endswith(('.a', '.dylib'))]
        common.require(changed_libraries == [NATIVE_LIBRARY], 'only native engine library changed; shared DSP/probe identical')
        before = saved['clients']['candidate']
        common.require(before['source'] == BEFORE_SOURCE and before['prepare_ABI'] == 'ContractV4Tag'
                       and before['contract_version'] == 4 and before['architectures'] == ['arm64'], 'existing bfa V4 arm64 client')
        for key in ('binary', 'object', 'depfile', 'compiler', 'flags_file', 'link_template', 'undefined_symbols'):
            common.require(common.identity(before[key]['path']) == before[key], 'before immutable artifact: ' + key)
        common.require(Path(before['binary']['path']).is_relative_to(args.before_client.resolve().parent)
                       and Path(before['object']['path']).is_relative_to(args.before_client.resolve().parent),
                       'before executable/object retained in their own client directory')
        common.require(common.identity(saved['source']['path']) == saved['source']
                       and common.identity(saved['copied_source']['path']) == saved['copied_source'], 'before original/copied body')
        previous_deps = []
        for item in before['dependencies']:
            actual = common.identity(item['path'])
            common.require(actual == {k: item[k] for k in ('path', 'bytes', 'sha256')}, 'before dependency actual bytes')
            if item.get('source_path'):
                common.require(m03.get(item['source_path']) == m04.get(item['source_path']) == item['sha256'], 'same V4 helper/header bytes')
            previous_deps.append(item)
        common.require(len(before['libraries']) == 10 and len({Path(x['path']).name for x in before['libraries']}) == 10, 'before exact ten link inputs')
        previous_libraries, mappings = [], []
        for item in before['libraries']:
            name = Path(item['path']).name
            common.require(name in arc03 and arc03[name]['original'] == item, 'historical link input maps exactly to archive03')
            previous_libraries.append(arc03[name]['archived'])
            mappings.append({'name': name, 'historical_path': item['path'], 'historical_bytes': item['bytes'],
                             'historical_sha256': item['sha256'], 'verified_archived': arc03[name]['archived']})
        flags_path, template_path = Path(before['flags_file']['path']), Path(before['link_template']['path'])
        flags, template = frozen.flags_from_make(flags_path), shlex.split(template_path.read_text())
        common.require(flags == before['flags'] and not flags['CXX_DEFINES']
                       and flags['CXX_INCLUDES'] == ['-I' + str(source_root / 'src')]
                       and '-std=c++20' in flags['CXX_FLAGS'] and '-O3' in flags['CXX_FLAGS'], 'same compile flags/macros')
        build_dir = Path(build['binaries']['phase62_control_cpu_native']['path']).parent.resolve()
        common.require(build_dir == Path(before['build']).resolve(), 'same native link template directory')
        anchor = build['binaries']['phase62_control_cpu_native']
        common.require(common.identity(anchor['path']) == anchor and arc04[Path(anchor['path']).name]['original'] == anchor,
                       'final04 native anchor actual/archive identity')
        objects = [i for i, s in enumerate(template) if s.endswith('.o')]
        outputs = [i for i, s in enumerate(template) if s == '-o']
        common.require(len(objects) == len(outputs) == 1 and outputs[0] + 1 < len(template), 'single native link object/output')
        reconstructed = template.copy();reconstructed[objects[0]] = before['object']['path'];reconstructed[outputs[0] + 1] = before['binary']['path']
        common.require(reconstructed == before['link_command'], 'before link command equals same native template')
        compiler = template[0]
        common.require(common.identity(compiler) == before['compiler']
                       and subprocess.check_output([compiler, '--version'], text=True) == before['compiler_version'], 'same compiler/version')
        libraries = []
        for token in template[1:]:
            if token.endswith(('.a', '.dylib')):
                item = common.identity(build_dir / token);name = Path(token).name
                common.require(name in arc04 and arc04[name]['original'] == item, 'after actual/archive04 link input')
                libraries.append(item)
        common.require([Path(x['path']).name for x in libraries] == [Path(x['path']).name for x in before['libraries']], 'same ordered library names')
        common.require([Path(a['path']).name for a, b in zip(libraries, before['libraries']) if a['sha256'] != b['sha256']] == [NATIVE_LIBRARY], 'link differs only in native engine')
        input_info = common.wav_identity(args.input, 48000, 1)
        common.require(input_info['sha256'] == saved['input']['sha256'] == original.INPUT_SHA, 'same fixed chain300 input')
        copied = out / 'client.cpp';shutil.copyfile(saved['copied_source']['path'], copied)
        common.require(common.identity(copied)['sha256'] == original.CLIENT_SOURCE_SHA, 'identical C++ body bytes')
        after_dir = out / 'after_wait';after_dir.mkdir()
        obj, dep, binary = after_dir / 'client.o', after_dir / 'client.d', after_dir / 'armed_wait_native'
        command = [compiler, *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'], '-I' + str(source_root / 'tests'),
                   *flags['CXX_FLAGS'], '-MD', '-MT', str(obj), '-MF', str(dep), '-o', str(obj), '-c', str(copied)]
        old_command = before['compile_command'].copy()
        for option, value in (('-MT', str(obj)), ('-MF', str(dep)), ('-o', str(obj)), ('-c', str(copied))):
            common.require(old_command.count(option) == 1, 'one compiler path option')
            old_command[old_command.index(option) + 1] = value
        common.require(command == old_command, 'compile command identical except generated artifact paths')
        record.update(before_client=before_id, before_build=saved['candidate_build'], after_build=after_id,
            before_archive=arc03_id, after_archive=arc04_id, archive03_files=archive03, archive04_files=archive04,
            before_source_snapshot=snap03, after_source_snapshot=snap04, patch=patch_id, source=saved['source'],
            before_copied_source=saved['copied_source'], copied_source=common.identity(copied), input_format=input_info,
            input={k: input_info[k] for k in ('path', 'bytes', 'sha256')}, preset=saved['preset'],
            before_library_archive_mapping=mappings, source_changed_files=changed,
            archive_comparison={'total': 54, 'identical': 39, 'changed': 15, 'changed_names': changed_targets,
                                'changed_libraries': changed_libraries, 'shared_DSP_all_identical': True},
            runtime_heap_probe=next(x for x in libraries if x['path'].endswith('.dylib')),
            native_link_anchor=anchor, cpu_window_s=20, child_timeout_s=150)
        record['clients']['before_wait'] = {key: before[key] for key in ('source', 'binary', 'object', 'depfile',
            'compiler', 'compiler_version', 'flags', 'flags_file', 'link_template', 'undefined_symbols',
            'prepare_ABI', 'contract_version', 'architectures', 'compile_command', 'link_command')}
        record['clients']['before_wait'].update(source_root=snap03['root'], dependencies=previous_deps,
            libraries=previous_libraries, native_version='candidate', reused_binary=True, reused_object=True,
            relinked=False, historical_build_root=before['build'])
        common.save(out / 'CLIENT.json', record)
        # Only after_wait is compiled and linked. Never relink the saved before object.
        record['commands'].append(frozen.run(command, build_dir, after_dir / 'compile.log'))
        dependencies = []
        for token in frozen.make_dependencies(dep):
            path = (build_dir / token).resolve();item = common.identity(path)
            if path == copied:
                item['origin'] = 'same_client_source'
            elif path.is_relative_to(source_root):
                relative = str(path.relative_to(source_root))
                common.require(m04.get(relative) == item['sha256'], 'after source/helper/header belongs to source04')
                item.update(origin='after_source_manifest', source_path=relative)
            else:
                common.require(not path.is_relative_to(Path(snap03['root'])), 'mixed before snapshot include')
                item['origin'] = 'toolchain_or_system'
            dependencies.append(item)
        common.require(dependency_signature(dependencies) == dependency_signature(previous_deps),
                       'all common body/helper/header/toolchain dependency byte identities')
        symbols = subprocess.check_output(['/usr/bin/nm', '-u', str(obj)], text=True)
        prepare = [line for line in symbols.splitlines() if 'ProgressiveMacPlaybackEngine' in line and 'prepare' in line]
        common.require(any('ContractV4Tag' in line for line in prepare) and not any('ContractV3Tag' in line for line in prepare), 'after V4 prepare ABI')
        (after_dir / 'undefined_symbols.txt').write_text(symbols)
        link = template.copy();link[objects[0]] = str(obj);link[outputs[0] + 1] = str(binary)
        common.require(sum(a != b for a, b in zip(template, link)) == 2, 'link changes only object/output')
        record['commands'].append(frozen.run(link, build_dir, after_dir / 'link.log'))
        for entry in (before, {'binary': common.identity(binary)}):
            common.require(subprocess.check_output(['/usr/bin/lipo', '-archs', entry['binary']['path']], text=True).split() == ['arm64'], 'arm64 client')
        record['clients']['after_wait'] = {'source': AFTER_SOURCE, 'source_root': str(source_root),
            'binary': common.identity(binary), 'object': common.identity(obj), 'depfile': common.identity(dep),
            'dependencies': dependencies, 'libraries': libraries, 'compiler': common.identity(compiler),
            'compiler_version': before['compiler_version'], 'flags': flags, 'flags_file': common.identity(flags_path),
            'link_template': common.identity(template_path), 'undefined_symbols': common.identity(after_dir / 'undefined_symbols.txt'),
            'prepare_ABI': 'ContractV4Tag', 'contract_version': 4, 'architectures': ['arm64'],
            'compile_command': command, 'link_command': link, 'native_version': 'candidate',
            'reused_binary': False, 'reused_object': False, 'relinked': True}
        record['dependency_equivalence'] = {'status': 'PASS', 'total': len(dependencies),
            'source_helper_header_files': sum(bool(d.get('source_path')) for d in dependencies),
            'same_body': True, 'same_all_dependencies_bytes': True, 'same_flags_macros': True, 'both_V4': True,
            'only_link_library_change': NATIVE_LIBRARY}
        # Recheck saved before executable/object and all current artifacts after the compile.
        for entry in record['clients'].values():
            for item in [entry[k] for k in ('binary', 'object', 'depfile', 'compiler', 'flags_file', 'link_template', 'undefined_symbols')] + entry['dependencies'] + entry['libraries']:
                common.require(common.identity(item['path']) == {k: item[k] for k in ('path', 'bytes', 'sha256')}, 'artifact changed during after compile')
        for snapshot in (snap03, snap04):
            common.require(common.current_source_digest(Path(snapshot['root'])) == snapshot['source'], 'saved source changed during compile')
        common.require(common.current_source_digest(source_root) == AFTER_SOURCE, 'current source changed during compile')
        for item in [record[k] for k in ('before_client', 'before_build', 'after_build', 'before_archive', 'after_archive', 'patch', 'source', 'before_copied_source', 'copied_source', 'runtime_heap_probe', 'native_link_anchor')] + record['helpers'] + [record['driver']]:
            common.require(common.identity(item['path']) == item, 'record/recipe changed during compile')
        for archive in (archive03, archive04):
            for row in archive:
                common.require(common.identity(row['archived']['path']) == row['archived'], 'archived file changed during compile')
                if 'current_original' in row:
                    common.require(common.identity(row['current_original']['path']) == row['current_original'], 'current original changed during compile')
        jobs = jobs_for(record, out / 'run_not_started')
        common.save(out / 'RUN_PLAN.json', {'schema': 'armed-wait-revision-pairs-v1', 'status': 'NOT_RUN',
            'expected_programs': 6, 'expected_checks': 48, 'repeats_per_version': 3,
            'all_expected_ids': [j['id'] for j in jobs], 'required_check_ids': list(original.CHECK_IDS), 'jobs': jobs,
            'cpu_window_s': 20, 'child_timeout_s': 150, 'input': record['input'], 'preset': record['preset'],
            'client_source_sha256': original.CLIENT_SOURCE_SHA, 'native_version_both': 'candidate',
            'sources': {label: e['source'] for label, e in record['clients'].items()},
            'callback_gate': False, 'performance_improvement_approval': False, 'quality_approval': False,
            'RT_approval': False, 'physical_audio': None, 'application_F': None, 'exploration_added_to_count': False})
        record.update(status='PASS', run_plan=common.identity(out / 'RUN_PLAN.json'))
        common.save(out / 'CLIENT.json', record)
        print(out / 'CLIENT.json');return 0
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__ + ': ' + str(error))
        common.save(out / 'CLIENT.json', record)
        raise


if __name__ == '__main__':
    sys.exit(main())
