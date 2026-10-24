#!/usr/bin/env python3
"""停止済みの指定CMake生成物だけを透過圧縮する。作成/AST確認だけでは実行しない。

 --roots B/candidate/CMakeFiles B/debug_candidate/CMakeFiles B/baseline/CMakeFiles
 --quiescence B/quiescence_01.json --output B/compress_objects_01.json
指定rootsは上記3つの部分集合のみ。rootと出力は絶対pathまたはrepo相対path。
対象は>=64KiBの *.o, *.o.d, compiler_depend.make, compiler_depend.internal,
Makefile2。通常file、非symlink、nlink1以外は変更しない。

停止記録schema=build-object-compression-quiescence-v1、created_utc=aware ISO8601、
roots=指定順の絶対path配列、build_finished/audio_idle/all_children_stopped/
exclusive_maintenance=true。ps={command:['/bin/ps','-axo',PS_FIELDS],returncode:0,
stdout:文字列,stderr:''}、PS_FIELDS='pid=,ppid=,stat=,command='。
lsof=[{root:R,command:['/usr/sbin/lsof','-nP','-Fpcfatn','+D',R],returncode:1,
stdout:'',stderr:''},...]。使用中fileがない空結果だけ受理する。
開始時300秒以内。現在のps/lsofも別途検査。build/音声/新規child起動は禁止。
これは新規起動をOSで排他する機構ではなく、親の排他保守宣言も必須。

各file前に元サイズ+8MiBの空きが必要。decoded全byte/size/SHA、mode/mtimeを
確認し、実領域減少時だけDarwin RENAME_SWAPで交換。後検証まで元inodeをtempへ
保持し、失敗時は交換を戻す。原本/既存証拠削除や公開設定変更は行わない。
"""
import argparse
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[3]
BASE = (ROOT / 'build/performance_response_20261023_01').resolve()
ALLOWED_ROOTS = {BASE / n / 'CMakeFiles' for n in ('candidate', 'debug_candidate', 'baseline')}
PS_COMMAND = ['/bin/ps', '-axo', 'pid=,ppid=,stat=,command=']
MIN_BYTES = 65536
MARGIN = 8 * 1024 * 1024
EVIDENCE_SHA = '69c706137ff0b8a20bac5725aa797230aa1e7846d8852e2e0ee7bb0e37a86082'
BUILD_TOOLS = {'cmake', 'make', 'gmake', 'ninja', 'clang', 'clang++', 'cc', 'c++',
               'ld', 'ld64', 'ar', 'ranlib', 'dsymutil', 'xcodebuild', 'xcrun', 'ditto'}


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def safe_path(path):
    need(path.is_absolute() and path.is_relative_to(BASE), 'Path outside fixed B: ' + str(path))
    need('\n' not in str(path) and '\r' not in str(path), 'Newline in path')
    current = path
    while current != BASE:
        need(not current.is_symlink(), 'Symlink forbidden: ' + str(current))
        current = current.parent


def open_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd);raise RuntimeError('Regular file required: ' + str(path))
    return os.fdopen(fd, 'rb')


def sha(path):
    with open_read(path) as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path):
    return {'path': str(path), 'bytes': path.lstat().st_size, 'sha256': sha(path)}


def meta(s):
    return {'device': s.st_dev, 'inode': s.st_ino, 'nlink': s.st_nlink, 'bytes': s.st_size,
            'mode': stat.S_IMODE(s.st_mode), 'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns,
            'flags': s.st_flags, 'allocated_bytes': s.st_blocks * 512}


def original_inode(path, s):
    if not os.path.lexists(path):return False
    x = path.lstat()
    return stat.S_ISREG(x.st_mode) and (x.st_dev, x.st_ino) == (s.st_dev, s.st_ino)


def original_unchanged(path, s):
    return original_inode(path, s) and meta(path.lstat()) == meta(s)


def command(argv, timeout=60):
    try:
        run = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return {'command': argv, 'returncode': run.returncode, 'stdout': run.stdout,
                'stderr': run.stderr, 'timeout': False}
    except subprocess.TimeoutExpired as error:
        def text(value):return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
        return {'command': argv, 'returncode': None, 'stdout': text(error.stdout),
                'stderr': text(error.stderr), 'timeout': True}


