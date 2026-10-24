#!/usr/bin/env python3
"""08の最終索引とGit側小証拠を対応付ける。PCM/音声を実行せず承認もしない。"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
R = Path(__file__).resolve().parents[3]
B = R / 'build/performance_response_20261023_01'
O = R / 'results/performance_response'
sys.path.insert(0, str(R / 'scripts'))
from phase62_evidence import source_manifest
SOURCE = 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94'


def need(value, why):
    if not value:
        raise ValueError(why)


def identity(path):
    path = path.resolve()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path.relative_to(R)), 'bytes': path.stat().st_size, 'sha256': digest}


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--index', type=Path, required=True)
a = p.parse_args()
index = a.index.resolve()
need(index.is_relative_to(B) and index.is_file(), 'B内の最終索引')
actual = source_manifest(R)
need(actual['sha256'] == SOURCE and len(actual['files']) == 768, '08全source')
value = json.loads(index.read_text())
need(value['index_integrity'] == 'PASS' and value['source_inventory_sha256'] == SOURCE
     and value['local_overall'] == 'INCOMPLETE' and value['CPU_adoption'] == 'NOT_ADOPTED', '誤承認しない最終索引')
export = O / 'evidence/FINAL_GATES.json'
need(export.read_bytes() == index.read_bytes(), '索引copy全byte一致')
out = O / 'manifest.json'
need(not out.exists(), '既存manifestを上書きしない')
files = [identity(path) for path in sorted(O.rglob('*')) if path.is_file() and path != out
         and '__pycache__' not in path.parts]
need(all(item['bytes'] < 50_000_000 for item in files), 'Git blob上限')
build = json.loads((B / 'build_native_default_08/BUILD.json').read_text())
need(build['status'] == 'PASS' and build['source'] == SOURCE and len(build['binaries']) == 49, '08新build49')
git = lambda *args: subprocess.check_output(['git', *args], cwd=R)
patch = git('diff', '--binary', '--full-index', 'HEAD')
result = {'schema': 'performance-response-final-manifest-v1',
          'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'head': git('rev-parse', 'HEAD').decode().strip(),
          'branch': git('branch', '--show-current').decode().strip(),
          'uncommitted': bool(git('status', '--porcelain=v1', '-uall')),
          'source_manifest': actual, 'tracked_patch': {'bytes': len(patch), 'sha256': hashlib.sha256(patch).hexdigest()},
          'index_original': identity(index), 'index_export': identity(export),
          'candidate_build': identity(B / 'build_native_default_08/BUILD.json'),
          'configuration': 'Release arm64 C++20 -O3 -DNDEBUG', 'candidate_binaries': build['binaries'],
          'local_overall': 'INCOMPLETE', 'CPU_bundle': 'NOT_ADOPTED',
          'public_release': 'WITHHELD', 'Merodoa_default': 'UNCHANGED',
          'evidence_files': files, 'excluded_self': str(out.relative_to(R)),
          'counts_policy': '各SUMMARY/EXPECTEDのsourceと単位を維持し、総PASS件数へ加算しない。',
          'large_assets': str(B.relative_to(R)),
          'restore': 'REPRODUCE.mdと元EXPECTED/BUILD/SOURCEを参照。必須凍結素材欠落はBLOCKED。',
          'no_PCM_rehash_or_new_test_credit': True, 'no_commit_push_release': True}
need(source_manifest(R) == actual and git('diff', '--binary', '--full-index', 'HEAD') == patch,
     'manifest作成中のsource/差分変更')
need([identity(R / item['path']) for item in files] == files, 'small証拠の途中変更')
out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
print(json.dumps({'manifest': identity(out), 'source': SOURCE, 'local_overall': result['local_overall']}, ensure_ascii=False))
