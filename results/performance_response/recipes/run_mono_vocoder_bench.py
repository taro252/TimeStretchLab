#!/usr/bin/env python3
"""mono Phase35だけの独立ソース対照。native/FFT/PCM/RT性能承認ではない。"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
OWNED_OUTPUT = None
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity, source_manifest


def need(value, why):
    if not value:
        raise ValueError(why)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    global OWNED_OUTPUT
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    out = args.output.resolve()
    need(out.is_relative_to(ROOT / 'build'), '新規build/出力が必要')
    out.mkdir(parents=True, exist_ok=False)
    OWNED_OUTPUT = out
    need(not any(os.environ.get(k) for k in ('CPATH', 'CPLUS_INCLUDE_PATH', 'C_INCLUDE_PATH',
             'OBJC_INCLUDE_PATH', 'LIBRARY_PATH')) and
         not any(k.startswith('DYLD_') and v for k, v in os.environ.items()), '外部include/link/runtime overrideを使わない')
    source = source_manifest(ROOT)
    need(source['sha256'] in ('0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e',
         'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94'), '同じPVを持つ05/08のみ')
    provenance = ROOT / 'tests/reference/performance_response/PROVENANCE.json'
    need(identity(provenance)['sha256'] == '2e76c422a19685583dc266da5ae1478c2806742c722aac751336f6f4ed21fae7', '独立scalar参照manifest')
    ref = json.loads(provenance.read_text())
    for row in ref['files']:
        actual = identity(ROOT / row['copy'])
        need(all(actual[k] == row[k] for k in ('bytes', 'sha256')), '凍結参照変更')
    paths = [Path(__file__).resolve().with_name('mono_vocoder_bench.cpp'),
             ROOT / 'tests/reference/performance_response/Frozen5674PhaseVocoder.cpp',
             ROOT / 'tests/reference/performance_response/Frozen5674PhaseLocker.cpp',
             ROOT / 'src/prototype/Phase35PhaseVocoder.cpp', ROOT / 'src/dsp/PhaseLocker.cpp']
    need(identity(paths[0])['sha256'] == 'b993969ef9e47419eef9abb81f823cdfe9ed89144a260dfcb6322ceb7142187f', '固定54標本本文')
    need(identity(paths[3])['sha256'] == '49168f671ebdc8bd6fbe882872df706a5383328d55096b7a060e3b3ca11ae4ce', '05 PV本文')
    compiler = '/usr/bin/c++'
    baseline_path = ROOT / 'build/performance_response_20261023_01/frozen_clients_02/CLIENT.json'
    baseline_id = identity(baseline_path)
    need(baseline_id['sha256'] == '45eca7d30805baea514d79eb2291ed359c2daa17f5c83d4269fea830a4447087', '固定baseline compiler台帳')
    baseline = json.loads(baseline_path.read_text())
    need(identity(compiler) == baseline['compiler'], '基準compiler shimの変更')
    cases = ['mono_fft' + str(n) + '_hs' + ratio for n in (1024, 4096, 8192)
             for ratio in ('050', '100', '200')]
    ids = [case + '_r0' + str(repeat) + '_' + version for repeat in (1, 2, 3)
           for case in cases for version in (('frozen5674', 'current05pv') if repeat % 2
                                              else ('current05pv', 'frozen5674'))]
    command = [compiler, '-O3', '-DNDEBUG', '-std=c++20', '-arch', 'arm64', '-I' + str(ROOT / 'src'),
               '-I' + str(ROOT / 'tests'), *map(str, paths), '-o', str(out / 'mono_vocoder_bench')]
    expected = {'source_inventory': source['sha256'], 'driver': identity(__file__),
                'sources': [identity(x) for x in paths], 'frozen_provenance': identity(provenance),
                'compiler': identity(compiler), 'compile_command': command,
                'baseline_compiler_record': baseline_id,
                'expected_samples': 54, 'prevalidation_cases': 9, 'required_ids': ids,
                'required_prevalidation_ids': cases,
                'scope': '合成constant spectrumのscalar対照。全内部状態直読・全曲PCM・native CPU・RT承認ではない。'}
    save(out / 'EXPECTED.json', expected)
    version = subprocess.run([compiler, '--version'], text=True, capture_output=True, check=True)
    (out / 'compiler.txt').write_text(version.stdout + version.stderr)
    with (out / 'build.log').open('w') as f:
        compiled = subprocess.run(command, stdout=f, stderr=subprocess.STDOUT, timeout=180)
    save(out / 'BUILD.json', {'status': 'PASS' if compiled.returncode == 0 else 'FAIL',
         'returncode': compiled.returncode, 'command': command, 'log': identity(out / 'build.log'),
         'compiler_version': identity(out / 'compiler.txt')})
    need(compiled.returncode == 0, '失敗buildの旧binaryを使わない')
    binary = identity(out / 'mono_vocoder_bench')
    with (out / 'run.log').open('w') as f:
        run = subprocess.run([binary['path']], stdout=f, stderr=subprocess.STDOUT, timeout=180)
    lines = (out / 'run.log').read_text().splitlines()
    def parse(text):
        return json.loads(text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    summaries = [parse(x[8:]) for x in lines if x.startswith('SUMMARY ')]
    need(len(summaries) == 1, '最終統計が1件必要')
    result = summaries[0]
    rows = [parse(x[4:]) for x in lines if x.startswith('ROW ')]
    specs = [parse(x[9:]) for x in lines if x.startswith('EXPECTED ')]
    checks = [parse(x[6:]) for x in lines if x.startswith('CHECK ')]
    def timing(value):
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    statistics = result.get('statistics', [])
    stats_valid = (len(statistics) == 9 and [v.get('case') for v in statistics] == cases and
                   all(set(v.get('cpu_s', {})) == {'frozen5674', 'current05pv'} and
                       all(s.get('n') == len(s.get('values', [])) == 3 and all(timing(x) for x in s['values'])
                           for s in v['cpu_s'].values()) for v in statistics))
    complete = (run.returncode == 0 and result['status'] == 'PASS' and result['run_complete'] and
                result['coverage_pass'] and result['expected_samples'] == result['executed_samples'] == 54 and
                result['passed_samples'] == 54 and len(rows) == 54 and len(checks) == 9 and
                len(specs) == 1 and [x['id'] for x in rows] == specs[0]['required_ids'] == ids and
                len(set(ids)) == 54 and [x['id'] for x in checks] == cases and len(set(cases)) == 9 and
                result['actual_ids'] == ids and result['prevalidation_cases_passed'] == 9 and
                result['main_frame_pairs'] == 4608 and result['copy_frame_pairs'] == 144 and
                result['copy_vs_main_pairs'] == 288 and result['prevalidation_complex_values'] == 11187120 and
                result['timed_final_complex_values'] == 119862 and
                all(x.get('frames') == 512 and timing(x.get('cpu_s')) and timing(x.get('wall_s')) for x in rows) and
                stats_valid and
                all(x['pass'] for x in rows + checks))
    need(source_manifest(ROOT) == source and identity(binary['path']) == binary, '測定中の変更')
    for item in expected['sources']:
        need(identity(item['path']) == item, '測定中source変更')
    for item in (expected['driver'], expected['frozen_provenance'], expected['compiler'], baseline_id):
        need(identity(item['path']) == item, '測定中のrecipe/参照/ツール変更')
    result.update(wrapper_status='PASS' if complete else 'FAIL', returncode=run.returncode,
                  binary=binary, expected=identity(out / 'EXPECTED.json'), log=identity(out / 'run.log'))
    save(out / 'SUMMARY.json', result)
    print(out / 'SUMMARY.json')
    return 0 if complete else 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        if OWNED_OUTPUT is not None:
            save(OWNED_OUTPUT / 'SUMMARY.json', {'status': 'INCOMPLETE', 'run_complete': False,
                 'expected_samples': 54, 'error': type(error).__name__ + ': ' + str(error),
                 'whole_process_CPU_approval': False, 'PCM_oracle': False, 'RT_approval': None})
        raise
