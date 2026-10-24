"""Interactive120を選択実行できる同一clientを旧v3/候補v4へcompileする。native実行なし。

arm64 Python:
  build_interactive_generic_clients.py --candidate-build BUILD.json --candidate-source SHA \
  --candidate-archive ARCHIVE.json --candidate-snapshot SOURCE.json --output B/interactive_generic_clients_01
固定frozen_clients_02 / 明示候補BUILD+SOURCE+ARCHIVE+SNAPSHOT、music300 stereo44.1k。
候補は保存snapshotの全768ファイルとarchiveの全54保存物を検証して使う。
稼働中checkoutが別の候補でも、ヘッダ/9archive/probeを選択候補へ厳密に結び付ける。
原本の三重for直後への通常thread env selector一挿入だけ。未指定は元120件。
逆変換byte一致を検証。assert/FIFO/時刻/callback/回帰本体は変更しない。
24program×各5位置×旧新=48program/240cases、120秒process watchdogはrunner固定。
"""
import difflib
import argparse
import datetime
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys

import build_frozen_client as frozen
import build_seek_history_client as shared
import run_pairs as common

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
BODY = 'tests/Phase61InteractiveNativeTests.cpp'
SOURCE = ROOT / BODY
SOURCE_SHA = 'fdefd783388035582665fd63a0bd1bef7a886aee39707f2c236459477f19fc42'
DERIVED_SOURCE_SHA = 'dbbe107da21a114ab97a97a8bfb9e8c79617a377263f6ceaf0343288ee8a8287'
BASELINE_CLIENT_SHA = '45eca7d30805baea514d79eb2291ed359c2daa17f5c83d4269fea830a4447087'
INPUT_SHA = 'fc8be98125b35e0b2bde0728ef8ccfc60ab2aee4462b72f61c55733ae277cf58'

SELECTORS = ('TS_INTERACTIVE_SPEED_MICROS', 'TS_INTERACTIVE_PRESET', 'TS_INTERACTIVE_REPEAT')
POSITIONS = (1323000, 6615000, 11907000, 12568500, 3672645)
ANCHOR = b'    for(auto speed:{400000u,500000u,1000000u,2000000u})for(auto preset:{Preset::Candidate,Preset::Baseline})for(unsigned repeat=0;repeat<3;++repeat){\n'
INSERTION = b'''        // Normal control thread selection only; unset selectors retain all original 120 rows.
        const char* selectedSpeed=std::getenv("TS_INTERACTIVE_SPEED_MICROS");
        const char* selectedPreset=std::getenv("TS_INTERACTIVE_PRESET");
        const char* selectedRepeat=std::getenv("TS_INTERACTIVE_REPEAT");
        if((selectedSpeed&&std::string(selectedSpeed)!=std::to_string(speed))||
           (selectedPreset&&std::string(selectedPreset)!=(preset==Preset::Candidate?"candidate":"baseline"))||
           (selectedRepeat&&std::string(selectedRepeat)!=std::to_string(repeat)))continue;
'''


def derive_client(original):
    common.require(original.count(ANCHOR) == 1 and INSERTION not in original, 'one exact performance loop anchor')
    changed = original.replace(ANCHOR, ANCHOR + INSERTION, 1)
    common.require(changed.count(INSERTION) == 1 and changed.replace(INSERTION, b'', 1) == original,
                   'one insertion reverse reconstruction must equal original bytes')
    return changed


def normalized_link(tokens):
    values = tokens.copy()
    objects = [i for i, v in enumerate(values) if v.endswith('.o')]
    outputs = [i for i, v in enumerate(values) if v == '-o']
    common.require(len(objects) == len(outputs) == 1, 'one original object/output')
    values[objects[0]] = '<ONE_OBJECT>'
    values[outputs[0] + 1] = '<ONE_OUTPUT>'
    return values


