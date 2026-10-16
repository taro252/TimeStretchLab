#!/usr/bin/env python3
"""ステージ内容・送信履歴の50,000,000バイト以上のblobを拒否する。"""
import argparse
import json
import subprocess
import sys

LIMIT = 50_000_000


def git(*args, data=None):
    result = subprocess.run(['git', *args], input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError('Git検査に失敗: ' + ' '.join(args[:2]))
    return result.stdout


def blob_sizes(objects):
    ids = sorted(set(objects))
    if not ids:
        return {}
    output = git('cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)',
                 data=('\n'.join(ids) + '\n').encode())
    sizes = {}
    for line in output.decode().splitlines():
        parts = line.split()
        if len(parts) != 3:
            raise RuntimeError('オブジェクトを検査できません: ' + line)
        if parts[1] == 'blob':
            sizes[parts[0]] = int(parts[2])
    return sizes


def staged():
    changed = set(git('diff', '--cached', '--name-only', '--diff-filter=ACMRT', '-z').split(b'\0'))
    objects = {}
    for entry in git('ls-files', '--stage', '-z').split(b'\0'):
        if not entry:
            continue
        info, path = entry.split(b'\t', 1)
        mode, oid, stage = info.decode().split()
        if stage != '0':
            raise RuntimeError('未解決のマージがあるため検査を完了できません。')
        if path in changed and mode != '160000':
            objects.setdefault(oid, []).append(path.decode(errors='surrogateescape'))
    sizes = blob_sizes(objects)
    return [dict(blob=oid, bytes=size, paths=objects[oid])
            for oid, size in sizes.items() if size >= LIMIT]


def history(tips, bases):
    if not tips:
        return []
    revisions = [*tips, *('^' + base for base in bases)]
    output = git('rev-list', '--objects', '--stdin', data=('\n'.join(revisions) + '\n').encode())
    objects = {}
    for line in output.decode(errors='surrogateescape').splitlines():
        oid, _, path = line.partition(' ')
        objects.setdefault(oid, [])
        if path:
            objects[oid].append(path)
    sizes = blob_sizes(objects)
    return [dict(blob=oid, bytes=size, paths=objects[oid])
            for oid, size in sizes.items() if size >= LIMIT]


def is_zero(oid):
    return bool(oid) and set(oid) == {'0'}


def pre_push(remote, lines):
    tips = []
    advertised = set()
    for line in lines:
        parts = line.split()
        if len(parts) != 4:
            raise RuntimeError('pre-pushのref情報が不正です。')
        _, local_oid, _, remote_oid = parts
        if not is_zero(local_oid):
            tips.append(local_oid)
        if not is_zero(remote_oid):
            advertised.add(remote_oid)
    if not tips:  # ref削除だけなら新しいblobを送らない。
        return []
    # ローカルの古いremote追跡refだけを信用しない。新規ブランチでも
    # サーバーが今広告する履歴だけを既存扱いし、履歴途中のblobを調べる。
    for line in git('ls-remote', '--refs', '--', remote).decode().splitlines():
        advertised.add(line.split()[0])
    bases = []
    for oid in sorted(advertised):
        result = subprocess.run(['git', 'cat-file', '-e', oid], capture_output=True)
        if result.returncode == 0:
            bases.append(oid)
    # 未取得の広告refは除外しない。過剰検出の可能性はあるが、検査漏れで
    # Pushを許可しない。必要ならfetch後に再検査する。
    return history(tips, bases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    sub.add_parser('staged')
    h = sub.add_parser('history')
    h.add_argument('--tip', action='append', default=[])
    h.add_argument('--base', action='append', default=[])
    p = sub.add_parser('pre-push')
    p.add_argument('--remote', required=True)
    args = parser.parse_args()
    try:
        if args.mode == 'staged':
            violations = staged()
        elif args.mode == 'history':
            violations = history(args.tip or ['HEAD'], args.base)
        else:
            violations = pre_push(args.remote, sys.stdin.read().splitlines())
    except (RuntimeError, ValueError, OSError) as error:
        print('容量検査を完了できないため中止: ' + str(error), file=sys.stderr)
        return 2
    if violations:
        print('50,000,000バイト以上のblobを検出。コミット・Pushを中止してください。', file=sys.stderr)
        print(json.dumps(violations, indent=2, ensure_ascii=True), file=sys.stderr)
        return 1
    print('Git blob容量検査: 合格（新規対象は50,000,000バイト未満）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
