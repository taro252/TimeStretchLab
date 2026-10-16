"""完了済みFix Debugビルドを全ファイルSHA照合後に無損失保存する。"""
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from phase57_study import ROOT, sha
from phase59_fix_archive_trace import require_closed


def main():
    checks = ROOT/'results/phase59_fix/checks_final/summary.json'
    assert json.loads(checks.read_text())['PASS']
    source = ROOT/'build/phase59_fix_debug'
    assert source.is_dir() and not source.is_symlink()
    data = ROOT/'build/phase59_fix_artifacts'
    destination = data/'debug_build_final.tar.gz'
    report = ROOT/'results/phase59_fix/DEBUG_BUILD_ARCHIVE.json'
    assert not destination.exists() and not report.exists()
    require_closed(source)
    # EOS比較に必要な実行体を同一バイトのまま独立保存する。
    probe = data/'debug_eos_final'
    assert not probe.exists()
    shutil.copy2(source/'phase59_fix_eos_probe', probe)
    assert sha(probe) == sha(source/'phase59_fix_eos_probe')
    dependencies = subprocess.check_output(['otool', '-L', str(probe)], text=True)
    for line in dependencies.splitlines()[1:]:
        assert line.strip().startswith(('/System/', '/usr/lib/')), line
    ledger = []
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            ledger.append(dict(path=str(path.relative_to(source)), symlink=str(path.readlink())))
        elif path.is_file():
            ledger.append(dict(path=str(path.relative_to(source)), bytes=path.stat().st_size, sha256=sha(path)))
    before = shutil.disk_usage(ROOT).free
    with tarfile.open(destination, 'x:gz', compresslevel=4) as archive:
        archive.add(source, arcname=source.name)
    with tarfile.open(destination, 'r:gz') as archive:
        for row in ledger:
            member = archive.getmember(source.name+'/'+row['path'])
            if 'symlink' in row:
                assert member.issym() and member.linkname == row['symlink']
            else:
                digest = hashlib.sha256(); count = 0
                with archive.extractfile(member) as file:
                    for block in iter(lambda: file.read(1<<20), b''):
                        digest.update(block); count += len(block)
                assert digest.hexdigest() == row['sha256'] and count == row['bytes']
    for row in ledger:
        path = source/row['path']
        assert (str(path.readlink()) == row['symlink']) if 'symlink' in row else sha(path) == row['sha256']
    require_closed(source)
    record = dict(source=str(source), archive=str(destination), archive_sha256=sha(destination),
                  archive_bytes=destination.stat().st_size, files=ledger, restored_payloads_verified=True,
                  checks_sha256=sha(checks), script_sha256=sha(Path(__file__)),
                  eos_probe=dict(path=str(probe), sha256=sha(probe), dependencies=dependencies),
                  uncompressed_source_released=False, free_before_bytes=before,
                  restore_command=['tar', '-xzf', str(destination), '-C', str(source.parent)],
                  restore='元の場所へ展開後filesの全SHAを照合。既存ディレクトリは上書きしない。')
    report.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    shutil.rmtree(source)
    record.update(uncompressed_source_released=True, free_after_bytes=shutil.disk_usage(ROOT).free)
    report.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    print('Debug archive verified', record['archive_bytes'], 'free', record['free_after_bytes'], flush=True)


if __name__ == '__main__':
    main()