def candidate_evidence(build_path, snapshot_path, archive_path, expected_source, start):
    # The selected metadata bytes were pinned before any compilation/output.
    for key, path in (('candidate_build', build_path), ('candidate_snapshot', snapshot_path), ('candidate_archive', archive_path)):
        common.require(common.identity(path) == start[key], 'CLI start identity changed: ' + key)
    build, snapshot, archive = (common.load(p) for p in (build_path, snapshot_path, archive_path))
    rows = snapshot['files'] if 'files' in snapshot else snapshot['source_manifest']['files']
    common.require(build['status'] == 'PASS' and build['configuration'] == 'Release' and build['architecture'] == 'arm64', 'candidate Release arm64 BUILD')
    common.require(build['source'] == snapshot['source'] == archive['source'] == expected_source
                   and build['source_manifest']['sha256'] == common.manifest_digest(rows) == expected_source
                   and rows == build['source_manifest']['files'] and len(rows) == 768
                   and len({r['path'] for r in rows}) == 768, 'complete 768-file candidate source identity')
    common.require(archive['build'] == start['candidate_build'] and archive['source_snapshot'] == start['candidate_snapshot'], 'archive binds selected BUILD and SNAPSHOT')
    if 'build' in snapshot:
        common.require(snapshot['build'] == start['candidate_build'], 'snapshot binds BUILD')
    root = snapshot_path.resolve().parent
    common.require(shared.source_digest(root) == expected_source, 'saved candidate full source bytes')
    files = []
    for row in rows:
        p = (root / row['path']).resolve();common.require(p.is_relative_to(root), 'source path outside snapshot')
        item = common.identity(p);common.require(item['sha256'] == row['sha256'], 'snapshot file SHA: ' + row['path'])
        files.append({**item, 'source_path': row['path']})
    entries, archived_files = {}, []
    common.require(len(archive['files']) == 54, 'complete candidate archive of 54 targets')
    for row in archive['files']:
        old, saved = row['original'], row['archived'];name = Path(old['path']).name
        common.require(name not in entries and Path(saved['path']).name == name, 'unique archive target')
        common.require(old['bytes'] == saved['bytes'] and old['sha256'] == saved['sha256']
                       and common.identity(saved['path']) == saved, 'candidate archived actual bytes: ' + name)
        entries[name] = row
        archived_files.append({'name': name, 'archived': saved, 'historical_original_path': old['path'],
                               'historical_original_bytes': old['bytes'], 'historical_original_sha256': old['sha256']})
    return build, root, {'record': start['candidate_snapshot'], 'source': expected_source, 'root': str(root), 'files': files}, entries, archived_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-client', type=Path, default=BASE / 'frozen_clients_02/CLIENT.json')
    parser.add_argument('--candidate-build', type=Path, required=True)
    parser.add_argument('--candidate-source', required=True, help='完全source台帳SHA-256')
    parser.add_argument('--candidate-archive', type=Path, required=True)
    parser.add_argument('--candidate-snapshot', type=Path, required=True)
    parser.add_argument('--input', type=Path, default=ROOT / 'build/phase61_fast_seek/music_300s.wav')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    candidate_source = args.candidate_source
    common.require(len(candidate_source) == 64 and all(c in '0123456789abcdef' for c in candidate_source), 'explicit candidate source SHA')
    start = {key: common.identity(getattr(args, key)) for key in ('candidate_build', 'candidate_archive', 'candidate_snapshot')}
    out = args.output.resolve()
    common.require(out.is_relative_to(ROOT / 'build'), 'generated clients belong under build/')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'performance-interactive-generic-clients-v1', 'status': 'INCOMPLETE', 'compile_only': True,
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'driver': common.identity(__file__), 'helpers': [common.identity(m.__file__) for m in (frozen, shared, common)],
              'clients': {}, 'commands': [], 'candidate_start_inputs': start, 'candidate_requested_source': candidate_source}
    try:
        common.require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'native arm64 macOS Python required')
        common.require(not any(os.environ.get(k) for k in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH',
                       'OBJC_INCLUDE_PATH', 'LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES')), 'ambient include/library override')
        baseline = common.load(args.baseline_client)
        common.require(common.identity(args.baseline_client)['sha256'] == BASELINE_CLIENT_SHA, 'fixed frozen02 baseline record')
        candidate, candidate_root, snapshot_evidence, archive_entries, archive_files = candidate_evidence(
            args.candidate_build, args.candidate_snapshot, args.candidate_archive, candidate_source, start)
        common.require(baseline['schema'] == 'performance-frozen-client-v1' and baseline['status'] == candidate['status'] == 'PASS', 'PASS build records required')
        common.require(baseline['baseline_commit'] == frozen.OLD_COMMIT and baseline['baseline_source'] == frozen.OLD_SOURCE_SHA and baseline['contract_version'] == 3, 'fixed 5674 v3 baseline required')
        common.require(common.identity(baseline['baseline_build_record']['path']) == baseline['baseline_build_record'], 'baseline BUILD changed')
        common.require(common.identity(baseline['flags_file']['path']) == baseline['flags_file'] and common.identity(baseline['link_template']['path']) == baseline['link_template'], 'frozen02 compile/link template identity')
        old = common.load(Path(baseline['baseline_build_record']['path']))
        common.require(old['source'] == baseline['baseline_source'], 'baseline source mismatch')
        common.require(set(baseline['link_inputs']) == set(frozen.OLD_LINK_SHA), 'baseline link-input set')
        common.require(sum(n.endswith('.a') for n in baseline['link_inputs']) == 9 and sum(n.endswith('.dylib') for n in baseline['link_inputs']) == 1, 'nine archives and one heap probe required')
        for name, item in baseline['link_inputs'].items():
            common.require(common.identity(item['path']) == item and item['sha256'] == frozen.OLD_LINK_SHA[name], 'baseline archive/probe SHA: ' + name)
        input_info = common.wav_identity(args.input, 44100, 2)
        common.require(input_info['sha256'] == INPUT_SHA, 'fixed music300 stereo441 input SHA required')
        source_id = common.identity(SOURCE)
        common.require(source_id['sha256'] == SOURCE_SHA, 'fixed original Interactive source SHA required')
        source = out / 'client.cpp'
        original = SOURCE.read_bytes()
        copied_original = out / 'ORIGINAL.cpp'
        copied_original.write_bytes(original)
        changed = derive_client(original)
        source.write_bytes(changed)
        common.require(common.identity(source)['sha256'] == DERIVED_SOURCE_SHA, 'fixed one-insertion client SHA')
        patch = out / 'NORMAL_SELECTOR.patch'
        patch.write_text(''.join(difflib.unified_diff(original.decode().splitlines(keepends=True),
                         changed.decode().splitlines(keepends=True), fromfile=BODY, tofile='client.cpp')))
        common.require(common.identity(copied_original)['sha256'] == source_id['sha256'], 'original copy changed')
        record.update(source=source_id, copied_source=common.identity(source),
                      baseline_client=common.identity(args.baseline_client), baseline_build=baseline['baseline_build_record'],
                      baseline_link_inputs=list(baseline['link_inputs'].values()), candidate_build=common.identity(args.candidate_build),
                      input={k: input_info[k] for k in ('path', 'bytes', 'sha256')}, input_format=input_info,
                      baseline_commit=frozen.OLD_COMMIT, baseline_source=frozen.OLD_SOURCE_SHA,
                      candidate_source=candidate_source, candidate_snapshot=snapshot_evidence, candidate_archive=start['candidate_archive'],
                      candidate_archive_files=archive_files, expected_programs=48, expected_cases=240,
                      original_copy=common.identity(copied_original), selector_patch=common.identity(patch),
                      transformation={'one_insertion': True, 'removed_bytes_equal_original': True,
                         'selector_env': list(SELECTORS), 'default_all120_preserved': True,
                         'normal_thread_only': True, 'asserts_FIFO_callback_timing_unchanged': True},
                      client_extra_defines=['-DPHASE61_INTERACTIVE_CONTRACT=1'],
                      quality_approval=False, realtime_approval=False, public_approved=False)
        for version, build in (('old', old), ('candidate', candidate)):
            original_root = Path(build['source_root']).resolve()
            root = original_root if version == 'old' else candidate_root
            common.require(build['status'] == 'PASS' and build['architecture'] == 'arm64' and build['configuration'] == 'Release', 'Release arm64 build required')
            common.require(shared.digest(build['source_manifest']['files']) == build['source'] == build['source_manifest']['sha256'], 'manifest content SHA')
            common.require(shared.source_digest(root) == build['source'], version + ' source changed after build')
            source_map = {row['path']: row['sha256'] for row in build['source_manifest']['files']}
            common.require(source_map[BODY] == SOURCE_SHA, 'same original body in old/new frozen inventories')
            build_dir = (Path(baseline['baseline_build']) if version == 'old' else Path(build['binaries']['phase62_control_cpu_native']['path']).parent).resolve()
            template_path = build_dir / 'CMakeFiles/phase61_interactive_native_tests.dir/link.txt'
            flags_path = build_dir / 'CMakeFiles/phase61_interactive_native_tests.dir/flags.make'
            template, flags = shlex.split(template_path.read_text()), frozen.flags_from_make(flags_path)
            saved_template, saved_flags = template.copy(), {k: v.copy() for k, v in flags.items()}
            if version == 'old':
                common.require(flags == frozen.flags_from_make(Path(baseline['flags_file']['path'])), 'original Interactive flags differ from frozen old flags')
                common.require(normalized_link(template) == normalized_link(shlex.split(Path(baseline['link_template']['path']).read_text())), 'original Interactive links differ beyond one object/output')
            else:
                anchor = build['binaries']['phase62_control_cpu_native']
                common.require(archive_entries[Path(anchor['path']).name]['original'] == anchor, 'candidate BUILD anchor archive identity')
            objects = [i for i, token in enumerate(template) if token.endswith('.o')]
            outputs = [i for i, token in enumerate(template) if token == '-o']
            common.require(len(objects) == len(outputs) == 1 and outputs[0] + 1 < len(template), 'one link object/output')
            compiler = template[0]
            common.require(Path(compiler).is_absolute() and flags['CXX_INCLUDES'] == ['-I' + str(original_root / 'src')], 'compiler/include path')
            common.require(not flags['CXX_DEFINES'] and '-std=c++20' in flags['CXX_FLAGS'] and '-O3' in flags['CXX_FLAGS'], 'Release C++20 flags')
            frozen_flags = frozen.flags_from_make(Path(baseline['flags_file']['path']))
            common.require(saved_flags['CXX_FLAGS'] == frozen_flags['CXX_FLAGS'] and saved_flags['CXX_DEFINES'] == frozen_flags['CXX_DEFINES'], 'same Release compiler flags/macros across versions')
            libraries = []
            for token_index, token in enumerate(saved_template[1:], 1):
                if token.endswith(('.a', '.dylib')):
                    if version == 'old':
                        item = common.identity(build_dir / token)
                        common.require(baseline['link_inputs'].get(Path(token).name) == item, 'old link dependency differs from frozen client')
                    else:
                        entry = archive_entries.get(Path(token).name)
                        common.require(entry is not None and Path(entry['original']['path']).resolve() == (build_dir / token).resolve(), 'candidate native link input archive mapping')
                        item = entry['archived'];template[token_index] = item['path']
                    libraries.append(item)
            common.require(len(libraries) == 10 and sum(i['path'].endswith('.a') for i in libraries) == 9 and sum(i['path'].endswith('.dylib') for i in libraries) == 1, 'nine archives plus one dylib')
            link_adjustments = []
            if version == 'candidate':
                flags['CXX_INCLUDES'] = ['-I' + str(root / 'src')]
                # All selected shared libraries/probe come from one verified archive.
                probe = next(item for item in libraries if item['path'].endswith('.dylib'))
                rpaths = [i for i, token in enumerate(template) if token.startswith('-Wl,-rpath,')]
                common.require(len(rpaths) == 1 and template[rpaths[0]] == '-Wl,-rpath,' + str(build_dir), 'one native rpath')
                template[rpaths[0]] = '-Wl,-rpath,' + str(Path(probe['path']).parent)
                link_adjustments = [{'index': i, 'before': a, 'after': b} for i, (a, b) in enumerate(zip(saved_template, template)) if a != b]
                common.require(len(link_adjustments) == 11, 'exactly ten archive paths and one rpath relocation')
            directory = out / version
            directory.mkdir()
            obj, dep, binary = directory / 'client.o', directory / 'client.d', directory / 'interactive_selected_native'
            compile_command = [compiler, *flags['CXX_DEFINES'], '-DPHASE61_INTERACTIVE_CONTRACT=1', *flags['CXX_INCLUDES'], '-I' + str(root / 'tests'),
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
                    common.require(not any(path.is_relative_to(p) for p in (Path(old['source_root']).resolve(), Path(candidate['source_root']).resolve(), candidate_root)), 'mixed old/candidate source')
                    item['origin'] = 'toolchain_or_system'
                dependencies.append(item)
            for needed in ('tests/Phase61NativeTests.cpp', 'tests/Phase61CallbackMallocProbe.h', 'src/platform/macos/ProgressiveMacPlaybackEngine.h'):
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
                'flags': flags, 'original_flags': saved_flags, 'original_link_tokens': saved_template,
                'selected_link_tokens': template, 'link_adjustments': link_adjustments, 'include_relocation': version == 'candidate',
                'flags_file': common.identity(flags_path), 'link_template': common.identity(template_path),
                'undefined_symbols': common.identity(directory / 'undefined_symbols.txt'), 'prepare_ABI': tag,
                'contract_version': 3 if version == 'old' else 4, 'architectures': architectures,
                'compile_command': compile_command, 'link_command': link_command}
            common.save(out / 'CLIENT.json', record)
        for version, build in (('old', old), ('candidate', candidate)):
            common.require(shared.source_digest(Path(record['clients'][version]['source_root'])) == build['source'], version + ' source changed during compile')
            for item in record['clients'][version]['dependencies'] + record['clients'][version]['libraries']:
                common.require(common.identity(item['path'])['sha256'] == item['sha256'], 'final dependency SHA')
        common.require(common.identity(SOURCE) == source_id and common.identity(source) == record['copied_source'] and
                       common.identity(copied_original) == record['original_copy'] and common.identity(patch) == record['selector_patch'] and
                       common.identity(args.baseline_client) == record['baseline_client'] and
                       common.identity(args.candidate_build) == record['candidate_build'], 'source/build record changed')
        common.require(common.identity(input_info['path']) == record['input'], 'fixed input changed during compile')
        for item in record['helpers'] + [record['driver']]:
            common.require(common.identity(item['path']) == item, 'recipe/helper changed during compile')
        common.require(source.read_bytes() == derive_client(copied_original.read_bytes()), 'reverse proof/source drift')
        jobs = []
        for repeat in (0, 1, 2):
            for speed in (400000, 500000, 1000000, 2000000):
                for preset in ('candidate', 'baseline'):
                    pair = f's{speed}_{preset}_r{repeat}'
                    for version in (('old', 'candidate') if repeat % 2 == 0 else ('candidate', 'old')):
                        entry, key = record['clients'][version], pair + '_' + version
                        jobs.append({'id': key, 'pair_id': pair, 'repeat': repeat, 'version': version,
                            'preset': preset, 'speed_micros': speed, 'expected_rows': 5,
                            'environment': dict(zip(SELECTORS, (str(speed), preset, str(repeat)))),
                            'command': [entry['binary']['path'], input_info['path'], str(out / 'run_not_started' / key)]})
        common.require(len(jobs) == len({j['id'] for j in jobs}) == 48, 'fixed complete 48-program plan')
        common.save(out / 'RUN_PLAN.json', {'schema': 'interactive-generic-pairs-v1', 'status': 'NOT_RUN',
            'expected_programs': 48, 'expected_cases': 240, 'expected_cases_per_version': 120,
            'jobs': jobs, 'all_expected_ids': [j['id'] for j in jobs], 'input': record['input'],
            'original_source_sha256': source_id['sha256'], 'client_source_sha256': record['copied_source']['sha256'],
            'positions': list(POSITIONS), 'speeds_micros': [400000, 500000, 1000000, 2000000],
            'preset_names': ['candidate', 'baseline'], 'repeat_values': [0, 1, 2],
            'order': 'repeat0 old/candidate; repeat1 candidate/old; repeat2 old/candidate; speed then preset',
            'ready_target_p95_ms': 200, 'goal_scope': 'each version all120 combined FIFO Ready; 2x subgroup separate',
            'process_timeout_s': 120, 'timeout_allowed': False,
            'cost_scope': 'native accepted-to-FIFO and accepted-to-first PCM timestamps; external process cost separate',
            'physical_audio': None, 'application_F': None, 'quality_approval': False, 'public_approved': False})
        for item in start.values():
            common.require(common.identity(item['path']) == item, 'candidate CLI identity changed from start')
        for row in archive_files:
            common.require(common.identity(row['archived']['path']) == row['archived'], 'candidate archive changed during compile')
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
