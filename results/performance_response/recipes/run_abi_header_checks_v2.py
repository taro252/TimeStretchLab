#!/usr/bin/env python3
"""保存V3 objectと候補V4ライブラリのABI拒否、SDK27共有C++構文を別々に記録する。

実行例（音声・生成実行体の起動・CMakeは行わない）:
  /usr/local/bin/python3 -B results/performance_response/recipes/run_abi_header_checks.py \
    --observation-clients build/performance_response_20261023_01/ab_observation_clients_final_03/CLIENT.json \
    --candidate-build build/performance_response_20261023_01/build_final_04/BUILD.json \
    --archive build/performance_response_20261023_01/final_archive_04/ARCHIVE.json \
    --output build/performance_response_20261023_01/abi_headers_final_01

固定9行。旧objectは再コンパイルしない。候補link templateのobject/outputだけを変更し、
V4正リンクが成功し、V3 prepareだけが未定義となる負リンクを成功条件にする。
SDK27 device/simulatorの共有header＋変更PV/Coherence CPP各2本は構文のみ。
ABI負例は元macOS link条件、iOS構文probeは明示SDK/targetで分離する。
実iOS音声・アプリ実行・性能・RT・物理音声の合格は生成しない。
"""

import argparse
from contextlib import nullcontext
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
SOURCE = '02b81c089a78155232a5fa4428586f1a6f81c53de90b1a319924fa9a4b04ac4b'
OLD_SOURCE = '2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392'
OLD_COMMIT = '5674bd982d98caacaa3e87cdeae5bfc0b01c66ef'
V3 = '__ZN2ts8playback28ProgressiveMacPlaybackEngine7prepareERKNSt3__14__fs10filesystem4pathENS0_18ProgressiveOptionsENS0_11progressive13ContractV3TagE'
V4 = V3.replace('ContractV3Tag', 'ContractV4Tag')
IDS = ('abi_v4_symbols', 'abi_v4_control_link', 'abi_v3_object_rejected',
       'ios_device_headers', 'ios_device_phase35_pv', 'ios_device_phase35_coherence',
       'ios_simulator_headers', 'ios_simulator_phase35_pv', 'ios_simulator_phase35_coherence')
