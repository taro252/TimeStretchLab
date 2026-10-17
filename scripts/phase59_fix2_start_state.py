"""既存証拠を読取り専用で検証し、Fix 2の開始状態を保存する。"""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase59_fix2'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    OUT.mkdir(exist_ok=True)
    data = ROOT / 'build/phase59_fix2_artifacts'
    data.mkdir(exist_ok=True)
    names = {
        'phase59': ['REPORT.md', 'VERDICT.json', 'DEVICE_FAILURE_TIMELINES.json', 'DEVICE_REGRESSION_FAILURES.json'],
        'phase59_fix': ['REPORT.md', 'VERDICT.json', 'FINAL_NATIVE_FAILURES.json', 'FINAL_LEGACY_FAILURES.json',
                        'POST_TRACE_CLOCK_VM.json', 'CLOCK_REPRODUCTION.json', 'LEGACY_FAILURE_REVIEW.json',
                        'EOS_TRACE_OBSERVATIONS.json', 'PHASE_BEFORE_ANALYSIS.json', 'PHASE_AFTER_ANALYSIS.json',
                        'FINAL_CANDIDATE.json', 'FROZEN_REFERENCES.json', 'ARTIFACT_INDEX.json'],
    }
    evidence = [ROOT / 'results' / phase / name for phase, files in names.items() for name in files]
    evidence += [ROOT / 'docs' / name for name in ['PHASE59_FIX_ROOT_CAUSE.md', 'PHASE59_FIX_REALTIME.md', 'PHASE58_FIX_SCHEDULING.md']]
    frozen = json.loads((ROOT / 'results/phase59_fix/FINAL_CANDIDATE.json').read_text())
    binaries = []
    for name, expected in frozen['binary_sha256'].items():
        path = Path(frozen['frozen_directory']) / name
        digest = sha(path)
        assert digest == expected, str(path)
        binaries.append(dict(path=str(path), bytes=path.stat().st_size, sha256=digest))
    # 全原本を再走査する。結果はGit管理外に置き、開始manifestからSHAで参照する。
    protected = []
    for folder in ['results/phase59', 'results/phase59_fix', 'tests/golden']:
        for path in sorted((ROOT / folder).rglob('*')):
            if path.is_file():
                protected.append(dict(path=str(path), bytes=path.stat().st_size, sha256=sha(path)))
    protected_path = data / 'protected_files.json'
    with protected_path.open('x') as file:
        json.dump(protected, file, ensure_ascii=False, indent=2)
        file.write('\n')
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    state = dict(head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                 branch=subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
                 initial_status=status, free_bytes=shutil.disk_usage(ROOT).free,
                 host={name: subprocess.check_output(command, text=True).strip() for name, command in
                       [('macos', ['sw_vers']), ('machine', ['uname', '-m']), ('xcode', ['xcodebuild', '-version'])]},
                 evidence=[dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p)) for p in evidence],
                 binaries=binaries, protected_manifest=str(protected_path), protected_manifest_sha256=sha(protected_path),
                 protected_files=len(protected), push_assumed=False,
                 specification_correction='途中再生の余分なsample進行は原本989-471=518フレーム。依頼書の6とは異なる。',
                 restore='既存原本は変更せず元の絶対パスに保持。SHAを照合し、固定実行体・Goldenは置換しない。')
    with (OUT / 'START_STATE.json').open('x') as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        file.write('\n')
    print('開始状態保存:', len(binaries), '実行体、', len(protected), '保護ファイル、空き', state['free_bytes'])


if __name__ == '__main__':
    main()