def check_ps(result):
    need(result.get('command') == PS_COMMAND and result.get('returncode') == 0
         and not result.get('timeout', False) and result.get('stderr') == ''
         and isinstance(result.get('stdout'), str) and result['stdout'].strip(), 'Incomplete ps record')
    blocked = []
    for line in result['stdout'].splitlines():
        fields = line.strip().split(None, 3)
        need(len(fields) == 4 and fields[0].isdigit() and fields[1].isdigit(), 'Invalid ps row')
        pid, _, state, cmd = fields
        if int(pid) == os.getpid() or state.startswith('Z'):continue
        argv = cmd.split();need(bool(argv), 'Empty ps command')
        executable = Path(argv[0])
        native = executable.is_absolute() and executable.is_relative_to(BASE)
        recipe = any(Path(a).name.startswith(('run_', 'build_')) and a.endswith('.py')
                     and (str(ROOT) in a or '/performance_response/' in a) for a in argv[1:])
        if executable.name in BUILD_TOOLS or native or recipe:
            blocked.append({'pid': int(pid), 'state': state, 'command': cmd})
    need(not blocked, 'Build/audio/helper still running: ' + json.dumps(blocked))


def lsof_command(root):
    return ['/usr/sbin/lsof', '-nP', '-Fpcfatn', '+D', str(root)]


def check_unused(result):
    need(result.get('returncode') in (0, 1) and not result.get('timeout', False)
         and result.get('stderr') == '' and isinstance(result.get('stdout'), str),
         'lsof unavailable, timed out, or warned')
    need(not result['stdout'].strip(), 'lsof found open descriptor/mapping/cwd; refuse replacement')


def root_lsof(root):
    result = command(lsof_command(root), 90);result['root'] = str(root)
    check_unused(result);return result


def file_lsof(paths):
    result = command(['/usr/sbin/lsof', '-nP', '-Fpcfatn', '--', *map(str, paths)], 60)
    check_unused(result);return result


def compare_decoded(first, second, size, expected_sha):
    left_hash, right_hash = hashlib.sha256(), hashlib.sha256();count = 0
    with open_read(first) as left, open_read(second) as right:
        while True:
            a, b = left.read(1024 * 1024), right.read(1024 * 1024)
            need(a == b, 'Decoded byte comparison failed')
            left_hash.update(a);right_hash.update(b);count += len(a)
            if not a:break
    need(count == size and left_hash.hexdigest() == right_hash.hexdigest() == expected_sha,
         'Decoded size/SHA mismatch')
    return {'compared_bytes': count, 'sha256': expected_sha, 'all_decoded_bytes_equal': True}


def swap(first, second):
    # macOS SDK sys/stdio.h: renamex_np(..., RENAME_SWAP=0x00000002).
    libc = ctypes.CDLL(None, use_errno=True);function = libc.renamex_np
    function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    function.restype = ctypes.c_int
    result = function(os.fsencode(first), os.fsencode(second), 0x00000002)
    if result:
        error = ctypes.get_errno();raise OSError(error, os.strerror(error))


