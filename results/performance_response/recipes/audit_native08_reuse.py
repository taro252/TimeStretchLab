#!/usr/bin/env python3
"""05→08の同一実行体による旧core結果の限定再利用を監査する。試験は行わない。

 --output build/performance_response_20261023_01/native08_reuse_audit_01
実行時に768 source×両snapshot、現在08 source、05保存54、08保存54+6、
現在49実行体を全SHA確認する。作成/AST検査時にはこれらを実行しない。
FINAL05_REUSE_AUDITの固定16行を対象に、実際の歴史的実行体SHAが08保存exeと
同じ場合だけ旧実施として継承する。依存ライブラリ一致による代替推定は禁止。
libphase57_synthesis.aの差を保持し、shared lib全一致とは主張しない。
native CPU/応答/RT、新captureは常に非継承。曖昧/欠落はNOT_TRANSFERRED。
入力/RAW参照のpayloadは再hashせず、元EXPECTED/SUMMARYの固定identityに含まれる
原path/size/SHAを保持し、存在/記録sizeだけ確認する。小metadata/参照exeは再hash。
元PCM比較の再試験や新PASS数へは数えず、元品質FAILもそのまま保持する。
"""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BASE = (ROOT / 'build/performance_response_20261023_01').resolve()
SOURCE05 = '0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e'
SOURCE08 = 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94'
HEAD = '5674bd982d98caacaa3e87cdeae5bfc0b01c66ef'
HEADER = 'src/platform/macos/ProgressiveMacPlaybackEngine.h'
LEDGER = BASE / 'FINAL05_REUSE_AUDIT.json'
PINS = {
    'FINAL05_REUSE_AUDIT.json': 'fd0266ad944d251e6c8e49c132a88e416f5af0a7f0a0feeefb8352a075b4615d',
    'timer_source_05/SOURCE.json': 'fc23fd8e517609bb5f7bce0f95622485f821c582c7bf54d4bda9737e5b9d77ed',
    'timer_archive_05/ARCHIVE.json': '9ae4f1e70954e41a7ebda4cfa82a205444d5390fb00f017dd2909ac827434313',
    'build_timer_candidate_05/BUILD.json': '7f2476aacbbf5a16fd2c444de0d4cce6ddba2333a89b9a2f637aab60ee97777f',
    'native_source_08/SOURCE.json': 'f2304408ea89ba72b4d0c2dc3f1e8d609b1a780b69d0835f854586d4016515ad',
    'native_archive_08/ARCHIVE.json': '8559063d9905dddabe366c225368e27ba628250042d4e79877bd8162aae14f3a',
    'build_native_default_08/BUILD.json': '6a1ea92a6b968e916ce416f7e74e69b2a421cb7b4ee9392759fda3fbec97454f'}
CORE_IDS = {'fixed10304', 'exact896', 'golden25', 'finite_loop966', 'dynamic640', 'formats32',
            'planner52', 'dsp156', 'planner72', 'c2_standard_full_03', 'c2_workgroup_full_03',
            'c2_unstarted', 'checkpoint_positive', 'checkpoint_rejection', 'v4_contract', 'quality78'}
RAW_SUFFIXES = {'.wav', '.pcm', '.f32', '.raw', '.aif', '.aiff', '.flac'}


def need(ok, message):
    if not ok:raise ValueError(message)


def path_of(value):
    path = Path(value['path'] if isinstance(value, dict) else value)
    return (path if path.is_absolute() else ROOT / path).resolve()


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path):
    path = path_of(path)
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha(path)}


def read(path):
    def pairs(entries):
        result = {}
        for key, value in entries:need(key not in result, 'Duplicate JSON key');result[key] = value
        return result
    def reject(value):raise ValueError('Nonfinite JSON: ' + value)
    value = json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=reject)
    def inspect(child):
        if isinstance(child, dict):
            for v in child.values():inspect(v)
        elif isinstance(child, list):
            for v in child:inspect(v)
        elif isinstance(child, float):need(math.isfinite(child), 'Nonfinite JSON number')
    inspect(value);return value


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    temp = path.with_name('.' + path.name + '.tmp');need(not temp.exists(), 'Temporary output already exists')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n');os.replace(temp, path)
    finally:
        if temp.exists():temp.unlink()


def metadata_equal(first, second):
    return path_of(first) == path_of(second) and all(first[k] == second[k] for k in ('bytes', 'sha256'))


