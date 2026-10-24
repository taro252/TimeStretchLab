"""同一の新clientを、固定済み旧v3ヘッダと旧ライブラリだけでビルドする。

例: python3 results/performance_response/recipes/build_frozen_client.py \
      --output build/performance_response_20261023_01/frozen_clients_01
旧build/ソース/ライブラリは変更しない。出力先は未作成のディレクトリに限る。
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
OLD_SOURCE_SHA = '2dae7749b928a72c36a8942563071ff073d89883012af77fb3822342453de392'
OLD_COMMIT = '5674bd982d98caacaa3e87cdeae5bfc0b01c66ef'
# 旧BUILD.jsonにはarchive個別SHAがない。2026-10-23に旧baselineを
# 読み取りで固定した値を使い、コンパイル/リンクの前後で再確認する。
OLD_LINK_SHA = {
    'libmacos_progressive_playback_engine.a': '51ffdf0140436c821f5d3080f8e32a736fda1e3c3054422763751ee2c33408a9',
    'libphase61_callback_heap_probe.dylib': '9ec0f1eb959dfa2cab8224ea7d8482ca0e5d5c7cde6c226e5345d0c1eebb259c',
    'libphase58_realtime.a': '19b2b69a20dc31893f750681432d03029d61e40e9c7c74ba79e944118fdb4630',
    'libphase57_synthesis.a': 'cdb0928208b5d629e18f570b6fd53d4204ee3a7514c68bc56788db2f0d23990a',
    'libphase59_transition.a': '82f815b44da036f7a7b94d9b76f15640738453f692d50e30640bae8ccec7b17d',
    'libphase56_incremental.a': '016742db5ad7b33ef92edea021a7fef9564ee376e38c695ac9a1ffeae4e15290',
    'libphase39_variable.a': 'd632c0e8b4a48bc0b2a2e99c240c3d24fd77a93bce7216a410fc6b8bb20507e0',
    'libphase36_variable.a': '2bcf0f26dca449dce16959055b13c5f3d88fb0c51569a2c88088b0d4708e8120',
    'libphase24_variable.a': '3a87cea191971e24dd59b61decaefea4dc4e6a4b29cf2c9fec42c794b77e03d0',
    'libtimestretch_core.a': '40565d210aefc23a026650d8e76f37c325c75d4777fa1c3ff792544d0018b7bf',
}
CLIENTS = {
    'steady': ('tests/PerformanceSteadyNative.cpp', 'performance_steady_native'),
    'ab': ('tests/ProgressiveAdoptionAbNative.cpp', 'progressive_adoption_ab_native'),
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def identity(path):
    path = pathlib.Path(path).resolve()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def make_dependencies(path):
    """clang -MDのMake形式。空白/コロン/バックスラッシュを含むパスも読む。"""
    text = path.read_text().replace('\\\r\n', '').replace('\\\n', '')
    split = re.search(r'(?<!\\):\s', text)
    require(split is not None, 'dependency target missing')
    words, word, escaped = [], [], False
    for char in text[split.end():]:
        if escaped:
            word.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char.isspace():
            if word:
                words.append(''.join(word).replace('$$', '$'))
                word = []
        else:
            word.append(char)
    require(not escaped, 'unterminated dependency escape')
    if word:
        words.append(''.join(word).replace('$$', '$'))
    return sorted(set(words))


def flags_from_make(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.match(r'^(CXX_DEFINES|CXX_INCLUDES|CXX_FLAGS)\s*=\s*(.*)$', line)
        if match:
            values[match[1]] = shlex.split(match[2])
    require(set(values) == {'CXX_DEFINES', 'CXX_INCLUDES', 'CXX_FLAGS'}, 'old flags missing')
    return values


def run(command, cwd, log):
    begin = time.monotonic()
    with log.open('w') as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    row = {'argv': list(map(str, command)), 'cwd': str(cwd), 'returncode': result.returncode,
           'wall_s': time.monotonic() - begin, 'log': identity(log)}
    require(result.returncode == 0, 'command failed: ' + str(log))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    parser.add_argument('--baseline-build-record', type=pathlib.Path,
                        default=BASE / 'build_baseline_01/BUILD.json')
    parser.add_argument('--baseline-build', type=pathlib.Path, default=BASE / 'baseline')
    parser.add_argument('--source-root', type=pathlib.Path, default=ROOT)
    parser.add_argument('--suites', nargs='+', choices=CLIENTS, default=list(CLIENTS))
    args = parser.parse_args()
    out = args.output.resolve()
    require(out.is_relative_to(ROOT / 'build'), 'generated clients must be written under build/')
    # helper/ヘッダが現ソース側からquoted includeで拾われない独立出力を作る。
    require(out != args.source_root.resolve(), 'source root cannot be the output')
    out.mkdir(parents=True, exist_ok=False)
    record = {'schema': 'performance-frozen-client-v1', 'status': 'INCOMPLETE',
              'baseline_commit': OLD_COMMIT, 'baseline_source': OLD_SOURCE_SHA,
              'contract_version': 3, 'clients': {}, 'binaries': {}, 'commands': [],
              'driver': identity(__file__), 'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'archive_pin_provenance': '2026-10-23旧baseline読取り固定。旧BUILDに個別archive SHAなし。'}
    try:
        old_build = args.baseline_build.resolve()
        build = json.loads(args.baseline_build_record.read_text())
        require(build['status'] == 'PASS' and build['source'] == OLD_SOURCE_SHA, 'wrong baseline BUILD')
        require(build['architecture'] == 'arm64' and build['configuration'] == 'Release', 'old build configuration')
        old_root = pathlib.Path(build['source_root']).resolve()
        manifest = build['source_manifest']
        require(manifest['sha256'] == OLD_SOURCE_SHA, 'old source manifest identity')
        manifest_rows = manifest['files']
        computed = hashlib.sha256(json.dumps(manifest_rows, sort_keys=True).encode()).hexdigest()
        require(computed == OLD_SOURCE_SHA, 'old manifest content SHA')
        old_sources = {row['path']: row['sha256'] for row in manifest_rows}
        header = old_root / 'src/platform/macos/ProgressiveMacPlaybackEngine.h'
        require('progressive::ContractV3Tag' in header.read_text(), 'old prepare must use the v3 ABI')
        link_file = old_build / 'CMakeFiles/phase62_control_cpu_native.dir/link.txt'
        flags_file = old_build / 'CMakeFiles/phase62_control_cpu_native.dir/flags.make'
        template = shlex.split(link_file.read_text())
        objects = [i for i, token in enumerate(template) if token.endswith('.o')]
        outputs = [i for i, token in enumerate(template) if token == '-o']
        require(len(objects) == len(outputs) == 1 and outputs[0] + 1 < len(template), 'one object/output required')
        link_inputs = {}
        library_tokens = [token for token in template[1:] if token.endswith(('.a', '.dylib'))]
        require(len(library_tokens) == len(OLD_LINK_SHA), 'duplicate/missing old link input')
        for token in template[1:]:
            if token.endswith(('.a', '.dylib')):
                path = (old_build / token).resolve()
                require(path.name in OLD_LINK_SHA, 'unrecognized link input ' + str(path))
                value = identity(path)
                require(value['sha256'] == OLD_LINK_SHA[path.name], 'old link input SHA changed: ' + path.name)
                require(path.parent == old_build, 'library outside old build')
                link_inputs[path.name] = value
        require(set(link_inputs) == set(OLD_LINK_SHA), 'old link inputs missing/duplicated')
        flags = flags_from_make(flags_file)
        require(flags['CXX_INCLUDES'] == ['-I' + str(old_root / 'src')], 'unexpected old include search path')
        require('-std=c++20' in flags['CXX_FLAGS'] and '-O3' in flags['CXX_FLAGS'], 'old compile flags')
        # CPATH等による現ヘッダ混入を防ぐ。SDK設定等も記録する。
        forbidden = ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH', 'OBJC_INCLUDE_PATH', 'LIBRARY_PATH')
        require(not any(os.environ.get(key) for key in forbidden), 'ambient include/library path is set')
        compiler = pathlib.Path(template[0])
        require(compiler.is_absolute(), 'old compiler must be absolute')
        record.update(baseline_build_record=identity(args.baseline_build_record),
                      baseline_build=str(old_build), old_source_root=str(old_root),
                      source_manifest_sha256=OLD_SOURCE_SHA, link_template=identity(link_file),
                      flags_file=identity(flags_file), compile_flags=flags, link_inputs=link_inputs,
                      compiler=identity(compiler), compiler_version=subprocess.check_output([str(compiler), '--version'], text=True),
                      environment={key: os.environ.get(key) for key in ('SDKROOT', 'MACOSX_DEPLOYMENT_TARGET', 'DEVELOPER_DIR', 'PATH')},
                      architecture='arm64', configuration='Release')
        save(out / 'CLIENT.json', record)
        for suite in dict.fromkeys(args.suites):
            relative, target = CLIENTS[suite]
            directory = out / suite
            directory.mkdir()
            require(not (directory / 'Phase62InitialLoopNative.cpp').exists(), 'unexpected local helper')
            original = args.source_root.resolve() / relative
            source_id = identity(original)
            source = directory / 'client.cpp'
            shutil.copyfile(original, source)
            require(identity(source)['sha256'] == source_id['sha256'], 'source copy mismatch')
            obj, dep, binary = directory / 'client.o', directory / 'client.d', directory / target
            compile_command = [str(compiler), *flags['CXX_DEFINES'], *flags['CXX_INCLUDES'],
                               '-I' + str(old_root / 'tests'), *flags['CXX_FLAGS'],
                               '-MD', '-MT', str(obj), '-MF', str(dep), '-o', str(obj), '-c', str(source)]
            record['commands'].append(run(compile_command, old_build, directory / 'compile.log'))
            dependencies = []
            for raw in make_dependencies(dep):
                path = (old_build / raw).resolve()
                item = identity(path)
                if path == source:
                    item['origin'] = 'copied_current_client'
                elif path.is_relative_to(old_root):
                    relative_header = str(path.relative_to(old_root))
                    require(old_sources.get(relative_header) == item['sha256'], 'old dependency not frozen: ' + relative_header)
                    item.update(origin='old_source_manifest', source_path=relative_header)
                else:
                    require(not path.is_relative_to(args.source_root.resolve()), 'current source/helper leaked into old client')
                    item['origin'] = 'toolchain_or_system'
                dependencies.append(item)
            require(any(d.get('source_path') == 'tests/Phase62InitialLoopNative.cpp' for d in dependencies), 'old helper was not used')
            require(any(d.get('source_path') == 'src/platform/macos/ProgressiveMacPlaybackEngine.h' for d in dependencies), 'old engine header was not used')
            # 未定義prepare参照の型名にもv3タグが残ることを検査する。
            symbols = subprocess.check_output(['/usr/bin/nm', '-u', str(obj)], text=True)
            (directory / 'undefined_symbols.txt').write_text(symbols)
            require(any('prepare' in line and 'ContractV3Tag' in line for line in symbols.splitlines()), 'prepare is not linked through the old v3 symbol')
            link_command = template.copy()
            link_command[objects[0]] = str(obj)
            link_command[outputs[0] + 1] = str(binary)
            require([i for i, (a, b) in enumerate(zip(template, link_command)) if a != b] == sorted([objects[0], outputs[0] + 1]), 'link changed beyond object/output')
            record['commands'].append(run(link_command, old_build, directory / 'link.log'))
            arches = subprocess.check_output(['/usr/bin/lipo', '-archs', str(binary)], text=True).split()
            require(arches == ['arm64'], 'client architecture mismatch')
            require(identity(original) == source_id, 'client source changed during build')
            require(identity(source)['sha256'] == source_id['sha256'], 'copied source changed')
            for item in dependencies:
                require(identity(item['path'])['sha256'] == item['sha256'], 'dependency changed during build')
            binary_id = identity(binary)
            client = {'target': target, 'source_relative': relative, 'source': source_id,
                      'copied_source': identity(source), 'object': identity(obj), 'depfile': identity(dep),
                      'dependencies': dependencies, 'undefined_symbols': identity(directory / 'undefined_symbols.txt'),
                      'binary': binary_id, 'compile_command': compile_command, 'link_command': link_command,
                      'architecture': arches, 'contract_version': 3}
            record['clients'][suite] = client
            record['binaries'][target] = binary_id
            save(out / 'CLIENT.json', record)
        for item in link_inputs.values():
            require(identity(item['path']) == item, 'old library changed during client build')
        require(identity(link_file) == record['link_template'] and identity(flags_file) == record['flags_file'], 'old CMake template changed')
        require(identity(args.baseline_build_record) == record['baseline_build_record'], 'old BUILD record changed')
        record['status'] = 'PASS'
        save(out / 'CLIENT.json', record)
        print(out / 'CLIENT.json')
        return 0
    except BaseException as error:
        record.update(status='FAIL', error=type(error).__name__ + ': ' + str(error))
        save(out / 'CLIENT.json', record)
        raise


if __name__ == '__main__':
    sys.exit(main())
