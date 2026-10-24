#!/usr/bin/env python3
"""mono1倍CPU: 旧5674/保存08/新09を固定n3・3版9programで直列比較する。

 /path/to/arm64/python3 -B results/performance_response/recipes/run_mono1_digest_on_ablation.py \
   --new-build B/build_experiment_09/BUILD.json --new-source SOURCE_SHA64 \
   --output B/mono1_digest_on_ablation_01

同一PerformanceSteadyNative本文、chain300 mono48、Candidate、1.0倍、30秒。
順序はr1=old5674/saved08/new09、r2=saved08/new09/old5674、r3=new09/old5674/saved08。
08は必ず保存archive内の既link済み実行体を使い、candidate同名実行体へ置換しない。
旧baselineの.aは後日固定CLIENTのSHAへ照合する。旧BUILD自体が当時個別archive
SHAを持っていたとは主張しない。Mach-Oからprobeの実解決先も確認する。
CPUは記述統計のみ。RT/収録完了と分離し、改善・非悪化・採用を自動承認しない。
"""

import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
COMMON = Path(__file__).with_name('run_pairs.py')
COMMON_SHA = 'a92c133f2a33d8c4ff23153218aadb22e12304edba3674bb0df10d6b080515fb'
OLD_SOURCE = '2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392'
SAVED_SOURCE = 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94'
CLIENT_SHA = '45eca7d30805baea514d79eb2291ed359c2daa17f5c83d4269fea830a4447087'
ARCHIVE_SHA = '8559063d9905dddabe366c225368e27ba628250042d4e79877bd8162aae14f3a'
SNAPSHOT_SHA = 'f2304408ea89ba72b4d0c2dc3f1e8d609b1a780b69d0835f854586d4016515ad'
BUILD08_SHA = '6a1ea92a6b968e916ce416f7e74e69b2a421cb7b4ee9392759fda3fbec97454f'
REVIEWED_CPP_SHA = 'c12dee6510abcc9295f72634b127c144ad01c21abd6dfeade9a9aa8d81e0d76b'
DERIVED_BASE = Path(__file__).with_name('run_mono2_digest_ablation.py')
DERIVED_BASE_SHA = '866c3f5dac667e513e81810aebad34539220ad574cccf5c9896788c6a84e6916'
BODY = 'tests/PerformanceSteadyNative.cpp'
BODY_SHA = '696004d7cf55101529590fb0ce7c9137c12fcc9dd811a9765aacb40c7ba0e1a6'
INPUT_SHA = '13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0'
PROBE = 'libphase61_callback_heap_probe.dylib'
LABELS = ('old5674', 'saved08', 'new09')
ORDERS = (LABELS, ('saved08', 'new09', 'old5674'), ('new09', 'old5674', 'saved08'))
ALLOWED_CHANGES = {'src/prototype/Phase57ProgressiveSynthesis.cpp'}
SCOPE = {'CPU_approval': False, 'adoption_approved': False, 'quality_approval': False,
         'physical_audio': None, 'application_F': None,
         'statistics': 'Descriptive n3 only; no significance/tolerance/automatic non-regression acceptance.',
         'CPU_scope': 'Native 30-second process user+system/wall window; wait4 whole child cost is separate.',
         'history': '9 new programs only; prior steady48/followup18/Armed/OFF07 comparisons not added.',
         'ordinary_speed_requests': 'Fixed initial speed; no new Accepted speed-operation audit is claimed.',
         'stage_digest_setting': 'old5674 unconditional ON; saved08/new09 native option default ON, profiles OFF',
         'historical_result': 'Old experiment07 OFF/mono2 failure remains REJECTED; this ON/mono1 source09 is a distinct condition.',
         'rejection_policy': 'No CPU improvement means reject this isolated experiment; no automatic adoption or extra repetitions.'}


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def read(path):
    def pairs(items):
        value = {}
        for key, child in items:
            need(key not in value, 'Duplicate JSON key: ' + key)
            value[key] = child
        return value
    def reject(value):
        raise ValueError('Nonfinite JSON: ' + value)
    value = json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=reject)
    def finite(child):
        if isinstance(child, dict):
            for v in child.values():
                finite(v)
        elif isinstance(child, list):
            for v in child:
                finite(v)
        elif type(child) is float:
            need(math.isfinite(child), 'Nonfinite JSON number')
    finite(value)
    return value


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def load_common():
    need(hashlib.sha256(COMMON.read_bytes()).hexdigest() == COMMON_SHA, 'Original run_pairs source changed')
    spec = importlib.util.spec_from_file_location('mono1_fixed_run_pairs', COMMON)
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    return common