def embedded_contexts(value):
    """元metadata内の入力/参照identityを保持する。payloadの新SHAを捏造しない。"""
    found = {}
    def add(item):
        if isinstance(item.get('path'), str) and isinstance(item.get('sha256'), str) and len(item['sha256']) == 64:
            kept = {k: item[k] for k in ('path', 'bytes', 'sha256') if k in item}
            found[canonical_sha(kept)] = kept
    def walk(child, pointer=''):
        if isinstance(child, dict):
            context = any(word in pointer.lower() for word in ('input', 'reference', 'oracle', 'fixture', 'raw'))
            if context or Path(str(child.get('path', ''))).suffix.lower() in RAW_SUFFIXES:add(child)
            for key, digest in child.items():
                if key.endswith('_sha256') and isinstance(digest, str):
                    name = key[:-7];candidate = child.get(name)
                    if isinstance(candidate, str) and any(word in name.lower() for word in ('input', 'reference', 'oracle', 'fixture', 'raw')):
                        add({'path': candidate, 'sha256': digest})
                # source_manifest.filesの相対pathは、その凍結source root内の座標。
                # 入力/参照payloadとして現在のROOTへ誤って解決しない。
                if key not in ('source_manifest', 'oracle_source_manifest'):
                    walk(digest, pointer + '/' + key)
        elif isinstance(child, list):
            for index, entry in enumerate(child):walk(entry, pointer + '/' + str(index))
    walk(value);return [found[k] for k in sorted(found)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True);args = parser.parse_args()
    out = args.output.resolve();need(out.is_relative_to(BASE) and out != BASE, 'New B output directory required')
    out.mkdir(parents=True, exist_ok=False)
    result = {'schema': 'native08-core-reuse-audit-v1', 'status': 'INCOMPLETE',
              'source05': SOURCE05, 'source08': SOURCE08, 'new_test_programs': 0, 'new_PASS_count': 0,
              'all_reused_results_are_historical_not_new_runs': True, 'no_grand_total': True,
              'native_CPU_latency_RT_and_new_captures_transferred': False,
              'full_input_RAW_PCM_rehash': False, 'CPU_public_quality_approval': False,
              'shared_libraries_all_identical': False, 'rows': [],
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(out / 'AUDIT.json', result)
    checked = {};raw_stats = {};contexts = {}
    def verify(path, declared=None, binary=False):
        path = path_of(path);need(path.is_relative_to(ROOT) and path.is_file(), 'Missing/outside repository: ' + str(path))
        need(path.suffix.lower() not in RAW_SUFFIXES, 'Raw payload hash forbidden in this audit')
        if not binary:need(path.stat().st_size <= 32 * 1024 * 1024, 'Metadata too large')
        key = str(path)
        if key not in checked:checked[key] = identity(path)
        item = checked[key]
        if declared is not None:need(metadata_equal(item, declared), 'Original identity mismatch: ' + str(path))
        return item
    def context_for(meta_id):
        key = meta_id['path']
        if key in contexts:return key
        value = read(key);records = embedded_contexts(value);rows = []
        for original in records:
            path = path_of(original);need(path.is_relative_to(ROOT) and path.is_file(), 'Original input/reference unavailable: ' + str(path))
            need('bytes' not in original or path.stat().st_size == original['bytes'], 'Original payload size changed')
            row = {'original_identity': original}
            if path.suffix.lower() in RAW_SUFFIXES:
                row.update(verification='ORIGINAL_RECORDED_SHA_PRESERVED; payload SHA not rechecked',
                           observed_bytes=path.stat().st_size)
                raw_stats[str(path)] = path.stat().st_size
            else:
                current = verify(path, binary=True)
                need(current['sha256'] == original['sha256'], 'Reference/fixture metadata or binary changed')
                row.update(verification='CURRENT_FULL_SHA_MATCH', current=current)
            rows.append(row)
        contexts[key] = {'metadata_identity': meta_id, 'original_context_count': len(records),
                         'original_context_sha256': canonical_sha(records), 'identities': rows,
                         'binding': 'Original metadata bytes/SHA unchanged. Does not certify fresh RAW equality.'}
        return key
    try:
        records = {name: verify(BASE / name) for name in PINS}
        need(all(records[n]['sha256'] == expected for n, expected in PINS.items()), 'Pinned provenance differs')
        ledger = read(LEDGER);need(ledger['final_source'] == SOURCE05 and ledger['status'] == 'PASS_IDENTITY_AUDIT', 'Original05 ledger required')
        selected = [r for r in ledger['reuse_rows'] if r.get('reuse_eligible') is True]
        need(len(selected) == ledger['reuse_eligible_rows'] == 16 and {r['id'] for r in selected} == CORE_IDS, 'Exact16 original core rows required')
        sys.path.insert(0, str(ROOT / 'scripts'))
        from phase62_evidence import source_manifest
        snapshots = {};archives = {};builds = {};manifests = {};artifact_maps = {}
        for label, src, directory, arc_dir, build_name in (
            ('05', SOURCE05, 'timer_source_05', 'timer_archive_05', 'build_timer_candidate_05/BUILD.json'),
            ('08', SOURCE08, 'native_source_08', 'native_archive_08', 'build_native_default_08/BUILD.json')):
            snapshot = read(BASE / directory / 'SOURCE.json');archive = read(BASE / arc_dir / 'ARCHIVE.json');build = read(BASE / build_name)
            manifest = source_manifest(BASE / directory)
            need(manifest == snapshot['source_manifest'] == build['source_manifest'] and manifest['sha256'] == src
                 and len(manifest['files']) == 768 and snapshot['source'] == archive['source'] == build['source'] == src,
                 'Full snapshot/source/build binding failed: ' + label)
            need(build['status'] == 'PASS' and metadata_equal(records[build_name], archive['build'])
                 and metadata_equal(records[directory + '/SOURCE.json'], archive['source_snapshot']), 'Archive metadata binding failed')
            need(len(archive['files']) == 54, '54 primary members required')
            mapping = {}
            for row in archive['files']:
                original, saved = row['original'], row['archived'];path = path_of(saved)
                need(path.parent == BASE / arc_dir and path.name not in mapping
                     and all(original[k] == saved[k] for k in ('bytes', 'sha256')), 'Primary artifact path/uniqueness/origin')
                verify(path, saved, binary=True);mapping[path.name] = row
            snapshots[label] = snapshot;archives[label] = archive;builds[label] = build
            manifests[label] = manifest;artifact_maps[label] = mapping
        need(set(artifact_maps['05']) == set(artifact_maps['08']), 'Same54 primary artifact names required')
        maps = {label: {r['path']: r['sha256'] for r in manifests[label]['files']} for label in ('05', '08')}
        need(set(maps['05']) == set(maps['08']), 'Same768 source path set required')
        changed_source = [p for p in maps['05'] if maps['05'][p] != maps['08'][p]]
        need(changed_source == [HEADER], '05→08 changes must be Engine.h only')
        before = (BASE / 'timer_source_05' / HEADER).read_bytes();after = (BASE / 'native_source_08' / HEADER).read_bytes()
        old_block = '    bool recordStageDigests=false; // 内部DSP hash。入力SHAと最終PCM照合は省略しない。\n'.encode()
        new_block = ('    // 内部DSP hash。OFFでmonoの全体CPU増加を実測したため既存ONを維持する。\n'
                     '    // 詳細profileとは独立し、入力SHAと最終PCM照合も省略しない。\n'
                     '    bool recordStageDigests=true;\n').encode()
        need(before.count(old_block) == 1 and before.replace(old_block, new_block) == after,
             'Only native digest default false→true and its explanatory comments may differ')
        current = source_manifest(ROOT);need(current == manifests['08'], 'Current source is not canonical08')
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip();need(head == HEAD, 'Fixed HEAD changed')
        artifact_comparison = []
        for name in sorted(artifact_maps['05']):
            old, new = artifact_maps['05'][name]['archived'], artifact_maps['08'][name]['archived']
            same = all(old[k] == new[k] for k in ('bytes', 'sha256'))
            artifact_comparison.append({'name': name, 'same_bytes_SHA': same, 'original05': old, 'native08': new})
        equal = [r['name'] for r in artifact_comparison if r['same_bytes_SHA']]
        different = [r['name'] for r in artifact_comparison if not r['same_bytes_SHA']]
        need(len(equal) == 38 and len(different) == 16 and 'libphase57_synthesis.a' in different,
             'Expected38 same/16 changed and changed phase57 archive')
        extras = archives['08']['extra_target_files'];need(len(extras) == 6, 'Six08 extra target files required')
        all08 = dict(artifact_maps['08'])
        for row in extras:
            path = path_of(row['archived']);need(path.parent == BASE / 'native_archive_08/extra_targets'
                and path.name not in all08 and all(row['original'][k] == row['archived'][k] for k in ('bytes', 'sha256')), 'Extra artifact identity')
            verify(path, row['archived'], binary=True);all08[path.name] = row
        binaries = builds['08']['binaries'];need(len(binaries) == archives['08']['distinct_executables'] == 49, '49 native08 executables required')
        exe_rows = []
        for name, declared in binaries.items():
            need(name in all08 and metadata_equal(declared, all08[name]['original']), '08 BUILD/executable/archive mismatch')
            verify(declared['path'], declared, binary=True)
            old = artifact_maps['05'].get(name)
            state = ('NO_05_PRIMARY_ENTRY' if old is None else 'SAME_EXE' if all(
                old['archived'][k] == all08[name]['archived'][k] for k in ('bytes', 'sha256')) else 'CHANGED_EXE')
            exe_rows.append({'target': name, 'classification': state, 'original05': old['archived'] if old else None,
                             'native08': all08[name]['archived'], 'current08': declared})
        for original in selected:
            row = {'id': original['id'], 'run': original.get('run'), 'historical_status': original.get('historical_status'),
                   'historical_counts': original.get('historical_counts'), 'original_basis': original.get('basis'),
                   'original_scope': original.get('scope'), 'original_runtime': original.get('runtime'),
                   'original_dependencies': original.get('dependencies'), 'new_execution_count': 0,
                   'classification': 'NOT_TRANSFERRED', 'input_reference_context_keys': [], 'reasons': []}
            try:
                need(original.get('basis') == 'SAME_BINARY', 'Original row relied on a different client/dependency basis; do not infer')
                need(bool(original.get('runtime')), 'No original runtime identity')
                proof = []
                for runtime in original['runtime']:
                    target = runtime['target'];need(target in binaries and target in artifact_maps['05'], 'Missing target binding')
                    old, new = artifact_maps['05'][target]['archived'], all08[target]['archived']
                    need(metadata_equal(old, runtime['timer05']) and runtime['historical_runtime_sha256'] == old['sha256']
                         and all(old[k] == new[k] for k in ('bytes', 'sha256')), 'Historical/05/08 executable not identical')
                    proof.append({'target': target, 'historical_runtime_sha256': runtime['historical_runtime_sha256'], 'saved05': old, 'native08': new})
                need(not original.get('dependencies'), 'Ambiguous additional runtime dependencies; do not infer')
                evidence = []
                for item in [*original.get('evidence', []), *original.get('extra_identity', [])]:
                    declared = item['expected'];need(item.get('match') is True, 'Prior metadata identity was not verified')
                    current_id = verify(declared['path'], declared, binary=True);evidence.append(current_id)
                    if path_of(declared).suffix.lower() == '.json':row['input_reference_context_keys'].append(context_for(current_id))
                need(bool(evidence) and bool(row['input_reference_context_keys']), 'Missing preserved input/reference metadata context')
                row.update(classification='HISTORICAL_SAME_EXE_ONLY', reuse_eligible=True,
                           runtime_identity_proof=proof, original_evidence_verified=evidence,
                           inherited_scope='Only original PCM/numeric/planner/functional findings. Native CPU/response/RT and new capture excluded.')
            except (ValueError, OSError, KeyError, TypeError) as error:
                row.update(reuse_eligible=False);row['reasons'].append(type(error).__name__ + ': ' + str(error))
            result['rows'].append(row)
        context_path = out / 'INPUT_REFERENCE_IDENTITIES.json'
        save(context_path, {'schema': 'native08-preserved-historical-context-v1', 'contexts': contexts,
                            'payload_policy': 'Original recorded identities/size retained; no new raw payload SHA test.',
                            'new_PCM_checks': 0})
        result.update(records=records, original05_ledger=records['FINAL05_REUSE_AUDIT.json'],
                      source_difference={'files_each': 768, 'changed_paths': changed_source, 'other767_identical': True,
                                         'default_change_and_explanatory_comments_only': True}, primary_artifacts=artifact_comparison,
                      artifact_counts={'same': len(equal), 'changed': len(different), 'extras08': 6},
                      changed_artifacts=different, unchanged_artifacts=equal, executables49=exe_rows,
                      input_reference_contexts=identity(context_path),
                      excluded_original_rows=[r['id'] for r in ledger['reuse_rows'] if not r.get('reuse_eligible')],
                      old_native_measurements_not_transferred=[{'run': r.get('run'), 'run_source': r.get('run_source')}
                                                              for r in ledger['old_native_measurements_not_transferred']],
                      reused_historical_rows=sum(r.get('reuse_eligible', False) for r in result['rows']),
                      not_transferred_core_rows=[r['id'] for r in result['rows'] if not r.get('reuse_eligible')])
        need(source_manifest(ROOT) == current and source_manifest(BASE / 'timer_source_05') == manifests['05']
             and source_manifest(BASE / 'native_source_08') == manifests['08'], 'Source changed during audit')
        need(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == head, 'HEAD changed')
        for path, item in checked.items():need(identity(path) == item, 'Verified artifact/metadata changed during audit')
        for path, size in raw_stats.items():need(Path(path).is_file() and Path(path).stat().st_size == size, 'Historical payload disappeared/size changed')
        result.update(status='PASS_IDENTITY_AUDIT', begin_end_source_artifact_context_consistent=True,
                      full_snapshot_and_binary_SHA_verified_at_runtime=True)
    except BaseException as error:
        result.update(status='INCOMPLETE', error=type(error).__name__ + ': ' + str(error))
    save(out / 'AUDIT.json', result)
    print(json.dumps({'status': result['status'], 'new_execution_count': 0,
                      'audit': identity(out / 'AUDIT.json')}, ensure_ascii=False))
    return 0 if result['status'] == 'PASS_IDENTITY_AUDIT' else 2


if __name__ == '__main__':
    raise SystemExit(main())
