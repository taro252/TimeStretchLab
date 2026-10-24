#!/usr/bin/env python3
"""既存の実行証拠を小さい最終索引へ結ぶ。試験・音声・承認は実行しない。

全ソース台帳と保存05を照合し、保存archiveの全54 memberを再hashする。
元SUMMARYのFAILやINCOMPLETEを変更せず、追加索引の判定と区別する。
大量PCMは再hashせず、実行時と独立capture監査の記録を参照する。
--output は新しいGit管理外directory。結果を確認して必要な小さいJSONだけを転記する。
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
SOURCE = '0d8d2e867a70878107400c85b37221c466b6243b0349adaee4ae04f8cf81b41e'
HEAD = '5674bd982d98caacaa3e87cdeae5bfc0b01c66ef'
PINS = {
    'build_timer_candidate_05/BUILD.json': '7f2476aacbbf5a16fd2c444de0d4cce6ddba2333a89b9a2f637aab60ee97777f',
    'timer_source_05/SOURCE.json': 'fc23fd8e517609bb5f7bce0f95622485f821c582c7bf54d4bda9737e5b9d77ed',
    'timer_archive_05/ARCHIVE.json': '9ae4f1e70954e41a7ebda4cfa82a205444d5390fb00f017dd2909ac827434313',
}
RUNS = (
    'interactive_pairs_final06', 'steady_pairs_final06', 'steady_followup_final07',
    'ab_main_recovered_final07', 'ab_nonfresh_pairs_final07', 'ab_capture_audit_final07',
    'warm_ab_pairs_final08', 'paused_deep_pairs_final08', 'warm_ab_capture_audit_final08',
    'reservation_probe_validation_final08', 'abi_headers_final07', 'debug_functional_final06',
    'debug_checkpoint_final07', 'd3_related_timer_02', 'checkpoint_rejection_final_01',
    'checkpoint_positive_final_02', 'steady_thread_cpu_pairs_01', 'steady_thread_cpu_pairs_02',
    'steady_digest_cpu_pairs_01', 'mono2_ablation_01', 'diagnostic_sample_final07',
    'mono2_diagnostic_sample_01',
    'mono_vocoder_bench_01',
)
HISTORY = (
    'ab_main_pairs_final06', 'ab_nonfresh_pairs_final06', 'ab_capture_audit_final06',
    'steady_followup_final06', 'warm_ab_pairs_final07', 'paused_deep_pairs_final07',
    'warm_ab_capture_audit_final07', 'debug_checkpoint_final06', 'abi_headers_final06',
    'armed_wait_revision_pairs_final_01',
    'mono2_digest_ablation_01', 'checkpoint_positive_experiment07',
)
RECORDS = (
    'build_timer_candidate_05/BUILD.json', 'timer_source_05/SOURCE.json',
    'timer_archive_05/ARCHIVE.json', 'build_d3_regressions_02/BUILD.json',
    'build_debug_01/BUILD.json', 'build_restored_05/BUILD.json',
    'FINAL05_REUSE_AUDIT.json', 'FINAL05_NATIVE_STATUS_REVIEW.json',
    'EXPERIMENT06_REJECTED.json', 'experiment06_archive/ARCHIVE.json',
    'EXPERIMENT07_REJECTED.json', 'experiment07_archive/ARCHIVE.json',
    'steady_thread_cpu_clients_02/CLIENT.json',
    'steady_digest_cpu_clients_01/CLIENT.json',
    'AB_FINAL_PREFIX_SHARING01.json', 'AB_FINAL_RECLAIM_QUIESCENCE01.json',
)
REVIEWS = ('FINAL_CPU_REVIEW_02.md', 'FINAL_PRODUCT_REVIEW_02.md',
           'FINAL05_NATIVE_STATUS_REVIEW.md', 'THREAD_CPU_REVIEW.md',
           'CPU_REGRESSION_CAUSE_REVIEW.md', 'STAGE_DIGEST_DISPATCH_REVIEW.md',
           'DIGEST_ASSEMBLY_REVIEW.md', 'MONO_BENCH_WRAPPER_REVIEW.md')


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def identity(path):
    p = Path(path).resolve()
    with p.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    return {'path': str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
            'bytes': p.stat().st_size, 'sha256': digest}


def read(path):
    return json.loads(Path(path).read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    need(out.is_relative_to(ROOT / 'build'), 'Git管理外の新規出力先が必要')
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from phase62_evidence import source_manifest
    source = source_manifest(ROOT)
    pinned = {p: identity(BASE / p) for p in PINS}
    need(all(pinned[p]['sha256'] == digest for p, digest in PINS.items()), '保存05の固定metadata SHAが異なる')
    snapshot = read(BASE / 'timer_source_05/SOURCE.json')
    need(source['sha256'] == SOURCE == snapshot['source'], '現在のソースが保存05と異なる')
    need(source == snapshot['source_manifest'], '全ソースfile台帳が異なる')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    need(head == HEAD, 'HEADが変わったため索引条件の更新が必要')
    archive = read(BASE / 'timer_archive_05/ARCHIVE.json')
    need(archive['source'] == SOURCE and len(archive['files']) == 54, '保存54memberが必要')
    for key, relative in (('build', 'build_timer_candidate_05/BUILD.json'),
                          ('source_snapshot', 'timer_source_05/SOURCE.json')):
        need(all(archive[key][k] == pinned[relative][k] for k in ('bytes', 'sha256')) and
             Path(archive[key]['path']).resolve() == (BASE / relative).resolve(), 'archiveとbuild/source bindingが異なる')
    verified = [];names = set()
    for row in archive['files']:
        saved = Path(row['archived']['path']).resolve()
        need(saved.parent == BASE / 'timer_archive_05' and saved.name not in names and
             all(row['original'][k] == row['archived'][k] for k in ('bytes', 'sha256')), '保存memberの一意性・元SHA・directory')
        names.add(saved.name)
        item = identity(row['archived']['path'])
        need(all(item[k] == row['archived'][k] for k in ('bytes', 'sha256')), '保存archiveの変更')
        verified.append(item)
    rows = []
    for historical, names in ((False, RUNS), (True, HISTORY)):
        for name in names:
            p = BASE / name / 'SUMMARY.json'
            need(p.is_file(), '必須要約の欠落: ' + str(p))
            if not historical:
                need((BASE / name / 'EXPECTED.json').is_file(), '必須実行の期待台帳が欠落: ' + name)
            if name in ('steady_thread_cpu_pairs_01', 'steady_thread_cpu_pairs_02', 'steady_digest_cpu_pairs_01'):
                need((BASE / name / 'ROWS.json').is_file(), '診断の別ROWS台帳が欠落: ' + name)
            value = read(p)
            scalars = {k: v for k, v in value.items() if not isinstance(v, (dict, list))}
            companions = [identity(BASE / name / n) for n in ('EXPECTED.json', 'ROWS.json')
                          if (BASE / name / n).is_file()]
            rows.append({'run': name, 'historical_attempt': historical, 'summary': identity(p),
                         'original_scalar_fields': scalars, 'companion_records': companions,
                         'source_scope': '各元EXPECTEDのsource/build/版別対応を参照。全行を現在05実行へ付替えない。',
                         'interpretation': '元statusを保持。機能・RT・性能・品質を別判定する'})
    records = [identity(BASE / p) for p in (*RECORDS, *REVIEWS)]
    git_status = subprocess.check_output(['git', 'status', '--porcelain=v1', '-uall'], cwd=ROOT, text=True)
    (out / 'GIT_STATUS.txt').write_text(git_status)
    patch = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=ROOT)
    (out / 'TRACKED.patch').write_bytes(patch)
    tracked = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD'], cwd=ROOT, text=True).splitlines()
    untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    delivery = [identity(ROOT / p) for p in sorted(set(tracked + untracked)) if (ROOT / p).is_file()]
    need(not any(p['bytes'] >= 50_000_000 for p in delivery), '変更fileがGit blob上限以上')
    result = {'schema': 'performance-response-final-evidence-v1',
              'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'index_collection': 'COMPLETE', 'canonical_source_archive_verification': 'PASS',
              'tests_executed_by_this_indexer': 0,
              'run_results_revalidated_by_this_indexer': False,
              'run_validation_scope': '個別driverと独立最終監査の結果を索引する。元件数/PCM/RTを再実行・再判定したPASSではない。',
              'head': head, 'branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
              'source_inventory_sha256': SOURCE, 'source_files': len(source['files']),
              'source_inventory_is_not_commit_SHA': True, 'uncommitted': bool(git_status),
              'tracked_patch': identity(out / 'TRACKED.patch'), 'git_status': identity(out / 'GIT_STATUS.txt'),
              'delivery_files_except_later_generated_final_indexes': delivery,
              'canonical_archive_54_full_SHA_verified': verified, 'records': records, 'runs': rows,
              'core_gates': identity(ROOT / 'results/performance_response/evidence/CORE_GATES.json'),
              'original_failure_history': identity(ROOT / 'results/performance_response/evidence/FAILURE_HISTORY.json'),
              'large_PCM_policy': '今回の索引では再hashしない。元EXPECTED/参照manifest/独立capture最終監査に記録された全byte照合を限定再利用。新しいPCM試験数に加えない。',
              'no_grand_total': True, 'CPU_adoption': 'WITHHELD', 'local_overall': 'INCOMPLETE',
              'public_release': 'NOT_APPROVED', 'Merodoa_default': 'NOT_APPROVED',
              'human_physical_application_F': 'NOT_RUN', 'commit_push_release_performed': False}
    need(source_manifest(ROOT) == source and
         subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == head and
         subprocess.check_output(['git', 'status', '--porcelain=v1', '-uall'], cwd=ROOT, text=True) == git_status and
         subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=ROOT) == patch,
         '索引作成中にsource/HEAD/差分が変わった')
    for item in (*verified, *records, *delivery, *pinned.values()):
        path = Path(item['path'])
        need(identity(path if path.is_absolute() else ROOT / path) == item, '索引作成中のfile変更')
    result['begin_end_source_HEAD_metadata_delivery_consistent'] = True
    (out / 'FINAL_GATES.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': 'PASS', 'indexed_runs': len(rows), 'archive_members': len(verified),
                      'record': identity(out / 'FINAL_GATES.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