def checked(common, record):
    actual = common.identity(record['path'])
    need(all(actual[k] == record[k] for k in ('path', 'bytes', 'sha256')), 'Identity differs: ' + record['path'])
    return actual


def pinned(common, path, expected_sha):
    item = common.identity(path)
    need(item['sha256'] == expected_sha, 'Pinned metadata differs: ' + str(path))
    return item, read(path)


def source_map(common, value, source):
    rows = value['source_manifest']['files']
    count = 752 if source == OLD_SOURCE else 768
    need(value['source'] == value['source_manifest']['sha256'] == common.manifest_digest(rows) == source
         and len(rows) == count and len({r['path'] for r in rows}) == count, 'Complete fixed source ledger')
    return {row['path']: row['sha256'] for row in rows}


def flags(path):
    result = {}
    for line in path.read_text().splitlines():
        match = re.match(r'^(CXX_DEFINES|CXX_INCLUDES|CXX_FLAGS)\s*=\s*(.*)$', line)
        if match:
            result[match[1]] = shlex.split(match[2])
    need(set(result) == {'CXX_DEFINES', 'CXX_INCLUDES', 'CXX_FLAGS'}, 'Complete target compile flags')
    return result


def tool(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    need(result.returncode == 0 and not result.stderr.strip(), 'Metadata tool failed/warned: ' + str(command))
    return {'command': command, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}


def linkage(common, binary, expected_probe):
    """既定dyld環境で、非system依存probeの解決先をLC_RPATHから固定する。"""
    path = Path(binary['path'])
    arch = tool(['/usr/bin/lipo', '-archs', str(path)])
    need(arch['stdout'].split() == ['arm64'], 'Native arm64 executable required')
    loaded = tool(['/usr/bin/otool', '-L', str(path)])
    commands = tool(['/usr/bin/otool', '-l', str(path)])
    dependencies = [line.strip().split(' (compatibility', 1)[0] for line in loaded['stdout'].splitlines()[1:] if line.strip()]
    rpaths = []
    lines = commands['stdout'].splitlines()
    for i, line in enumerate(lines):
        if line.strip() == 'cmd LC_RPATH':
            match = re.search(r'^\s*path (.+) \(offset \d+\)\s*$', '\n'.join(lines[i + 1:i + 5]), re.MULTILINE)
            need(match is not None, 'Cannot decode LC_RPATH')
            rpaths.append(match.group(1))
    def expand(text):
        if text.startswith('@loader_path/'):
            return path.parent / text[len('@loader_path/'):]
        if text.startswith('@executable_path/'):
            return path.parent / text[len('@executable_path/'):]
        need(text.startswith('/'), 'Unsupported dyld path: ' + text)
        return Path(text)
    product = [p for p in dependencies if not p.startswith(('/System/Library/', '/usr/lib/'))]
    need(len(product) == 1 and Path(product[0]).name == PROBE, 'Unexpected non-system dynamic dependency')
    reference = product[0]
    candidates = ([expand(p) / reference[len('@rpath/'):] for p in rpaths]
                  if reference.startswith('@rpath/') else [expand(reference)])
    existing = [p.resolve() for p in candidates if p.is_file()]
    need(bool(existing), 'No actual dyld heap probe resolution')
    probe = common.identity(existing[0])
    need(probe['bytes'] == expected_probe['bytes'] and probe['sha256'] == expected_probe['sha256'],
         'Resolved runtime probe differs from its immutable version archive')
    probe_loads = tool(['/usr/bin/otool', '-L', probe['path']])
    extra = [line.strip().split(' (compatibility', 1)[0] for line in probe_loads['stdout'].splitlines()[1:] if line.strip()]
    need(all(p.startswith(('/System/Library/', '/usr/lib/')) or p == reference or
             p == '@rpath/' + PROBE for p in extra), 'Unexpected transitive non-system probe dependency')
    return {'binary': binary, 'architecture': arch, 'loads': loaded, 'load_commands': commands,
            'LC_RPATH': rpaths, 'probe_reference': reference, 'ordered_probe_candidates': list(map(str, candidates)),
            'resolved_probe': probe, 'probe_loads': probe_loads,
            'scope': 'Default dyld paths, environment overrides forbidden; system dylibs not independently rehashed.'}


def capacity(input_bytes):
    paths = {str(Path(tempfile.gettempdir()).resolve()), str(Path('/tmp').resolve())}
    for name in ('TMPDIR', 'TMP', 'TEMP', 'TEMPDIR'):
        if os.environ.get(name):
            path = Path(os.environ[name]).resolve()
            need(path.is_dir(), 'Configured native temp directory unavailable: ' + name)
            paths.add(str(path))
    required = input_bytes + 256 * 1024 * 1024
    result = []
    for name in sorted(paths):
        free = shutil.disk_usage(name).free
        result.append({'path': name, 'free_bytes': free, 'input_bytes': input_bytes,
                       'reserve_bytes': 256 * 1024 * 1024, 'required_bytes': required, 'pass': free >= required})
    need(all(row['pass'] for row in result), 'Input copy plus 256MiB reserve unavailable on temp volume')
    return result


def jobs_for(hosts, input_id, out):
    jobs = []
    for repeat, order in enumerate(ORDERS, 1):
        for label in order:
            name = f'mono1_candidate_r{repeat:02d}_{label}'
            jobs.append({'id': name, 'repeat': repeat, 'label': label, 'version': label, 'preset': 'candidate',
                         'input': 'mono48chain300s', 'speed': 1.0, 'source': hosts[label]['source'],
                         'command': [hosts[label]['binary']['path'], input_id['path'], 'candidate', '1.0',
                                     '30', str(out / name)]})
    return jobs


def preflight(common, args, out):
    need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native arm64 macOS Python required')
    need(not any(k.startswith('DYLD_') and v for k, v in os.environ.items()), 'Ambient dyld override forbidden')
    base_id, base = pinned(common, BASE / 'frozen_clients_02/CLIENT.json', CLIENT_SHA)
    arc_id, arc = pinned(common, BASE / 'native_archive_08/ARCHIVE.json', ARCHIVE_SHA)
    snap_id, snap = pinned(common, BASE / 'native_source_08/SOURCE.json', SNAPSHOT_SHA)
    build08_id, build08 = pinned(common, BASE / 'build_native_default_08/BUILD.json', BUILD08_SHA)
    new_id, new = common.identity(args.new_build.resolve()), read(args.new_build)
    need(new['status'] == build08['status'] == 'PASS' and new['configuration'] == build08['configuration'] == 'Release'
         and new['architecture'] == build08['architecture'] == 'arm64' and new['source'] == args.new_source,
         'PASS Release arm64 builds and explicit new source')
    old_build_id = checked(common, base['baseline_build_record'])
    old_build = read(old_build_id['path'])
    need(old_build['status'] == 'PASS' and old_build['configuration'] == 'Release'
         and old_build['architecture'] == 'arm64', 'Old5674 Release arm64 build')
    need(base['status'] == 'PASS' and base['baseline_commit'] == common.OLD_COMMIT
         and base['baseline_source'] == OLD_SOURCE and base['contract_version'] == 3,
         'Fixed independent old5674 V3 client')
    old_map = source_map(common, old_build, OLD_SOURCE)
    saved_map = source_map(common, snap, SAVED_SOURCE)
    need(source_map(common, build08, SAVED_SOURCE) == saved_map and arc['build'] == build08_id
         and arc['source_snapshot'] == snap_id and arc['source'] == SAVED_SOURCE, 'Saved08 archive/build/source binding')
    new_map = source_map(common, new, args.new_source)
    need(set(new_map) == set(saved_map), 'Same complete768 source file set')
    changes = sorted(p for p in new_map if new_map[p] != saved_map[p])
    need(bool(changes) and set(changes) <= ALLOWED_CHANGES, 'Experiment09 must change only Phase57 block digest dispatch')
    draft_path = BASE / 'stage_digest_experiment07_draft/after.cpp'
    draft_id = common.identity(draft_path)
    need(draft_id['sha256'] == new_map['src/prototype/Phase57ProgressiveSynthesis.cpp'] == REVIEWED_CPP_SHA,
         'Exact reviewed ON/OFF block-dispatch CPP body, not historical OFF experiment metadata')
    need(new_map['src/platform/macos/ProgressiveMacPlaybackEngine.h'] == saved_map['src/platform/macos/ProgressiveMacPlaybackEngine.h'],
         'Native hash-ON default header unchanged')
    new_root = Path(new['source_root']).resolve()
    need(new_root.is_relative_to(BASE) and new_root != ROOT.resolve() and new_root != (BASE / 'native_source_08').resolve() and
         not out.is_relative_to(new_root), 'Experiment09 must use a separate B-owned source root; ROOT08 stays unchanged')
    need(saved_map[BODY] == new_map[BODY] == base['clients']['steady']['source']['sha256'] ==
         base['clients']['steady']['copied_source']['sha256'] == BODY_SHA, 'Same common steady native body')
    input_id = common.wav_identity(ROOT / 'results/phase56/long/chain_300s.wav', 48000, 1)
    need(input_id['sha256'] == INPUT_SHA and input_id['frames'] == 14400000 and input_id['sample_format'] == 'Float32',
         'Fixed Float32 mono48 chain300')
    initial_space = capacity(input_id['bytes'])
    roots = [{'label': 'old5674', 'root': str(Path(base['old_source_root']).resolve()), 'source': OLD_SOURCE},
             {'label': 'saved08', 'root': str((BASE / 'native_source_08').resolve()), 'source': SAVED_SOURCE},
             {'label': 'new09', 'root': str(new_root), 'source': args.new_source},
             {'label': 'ROOT08_guard', 'root': str(ROOT.resolve()), 'source': SAVED_SOURCE}]
    for row in roots:
        need(common.current_source_digest(Path(row['root'])) == row['source'], 'Current/saved full source differs: ' + row['label'])
    headers = []
    for row, mapped, tag in zip(roots, (old_map, saved_map, new_map), (3, 4, 4)):
        for name in ('src/platform/macos/ProgressiveMacPlaybackEngine.h', 'src/playback/ProgressiveContract.h',
                     'src/playback/ProgressiveLoopContract.h', 'src/prototype/Phase58RealtimePipeline.h',
                     'src/prototype/Phase35PhaseVocoder.h', 'src/prototype/Phase35StereoPhaseCoherence.h',
                     'tests/Phase62InitialLoopNative.cpp', BODY):
            if row['label'] == 'old5674' and name == BODY:
                # 共通host本文はbaseline source752の後で追加し、旧V3 headers/libsへ個別linkした。
                item = checked(common, base['clients']['steady']['copied_source'])
                headers.append({'label': row['label'], 'relative': name, 'identity': item,
                                'contract_version': tag, 'origin': 'frozen02 external common host body'})
                continue
            item = common.identity(Path(row['root']) / name)
            need(item['sha256'] == mapped[name], 'Frozen source/header identity: ' + row['label'] + '/' + name)
            headers.append({'label': row['label'], 'relative': name, 'identity': item, 'contract_version': tag})
    by_name = {}
    need(arc['status'] == 'PASS' and len(arc['files']) == 54 and len(arc['extra_target_files']) == 6 and
         len({Path(x['original']['path']).name for x in arc['files'] + arc['extra_target_files']}) == 60, 'Saved08 complete unique54+6 archive')
    for row in arc['files']:
        original, archived = row['original'], row['archived']
        name = Path(archived['path']).name
        need(name not in by_name and all(original[k] == archived[k] for k in ('bytes', 'sha256'))
             and Path(archived['path']).resolve().is_relative_to(BASE / 'native_archive_08'), 'Unique immutable08 archive member')
        by_name[name] = row
    setting = {}
    for row in roots[:3]:
        root = Path(row['root'])
        header = (root / 'src/platform/macos/ProgressiveMacPlaybackEngine.h').read_text()
        synthesis = (root / 'src/prototype/Phase57ProgressiveSynthesis.cpp').read_text()
        if row['label'] == 'old5674':
            need('recordStageDigests' not in synthesis and all(re.search(r'hashFloat\(digests\.'+name+r'\s*,', synthesis)
                 for name in ('lowFir', 'highFir', 'fir')), 'Old5674 actual unconditional stage hash code')
            setting[row['label']] = 'unconditional legacy hashes; no ON/OFF setting'
        else:
            need(re.search(r'bool\s+recordStageDigests\s*=\s*true\s*;', header), 'Native08/09 default stage hashes must be ON')
            setting[row['label']] = 'recordStageDigests=true default; fixed host has no override'
    need('recordStageDigests' not in (Path(roots[1]['root']) / BODY).read_text(), 'Common normal steady body must not override native ON default')
    saved_host = by_name['performance_steady_native']['archived']
    need(all(saved_host[k] == build08['binaries']['performance_steady_native'][k] for k in ('bytes', 'sha256')),
         'Saved08 host is the recorded08 build; never use current candidate host for08')
    hosts = {'old5674': {'source': OLD_SOURCE, 'binary': base['clients']['steady']['binary'], 'contract_version': 3},
             'saved08': {'source': SAVED_SOURCE, 'binary': saved_host, 'contract_version': 4},
             'new09': {'source': args.new_source, 'binary': new['binaries']['performance_steady_native'], 'contract_version': 4}}
    need(base['clients']['steady']['copied_source']['sha256'] == BODY_SHA, 'Immutable old native body')
    inventory = [base_id, arc_id, snap_id, build08_id, new_id, old_build_id, common.identity(__file__),
                 common.identity(COMMON), checked(common, base['clients']['steady']['source']),
                 checked(common, base['clients']['steady']['copied_source']),
                 checked(common, base['clients']['steady']['object']), checked(common, base['clients']['steady']['depfile']),
                 checked(common, base['compiler']), *[row['identity'] for row in headers],
                 {k: input_id[k] for k in ('path', 'bytes', 'sha256')}]
    libraries = {'old5674': list(base['link_inputs'].values()), 'saved08': [], 'new09': []}
    for name in base['link_inputs']:
        need(name in by_name, 'Same nine-library plus probe set')
        libraries['saved08'].append(by_name[name]['archived'])
    new_dir = Path(hosts['new09']['binary']['path']).parent.resolve()
    need(new_dir.is_relative_to(BASE) and new_dir != (BASE / 'candidate').resolve(), 'Use isolated09 build directory; do not overwrite live08 candidate')
    link_path = new_dir / 'CMakeFiles/performance_steady_native.dir/link.txt'
    flags_path = new_dir / 'CMakeFiles/performance_steady_native.dir/flags.make'
    link = shlex.split(link_path.read_text())
    tokens = [t for t in link if t.endswith(('.a', '.dylib'))]
    need(len(tokens) == len(set(Path(t).name for t in tokens)) == 10
         and set(Path(t).name for t in tokens) == set(base['link_inputs']), 'New09 exact nine archives/probe link set')
    libraries['new09'] = [common.identity((new_dir / t).resolve()) for t in tokens]
    new_flags = flags(flags_path)
    need(new_flags['CXX_FLAGS'] == base['compile_flags']['CXX_FLAGS']
         and new_flags['CXX_DEFINES'] == base['compile_flags']['CXX_DEFINES']
         and new_flags['CXX_INCLUDES'] == ['-I' + str(Path(new['source_root']).resolve() / 'src')],
         'Common Release compiler flags, no extra preset/profile/optimization macro')
    compile_id = checked(common, new['compile_commands'])
    compilation = read(compile_id['path'])
    source_rows = [r for r in compilation if Path(r['file']).resolve() == Path(new['source_root']).resolve() / BODY]
    need(len(source_rows) == 1, 'One actual new09 steady compilation command')
    command = source_rows[0].get('arguments') or shlex.split(source_rows[0]['command'])
    compiler = common.identity(command[0])
    need(compiler == base['compiler'], 'Same actual compiler')
    need('-o' in command and '-std=c++20' in command and '-O3' in command and '-DNDEBUG' in command,
         'Actual steady compile command configuration')
    object_path = (Path(source_rows[0]['directory']) / command[command.index('-o') + 1]).resolve()
    inventory.extend([compile_id, common.identity(link_path), common.identity(flags_path), compiler,
                      common.identity(object_path), common.identity(str(object_path) + '.d')])
    linkages = {}
    for label in LABELS:
        need(len(libraries[label]) == 10, 'All mathematical link inputs recorded: ' + label)
        inventory.extend(libraries[label])
        checked(common, hosts[label]['binary'])
        inventory.append(hosts[label]['binary'])
        probe = next(item for item in libraries[label] if Path(item['path']).name == PROBE)
        linkages[label] = linkage(common, hosts[label]['binary'], probe)
        inventory.append(linkages[label]['resolved_probe'])
    need(all(linkages[label]['resolved_probe']['sha256'] == linkages['saved08']['resolved_probe']['sha256']
             for label in LABELS), 'Same actual callback heap probe for all three versions')
    phase57_rows = [r for r in compilation if Path(r['file']).resolve() == new_root / 'src/prototype/Phase57ProgressiveSynthesis.cpp']
    need(len(phase57_rows) == 1, 'One actual new09 Phase57 compilation')
    phase57_command = phase57_rows[0].get('arguments') or shlex.split(phase57_rows[0]['command'])
    need(common.identity(phase57_command[0]) == base['compiler'] and all(x in phase57_command for x in ('-O3', '-DNDEBUG', '-std=c++20'))
         and not any(x.startswith(('-Ofast', '-ffast-math', '-funsafe-math')) for x in phase57_command),
         'Phase57 same compiler/Release arithmetic flags, no fast math')
    phase57_flags_path = new_dir / 'CMakeFiles/phase57_synthesis.dir/flags.make'
    phase57_flags = flags(phase57_flags_path)
    need(phase57_flags['CXX_FLAGS'] == new_flags['CXX_FLAGS'] + ['-Wall', '-Wextra', '-Wpedantic'] and
         phase57_flags['CXX_DEFINES'] == new_flags['CXX_DEFINES'] and phase57_flags['CXX_INCLUDES'] == ['-I' + str(new_root / 'src')],
         'Actual Phase57 compile flags/includes match fixed Release configuration')
    inventory.extend([draft_id, common.identity(phase57_flags_path)])
    base_recipe_id = common.identity(DERIVED_BASE)
    need(base_recipe_id['sha256'] == DERIVED_BASE_SHA, 'Original mono2 OFF recipe changed')
    inventory.append(base_recipe_id)
    for item in inventory:
        checked(common, item)
    return {'hosts': hosts, 'input': input_id, 'roots': roots, 'headers': headers, 'libraries': libraries,
            'inventory': inventory, 'runtime_linkages': linkages, 'changes08_to09': changes,
            'initial_space': initial_space, 'new_compile_flags': new_flags, 'new_compile_command': source_rows[0],
            'old_archive_pin_provenance': base['archive_pin_provenance'],
            'old_host_body_provenance': 'Pinned external common body compiled against old V3 headers/libs; absent from baseline752 ledger.',
            'source_entries': {'old5674': 752, 'saved08': 768, 'new09': 768, 'ROOT08_guard': 768},
            'stage_digest_settings': setting, 'reviewed_block_dispatch_body': draft_id, 'derived_recipe': base_recipe_id,
            'new_phase57_compile_flags': phase57_flags, 'new_phase57_compile_command': phase57_rows[0],
            'archive08_actual_check_scope': 'Saved steady host, nine static libraries and heap probe; other archive members metadata only.',
            'old08_compile_commands_scope': 'Historical BUILD SHA retained; its overwritten live compile_commands path is not used.',
            'runtime': {'platform': platform.platform(), 'machine': platform.machine(), 'python': sys.version},
            'sources': {'old5674': OLD_SOURCE, 'saved08': SAVED_SOURCE, 'new09': args.new_source}}


def frozen(common, plan, path):
    errors = []
    for item in plan['inventory']:
        try:
            checked(common, item)
        except (OSError, ValueError) as error:
            errors.append(str(error))
    for root in plan['roots']:
        if common.current_source_digest(Path(root['root'])) != root['source']:
            errors.append('Source changed: ' + root['label'])
    save(path, {'status': 'PASS' if not errors else 'FAIL', 'checked_files': len(plan['inventory']),
                'inventory_sha256': common.manifest_digest(plan['inventory']), 'errors': errors})
    need(not errors, 'Source/header/archive/binary/probe/input freeze failed')


def stats(values, common):
    return {'n': len(values), 'samples': values, 'mean': statistics.mean(values),
            'median': statistics.median(values), 'min': min(values), 'max': max(values),
            'p95': common.percentile(values), 'sample_stdev': statistics.stdev(values)}


def aggregate(rows, common):
    versions = {label: [r for r in rows if r['label'] == label] for label in LABELS}
    values = {label: stats([r['summary']['cpu_percent'] for r in selected], common)
              for label, selected in versions.items() if len(selected) == 3 and all(r['integrity_pass'] for r in selected)}
    comparisons = []
    for left, right in (('old5674', 'saved08'), ('old5674', 'new09'), ('saved08', 'new09')):
        pairs = []
        for repeat in (1, 2, 3):
            found = {r['label']: r for r in rows if r['repeat'] == repeat}
            if left not in found or right not in found:
                continue
            a, b = found[left], found[right]
            valid = a['integrity_pass'] and b['integrity_pass']
            av, bv = a.get('summary', {}).get('cpu_percent'), b.get('summary', {}).get('cpu_percent')
            finite = valid and common.finite(av) and common.finite(bv)
            pairs.append({'repeat': repeat, 'left': av, 'right': bv, 'right_minus_left_pp': bv - av if finite else None,
                          'right_over_left': bv / av if finite and av > 0 else None,
                          'functional_measurement_pair': finite, 'RT_pair_pass': a['rt_pass'] and b['rt_pass']})
        differences = [p['right_minus_left_pp'] for p in pairs if p['functional_measurement_pair']]
        complete = len(pairs) == len(differences) == 3 and left in values and right in values
        overlap = (max(values[left]['min'], values[right]['min']) <= min(values[left]['max'], values[right]['max'])) if complete else None
        lower, higher = sum(v < 0 for v in differences), sum(v > 0 for v in differences)
        rt_valid = complete and all(p['RT_pair_pass'] for p in pairs)
        direction = ('NOT_QUALIFIED_RT' if complete and not rt_valid else
                     'OBSERVED_CONSISTENT_DECREASE' if complete and lower == 3 and not overlap else
                     'OBSERVED_CONSISTENT_INCREASE' if complete and higher == 3 and not overlap else 'NOT_DEMONSTRATED')
        comparisons.append({'left': left, 'right': right, 'pairs': pairs, 'complete_n3': complete,
                            'RT_all_pairs_pass': rt_valid,
                            'pair_differences_pp': stats(differences, common) if len(differences) >= 2 else None,
                            'ranges_overlap': overlap, 'lower_pairs': lower, 'higher_pairs': higher,
                            'mean_right_minus_left_pp': values[right]['mean'] - values[left]['mean'] if complete else None,
                            'median_right_minus_left_pp': values[right]['median'] - values[left]['median'] if complete else None,
                            'classification': direction, 'scope': 'Observed n3 pattern, never automatic adoption/significance.'})
    return {'versions': values, 'comparisons': comparisons}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--new-build', type=Path, required=True)
    parser.add_argument('--new-source', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--supervisor', type=Path)
    parser.add_argument('--supervisor-sha')
    args = parser.parse_args()
    need((args.supervisor is None) == (args.supervisor_sha is None), 'Supervisor path and fixed SHA must be supplied together')
    need(sys.version_info >= (3, 11), 'Python>=3.11 required')
    need(len(args.new_source) == 64 and all(c in '0123456789abcdef' for c in args.new_source)
         and args.new_source not in (OLD_SOURCE, SAVED_SOURCE), 'Explicit experiment09 source SHA')
    out = args.output.resolve()
    need(out.is_relative_to(BASE), 'New evidence directory under B')
    out.mkdir(parents=True, exist_ok=False)
    fixed_ids = [f'mono1_candidate_r{repeat:02d}_{label}' for repeat, order in enumerate(ORDERS, 1) for label in order]
    expected = {'schema': 'performance-mono1-fixed-ablation-v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'expected_programs': 9, 'repeats_per_version': 3, 'labels': list(LABELS), 'orders': ORDERS,
                'all_expected_ids': fixed_ids, 'preset': 'candidate', 'speed': 1.0, 'measurement_seconds': 30,
                'per_native_timeout_s': 180, 'callback_gate': False, 'new_requested_source': args.new_source, 'stage_digests_required': 'ON all three labels',
                'new_build_path': str(args.new_build.resolve()), 'preflight_status': 'PENDING',
                'reserve_bytes': 256 * 1024 * 1024, 'comparisons': [['old5674', 'saved08'], ['old5674', 'new09'], ['saved08', 'new09']], **SCOPE}
    save(out / 'EXPECTED.json', expected)
    common, plan, rows, error = None, None, [], None
    try:
        common = load_common()
        plan = preflight(common, args, out)
        supervisor = None
        if args.supervisor is not None:
            helper_path = args.supervisor.resolve()
            need(helper_path == Path(__file__).with_name('native08_driver_supervisor.py').resolve() and
                 len(args.supervisor_sha) == 64 and all(x in '0123456789abcdef' for x in args.supervisor_sha), 'Dedicated final supervisor path/SHA only')
            helper_id = common.identity(helper_path)
            need(helper_id['sha256'] == args.supervisor_sha, 'Final supervisor SHA differs')
            spec = importlib.util.spec_from_file_location('mono1_on_native_supervisor', helper_path)
            supervisor = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(supervisor)
            plan['inventory'].append(helper_id)
            plan['supervision'] = {'mode': 'pinned native08 supervisor', 'helper': helper_id}
        else:
            plan['supervision'] = {'mode': 'direct native common.execute', 'SIGTERM': 'wrapper KeyboardInterrupt handler; common direct-child wait4/finally retirement; no delegated driver/grandchild'}
        jobs = jobs_for(plan['hosts'], plan['input'], out)
        need([j['id'] for j in jobs] == fixed_ids and len(set(fixed_ids)) == 9, 'Fixed rotation9 IDs')
        expected.update(preflight_status='PASS', plan=plan, jobs=jobs, driver=common.identity(__file__),
                        helper=common.identity(COMMON))
        save(out / 'EXPECTED.json', expected)
        frozen(common, plan, out / 'FROZEN_BEFORE.json')
        def stop(signum, frame):
            raise KeyboardInterrupt(signal.Signals(signum).name)
        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            for job in jobs:
                frozen(common, plan, out / ('FROZEN_before_' + job['id'] + '.json'))
                space = capacity(plan['input']['bytes'])
                if supervisor is not None:
                    quiescence = supervisor.assert_managed_quiescent(BASE)
                    execution = supervisor.execute(job['command'], out / (job['id'] + '.log'), 180,
                                                   metadata=out / (job['id'] + '_SUPERVISOR.json'))
                else:
                    execution = common.execute(job['command'], out / (job['id'] + '.log'), 180)
                path = out / job['id'] / 'SUMMARY.json'
                try:
                    native = read(path) if path.is_file() else {}
                    assessed = common.assess('steady', job, native, {}, execution, plan['input'], 30, 48000, 512)
                except (OSError, ValueError, KeyError, TypeError) as failure:
                    native = {}
                    assessed = {'integrity_pass': False, 'rt_pass': False,
                                'errors': [type(failure).__name__ + ': ' + str(failure)],
                                'latency_target_ms': None, 'latency_sample_pass': None}
                if supervisor is not None and not (execution.get('cleanup_confirmed') is True and execution.get('next_job_allowed') is True):
                    assessed['integrity_pass'] = False
                    assessed['rt_pass'] = False
                    assessed['errors'].append('Supervisor retirement incomplete; no next native job allowed')
                row = {**job, **assessed, 'summary': native, 'execution': execution, 'space_before': space,
                       'artifacts': [common.identity(p) for p in sorted((out / job['id']).rglob('*')) if p.is_file()]}
                rows.append(row)
                plan['inventory'].extend(row['artifacts'])
                if execution.get('log'):
                    plan['inventory'].append(execution['log'])
                if supervisor is not None:
                    row['managed_quiescence_before'] = quiescence
                if execution.get('supervisor'):
                    plan['inventory'].append(execution['supervisor'])
                save(out / 'PROGRESS.json', {'status': 'IN_PROGRESS', 'expected_programs': 9, 'executed_programs': len(rows), 'rows': rows})
                print(job['id'], execution['returncode'], 'functional', row['integrity_pass'], 'RT', row['rt_pass'], flush=True)
                need(row['integrity_pass'] is True and not execution['interrupted'], 'Native incomplete/invalid; stop, retain remaining NOT_RUN IDs')
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    except (Exception, KeyboardInterrupt) as failure:
        error = type(failure).__name__ + ': ' + str(failure)
        if plan is None:
            expected.update(preflight_status='BLOCKED', preflight_error=error)
            save(out / 'EXPECTED.json', expected)
    finally:
        if common and plan:
            try:
                frozen(common, plan, out / 'FROZEN_AFTER.json')
            except (Exception, KeyboardInterrupt) as failure:
                error = (error + '; ' if error else '') + 'final freeze: ' + str(failure)
    complete = error is None and len(rows) == 9 and [r['id'] for r in rows] == fixed_ids
    rt = complete and all(r['rt_pass'] is True for r in rows)
    data = aggregate(rows, common) if common and rows else {'versions': {}, 'comparisons': []}
    result = {'schema': 'performance-mono1-fixed-ablation-summary-v1',
              'status': 'COMPLETE_OBSERVATIONS' if complete and rt else 'FAIL_OR_INCOMPLETE',
              'complete': complete, 'collection_status': 'PASS' if complete else 'FAIL_OR_INCOMPLETE',
              'RT_supply_status': 'PASS' if rt else ('FAIL' if complete else 'INCOMPLETE'),
              'expected_programs': 9, 'executed_programs': len(rows), 'all_expected_ids': fixed_ids,
              'executed_ids': [r['id'] for r in rows], 'NOT_RUN_ids': [n for n in fixed_ids if n not in {r['id'] for r in rows}],
              'reason': error, 'rows': rows, **data, 'whole_CPU_improvement': 'NOT_APPROVED_AUTOMATICALLY',
              'expected': common.identity(out / 'EXPECTED.json') if common else None, **SCOPE}
    save(out / 'SUMMARY.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'executed_programs', 'RT_supply_status', 'reason')}, ensure_ascii=False))
    return 0 if complete and rt else 2


if __name__ == '__main__':
    raise SystemExit(main())
