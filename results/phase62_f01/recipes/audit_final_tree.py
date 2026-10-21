"""未ステージの最終差分を識別する。stage/commitや既存証拠の削除は行わない。"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from phase62_evidence import identity, source_manifest


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    out = ROOT / 'results/phase62_f01/ARTIFACTS.json'
    assert not out.exists(), '確定索引を上書きしない'
    manifest = json.loads((ROOT / 'results/phase62_f01/MANIFEST.json').read_text())
    source = source_manifest(ROOT)
    assert source['sha256'] == manifest['source_inventory_sha256']
    assert git('rev-parse', 'HEAD').decode().strip() == manifest['final_head']
    assert git('diff', '--cached', '--name-only') == b'', '既存stageを変更しない'
    subprocess.run(['git', 'diff', '--check'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, 'scripts/check_git_blob_sizes.py', 'staged'], cwd=ROOT, check=True)
    tracked = git('diff', '--name-only', '-z', 'HEAD').decode().split('\0')
    untracked = git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
    names = sorted(set(filter(None, tracked + untracked)))
    rows = []
    for name in names:
        path = ROOT / name
        assert path.is_file() and path.stat().st_size < 50_000_000, name
        if name in untracked and path.suffix in {'.md', '.py', '.json', '.txt'}:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                assert line.rstrip() == line, f'未追跡ファイル末尾空白: {name}:{number}'
        rows.append(dict(path=name, **{k:v for k,v in identity(path).items() if k != 'path'}))
    result = dict(status='PASS', source_inventory_sha256=source['sha256'], head=manifest['final_head'],
                  branch=git('branch', '--show-current').decode().strip(), staged_files=[],
                  tracked_diff_sha256=hashlib.sha256(git('diff', '--binary', 'HEAD')).hexdigest(),
                  changed_files=names, files=rows, max_file_bytes=max(r['bytes'] for r in rows),
                  new_blob_limit_bytes=50_000_000, index_excludes_itself=True,
                  committed=False, pushed=False, old_evidence_deleted=False)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(status='PASS', files=len(rows), max_file_bytes=result['max_file_bytes'], source=source['sha256'])))


if __name__ == '__main__':
    raise SystemExit(main())
