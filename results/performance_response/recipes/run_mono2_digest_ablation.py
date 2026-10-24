#!/usr/bin/env python3
"""mono2倍CPU: 旧5674/保存05/新07を固定n3・3版9programで直列比較する。

 /path/to/arm64/python3 -B results/performance_response/recipes/run_mono2_digest_ablation.py \
   --new-build B/build_experiment_07/BUILD.json --new-source SOURCE_SHA64 \
   --output B/mono2_ablation_01

同一PerformanceSteadyNative本文、chain300 mono48、Candidate、2.0倍、30秒。
順序はr1=old5674/saved05/new07、r2=saved05/new07/old5674、r3=new07/old5674/saved05。
05は必ず保存archive内の既link済み実行体を使い、candidate同名実行体へ置換しない。
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
SAVED_SOURCE = '0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e'
CLIENT_SHA = '45eca7d30805baea514d79eb2291ed359c2daa17f5c83d4269fea830a4447087'
ARCHIVE_SHA = '9ae4f1e70954e41a7ebda4cfa82a205444d5390fb00f017dd2909ac827434313'
SNAPSHOT_SHA = 'fc23fd8e517609bb5f7bce0f95622485f821c582c7bf54d4bda9737e5b9d77ed'
BUILD05_SHA = '7f2476aacbbf5a16fd2c444de0d4cce6ddba2333a89b9a2f637aab60ee97777f'
BODY = 'tests/PerformanceSteadyNative.cpp'
BODY_SHA = '696004d7cf55101529590fb0ce7c9137c12fcc9dd811a9765aacb40c7ba0e1a6'
INPUT_SHA = '13c957e5c0f5e3d64c4973ac27117930bcc541ac67f4d21459417d8f5a4e0bd0'
PROBE = 'libphase61_callback_heap_probe.dylib'
LABELS = ('old5674', 'saved05', 'new07')
ORDERS = (LABELS, ('saved05', 'new07', 'old5674'), ('new07', 'old5674', 'saved05'))
ALLOWED_CHANGES = {'src/prototype/Phase57ProgressiveSynthesis.cpp'}
SCOPE = {'CPU_approval': False, 'adoption_approved': False, 'quality_approval': False,
         'physical_audio': None, 'application_F': None,
         'statistics': 'Descriptive n3 only; no significance/tolerance/automatic non-regression acceptance.',
         'CPU_scope': 'Native 30-second process user+system/wall window; wait4 whole child cost is separate.',
         'history': '9 new programs only; prior steady48/followup12/Armed comparisons not added.',
         'ordinary_speed_requests': 'Fixed initial speed; no new Accepted speed-operation audit is claimed.'}


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
    spec = importlib.util.spec_from_file_location('mono2_fixed_run_pairs', COMMON)
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
            name = f'mono2_candidate_r{repeat:02d}_{label}'
            jobs.append({'id': name, 'repeat': repeat, 'label': label, 'version': label, 'preset': 'candidate',
                         'input': 'mono48chain300s', 'speed': 2.0, 'source': hosts[label]['source'],
                         'command': [hosts[label]['binary']['path'], input_id['path'], 'candidate', '2.0',
                                     '30', str(out / name)]})
    return jobs


def preflight(common, args, out):
    need(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native arm64 macOS Python required')
    need(not any(k.startswith('DYLD_') and v for k, v in os.environ.items()), 'Ambient dyld override forbidden')
    base_id, base = pinned(common, BASE / 'frozen_clients_02/CLIENT.json', CLIENT_SHA)
    arc_id, arc = pinned(common, BASE / 'timer_archive_05/ARCHIVE.json', ARCHIVE_SHA)
    snap_id, snap = pinned(common, BASE / 'timer_source_05/SOURCE.json', SNAPSHOT_SHA)
    build05_id, build05 = pinned(common, Path(arc['build']['path']), BUILD05_SHA)
    new_id, new = common.identity(args.new_build.resolve()), read(args.new_build)
    need(new['status'] == build05['status'] == 'PASS' and new['configuration'] == build05['configuration'] == 'Release'
         and new['architecture'] == build05['architecture'] == 'arm64' and new['source'] == args.new_source,
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
    need(source_map(common, build05, SAVED_SOURCE) == saved_map and arc['build'] == build05_id
         and arc['source_snapshot'] == snap_id and arc['source'] == SAVED_SOURCE, 'Saved05 archive/build/source binding')
    new_map = source_map(common, new, args.new_source)
    need(set(new_map) == set(saved_map), 'Same complete source file set')
    changes = sorted(p for p in new_map if new_map[p] != saved_map[p])
    need(bool(changes) and set(changes) <= ALLOWED_CHANGES, 'Experiment07 must change only Phase57 block digest dispatch')
    draft_path = BASE / 'stage_digest_experiment07_draft/DRAFT.json'
    draft_id = common.identity(draft_path);draft = read(draft_path)
    need(draft['old_sha'] == saved_map['src/prototype/Phase57ProgressiveSynthesis.cpp'] ==
         '34cee028e51b9e517e0f2b685b8f89c79eef97ec379bd9a4daa68834b361478e' and
         draft['new_sha'] == new_map['src/prototype/Phase57ProgressiveSynthesis.cpp'] ==
         'c12dee6510abcc9295f72634b127c144ad01c21abd6dfeade9a9aa8d81e0d76b',
         'Exact reviewed block-dispatch body required')
    need(saved_map[BODY] == new_map[BODY] == base['clients']['steady']['source']['sha256'] ==
         base['clients']['steady']['copied_source']['sha256'] == BODY_SHA, 'Same common steady native body')
    input_id = common.wav_identity(ROOT / 'results/phase56/long/chain_300s.wav', 48000, 1)
    need(input_id['sha256'] == INPUT_SHA and input_id['frames'] == 14400000 and input_id['sample_format'] == 'Float32',
         'Fixed Float32 mono48 chain300')
    initial_space = capacity(input_id['bytes'])
    roots = [{'label': 'old5674', 'root': str(Path(base['old_source_root']).resolve()), 'source': OLD_SOURCE},
             {'label': 'saved05', 'root': str((BASE / 'timer_source_05').resolve()), 'source': SAVED_SOURCE},
             {'label': 'new07', 'root': str(Path(new['source_root']).resolve()), 'source': args.new_source}]
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
    need(len(arc['files']) == 54, 'Saved05 archive54')
    for row in arc['files']:
        original, archived = row['original'], row['archived']
        name = Path(archived['path']).name
        need(name not in by_name and all(original[k] == archived[k] for k in ('bytes', 'sha256'))
             and Path(archived['path']).resolve().is_relative_to(BASE / 'timer_archive_05'), 'Unique immutable05 archive member')
        by_name[name] = row
    saved_host = by_name['performance_steady_native']['archived']
    need(all(saved_host[k] == build05['binaries']['performance_steady_native'][k] for k in ('bytes', 'sha256')),
         'Saved05 host is the recorded05 build; never use current candidate host for05')
    hosts = {'old5674': {'source': OLD_SOURCE, 'binary': base['clients']['steady']['binary'], 'contract_version': 3},
             'saved05': {'source': SAVED_SOURCE, 'binary': saved_host, 'contract_version': 4},
             'new07': {'source': args.new_source, 'binary': new['binaries']['performance_steady_native'], 'contract_version': 4}}
    need(base['clients']['steady']['copied_source']['sha256'] == BODY_SHA, 'Immutable old native body')
    inventory = [base_id, arc_id, snap_id, build05_id, new_id, old_build_id, common.identity(__file__),
                 common.identity(COMMON), checked(common, base['clients']['steady']['source']),
                 checked(common, base['clients']['steady']['copied_source']),
                 checked(common, base['clients']['steady']['object']), checked(common, base['clients']['steady']['depfile']),
                 checked(common, base['compiler']), *[row['identity'] for row in headers],
                 {k: input_id[k] for k in ('path', 'bytes', 'sha256')}]
    libraries = {'old5674': list(base['link_inputs'].values()), 'saved05': [], 'new07': []}
    for name in base['link_inputs']:
        need(name in by_name, 'Same nine-library plus probe set')
        libraries['saved05'].append(by_name[name]['archived'])
    new_dir = Path(hosts['new07']['binary']['path']).parent
    link_path = new_dir / 'CMakeFiles/performance_steady_native.dir/link.txt'
    flags_path = new_dir / 'CMakeFiles/performance_steady_native.dir/flags.make'
    link = shlex.split(link_path.read_text())
    tokens = [t for t in link if t.endswith(('.a', '.dylib'))]
    need(len(tokens) == len(set(Path(t).name for t in tokens)) == 10
         and set(Path(t).name for t in tokens) == set(base['link_inputs']), 'New07 exact nine archives/probe link set')
    libraries['new07'] = [common.identity((new_dir / t).resolve()) for t in tokens]
    new_flags = flags(flags_path)
    need(new_flags['CXX_FLAGS'] == base['compile_flags']['CXX_FLAGS']
         and new_flags['CXX_DEFINES'] == base['compile_flags']['CXX_DEFINES']
         and new_flags['CXX_INCLUDES'] == ['-I' + str(Path(new['source_root']).resolve() / 'src')],
         'Common Release compiler flags, no extra preset/profile/optimization macro')
    compile_id = checked(common, new['compile_commands'])
    compilation = read(compile_id['path'])
    source_rows = [r for r in compilation if Path(r['file']).resolve() == Path(new['source_root']).resolve() / BODY]
    need(len(source_rows) == 1, 'One actual new07 steady compilation command')
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
    need(all(linkages[label]['resolved_probe']['sha256'] == linkages['saved05']['resolved_probe']['sha256']
             for label in LABELS), 'Same actual callback heap probe for all three versions')
    inventory.append(draft_id)
    for item in inventory:
        checked(common, item)
    return {'hosts': hosts, 'input': input_id, 'roots': roots, 'headers': headers, 'libraries': libraries,
            'inventory': inventory, 'runtime_linkages': linkages, 'changes05_to07': changes,
            'initial_space': initial_space, 'new_compile_flags': new_flags, 'new_compile_command': source_rows[0],
            'old_archive_pin_provenance': base['archive_pin_provenance'],
            'old_host_body_provenance': 'Pinned external common body compiled against old V3 headers/libs; absent from baseline752 ledger.',
            'source_entries': {'old5674': 752, 'saved05': 768, 'new07': 768},
            'archive05_actual_check_scope': 'Saved steady host, nine static libraries and heap probe; other archive members metadata only.',
            'old05_compile_commands_scope': 'Historical BUILD SHA retained; its overwritten live compile_commands path is not used.',
            'runtime': {'platform': platform.platform(), 'machine': platform.machine(), 'python': sys.version},
            'sources': {'old5674': OLD_SOURCE, 'saved05': SAVED_SOURCE, 'new07': args.new_source}}


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
    for left, right in (('old5674', 'saved05'), ('old5674', 'new07'), ('saved05', 'new07')):
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
    args = parser.parse_args()
    need(sys.version_info >= (3, 11), 'Python>=3.11 required')
    need(len(args.new_source) == 64 and all(c in '0123456789abcdef' for c in args.new_source)
         and args.new_source not in (OLD_SOURCE, SAVED_SOURCE), 'Explicit experiment07 source SHA')
    out = args.output.resolve()
    need(out.is_relative_to(BASE), 'New evidence directory under B')
    out.mkdir(parents=True, exist_ok=False)
    fixed_ids = [f'mono2_candidate_r{repeat:02d}_{label}' for repeat, order in enumerate(ORDERS, 1) for label in order]
    expected = {'schema': 'performance-mono2-fixed-ablation-v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'expected_programs': 9, 'repeats_per_version': 3, 'labels': list(LABELS), 'orders': ORDERS,
                'all_expected_ids': fixed_ids, 'preset': 'candidate', 'speed': 2.0, 'measurement_seconds': 30,
                'per_native_timeout_s': 180, 'callback_gate': False, 'new_requested_source': args.new_source,
                'new_build_path': str(args.new_build.resolve()), 'preflight_status': 'PENDING',
                'reserve_bytes': 256 * 1024 * 1024, 'comparisons': [['old5674', 'saved05'], ['old5674', 'new07'], ['saved05', 'new07']], **SCOPE}
    save(out / 'EXPECTED.json', expected)
    common, plan, rows, error = None, None, [], None
    try:
        common = load_common()
        plan = preflight(common, args, out)
        jobs = jobs_for(plan['hosts'], plan['input'], out)
        need([j['id'] for j in jobs] == fixed_ids and len(set(fixed_ids)) == 9, 'Fixed rotation9 IDs')
        expected.update(preflight_status='PASS', plan=plan, jobs=jobs, driver=common.identity(__file__),
                        helper=common.identity(COMMON))
        save(out / 'EXPECTED.json', expected)
        frozen(common, plan, out / 'FROZEN_BEFORE.json')
        previous = signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt('SIGTERM')))
        try:
            for job in jobs:
                frozen(common, plan, out / ('FROZEN_before_' + job['id'] + '.json'))
                space = capacity(plan['input']['bytes'])
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
                row = {**job, **assessed, 'summary': native, 'execution': execution, 'space_before': space,
                       'artifacts': [common.identity(p) for p in sorted((out / job['id']).rglob('*')) if p.is_file()]}
                rows.append(row)
                save(out / 'PROGRESS.json', {'status': 'IN_PROGRESS', 'expected_programs': 9, 'executed_programs': len(rows), 'rows': rows})
                print(job['id'], execution['returncode'], 'functional', row['integrity_pass'], 'RT', row['rt_pass'], flush=True)
                need(row['integrity_pass'] is True and not execution['interrupted'], 'Native incomplete/invalid; stop, retain remaining NOT_RUN IDs')
        finally:
            signal.signal(signal.SIGTERM, previous)
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
    result = {'schema': 'performance-mono2-fixed-ablation-summary-v1',
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
