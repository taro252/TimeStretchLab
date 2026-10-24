#!/usr/bin/env python3
"""49targetを含むABI用60member索引を追加する。保存54member索引は変更しない。"""
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity
B = ROOT / 'build/performance_response_20261023_01'
original = B / 'native_archive_08/ARCHIVE.json'
out = original.with_name('ABI_ARCHIVE60.json')
if out.exists():
    raise FileExistsError(out)
archive = json.loads(original.read_text())
current = json.loads((B / 'native_source_08/SOURCE.json').read_text())
previous = json.loads((B / 'timer_source_05/SOURCE.json').read_text())
if archive['source'] != current['source'] or current['source'] != 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94':
    raise ValueError('source08のみ')
before = {r['path']: r['sha256'] for r in previous['source_manifest']['files']}
after = {r['path']: r['sha256'] for r in current['source_manifest']['files']}
changes = [p for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]
if changes != ['src/platform/macos/ProgressiveMacPlaybackEngine.h']:
    raise ValueError('05からの差分が異なる')
rows = archive['files'] + archive['extra_target_files']
if len(rows) != 60 or len({r['original']['path'] for r in rows}) != 60:
    raise ValueError('49exe/10archive/1probeの完全集合が必要')
for row in rows:
    if identity(row['archived']['path']) != row['archived']:
        raise ValueError('保存fileの変更')
archive.update(files=rows, old_source=previous['source'], changed_source_paths=changes,
               parent_archive=identity(original), adapter_driver=identity(__file__),
               scope='ABIの全49実行体対応用metadata。元54member索引と実ファイルは変更しない。')
out.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + '\n')
print(out)
