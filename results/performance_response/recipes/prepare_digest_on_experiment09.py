#!/usr/bin/env python3
"""08を保持し、07のblock分岐だけをON条件で再評価する独立ソース09を作る。"""
import ctypes
import datetime
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
B = ROOT / 'build/performance_response_20261023_01'
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity, source_manifest


def need(value, why):
    if not value:
        raise ValueError(why)


source08 = 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94'
source = source_manifest(ROOT)
need(source['sha256'] == source08, 'root08保持')
snapshot = B / 'digest_on_source_09'
record = B / 'DIGEST_ON_EXPERIMENT09_PLAN.json'
need(not snapshot.exists() and not record.exists(), '一意な新規出力先')
draft = B / 'stage_digest_experiment07_draft/after.cpp'
need(identity(draft)['sha256'] == 'c12dee6510abcc9295f72634b127c144ad01c21abd6dfeade9a9aa8d81e0d76b', '保存07原文')
cpp = 'src/prototype/Phase57ProgressiveSynthesis.cpp'
plan = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status': 'PLANNED', 'live_source': source08, 'modified_paths': [cpp],
        'before': identity(ROOT / cpp), 'after': identity(draft), 'snapshot': str(snapshot),
        'conditions': {'native_stage_hash': True, 'speed_micros': 1000000,
                       'input': 'mono48 Float32 chain300', 'preset': 'candidate',
                       'steady_seconds': 30, 'versions': ['old5674', 'saved08', 'new09'],
                       'repeats': 3, 'expected_native_programs': 9,
                       'order': ['old/saved/new', 'saved/new/old', 'new/old/saved']},
        'small_precheck': '同構成の独立固定RAWによるcheckpoint拒否後suffix/明示Exact全PCMの3case',
        'decision': 'ON条件のCPUを測り、改善しなければ採用しない。広い回帰は有望な場合だけ。',
        'history': '07はOFF/mono2で棄却済み。その結果をON/mono1の成功へ書き換えない。',
        'live_product_modified': False, 'driver': identity(__file__)}
record.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
snapshot.mkdir()
libc = ctypes.CDLL(None, use_errno=True)
clone = libc.clonefile
clone.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
clone.restype = ctypes.c_int
for row in source['files']:
    original, dest = ROOT / row['path'], snapshot / row['path']
    dest.parent.mkdir(parents=True, exist_ok=True)
    if clone(os.fsencode(original), os.fsencode(dest), 0):
        raise OSError(ctypes.get_errno(), 'clonefile: ' + str(original))
    need(identity(dest)['sha256'] == row['sha256'], '複製全SHA')
(snapshot / cpp).write_bytes(draft.read_bytes())
experiment = source_manifest(snapshot)
before = {r['path']: r['sha256'] for r in source['files']}
after = {r['path']: r['sha256'] for r in experiment['files']}
need([p for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)] == [cpp], '差分は1cppのみ')
need(source_manifest(ROOT) == source, 'root08不変')
(snapshot / 'SOURCE.json').write_text(json.dumps({'source': experiment['sha256'],
    'source_manifest': experiment, 'parent_source': source08, 'changed_paths': [cpp],
    'plan': identity(record), 'driver': identity(__file__), 'product_adoption': False},
    ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'status': 'PASS_SOURCE_PREPARED', 'source': experiment['sha256'],
                  'source_files': len(experiment['files']), 'live_product_modified': False}))
