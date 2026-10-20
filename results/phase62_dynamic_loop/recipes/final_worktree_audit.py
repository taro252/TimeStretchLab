"""試験終了後の未commit差分と容量を記録する。Gitのindex/履歴は変更しない。"""
import hashlib
import argparse
import json
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity, source_manifest

OUT = ROOT / 'results/phase62_dynamic_loop'
BASE = ROOT / 'build/phase62_dynamic_20261020'
EXPECTED_HEAD = '7c05319d8142ef53a70c95be4f214f293bb2428a'
LIMIT = 50_000_000
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--commit-authorized', action='store_true',
                    help='後続のコミット許可を記録する。監査自体はindex/履歴を変更しない。')
args = parser.parse_args()


def run(command, data=None):
    p = subprocess.run(command, input=data, capture_output=True)
    return p.returncode, p.stdout, p.stderr


def git(*args):
    code, out, err = run(['git', *args])
    if code:
        raise RuntimeError(err.decode())
    return out


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


head = git('rev-parse', 'HEAD').decode().strip()
branch = git('branch', '--show-current').decode().strip()
assert head == EXPECTED_HEAD and branch == 'main'
assert not git('diff', '--cached', '--name-only')
manifest = json.loads((OUT / 'MANIFEST.json').read_text())
source = source_manifest(ROOT)
assert source['sha256'] == manifest['final_source_inventory_sha256']
assert manifest['status'] == 'INCOMPLETE' and not manifest['local_overall_go']
assert len(manifest['suites']) == 17
assert all(row['status'] == 'PASS' for row in manifest['suites'])

archive = json.loads((OUT / 'FINAL_SOURCE_ARCHIVE.json').read_text())
assert archive['source'] == source['sha256']
assert identity(archive['archive']['path']) == archive['archive']
expected = {row['path']: row['sha256'] for row in source['files']}
actual = {}
with tarfile.open(archive['archive']['path']) as stream:
    for member in stream.getmembers():
        if member.isfile():
            name = member.name.removeprefix('./')
            assert name in expected
            actual[name] = hashlib.sha256(stream.extractfile(member).read()).hexdigest()
assert expected == actual
for ref in manifest['references']:
    assert identity(ref['binary']['path']) == ref['binary']

patch = BASE / 'FINAL_TRACKED.patch'
patch.write_bytes(git('diff', '--binary', '--full-index'))
paths = sorted(set(filter(None, (
    git('diff', '--name-only', '-z') +
    git('ls-files', '--others', '--exclude-standard', '-z')
).decode().split('\0'))))
excluded = ['results/phase62_dynamic_loop/CHANGESET.json',
            'results/phase62_dynamic_loop/FINAL_WORKTREE_CHECKS.json']
files = []
for name in paths:
    if name in excluded:
        continue
    path = ROOT / name
    assert path.is_file(), '削除/型変更は本監査で想定しない: ' + name
    row = identity(path)
    row['path'] = name
    files.append(row)
digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
write(OUT / 'CHANGESET.json', dict(
    schema=1, base_commit=EXPECTED_HEAD, head=head, branch=branch,
    final_source_inventory_sha256=source['sha256'],
    file_inventory_sha256=digest, files=files, tracked_diff=identity(patch),
    excluded_generated_records=excluded,
    exclusion_reason='自己参照となるhashと、その後に生成する監査結果だけを除外。製品ソース/文書/recipe/manifestは上記一覧で識別。',
    capture_phase='コミット許可後・ステージ前' if args.commit_authorized else '検証完了時・ステージ前',
    subsequent_commit_authorized=args.commit_authorized,
    git_actions='no stage/commit/push/PR/history rewrite at capture; subsequent commit authorized, push not authorized'
                if args.commit_authorized else 'no stage/commit/push/PR/history rewrite'))

checks = []
for label, command in [
    ('diff_whitespace', ['git', 'diff', '--check']),
    ('empty_staged_blob_check', ['python3', 'scripts/check_git_blob_sizes.py', 'staged']),
]:
    code, out, err = run(command)
    log = BASE / ('final_' + label + '.log')
    log.write_bytes(out + err)
    checks.append(dict(id=label, command=command, exit=code,
                       status='PASS' if code == 0 else 'FAIL', log=identity(log)))
    assert code == 0

artifacts = json.loads((OUT / 'ARTIFACTS.json').read_text())['artifacts']
media = [row['path'] for row in artifacts]
code, ignored, err = run(['git', 'check-ignore', '-z', '--stdin'],
                         ('\0'.join(media) + '\0').encode())
assert code == 0 and sorted(ignored.decode().split('\0')[:-1]) == sorted(media), err
checks.append(dict(id='media_ignored', status='PASS', expected=len(media),
                   executed=len(media), index='ARTIFACTS.json'))

for name, pattern in [
    ('src/platform/macos/ProgressiveMacPlaybackEngine.h', 'allowExperimentalLoops=false'),
    ('src/playback/ProgressiveLoopContract.h', 'publicLoopApproved=false'),
    ('src/playback/ProgressiveLoopContract.h', 'currentCycleSpeedChanges=false'),
    ('src/playback/ProgressiveContract.h', 'seek=false'),
]:
    assert pattern in (ROOT / name).read_text()
checks.append(dict(id='public_flags_unchanged', status='PASS'))

# 生成したCHANGESETも含め、Gitへ追加可能な変更ファイルの生サイズを調べる。
paths = sorted(set(filter(None, (
    git('diff', '--name-only', '-z') +
    git('ls-files', '--others', '--exclude-standard', '-z')
).decode().split('\0'))))
sizes = [dict(path=name, bytes=(ROOT / name).stat().st_size)
         for name in paths if name != excluded[1]]
violations = [row for row in sizes if row['bytes'] >= LIMIT]
assert not violations
existing = json.loads((OUT / 'EXISTING_HISTORY_BLOBS.json').read_text())
assert existing['count'] == len(existing['blobs']) == 4
status = git('status', '--short').decode()
status_file = BASE / 'final_git_status.log'
status_file.write_text(status)
write(OUT / 'FINAL_WORKTREE_CHECKS.json', dict(
    status='PASS', head=head, branch=branch,
    source_inventory_sha256=source['sha256'], checks=checks,
    source_archive_files_verified=len(actual),
    working_file_size=dict(threshold_bytes=LIMIT, comparison='bytes < 50000000',
                          inspected=len(sizes), max=max(sizes, key=lambda row: row['bytes']),
                          violations=violations, files=sizes),
    existing_history=dict(status='EXISTING_VIOLATIONS', count=4,
                          record='EXISTING_HISTORY_BLOBS.json', new_work=False),
    git_status=identity(status_file), index_empty=True,
    commit_push='not performed at capture; subsequent commit authorized, no push'
                if args.commit_authorized else 'not performed', changeset='CHANGESET.json',
    self_exclusion='本監査ファイル自身はhash/サイズ一覧から除外。保存後に50,000,000バイト未満を検査。'))
assert (OUT / 'FINAL_WORKTREE_CHECKS.json').stat().st_size < LIMIT
assert not git('diff', '--cached', '--name-only')
assert git('rev-parse', 'HEAD').decode().strip() == head
print(json.dumps(dict(status='PASS', source=source['sha256'],
    suites=len(manifest['suites']), source_archive_files=len(actual),
    ignored_artifacts=len(media), working_files=len(sizes),
    max_bytes=max(row['bytes'] for row in sizes), existing_history_oversize=4,
    local_overall_go=False)))