HEADER = r'''#include "playback/ProgressiveFeatureContract.h"
#include "playback/ProgressiveContract.h"
#include "playback/ProgressiveSeekContract.h"
#include "playback/ProgressiveLoopContract.h"
#include "platform/macos/ProgressiveMacPlaybackEngine.h"
#include "prototype/Phase35PhaseVocoder.h"
#include "prototype/Phase35StereoPhaseCoherence.h"
#include <type_traits>
#include <utility>
namespace p = ts::playback::progressive;
using Engine = ts::playback::ProgressiveMacPlaybackEngine;
using Options = ts::playback::ProgressiveOptions;
using PV = ts::prototype::Phase35PhaseVocoder;
using Prepare = bool (Engine::*)(const std::filesystem::path&, Options, p::ContractV4Tag);
static_assert(p::contractVersion == 4);
static_assert(std::is_same_v<p::ContractV3Tag, p::ContractV4Tag>);
static_assert(std::is_empty_v<p::ContractV4Tag>);
static_assert(std::is_same_v<decltype(&Engine::prepare), Prepare>);
static_assert(std::is_same_v<decltype(Options::recordStageDigests), bool>);
static_assert(std::is_same_v<decltype(std::declval<const PV&>().inputPolarView()), PV::InputPolarView>);
static_assert(noexcept(std::declval<const PV::InputPolarView&>().validFor(
    std::declval<const PV&>(), static_cast<const std::complex<float>*>(nullptr), std::size_t{})));
Options shared_options_probe() { return Options::macOSProduct(); }
'''


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def load(path):
    def reject(value):
        raise ValueError('Nonfinite JSON: ' + value)
    return json.loads(Path(path).read_text(), parse_constant=reject)


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def stat(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


class Files:
    def __init__(self):
        self.values = {}

    def identity(self, path):
        path = Path(path).resolve()
        before = stat(path)
        if str(path) in self.values:
            value = self.values[str(path)]
            require(value['stat'] == before, 'Frozen file changed: ' + str(path))
            return dict(value)
        value = {'path': str(path), 'bytes': before[2], 'sha256': sha(path), 'stat': before}
        require(stat(path) == before, 'File changed while hashing: ' + str(path))
        self.values[str(path)] = value
        return dict(value)

    def check(self, record):
        require(isinstance(record, dict) and {'path', 'bytes', 'sha256'} <= set(record), 'Missing file identity')
        value = self.identity(record['path'])
        require(value['bytes'] == record['bytes'] and value['sha256'] == record['sha256'],
                'Recorded file SHA/size differs: ' + value['path'])
        return value

    def unchanged(self):
        for path, value in self.values.items():
            require(stat(path) == value['stat'], 'File changed before final audit: ' + path)


def source_rows(root):
    paths = [root / 'CMakeLists.txt']
    for directory in ('src', 'tests', 'scripts'):
        paths.extend(p for p in (root / directory).rglob('*') if p.is_file()
                     and p.suffix in ('.h', '.hpp', '.cpp', '.mm', '.py', '.c', '.m'))
    return [{'path': str(path.relative_to(root)), 'sha256': sha(path)} for path in sorted(paths)]


def manifest_digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def dependencies(path):
    text = Path(path).read_text().replace('\\\r\n', '').replace('\\\n', '')
    split = re.search(r'(?<!\\):\s', text)
    require(split is not None, 'Dependency target missing')
    words, word, escaped = [], '', False
    for char in text[split.end():]:
        if escaped:
            word += char
            escaped = False
        elif char == '\\':
            escaped = True
        elif char.isspace():
            if word:
                words.append(word.replace('$$', '$'))
                word = ''
        else:
            word += char
    require(not escaped, 'Unterminated dependency escape')
    if word:
        words.append(word.replace('$$', '$'))
    return sorted(set(words))


class Runner:
    def __init__(self, out, files):
        self.out, self.files, self.commands = out, files, []

    def run(self, name, command, cwd, timeout=60, separate_stderr=False):
        log = self.out / (f'{len(self.commands):03d}_' + name + '.log')
        begin, timed = time.monotonic(), False
        pending = {'id': name, 'argv': list(map(str, command)), 'cwd': str(cwd),
                   'timeout_limit_s': timeout, 'status': 'NOT_COMPLETED'}
        save(self.out / 'COMMANDS.json', {'completed': self.commands, 'pending': pending})
        stderr_log = log.with_suffix('.stderr')
        with log.open('wb') as stream, (stderr_log.open('wb') if separate_stderr else nullcontext(None)) as errors:
            child = subprocess.Popen(pending['argv'], cwd=cwd, stdout=stream,
                                     stderr=errors if separate_stderr else subprocess.STDOUT, start_new_session=True)
            try:
                code = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed = True
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                code = child.wait()
            except BaseException:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                raise
        value = {'id': name, 'argv': list(map(str, command)), 'cwd': str(cwd), 'returncode': code,
                 'timeout': timed, 'wall_s': time.monotonic() - begin, 'log': self.files.identity(log)}
        if separate_stderr:
            value['stderr'] = self.files.identity(stderr_log)
        self.commands.append(value)
        save(self.out / 'COMMANDS.json', {'completed': self.commands, 'pending': None})
        return value

    def query(self, name, command, cwd):
        result = self.run(name, command, cwd, 30, separate_stderr=True)
        require(result['returncode'] == 0 and not result['timeout'], 'Tool query failed: ' + name)
        return Path(result['log']['path']).read_text().strip()


def case(rows, name, action):
    try:
        facts = action()
        rows[name] = {'id': name, 'status': 'PASS', 'facts': facts}
    except Exception as error:
        rows[name] = {'id': name, 'status': 'FAIL', 'reason': type(error).__name__ + ': ' + str(error)}


def prepare_provenance(args, files):
    build, obs, archive = load(args.candidate_build), load(args.observation_clients), load(args.archive)
    require(build['status'] == 'PASS' and build['source'] == SOURCE
            and build['architecture'] == 'arm64' and build['configuration'] == 'Release', 'Frozen final Release arm64 build required')
    root = Path(build['source_root']).resolve()
    rows = source_rows(root)
    require(rows == build['source_manifest']['files'] and manifest_digest(rows) == build['source_manifest']['sha256'] == SOURCE,
            'Candidate source is not the frozen 02b81 manifest')
    require(obs['schema'] == 'performance-ab-observation-clients-v1' and obs['status'] == 'PASS'
            and obs['baseline_commit'] == OLD_COMMIT and obs['baseline_source'] == OLD_SOURCE
            and obs['candidate_source'] == SOURCE and set(obs['clients']) == {'old', 'candidate'}, 'Observation source/version provenance')
    require(files.check(obs['candidate_build'])['sha256'] == files.identity(args.candidate_build)['sha256'], 'Observation build identity differs')
    baseline = load(files.check(obs['baseline_client'])['path'])
    old_build = load(files.check(obs['baseline_build_record'])['path'])
    require(baseline['status'] == old_build['status'] == 'PASS' and old_build['source'] == OLD_SOURCE
            and baseline['baseline_source'] == OLD_SOURCE and baseline['contract_version'] == 3, 'Frozen old V3 build required')
    require(manifest_digest(old_build['source_manifest']['files']) == old_build['source_manifest']['sha256'] == OLD_SOURCE,
            'Old source manifest content differs')
    old_map = {item['path']: item['sha256'] for item in old_build['source_manifest']['files']}
    new_map = {item['path']: item['sha256'] for item in rows}
    for item in obs['baseline_link_inputs']:
        files.check(item)
    for key in ('common_client', 'common_capture_source', 'client_source_original', 'capture_source_original', 'observation_diff'):
        files.check(obs[key])
    require(archive['source'] == SOURCE and archive['product_src_all_identical'] is True
            and len(archive['files']) == 54 and files.check(archive['build'])['sha256'] == files.identity(args.candidate_build)['sha256'],
            'Final 54-file archive/build source correspondence')
    archived = {item['original']['path']: item for item in archive['files']}
    for version, expected_source, contract, source_map in (('old', OLD_SOURCE, 3, old_map), ('candidate', SOURCE, 4, new_map)):
        item = obs['clients'][version]
        require(item['source'] == expected_source and item['contract_version'] == contract
                and item['prepare_ABI'] == ('ContractV3Tag' if version == 'old' else 'ContractV4Tag')
                and item['architectures'] == ['arm64'], 'Client object ABI/architecture provenance')
        for key in ('object', 'binary', 'depfile', 'compiler', 'flags_file', 'link_template', 'undefined_symbols'):
            files.check(item[key])
        for dep in item['dependencies']:
            files.check(dep)
            if dep.get('source_path'):
                require(source_map.get(dep['source_path']) == dep['sha256'], 'Client header/helper does not match its version manifest')
        require(any(dep.get('source_path') == 'src/platform/macos/ProgressiveMacPlaybackEngine.h'
                    for dep in item['dependencies']), 'Matching native contract header absent from object dependencies')
        require(any(dep.get('source_path') == 'src/playback/ProgressiveFeatureContract.h'
                    for dep in item['dependencies']), 'Matching shared contract header absent from object dependencies')
        for lib in item['libraries']:
            files.check(lib)
            if version == 'old':
                require(baseline['link_inputs'].get(Path(lib['path']).name, {}).get('sha256') == lib['sha256'], 'Old linked library provenance')
            else:
                require(lib['path'] in archived, 'Candidate library absent from final archive')
                frozen = archived[lib['path']]
                require(frozen['original']['sha256'] == frozen['archived']['sha256'] == lib['sha256'], 'Candidate library/archive SHA differs')
                files.check(frozen['archived'])
    engine = build['binaries']['progressive_adoption_ab_native']
    files.check(engine)
    require(engine['path'] in archived and archived[engine['path']]['archived']['sha256'] == engine['sha256'], 'Final candidate binary/archive correspondence')
    files.check(archived[engine['path']]['archived'])
    candidate = obs['clients']['candidate']
    template = shlex.split(Path(candidate['link_template']['path']).read_text())
    obj = [i for i, word in enumerate(template) if word.endswith('.o')]
    output = [i for i, word in enumerate(template) if word == '-o']
    require(len(obj) == len(output) == 1 and output[0] + 1 < len(template) and Path(template[0]).is_absolute(), 'Single object/output native link template required')
    cwd = Path(candidate['build']).resolve()
    links = {(cwd / word).resolve() for word in template if word.endswith(('.a', '.dylib'))}
    require(links == {Path(lib['path']).resolve() for lib in candidate['libraries']} and len(links) == 10, 'Candidate template libraries differ')
    require(not any('iphone' in word.lower() or word in ('-target', '-isysroot') for word in template), 'iOS SDK/target must not be introduced into the old-object native ABI check')
    return {'build': build, 'observation': obs, 'archive': archive, 'root': root, 'source_rows': rows,
            'source_map': new_map, 'template': template, 'object_index': obj[0], 'output_index': output[0] + 1,
            'cwd': cwd, 'final_binary': engine}


def abi_checks(provenance, runner, rows):
    obs, template, cwd = provenance['observation'], provenance['template'], provenance['cwd']
    old, new = obs['clients']['old'], obs['clients']['candidate']

    def symbols():
        facts = {}
        for version, item, wanted, forbidden in (('old', old, V3, V4), ('candidate', new, V4, V3)):
            raw = runner.query(version + '_object_undefined', ['/usr/bin/nm', '-u', '-j', item['object']['path']], cwd)
            values = raw.splitlines()
            require(values.count(wanted) == 1 and forbidden not in values, 'Object prepare undefined symbol mismatch: ' + version)
            require(runner.query(version + '_object_arch', ['/usr/bin/lipo', '-archs', item['object']['path']], cwd).split() == ['arm64'], 'Object architecture mismatch')
            facts[version] = {'object': item['object'], 'expected_undefined_prepare': wanted,
                              'compile_command_not_reexecuted': item['compile_command'], 'compiler_version_at_compile': item['compiler_version'],
                              'header_dependencies': item['dependencies']}
        candidates = {'observation_binary': new['binary'], 'final_binary': provenance['final_binary']}
        candidates['engine_archive'] = next(lib for lib in new['libraries'] if Path(lib['path']).name == 'libmacos_progressive_playback_engine.a')
        for label, item in candidates.items():
            raw = runner.query(label + '_defined_symbols', ['/usr/bin/nm', '-g', '-U', '-j', item['path']], cwd)
            require(V4 in raw.splitlines() and V3 not in raw.splitlines(), 'Candidate must define V4 and no V3 prepare: ' + label)
        facts['candidate_definitions'] = candidates
        facts['scope'] = 'Saved macOS objects/libraries. No mobile SDK qualification is inferred.'
        return facts
    case(rows, 'abi_v4_symbols', symbols)

    def link(version):
        binary = runner.out / ('v4_control_link' if version == 'candidate' else 'v3_must_not_link')
        command = template.copy()
        command[provenance['object_index']] = obs['clients'][version]['object']['path']
        command[provenance['output_index']] = str(binary)
        require(sum(a != b for a, b in zip(command, template)) == 2, 'Only native object/output substitutions are allowed')
        result = runner.run('link_' + version, command, cwd, 90)
        require(not result['timeout'], 'ABI link timeout is not an expected rejection')
        if version == 'candidate':
            require(result['returncode'] == 0 and binary.is_file(), 'V4 same-template positive link failed')
            defined = runner.query('v4_control_defined', ['/usr/bin/nm', '-g', '-U', '-j', str(binary)], cwd).splitlines()
            require(V4 in defined and V3 not in defined, 'V4 link control symbol differs')
            return {'execution': result, 'binary_not_executed': runner.files.identity(binary)}
        require(rows['abi_v4_symbols']['status'] == rows['abi_v4_control_link']['status'] == 'PASS', 'Negative result needs verified objects and successful same-template V4 control')
        require(result['returncode'] == 1 and not binary.exists(), 'Old V3 object unexpectedly linked or failed by another exit mode')
        text = Path(result['log']['path']).read_text()
        require(len(re.findall(r'^Undefined symbols for architecture arm64:\s*$', text, re.M)) == 1,
                'Expected arm64 linker undefined-symbol diagnostic absent')
        undefined = re.findall(r'^\s+"(.+)", referenced from:\s*$', text, re.M)
        require(len(undefined) == 1 and
                (undefined[0] == V3 or (undefined[0].startswith('ts::playback::ProgressiveMacPlaybackEngine::prepare(')
                 and 'progressive::ContractV3Tag)' in undefined[0])), 'Not exclusively the expected ContractV3Tag prepare symbol')
        require('ld: symbol(s) not found for architecture arm64' in text and
                not re.search(r'file not found|library not found|framework not found|no such file|incompatible architecture|unknown argument|malformed|fatal error:', text, re.I),
                'Other compile/link/toolchain failure must not count as an ABI rejection')
        return {'execution': result, 'expected_undefined_symbol': V3, 'actual_undefined_symbols': undefined,
                'object': old['object'], 'candidate_libraries': new['libraries'],
                'only_prepare_V3_unresolved': True, 'old_object_recompiled': False, 'mobile_SDK_used': False}
    case(rows, 'abi_v4_control_link', lambda: link('candidate'))
    case(rows, 'abi_v3_object_rejected', lambda: link('old'))


def mobile_checks(args, provenance, runner, rows, sdk_records):
    root, source_map = provenance['root'], provenance['source_map']
    probe = runner.out / 'SharedContractAndPolarHeaders.cpp'
    probe.write_text(HEADER)
    runner.files.identity(probe)
    units = [('headers', probe), ('phase35_pv', root / 'src/prototype/Phase35PhaseVocoder.cpp'),
             ('phase35_coherence', root / 'src/prototype/Phase35StereoPhaseCoherence.cpp')]
    for label, sdk, target in (('device', 'iphoneos', 'arm64-apple-ios' + args.deployment_target),
                               ('simulator', 'iphonesimulator', 'arm64-apple-ios' + args.deployment_target + '-simulator')):
        try:
            sdk_path = Path(runner.query(label + '_sdk_path', ['/usr/bin/xcrun', '--sdk', sdk, '--show-sdk-path'], root)).resolve()
            version = runner.query(label + '_sdk_version', ['/usr/bin/xcrun', '--sdk', sdk, '--show-sdk-version'], root)
            require(re.fullmatch(r'27(?:\.\d+){1,2}', version), 'SDK27 is required; another SDK must not be reported as compliant')
            clang = Path(runner.query(label + '_clang_path', ['/usr/bin/xcrun', '--sdk', sdk, '--find', 'clang++'], root)).resolve()
            clang_version = runner.query(label + '_clang_version', [str(clang), '--version'], root)
            settings = next((p for p in (sdk_path / 'SDKSettings.json', sdk_path / 'SDKSettings.plist') if p.is_file()), None)
            require(settings is not None, 'SDK settings identity unavailable')
            info = {'sdk': sdk, 'path': str(sdk_path), 'version': version, 'SDK_settings': runner.files.identity(settings),
                    'clang': runner.files.identity(clang), 'clang_version': clang_version, 'target': target,
                    'standard': 'C++20', 'phase': 'syntax_only_no_link_or_execution', 'ABI_negative_profile': 'SEPARATE_NOT_MIXED'}
            sdk_records[label] = info
        except Exception as error:
            for unit, _ in units:
                name = 'ios_' + label + '_' + unit
                rows[name] = {'id': name, 'status': 'BLOCKED', 'reason': type(error).__name__ + ': ' + str(error)}
            continue
        for unit, path in units:
            name = 'ios_' + label + '_' + unit
            def compile_unit(path=path, name=name):
                depfile = runner.out / (name + '.d')
                command = [str(clang), '-std=c++20', '-target', target, '-isysroot', str(sdk_path),
                           '-I' + str(root / 'src'), '-fsyntax-only', '-MD', '-MT', name, '-MF', str(depfile), str(path)]
                result = runner.run(name, command, root, 120)
                require(result['returncode'] == 0 and not result['timeout'], 'SDK27 C++ syntax failed or timed out')
                require(depfile.is_file(), 'Successful syntax check did not record dependencies')
                deps = []
                for token in dependencies(depfile):
                    dependency = (root / token).resolve()
                    value = runner.files.identity(dependency)
                    if dependency == probe:
                        value['origin'] = 'generated_frozen_probe'
                    elif dependency.is_relative_to(root):
                        relative = str(dependency.relative_to(root))
                        require(source_map.get(relative) == value['sha256'], 'Mobile dependency outside candidate source manifest')
                        value.update(origin='candidate_02b81_source', source_path=relative)
                    else:
                        require(not dependency.is_relative_to(Path(provenance['observation']['clients']['old']['source_root']).resolve()),
                                'Old V3 header contaminated SDK27 probe')
                        value['origin'] = 'SDK_or_toolchain_system_header'
                    deps.append(value)
                require(deps and any(d['path'] == str(path.resolve()) for d in deps), 'Translation unit missing from dependency list')
                return {'execution': result, 'translation_unit': runner.files.identity(path), 'depfile': runner.files.identity(depfile),
                        'dependencies': deps, 'sdk': info, 'source': SOURCE, 'link_performed': False, 'runtime_performed': False}
            case(rows, name, compile_unit)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--observation-clients', type=Path, default=BASE / 'ab_observation_clients_final_03/CLIENT.json')
    parser.add_argument('--candidate-build', type=Path, default=BASE / 'build_final_04/BUILD.json')
    parser.add_argument('--archive', type=Path, default=BASE / 'final_archive_04/ARCHIVE.json')
    parser.add_argument('--deployment-target', default='17.0')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch(r'\d{1,2}\.\d{1,2}', args.deployment_target), 'Finite explicit iOS deployment target required')
    out = args.output.resolve()
    require(out.is_relative_to(ROOT / 'build'), 'All generated output must stay under build/')
    out.mkdir(parents=True, exist_ok=False)
    files, rows, sdks = Files(), {name: {'id': name, 'status': 'NOT_RUN'} for name in IDS}, {}
    runner = Runner(out, files)
    expected = {'schema': 'performance-abi-header-checks-v1', 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'expected': len(IDS), 'required_ids': list(IDS), 'source': SOURCE, 'old_source': OLD_SOURCE,
                'expected_negative_symbol': V3, 'candidate_defined_symbol': V4, 'required_mobile_SDK_major': 27,
                'deployment_target': args.deployment_target, 'architecture': 'arm64', 'C++': 20,
                'observation_clients': str(args.observation_clients.resolve()), 'candidate_build': str(args.candidate_build.resolve()),
                'archive': str(args.archive.resolve()), 'old_object_compile': 'NOT_REQUESTED; existing verified V3 object only',
                'mobile_targets': ['arm64-apple-ios' + args.deployment_target, 'arm64-apple-ios' + args.deployment_target + '-simulator'],
                'scope': 'ABI symbol/link rejection and SDK27 C++ syntax only; native/macOS and mobile profiles remain separate.',
                'iOS_audio_runtime': 'NOT_RUN', 'iOS_app_runtime': 'NOT_RUN', 'native_audio': 'NOT_RUN',
                'realtime_approval': False, 'performance_approval': False, 'physical_audio_verified': None, 'public_approved': False}
    save(out / 'EXPECTED.json', expected)
    error, frozen = None, False
    try:
        require(platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Native arm64 macOS caller required')
        forbidden = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH', 'LIBRARY_PATH',
                     'DYLD_LIBRARY_PATH', 'DYLD_INSERT_LIBRARIES', 'SDKROOT', 'MACOSX_DEPLOYMENT_TARGET')
        require(not any(os.environ.get(key) for key in forbidden), 'Ambient include/library/SDK override is forbidden')
        expected['driver'] = files.identity(__file__)
        expected['records'] = {name: files.identity(path) for name, path in
                               (('observation_clients', args.observation_clients), ('candidate_build', args.candidate_build), ('archive', args.archive))}
        provenance = prepare_provenance(args, files)
        expected['old_object_provenance'] = provenance['observation']['clients']['old']
        expected['candidate_object_provenance'] = provenance['observation']['clients']['candidate']
        expected['native_link_template'] = provenance['template']
        expected['source_manifest_sha256'] = provenance['build']['source_manifest']['sha256']
        save(out / 'EXPECTED.json', expected)
        compiler = provenance['observation']['clients']['candidate']['compiler']['path']
        version = runner.query('native_link_compiler_version', [compiler, '--version'], provenance['cwd'])
        require(version == provenance['observation']['clients']['candidate']['compiler_version'].strip(), 'Native link compiler differs from saved candidate compiler')
        abi_checks(provenance, runner, rows)
        mobile_checks(args, provenance, runner, rows, sdks)
        require(source_rows(provenance['root']) == provenance['source_rows'], 'Candidate source changed during checks')
        files.unchanged()
        frozen = True
    except (Exception, KeyboardInterrupt) as failure:
        error = type(failure).__name__ + ': ' + str(failure)
        for name in IDS:
            if rows[name]['status'] == 'NOT_RUN':
                rows[name] = {'id': name, 'status': 'BLOCKED', 'reason': error}
    complete = all(row['status'] in ('PASS', 'FAIL') for row in rows.values()) and error is None
    good = complete and frozen and all(row['status'] == 'PASS' for row in rows.values())
    result = {'schema': 'performance-abi-header-checks-summary-v1', 'status': 'PASS' if good else 'FAIL_OR_INCOMPLETE',
              'run_complete': complete, 'expected': len(IDS), 'executed': sum(row['status'] in ('PASS', 'FAIL') for row in rows.values()),
              'passed': sum(row['status'] == 'PASS' for row in rows.values()), 'required_ids': list(IDS),
              'rows': [rows[name] for name in IDS], 'commands': runner.commands, 'mobile_SDKs': sdks,
              'source': SOURCE, 'source_unchanged': frozen, 'reason': error, 'expected_sha256': sha(out / 'EXPECTED.json'),
              'driver_sha256': sha(__file__), 'all_generated_binaries_executed': False,
              'iOS_audio_runtime': 'NOT_RUN', 'iOS_app_runtime': 'NOT_RUN', 'native_audio': 'NOT_RUN',
              'realtime_approval': False, 'performance_approval': False, 'physical_audio_verified': None, 'public_approved': False,
              'PASS_scope': 'Expected V3 ABI rejection, V4 symbol/link control, and SDK27 arm64 C++20 syntax only.'}
    save(out / 'SUMMARY.json', result)
    print(json.dumps({key: result[key] for key in ('status', 'expected', 'executed', 'passed', 'reason')}, ensure_ascii=False))
    return 0 if good else 2


if __name__ == '__main__':
    raise SystemExit(main())
