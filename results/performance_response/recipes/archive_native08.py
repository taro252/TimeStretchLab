#!/usr/bin/env python3
"""最終08の全ソースと実行体をAPFS複製して保存する。試験・性能承認はしない。"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity, source_manifest


def need(ok, message):
    if not ok:
        raise ValueError(message)


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--archive', type=Path, required=True)
    a = p.parse_args()
    snapshot, archive = a.snapshot.resolve(), a.archive.resolve()
    need(all(x.is_relative_to(BASE) and not x.exists() for x in (snapshot, archive)), '新規B内directory')
    source = source_manifest(ROOT)
    need(source['sha256'] == 'b17217d8f9a7fffd0535bb360adda447015c08df232af519917937de8470ac94', '08のみ')
    build_path = BASE / 'build_native_default_08/BUILD.json'
    build = json.loads(build_path.read_text())
    need(build['status'] == 'PASS' and build['source_manifest'] == source and
         build['source'] == source['sha256'] and len(build['binaries']) == 49, '新規49target BUILD')
    old_path = BASE / 'timer_archive_05/ARCHIVE.json'
    need(identity(old_path)['sha256'] == '9ae4f1e70954e41a7ebda4cfa82a205444d5390fb00f017dd2909ac827434313', '54 memberの名前集合')
    old = json.loads(old_path.read_text())
    need(len(old['files']) == 54, '43exe/10archive/1probe')
    snapshot.mkdir(); archive.mkdir()
    libc = ctypes.CDLL(None, use_errno=True)
    clone = libc.clonefile
    clone.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int)
    clone.restype = ctypes.c_int

    def copy(original, destination):
        need(original.is_file() and not original.is_symlink() and not destination.exists(), '通常fileのみ')
        before = identity(original)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if clone(os.fsencode(original), os.fsencode(destination), 0):
            raise OSError(ctypes.get_errno(), 'clonefile失敗: ' + str(original))
        after = identity(destination)
        need(identity(original) == before and
             all(before[k] == after[k] for k in ('bytes', 'sha256')), '複製の全byte照合')
        return {'original': before, 'archived': after}

    for row in source['files']:
        need(identity(ROOT / row['path'])['sha256'] == row['sha256'], 'source SHA')
        copy(ROOT / row['path'], snapshot / row['path'])
    need(source_manifest(snapshot) == source and source_manifest(ROOT) == source, '全768source照合')
    save(snapshot / 'SOURCE.json', {'source': source['sha256'], 'source_manifest': source,
         'build': identity(build_path), 'method': 'APFS clonefile; 全byte/SHA照合',
         'driver': identity(__file__)})
    rows = []
    names = set()
    build_dir = BASE / 'candidate'
    for row in old['files']:
        name = Path(row['original']['path']).name
        need(name not in names, '一意なmember名')
        names.add(name)
        item = copy(build_dir / name, archive / name)
        if name in build['binaries']:
            need(item['original'] == build['binaries'][name], 'BUILD実行体と一致')
        rows.append(item)
    extras = []
    for name, item in build['binaries'].items():
        if name not in names:
            extra = copy(Path(item['path']), archive / 'extra_targets' / name)
            need(extra['original'] == item, '追加BUILD実行体と一致')
            extras.append(extra)
    need(len(extras) == 6 and source_manifest(ROOT) == source, '43+6 distinct targets')
    save(archive / 'ARCHIVE.json', {'status': 'PASS', 'source': source['sha256'],
         'build': identity(build_path), 'source_snapshot': identity(snapshot / 'SOURCE.json'),
         'files': rows, 'extra_target_files': extras, 'distinct_executables': 49,
         'static_archives': 10, 'probe_dylibs': 1, 'method': 'APFS clonefile; 全byte/SHA照合',
         'driver': identity(__file__)})
    print(json.dumps({'status': 'PASS', 'source_files': len(source['files']),
          'primary_members': len(rows), 'extra_members': len(extras)}))


if __name__ == '__main__':
    main()