def eligible_name(name):
    return name.endswith(('.o', '.o.d')) or name in {
        'compiler_depend.make', 'compiler_depend.internal', 'Makefile2'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--roots', type=Path, nargs='+', required=True)
    parser.add_argument('--quiescence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = Path(os.path.abspath(args.output));safe_path(out)
    need(out.parent.is_dir() and not os.path.lexists(out), 'Fresh output JSON required')
    need(not any(out.is_relative_to(r) for r in ALLOWED_ROOTS), 'Output must be outside CMakeFiles')
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600);os.close(fd)
    record = {'schema': 'build-object-compression-v1', 'status': 'INCOMPLETE', 'complete': False,
              'driver': identity(Path(__file__)), 'roots': [], 'rows': [], 'skipped': [],
              'minimum_bytes': MIN_BYTES, 'temporary_free_margin_bytes': MARGIN,
              'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    def save():
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=out.parent,
                                             prefix='.' + out.name + '.', delete=False) as stream:
                temp = Path(stream.name);json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temp, out)
        finally:
            if temp is not None and temp.exists():temp.unlink()
    previous = {}
    try:
        save();need(platform.system() == 'Darwin' and hasattr(stat, 'UF_COMPRESSED'), 'macOS required')
        frozen = Path(__file__).with_name('compress_evidence.py')
        need(sha(frozen) == EVIDENCE_SHA, 'Frozen evidence helper changed')
        record['untouched_evidence_helper'] = identity(frozen)
        roots = []
        for value in args.roots:
            root = Path(os.path.abspath(value));safe_path(root)
            need(root in ALLOWED_ROOTS and root.is_dir() and root not in roots, 'Only three fixed nonduplicate CMakeFiles roots allowed')
            roots.append(root)
        record['roots'] = list(map(str, roots));record['free_before_bytes'] = shutil.disk_usage(BASE).free
        qpath = Path(os.path.abspath(args.quiescence));safe_path(qpath)
        need(qpath.is_file() and qpath.stat().st_size <= 8 * 1024 * 1024, 'Small fresh quiescence JSON required')
        qid = identity(qpath);q = json.loads(qpath.read_text())
        need(q.get('schema') == 'build-object-compression-quiescence-v1' and q.get('roots') == record['roots'],
             'Quiescence schema/exact ordered roots mismatch')
        need(all(q.get(k) is True for k in ('build_finished', 'audio_idle', 'all_children_stopped', 'exclusive_maintenance')),
             'Build/audio/children stopped and exclusive maintenance declaration required')
        created = datetime.datetime.fromisoformat(q['created_utc'].replace('Z', '+00:00'))
        need(created.tzinfo is not None, 'Aware quiescence timestamp required')
        age = (datetime.datetime.now(datetime.timezone.utc) - created).total_seconds()
        need(0 <= age <= 300, 'Quiescence older than 300 seconds or in future')
        check_ps(q['ps']);need(len(q.get('lsof', [])) == len(roots), 'Quiescence lsof for every root required')
        for root, snapshot in zip(roots, q['lsof']):
            need(snapshot.get('root') == str(root) and snapshot.get('command') == lsof_command(root), 'Exact lsof root command required')
            check_unused(snapshot)
        record['quiescence'] = {'identity': qid, 'record': q, 'age_seconds': age}
        record['ps_before'] = command(PS_COMMAND);check_ps(record['ps_before'])
        record['lsof_before'] = [root_lsof(r) for r in roots];save()
        def interrupted(signum, frame):raise KeyboardInterrupt('Signal ' + str(signum))
        for signum in (signal.SIGINT, signal.SIGTERM):previous[signum] = signal.signal(signum, interrupted)
        files = []
        for root in roots:
            for directory, dirs, names in os.walk(root, followlinks=False):
                for name in list(dirs):
                    path = Path(directory) / name
                    if path.is_symlink():
                        record['skipped'].append({'path': str(path), 'reason': 'symlink_directory'});dirs.remove(name)
                for name in names:
                    if not eligible_name(name):continue
                    path = Path(directory) / name;s = path.lstat()
                    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size < MIN_BYTES:
                        record['skipped'].append({'path': str(path), 'metadata': meta(s), 'reason': 'not_regular_nlink1_64KiB'})
                    else:safe_path(path);files.append((s.st_size, str(path)))
        record['eligible_files'] = len(files);save()
        for _, name in sorted(files):
            path = Path(name);safe_path(path);s = path.lstat()
            row = {'path': name, 'before': meta(s), 'status': 'INCOMPLETE'};record['rows'].append(row);save()
            need(stat.S_ISREG(s.st_mode) and s.st_nlink == 1 and s.st_size >= MIN_BYTES, 'Eligibility changed')
            need(identity(qpath) == qid, 'Quiescence record changed')
            ps = command(PS_COMMAND);check_ps(ps)
            row['ps_guard'] = {'status': 'PASS', 'stdout_sha256': hashlib.sha256(ps['stdout'].encode()).hexdigest()}
            row['lsof_before'] = file_lsof([path])
            free = shutil.disk_usage(path.parent).free;row['free_before_bytes'] = free
            row['required_temporary_free_bytes'] = s.st_size + MARGIN
            need(free >= row['required_temporary_free_bytes'], 'BLOCKED: original-size+8MiB temporary free guard')
            before = sha(path);row['sha256_before'] = before
            need(original_unchanged(path, s), 'Original changed during initial SHA')
            temp = path.with_name('.' + path.name + '.compress-' + uuid.uuid4().hex)
            row['temporary_path'] = str(temp);keep_temp = False
            try:
                need(not os.path.lexists(temp), 'Temporary path exists')
                row['ditto'] = command(['/usr/bin/ditto', '--hfsCompression', '--noclone', '--noqtn', str(path), str(temp)], 120)
                need(row['ditto']['returncode'] == 0 and row['ditto']['stderr'] == '' and not row['ditto']['timeout'], 'ditto failed/warned')
                t = temp.lstat();need(stat.S_ISREG(t.st_mode) and t.st_nlink == 1, 'Unsafe temporary type/links')
                repaired = False
                if (t.st_size == 0 and s.st_size > 0 and not (t.st_flags & stat.UF_COMPRESSED)
                        and 'com.apple.decmpfs' in os.listxattr(temp)):
                    os.chflags(temp, t.st_flags | stat.UF_COMPRESSED);repaired = True
                row['temporary_compressed_flag_repaired'] = repaired
                row['decoded_comparison'] = compare_decoded(path, temp, s.st_size, before)
                os.chmod(temp, stat.S_IMODE(s.st_mode));os.utime(temp, ns=(s.st_atime_ns, s.st_mtime_ns))
                t = temp.lstat();row['temporary_verified'] = meta(t)
                need(t.st_size == s.st_size and t.st_mtime_ns == s.st_mtime_ns
                     and stat.S_IMODE(t.st_mode) == stat.S_IMODE(s.st_mode), 'Temporary metadata mismatch')
                need(original_unchanged(path, s) and sha(path) == before, 'Original changed before swap')
                row['lsof_before_swap'] = file_lsof([path, temp])
                if t.st_blocks >= s.st_blocks:
                    temp.unlink();row['status'] = 'UNCHANGED_NO_REDUCTION'
                else:
                    swap(temp, path)
                    need(original_inode(temp, s), 'Original inode not retained at temporary path')
                    a = path.lstat()
                    need(stat.S_ISREG(a.st_mode) and a.st_nlink == 1 and a.st_size == s.st_size
                         and a.st_mtime_ns == s.st_mtime_ns and stat.S_IMODE(a.st_mode) == stat.S_IMODE(s.st_mode)
                         and a.st_blocks < s.st_blocks, 'Post-swap metadata/allocation mismatch')
                    row['post_swap_comparison'] = compare_decoded(temp, path, s.st_size, before)
                    row['lsof_after_swap'] = file_lsof([path, temp])
                    row['after'] = meta(path.lstat());row['sha256_after'] = sha(path)
                    need(row['sha256_after'] == before, 'Post-swap SHA mismatch')
                    row['status'] = 'VERIFIED_SWAP_OLD_INODE_RETAINED';save()
                    temp.unlink();row['status'] = 'COMPRESSED'
                row['after'] = meta(path.lstat());row['sha256_after'] = sha(path)
                need(row['sha256_after'] == before and row['after']['bytes'] == s.st_size
                     and row['after']['mode'] == stat.S_IMODE(s.st_mode) and row['after']['mtime_ns'] == s.st_mtime_ns,
                     'Final decoded content/mode/mtime mismatch')
            except BaseException:
                if original_inode(temp, s):
                    try:
                        swap(temp, path)
                        need(original_inode(path, s) and sha(path) == before, 'Rollback content/inode verification failed')
                        row['rollback'] = 'ORIGINAL_RESTORED'
                    except BaseException as rollback:
                        keep_temp = True;row['rollback'] = 'FAILED_RETAIN_BOTH_PATHS: ' + repr(rollback);raise
                elif not original_inode(path, s) and row['status'] != 'COMPRESSED':
                    keep_temp = True;row['rollback'] = 'AMBIGUOUS_RETAIN_BOTH_PATHS'
                else:row['original_or_verified_commit_preserved'] = True
                raise
            finally:
                if not keep_temp and os.path.lexists(temp):temp.unlink()
            row['free_after_bytes'] = shutil.disk_usage(path.parent).free;save()
        record['ps_after'] = command(PS_COMMAND);check_ps(record['ps_after'])
        record['lsof_after'] = [root_lsof(r) for r in roots]
        need(identity(qpath) == qid and sha(frozen) == EVIDENCE_SHA, 'Frozen input/helper changed')
        record.update(status='PASS', complete=True)
    except BaseException as error:
        record.update(status='INCOMPLETE', complete=False, error=type(error).__name__ + ': ' + str(error))
        if record['rows'] and record['rows'][-1]['status'] not in ('COMPRESSED', 'UNCHANGED_NO_REDUCTION'):
            record['rows'][-1]['status'] = 'INCOMPLETE'
    finally:
        for signum, handler in previous.items():signal.signal(signum, handler)
        record['free_after_bytes'] = shutil.disk_usage(BASE).free
        record['compressed_files'] = sum(r['status'] == 'COMPRESSED' for r in record['rows'])
        record['saved_allocated_bytes'] = sum(r['before']['allocated_bytes'] - r['after']['allocated_bytes']
                                             for r in record['rows'] if r['status'] == 'COMPRESSED')
        record['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat();save()
    print(json.dumps({k: record[k] for k in ('status', 'complete', 'compressed_files', 'saved_allocated_bytes')}))
    return 0 if record['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
