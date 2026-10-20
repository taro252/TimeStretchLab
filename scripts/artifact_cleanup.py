#!/usr/bin/env python3
"""TimeStretchLab成果物の読み取り専用監査と、検証を伴う可逆保管。"""
import argparse
import base64
import collections
import contextlib
import csv
import ctypes
import datetime as dt
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import uuid
import zlib

GIB = 1024 ** 3
MIB = 1024 ** 2
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'TimeStretchLab-artifact-archive-v1'
DATA_EXT = {'.wav', '.pcm', '.f32', '.raw', '.csv', '.xml', '.ktrace', '.trace', '.log'}
META_EXT = {'.md', '.json', '.jsonl', '.csv', '.py', '.txt', '.cmake'}
PERMANENT_EXT = {'.md', '.json', '.jsonl', '.py', '.sh', '.sha256'}
PROTECTED_WORDS = re.compile(r'golden|baseline|reference|oracle|frozen|正本|基準', re.I)
INPUT_WORDS = re.compile(r'(^|[/_\W])(input|inputs|source|original)([/_\W]|$)', re.I)
HOLD_WORDS = re.compile(r'NO[-_ ]GO|未解決|未特定|再解析必要|原因不明|判定未完|INDETERMINATE', re.I)
SHA = re.compile(r'^[0-9a-f]{64}$')


class SafetyError(RuntimeError):
    pass


def xattrs(fd):
    """macOSの拡張属性も標準ライブラリctypesで保存する（os版はLinux限定）。"""
    if hasattr(os, 'listxattr'):
        return {n: base64.b64encode(os.getxattr(fd, n)).decode('ascii') for n in os.listxattr(fd)}
    if sys.platform != 'darwin':
        raise SafetyError('拡張属性の保存を保証できないOSです')
    libc = ctypes.CDLL(None, use_errno=True)
    listing = libc.flistxattr
    listing.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
    listing.restype = ctypes.c_ssize_t
    getting = libc.fgetxattr
    getting.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    getting.restype = ctypes.c_ssize_t
    size = listing(fd, None, 0, 0)
    if size < 0:
        raise OSError(ctypes.get_errno(), '拡張属性の一覧取得失敗')
    buffer = ctypes.create_string_buffer(size)
    if listing(fd, buffer, size, 0) != size:
        raise SafetyError('拡張属性一覧の取得中に変更')
    result = {}
    for name in buffer.raw.split(b'\0'):
        if not name:
            continue
        length = getting(fd, name, None, 0, 0, 0)
        if length < 0 or length > MIB:
            raise SafetyError('拡張属性の読取り不能/サイズ超過')
        value = ctypes.create_string_buffer(length)
        if getting(fd, name, value, length, 0, 0) != length:
            raise SafetyError('拡張属性の取得中に変更')
        result[os.fsdecode(name)] = base64.b64encode(value.raw).decode('ascii')
    return result


def set_xattr(fd, name, value):
    if hasattr(os, 'setxattr'):
        os.setxattr(fd, name, value)
        return
    if sys.platform != 'darwin':
        raise SafetyError('拡張属性を復元できないOSです')
    libc = ctypes.CDLL(None, use_errno=True)
    setting = libc.fsetxattr
    setting.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    setting.restype = ctypes.c_int
    if setting(fd, os.fsencode(name), value, len(value), 0, 0) != 0:
        raise OSError(ctypes.get_errno(), '拡張属性の復元失敗')


def git(root, *args, data=None):
    p = subprocess.run(['git', '-C', str(root), *args], input=data, capture_output=True)
    if p.returncode:
        raise SafetyError('Git検査不能: ' + ' '.join(args[:2]))
    return p.stdout


def relative(value):
    """OSによる正規化前に脱出・曖昧なパスを拒否する。"""
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise SafetyError('不正な相対パス')
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ('', '.', '..', '.git') for x in value.split('/')):
        raise SafetyError('対象範囲外のパス: ' + repr(value))
    return value


def target_relative(value):
    value = relative(value)
    if value.split('/')[0] not in ('results', 'build') or len(value.split('/')) < 2:
        raise SafetyError('results/build以外の対象: ' + value)
    return value


def phase_of(name):
    parts = PurePosixPath(name).parts
    if len(parts) > 1 and re.fullmatch(r'phase\d+[a-z]?(?:_[A-Za-z0-9]+)*', parts[1]):
        return re.sub(r'_(artifacts|frozen)$', '', parts[1])
    return '(Phase不明)'


def signature(s):
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode, s.st_nlink]


@contextlib.contextmanager
def parent_fd(root, name, create=False):
    parts = relative(name).split('/')
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, parts[-1]
    finally:
        os.close(fd)


@contextlib.contextmanager
def safe_file(root, name):
    with parent_fd(root, name) as (fd, leaf):
        handle = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        if not stat.S_ISREG(os.fstat(handle).st_mode):
            raise SafetyError('通常ファイルではありません: ' + name)
        with os.fdopen(handle, 'rb', closefd=False) as stream:
            yield stream
    finally:
        os.close(handle)


def hash_stream(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(MIB), b''):
        h.update(block)
    return h.hexdigest()


def file_hash(root, name):
    with safe_file(root, name) as stream:
        before = signature(os.fstat(stream.fileno()))
        digest = hash_stream(stream)
        if before != signature(os.fstat(stream.fileno())):
            raise SafetyError('読み取り中に変更: ' + name)
    with parent_fd(root, name) as (fd, leaf):
        if signature(os.stat(leaf, dir_fd=fd, follow_symlinks=False)) != before:
            raise SafetyError('読み取り中に置換: ' + name)
    return digest, before


def secure_directory(path, create=False):
    """アーカイブ先を含め、すべての親のリンクを拒否する。"""
    path = Path(os.path.abspath(os.path.expanduser(str(path))))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if create and not current.exists():
            current.mkdir(mode=0o700)
        if current.is_symlink() or not current.is_dir():
            raise SafetyError('安全なディレクトリではありません: ' + str(current))
    return path


@contextlib.contextmanager
def exclusive(root):
    # ディレクトリFDをロックするため、ロックファイルや.gitへの書込みは不要。
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise SafetyError('別の整理処理が実行中です') from error
        yield
    finally:
        os.close(fd)


def require_idle(root, names):
    """読取り中の検証処理も含め、開かれた対象があれば処理しない。"""
    executable = shutil.which('lsof')
    if not executable:
        raise SafetyError('実行中ファイル検査にlsofが必要です')
    names = sorted(set(names))
    for offset in range(0, len(names), 100):
        p = subprocess.run([executable, '-nP', '-Fpn', '--',
                            *(str(root / n) for n in names[offset:offset + 100])],
                           capture_output=True, text=True, timeout=30)
        if p.stderr.strip() or p.returncode not in (0, 1):
            raise SafetyError('実行中ファイル検査不能: ' + p.stderr[:300])
        if p.stdout.strip():
            raise SafetyError('対象を使用中のプロセスがあります: ' + p.stdout[:500])


class MetadataReader:
    """親ディレクトリFDを少数だけ再利用し、リンクを辿らず大量資料を読む。"""
    def __init__(self, root):
        self.root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.cache = collections.OrderedDict()

    def directory(self, name):
        if not name:
            return self.root_fd
        if name in self.cache:
            self.cache.move_to_end(name)
            return self.cache[name]
        parent, _, leaf = name.rpartition('/')
        fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.directory(parent))
        self.cache[name] = fd
        while len(self.cache) > 128:
            _, old = self.cache.popitem(last=False)
            os.close(old)
        return fd

    @contextlib.contextmanager
    def open(self, name):
        relative(name)
        parent, _, leaf = name.rpartition('/')
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory(parent))
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SafetyError('資料が通常ファイルではありません: ' + name)
            yield stream

    def __enter__(self):
        return self

    def __exit__(self, *args):
        for fd in self.cache.values():
            os.close(fd)
        os.close(self.root_fd)


class Audit:
    def __init__(self, root=ROOT, older_than_days=7, prune_days=30, now=None, active_phases=()):
        self.root = Path(root).resolve()
        self.now = time.time() if now is None else now
        self.older = older_than_days
        self.prune_days = prune_days
        self.active = set(active_phases)
        self.files = {}
        self.dirs = {}
        self.refs = collections.defaultdict(list)
        self.reference_keys = collections.defaultdict(set)
        self.holds = set(active_phases)
        self.hold_scopes = set()
        self.errors = []
        self.metadata_fingerprint = hashlib.sha256()
        self.reference_hashes = {}
        self.evidence_signatures = {}
        self.missing_references = []
        self.missing_reference_keys = set()
        self.tracked = set(os.fsdecode(p) for p in git(self.root, 'ls-files', '-z').split(b'\0') if p)
        self.scan()
        self.cmake_roots = {n.rsplit('/', 1)[0] for n in self.files if n.endswith('/CMakeCache.txt')}
        target_names = [n for n in self.files if n.split('/')[0] in ('results', 'build')]
        # check-ignoreへ数十万パスを渡す方式はindex照合が極端に遅くなる。
        self.ignored = set(os.fsdecode(n) for n in git(
            self.root, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z').split(b'\0') if n)
        self.read_evidence()
        # ディレクトリ全体への同じ用途の参照は、子ファイルごとに複製しない。
        self.directory_refs = {}
        for name, refs in self.refs.items():
            if name not in self.dirs:
                continue
            grouped = {}
            for row in refs:
                key = (row['role'], bool(row.get('held')))
                if key not in grouped:
                    grouped[key] = dict(source=row['source'], role=row['role'], via_directory=name, source_count=0)
                    if row.get('held'):
                        grouped[key]['held'] = True
                grouped[key]['source_count'] += 1
            self.directory_refs[name] = list(grouped.values())
        self.items = self.classify(target_names)

    def scan(self):
        def failed(error):
            self.errors.append(str(error))
        for base, dirs, files in os.walk(self.root, followlinks=False, onerror=failed):
            dirs[:] = sorted(d for d in dirs if d != '.git')
            for name in list(dirs):
                path = Path(base) / name
                s = path.lstat()
                rel = path.relative_to(self.root).as_posix()
                if stat.S_ISLNK(s.st_mode):
                    dirs.remove(name)
                    self.files[rel] = self.info(s, 'symlink')
                else:
                    self.dirs[rel] = self.info(s, 'directory')
            for name in sorted(files):
                path = Path(base) / name
                try:
                    s = path.lstat()
                    kind = 'file' if stat.S_ISREG(s.st_mode) else 'symlink' if stat.S_ISLNK(s.st_mode) else 'special'
                    self.files[path.relative_to(self.root).as_posix()] = self.info(s, kind)
                except OSError as error:
                    failed(error)

    @staticmethod
    def info(s, kind):
        return dict(bytes=s.st_size, allocated_bytes=getattr(s, 'st_blocks', 0) * 512,
                    signature=signature(s), mtime=s.st_mtime, kind=kind)

    def resolve_reference(self, value, source, scope=None):
        if not isinstance(value, str) or not value or '\x00' in value:
            return []
        value = value.strip().removeprefix('file://')
        # シェル式・URL・パターンは推測展開しない。
        if any(c in value for c in ('\n', '\r', '*', '{', '}', '<', '>')) or '://' in value:
            return []
        candidates = []
        if value.startswith('/'):
            prefix = str(self.root) + '/'
            if value.startswith(prefix):
                candidates = [value[len(prefix):]]
            else:
                return []  # 外部原曲は読み取らない。
        else:
            if value.startswith(('results/', 'build/', 'tests/', 'scripts/', 'docs/', 'src/')):
                candidates.append(value)
            else:
                if scope:
                    candidates.append(scope + '/' + value)
                candidates.append(source.rpartition('/')[0] + '/' + value)
                # provenanceのrepo相対名と、analysis/内資料の実行ルート相対名。
                run_parent = source.rpartition('/')[0].rpartition('/')[0]
                if run_parent:
                    candidates.append(run_parent + '/' + value)
                candidates.append(value)
        found = []
        for candidate in candidates:
            normalized = os.path.normpath(candidate)
            if normalized in self.files or normalized in self.dirs:
                try:
                    relative(normalized)
                except SafetyError:
                    continue
                found.append(normalized)
        return list(dict.fromkeys(found))

    def add_reference(self, value, source, role='unknown', scope=None, digest=None, size=None, held=False):
        resolved = self.resolve_reference(value, source, scope)
        if not resolved and isinstance(value, str) and isinstance(digest, str) and SHA.fullmatch(digest.lower()):
            candidate = value
            prefix = str(self.root) + '/'
            if candidate.startswith(prefix):
                candidate = candidate[len(prefix):]
            elif not candidate.startswith(('results/', 'build/')) and not candidate.startswith('/'):
                candidate = (scope or source.rpartition('/')[0]) + '/' + candidate
            try:
                candidate = target_relative(candidate)
            except SafetyError:
                pass
            else:
                record = dict(path=candidate, source=source, sha256=digest, status='MISSING')
                identity = (candidate, source, digest)
                if identity not in self.missing_reference_keys:
                    self.missing_reference_keys.add(identity)
                    self.missing_references.append(record)
        for name in resolved:
            record = dict(source=source, role=role)
            if isinstance(digest, str) and SHA.fullmatch(digest.lower()):
                record['sha256'] = digest.lower()
            if isinstance(size, int) and not isinstance(size, bool):
                record['bytes'] = size
            if held:
                record['held'] = True
            identity = tuple(sorted(record.items()))
            if identity not in self.reference_keys[name]:
                self.reference_keys[name].add(identity)
                self.refs[name].append(record)

    @staticmethod
    def role(key):
        if (PROTECTED_WORDS.search(key) or INPUT_WORDS.search(key)
                or re.search(r'(^|[_\W])(ref|expected|gold)([_\W]|$)|入力|原本|参照', key, re.I)):
            return 'protected'
        if re.search(r'output|audition|generated|export|candidate', key, re.I):
            return 'output'
        return 'unknown'

    def json_refs(self, value, source, scope=None, role='unknown', held=False):
        if isinstance(value, dict):
            if (any(value.get(k) is False or str(value.get(k)).lower() in ('false', 'no', '0') for k in ('PASS', 'pass', 'overall_pass', 'functional_pass'))
                    or any(isinstance(value.get(k), str) and value[k].upper() in
                           ('FAIL', 'NO-GO', 'NO_GO', 'INCOMPLETE', 'INDETERMINATE', 'NOT_RUN', 'UNREVIEWED', 'ABNORMAL_EXIT', 'PARTIAL_STOP', 'RUNNING', 'IN_PROGRESS', 'STARTED')
                           for k in ('status', 'result', 'verdict', 'MEASUREMENT_QUALITY', 'STORAGE_STATUS'))):
                if source.startswith(('results/', 'build/')):
                    self.hold_scopes.add(source.rpartition('/')[0])
            for key in ('artifact_root', 'root'):
                if isinstance(value.get(key), str):
                    roots = self.resolve_reference(value[key], source, scope)
                    if roots:
                        scope = roots[0]
            held = held or value.get('reanalysis_needed') is True or value.get('deletion_authorized') is False
            for key, item in value.items():
                if not isinstance(item, (str, dict, list)):
                    continue
                # CSVの大量の数値・状態欄をパスとして解釈しない。
                if isinstance(item, str) and not any(c in item for c in ('/', '.', '\\')):
                    if SHA.fullmatch(item.lower()):
                        if '/' in key or '.' in key or self.resolve_reference(key, source, scope):
                            self.add_reference(key, source, self.role(key), scope, item, held=held)
                        continue
                    parent = scope or source.rpartition('/')[0]
                    if parent + '/' + item not in self.files and parent + '/' + item not in self.dirs:
                        continue
                if isinstance(item, str) and item and item[0] in '0123456789+-' and re.fullmatch(r'[-+\d.eE]+', item):
                    continue
                child_role = self.role(key)
                if child_role == 'unknown':
                    child_role = role
                if isinstance(item, str):
                    # path:foo/sha256:...、output_path/output_sha256双方を扱う。
                    stem = re.sub(r'(_path|_file|_wav)$', '', key)
                    digest = value.get(stem + '_sha256') or value.get(key + '_sha256')
                    if key in ('path', 'file', 'wav'):
                        digest = value.get('sha256') or value.get('sha256_file')
                    size = value.get('bytes', value.get('size')) if key in ('path', 'file', 'wav') else None
                    self.add_reference(item, source, child_role, scope, digest, size, held)
                    # パスを辞書キー、SHAを値とするmanifest。
                    if SHA.fullmatch(item.lower()):
                        self.add_reference(key, source, child_role, scope, item, held=held)
                else:
                    self.json_refs(item, source, scope, child_role, held)
        elif isinstance(value, list):
            for item in value:
                self.json_refs(item, source, scope, role, held)
        elif isinstance(value, str):
            self.add_reference(value, source, role, scope, held=held)

    def read_evidence(self):
        with MetadataReader(self.root) as reader:
            self._read_evidence(reader)

    def _read_evidence(self, reader):
        for name, info in self.files.items():
            p = PurePosixPath(name)
            # 全ての結果表・manifest・ソースを調査。巨大なデータ表は安全側で保留。
            relevant = (name in self.tracked or p.parts[0] in ('results', 'build'))
            if not relevant or p.suffix.lower() not in META_EXT or info['kind'] != 'file':
                continue
            # 外部依存物やCMakeの自動構成は検証資料ではない。容量と外側の
            # artifact manifestからの参照は引き続き監査する。
            generated = {'plot_dependencies', 'site-packages', 'node_modules', 'CMakeFiles', '__pycache__'}
            if name not in self.tracked and p.parts[0] == 'build' and generated.intersection(p.parts):
                continue
            if info['bytes'] > 32 * MIB:
                if re.search(r'manifest|provenance|custody', name, re.I):
                    self.errors.append('参照資料が32MiB上限を超過: ' + name)
                continue
            try:
                with reader.open(name) as f:
                    raw = f.read(32 * MIB + 1)
                    if signature(os.fstat(f.fileno())) != info['signature']:
                        raise SafetyError('監査中に変更: ' + name)
                if len(raw) > 32 * MIB:
                    raise SafetyError('監査中に資料が増大: ' + name)
                text = raw.decode('utf-8-sig')
                self.evidence_signatures[name] = info['signature']
                self.metadata_fingerprint.update(os.fsencode(name) + b'\0' + hashlib.sha256(raw).digest())
                if 'REPORT' in p.name.upper() and HOLD_WORDS.search(text):
                    if phase_of(name) == '(Phase不明)':
                        self.hold_scopes.add(name.rpartition('/')[0])
                    else:
                        self.holds.add(phase_of(name))
                if p.suffix.lower() in ('.json', '.jsonl', '.csv'):
                    failure = re.search(r'"(?:PASS|pass|overall_pass|functional_pass)"\s*:\s*false|"(?:status|result|verdict|MEASUREMENT_QUALITY|STORAGE_STATUS)"\s*:\s*"(?:FAIL|NO.GO|INCOMPLETE|INDETERMINATE|NOT_RUN|UNREVIEWED|ABNORMAL_EXIT|PARTIAL_STOP|RUNNING|IN_PROGRESS|STARTED)"', text, re.I)
                    if failure and name.startswith(('results/', 'build/')):
                        self.hold_scopes.add(name.rpartition('/')[0])
                    # 数値専用の巨大な測定表は参照を持たない。パス/パス欄の
                    # 存在を全バイトから確認し、余計なPythonオブジェクト生成を省く。
                    has_path = (re.search(r'manifest|provenance|custody|recipe', p.name, re.I)
                                or '/' in text or re.search(r'"(?:path|file|files|root|artifact_root|reference|binary|input|output)"\s*:', text)
                                or re.search(r'\.(?:wav|pcm|f32|raw|trace|ktrace|csv|xml|json|bin|log|dylib|a|o|so|exe|cpp|h|mm)(?:["\s,]|$)', text))
                    if not has_path:
                        continue
                if p.suffix.lower() == '.json':
                    self.json_refs(json.loads(text), name)
                elif p.suffix.lower() == '.jsonl':
                    for line in text.splitlines():
                        if line.strip():
                            self.json_refs(json.loads(line), name)
                elif p.suffix.lower() == '.csv':
                    for row in csv.DictReader(io.StringIO(text)):
                        self.json_refs(row, name)
                # 自由文・コマンド内の明示的パスも参照として扱う。文字列全体は空白対応。
                for value in re.findall(r'`([^`\n]+)`|["\']([^"\'\n]+)["\']', text):
                    token = value[0] or value[1]
                    if '/' in token:
                        self.add_reference(token, name)
                for token in re.findall(r'(?:results|build)/[^\s`"\'\)\],;]+', text):
                    self.add_reference(token.rstrip('.:'), name)
            except (UnicodeError, ValueError, TypeError, csv.Error, OSError, SafetyError) as error:
                # 任意コードを実行せず、読めない資料があれば変更系を一律停止する。
                self.errors.append(name + ': ' + str(error)[:180])

    def references(self, name):
        refs = list(self.refs.get(name, ()))
        for parent in PurePosixPath(name).parents:
            if str(parent) not in ('.', 'build', 'results'):
                refs.extend(self.directory_refs.get(str(parent), ()))
        return refs

    def assert_evidence_unchanged(self, exclude=()):
        tracked = set(os.fsdecode(p) for p in git(self.root, 'ls-files', '-z').split(b'\0') if p)
        if tracked != self.tracked:
            raise SafetyError('監査後にGit追跡対象が変更されました')
        for name, expected in self.evidence_signatures.items():
            if name in exclude:
                continue
            with parent_fd(self.root, name) as (fd, leaf):
                if signature(os.stat(leaf, dir_fd=fd, follow_symlinks=False)) != expected:
                    raise SafetyError('監査後に参照資料が変更されました: ' + name)

    def classify_file(self, name):
        info = self.files[name]
        refs = self.references(name)
        phase = phase_of(name)
        age = max(0, (self.now - info['mtime']) / 86400)
        base = PurePosixPath(name)
        if name in self.tracked:
            return 'KEEP', 'Git追跡済み'
        if info['kind'] != 'file':
            return 'REVIEW', 'リンク・特殊ファイルは処理しない'
        if info['signature'][-1] > 1:
            return 'REVIEW', 'ハードリンクの共有範囲が未確定'
        if ('golden' in [p.lower() for p in base.parts] or PROTECTED_WORDS.search(name)
                or INPUT_WORDS.search(name)):
            return 'KEEP', 'Golden・入力・固定基準/独立参照を保護'
        if any(r['role'] == 'protected' for r in refs):
            return 'KEEP', '入力・独立参照・baselineとして資料が参照'
        if base.suffix.lower() in PERMANENT_EXT or re.search(r'manifest|provenance|recipe|report|sha256', base.name, re.I):
            return 'KEEP', '判定資料・manifest・ハッシュ・生成レシピを保護'
        held_scope = any(str(p) in self.hold_scopes for p in base.parents)
        if phase in self.holds or held_scope or any(r.get('held') for r in refs):
            return 'REVIEW', '未解決/NO-GO/再解析対象Phaseの原本証拠'
        if self.errors:
            return 'REVIEW', '参照資料の監査が未完了'
        direct = self.refs.get(name, ())
        expected = {r['sha256'] for r in direct if 'sha256' in r}
        sizes = {r['bytes'] for r in direct if 'bytes' in r}
        if len(expected) > 1 or (sizes and sizes != {info['bytes']}):
            return 'REVIEW', '既存manifestの期待SHA同士/現物サイズが不一致'
        if age <= self.older:
            return 'KEEP', f'直近{self.older:g}日以内の成果物'
        # 出力としての明示的記録が必要。拡張子・ignore・古さだけでは許可しない。
        if any(r['role'] == 'output' for r in refs) and base.suffix.lower() in DATA_EXT:
            return 'ARCHIVE', '生成出力として記録済み。参照元を保存し、可逆保管後にのみ削除可'
        if refs:
            return 'REVIEW', '資料から参照されるが用途・復元保証が未確定'
        cmake = any(part == 'CMakeFiles' for part in base.parts)
        cache = any(str(p) in self.cmake_roots for p in base.parents) if cmake else False
        if (age > self.prune_days and cmake and cache and (self.root / 'CMakeLists.txt').is_file()
                and base.name.endswith(('.o', '.o.d'))):
            return 'PRUNE', 'CMake構成と再ビルド手順が存在する未参照中間物。削除にもアーカイブ必須'
        return 'REVIEW', '生成元・保存義務・復元方法を確認できない'

    def classify(self, names):
        packages = {n for n in self.dirs if n.endswith('.trace')}
        # 外側のtraceを単位とする。
        packages = {n for n in packages if not any(str(p) in packages for p in PurePosixPath(n).parents)}
        groups = collections.defaultdict(list)
        for name in names:
            package = next((str(p) for p in PurePosixPath(name).parents if str(p) in packages), None)
            groups[package or name].append(name)
        for package in packages:
            if package.split('/')[0] in ('results', 'build'):
                groups.setdefault(package, [])
        result = []
        priority = {'KEEP': 0, 'REVIEW': 1, 'ARCHIVE': 2, 'PRUNE': 3}
        for name, members in sorted(groups.items()):
            decisions = [self.classify_file(m) for m in members]
            if not decisions:
                decisions = [('REVIEW', '空のtraceパッケージ。用途を確認できない')]
            category, reason = min(decisions, key=lambda r: priority[r[0]])
            if name in packages:
                own = self.references(name)
                # パッケージ内部のファイル名・拡張子ではなく、外部資料の用途で判定する。
                category, reason = 'REVIEW', 'traceの用途・復元保証が未確定'
                if (any(r['role'] == 'output' for r in own) and not self.errors
                        and all(self.now - self.files[m]['mtime'] > self.older * 86400 for m in members)):
                    category, reason = 'ARCHIVE', '出力として記録されたtraceをパッケージ単位で可逆保管'
                if any(self.now - self.files[m]['mtime'] <= self.older * 86400 for m in members):
                    category, reason = 'KEEP', '直近のtraceパッケージ'
                if any(self.files[m]['kind'] != 'file' or self.files[m]['signature'][-1] > 1 for m in members):
                    category, reason = 'REVIEW', 'trace内にリンク・特殊ファイルが存在'
                if (any(r.get('held') for r in own) or phase_of(name) in self.holds
                        or any(str(p) in self.hold_scopes for p in [PurePosixPath(name), *PurePosixPath(name).parents])
                        or any(scope.startswith(name + '/') for scope in self.hold_scopes)):
                    category, reason = 'REVIEW', '再解析/未解決traceパッケージを一体で保持'
                if any(r['role'] == 'protected' for m in members for r in self.references(m)) or PROTECTED_WORDS.search(name):
                    category, reason = 'KEEP', '基準として参照されるtraceパッケージ'
                if any(PurePosixPath(m).suffix.lower() in ('.wav', '.pcm', '.f32', '.raw')
                       and INPUT_WORDS.search(m) for m in members):
                    category, reason = 'KEEP', '入力原本を含むtraceパッケージ'
                if any(m in self.tracked for m in members):
                    category, reason = 'KEEP', 'Git追跡ファイルを含むtraceパッケージ'
            refs = []
            seen_refs = set()
            for m in members:
                for r in self.references(m):
                    identity = tuple(sorted(r.items()))
                    if identity not in seen_refs:
                        seen_refs.add(identity)
                        refs.append(r)
            result.append(dict(path=name, phase=phase_of(name), classification=category, reason=reason,
                               bytes=sum(self.files[m]['bytes'] for m in members),
                               allocated_bytes=sum(self.files[m]['allocated_bytes'] for m in members),
                               file_count=len(members), members=members, references=refs,
                               protection=('permanent' if category == 'KEEP' and not reason.startswith('直近') else
                                           'recent' if category == 'KEEP' else 'none'),
                               git_status=('tracked' if any(m in self.tracked for m in members) else
                                           'ignored' if members and all(m in self.ignored for m in members) else 'untracked'),
                               age_days=round(max(0, (self.now - max((self.files[m]['mtime'] for m in members), default=self.now)) / 86400), 2)))
        return result

    def verify_references(self, names):
        """既存manifestの期待SHA/サイズを変更操作の前に照合する。"""
        results = []
        for name in names:
            refs = self.refs.get(name, [])
            expected = {r['sha256'] for r in refs if 'sha256' in r}
            sizes = {r['bytes'] for r in refs if 'bytes' in r}
            digest, sig = file_hash(self.root, name)
            if len(expected) > 1 or (expected and expected != {digest}) or (sizes and sizes != {sig[2]}):
                raise SafetyError('既存manifestと不一致: ' + name)
            results.append(dict(path=name, sha256=digest, signature=sig, bytes=sig[2],
                                references=refs, reference_check='PASS' if expected or sizes else '期待ハッシュなし・現物を記録'))
        return results

    def summary(self):
        def aggregate(pairs):
            totals = collections.defaultdict(lambda: dict(bytes=0, allocated_bytes=0, files=0))
            for key, info in pairs:
                totals[key]['bytes'] += info['bytes']
                totals[key]['allocated_bytes'] += info['allocated_bytes']
                totals[key]['files'] += info.get('file_count', 1)
            return dict(sorted(totals.items(), key=lambda kv: kv[1]['bytes'], reverse=True))
        targets = [(n, i) for n, i in self.files.items() if n.split('/')[0] in ('results', 'build')]
        directory_totals = collections.Counter()
        for n, info in targets:
            for parent in PurePosixPath(n).parents:
                if str(parent) != '.':
                    directory_totals[str(parent)] += info['bytes']
        categories = aggregate((i['classification'], i) for i in self.items)
        estimated = 0
        sample_bytes = 0
        for item in self.items:
            if item['classification'] != 'ARCHIVE':
                continue
            # 最大3箇所の64KiB標本。生成物を変更せずメモリ内で圧縮する。
            for name in item['members']:
                size = self.files[name]['bytes']
                with safe_file(self.root, name) as stream:
                    chunks = []
                    for offset in sorted({0, max(0, size // 2 - 32768), max(0, size - 65536)}):
                        stream.seek(offset)
                        chunks.append(stream.read(min(65536, size)))
                sampled = b''.join(chunks)
                sample_bytes += len(sampled)
                ratio = len(zlib.compress(sampled)) / max(1, len(sampled))
                estimated += max(0, int(size * (1 - ratio)) - 10240)
        return dict(schema='TimeStretchLab-artifact-audit-v1', created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                    root=str(self.root), repository=aggregate([('working_tree_excluding_git', dict(
                        bytes=sum(i['bytes'] for i in self.files.values()),
                        allocated_bytes=sum(i['allocated_bytes'] for i in self.files.values()) + sum(i['allocated_bytes'] for i in self.dirs.values()),
                        file_count=len(self.files)))]),
                    storage=aggregate((n.split('/')[0], i) for n, i in targets),
                    phases=aggregate((i['phase'], i) for i in self.items),
                    extensions=aggregate((PurePosixPath(n).suffix.lower() or '(拡張子なし)', i) for n, i in targets),
                    kinds=aggregate((('WAV' if PurePosixPath(n).suffix.lower() == '.wav' else
                                      'PCM' if PurePosixPath(n).suffix.lower() in ('.pcm', '.f32', '.raw') else
                                      'TRACE' if any(p.endswith(('.trace', '.ktrace', '.ktrace.gz', '.atrc')) for p in PurePosixPath(n).parts) else
                                      'CSV' if PurePosixPath(n).suffix.lower() == '.csv' else 'その他'), i) for n, i in targets),
                    classification=categories, git_status=aggregate((i['git_status'], i) for i in self.items),
                    protection=aggregate((i['protection'], i) for i in self.items if i['classification'] == 'KEEP'),
                    top_files=[dict(path=n, **i) for n, i in sorted(targets, key=lambda kv: kv[1]['bytes'], reverse=True)[:50]],
                    top_directories=[dict(path=n, bytes=b) for n, b in directory_totals.most_common(50)],
                    estimated_savings=dict(compression_sample_estimate_bytes=estimated, sample_bytes=sample_bytes,
                        archive_source_bytes=categories.get('ARCHIVE', {}).get('bytes', 0),
                        prune_source_bytes=categories.get('PRUNE', {}).get('bytes', 0),
                        immediate_deletion_bytes=0, archive_creation_alone_saves_bytes=0,
                        note='標本のzlib圧縮率による概算。元データ削除後・同一容量プール保管時の論理差。確約値ではない'),
                    disk=dict(shutil.disk_usage(self.root)._asdict()), errors=self.errors,
                    protected_phases=sorted(self.holds), protected_scopes=sorted(self.hold_scopes),
                    missing_references=self.missing_references,
                    directory_reference_index={n: self.refs[n] for n in self.directory_refs}, items=self.items)


def snapshot(audit, items):
    names = sorted(m for i in items for m in i['members'])
    records = audit.verify_references(names)
    directories = set()
    for item in items:
        if item['path'] in audit.dirs:
            directories.add(item['path'])
            directories.update(n for n in audit.dirs if n.startswith(item['path'] + '/'))
    for row in records:
        with safe_file(audit.root, row['path']) as stream:
            attrs = xattrs(stream.fileno())
        if sum(len(v) for v in attrs.values()) > MIB:
            raise SafetyError('拡張属性が大きいため個別確認が必要: ' + row['path'])
        row.update(kind='file', mode=stat.S_IMODE(row['signature'][5]), mtime_ns=row['signature'][3], xattrs=attrs)
    for name in sorted(directories):
        with parent_fd(audit.root, name) as (fd, leaf):
            handle = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            s = os.fstat(handle)
            attrs = xattrs(handle)
            records.append(dict(path=name, kind='directory', bytes=0, mode=stat.S_IMODE(s.st_mode),
                                mtime_ns=s.st_mtime_ns, xattrs=attrs, signature=signature(s)))
        finally:
            os.close(handle)
    return sorted(records, key=lambda r: r['path'])


def check_sources(root, records, items, after_rename=False):
    for row in records:
        if row['kind'] == 'directory':
            with parent_fd(root, row['path']) as (fd, leaf):
                sig = signature(os.stat(leaf, dir_fd=fd, follow_symlinks=False))
            expected = row['signature']
            if (not after_rename and sig != expected) or (after_rename and (sig[:4] != expected[:4] or sig[5:] != expected[5:])):
                raise SafetyError('パッケージの属性・内容が変更: ' + row['path'])
            continue
        digest, sig = file_hash(root, row['path'])
        original = row['signature']
        same = sig == original if not after_rename else sig[:4] == original[:4] and sig[5:] == original[5:]
        if digest != row['sha256'] or not same:
            raise SafetyError('元ファイルの変更・置換を検出: ' + row['path'])
    # パッケージに新しいファイル/空ディレクトリが増えた場合も停止する。
    expected = {r['path'] for r in records}
    for item in items:
        if item['path'] not in expected or not any(r['path'] == item['path'] and r['kind'] == 'directory' for r in records):
            continue
        found = {item['path']}
        for base, dirs, files in os.walk(root / item['path'], followlinks=False):
            for leaf in dirs + files:
                p = Path(base) / leaf
                if p.is_symlink():
                    raise SafetyError('パッケージ内にリンク: ' + str(p))
                found.add(p.relative_to(root).as_posix())
        if found != {n for n in expected if n == item['path'] or n.startswith(item['path'] + '/')}:
            raise SafetyError('traceパッケージの構成が変化: ' + item['path'])


def ensure_space(path, required):
    free = shutil.disk_usage(path).free
    if free < required:
        raise SafetyError(f'空き容量不足: 必要 {required:,} bytes、空き {free:,} bytes ({path})')
    return free


@contextlib.contextmanager
def tar_writer(path, method):
    with path.open('xb') as output:
        os.chmod(path, 0o600)
        if method == 'zstd':
            process = subprocess.Popen([shutil.which('zstd'), '-q', '-T1', '-3', '-c'],
                                       stdin=subprocess.PIPE, stdout=output, stderr=subprocess.PIPE)
            try:
                with tarfile.open(fileobj=process.stdin, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                    yield archive
                process.stdin.close()
                error = process.stderr.read()
                if process.wait() != 0:
                    raise SafetyError('zstd失敗: ' + error.decode(errors='replace')[:300])
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
                process.stderr.close()
                if not process.stdin.closed:
                    process.stdin.close()
        else:
            with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                    yield archive
        output.flush()
        os.fsync(output.fileno())


@contextlib.contextmanager
def tar_reader(path, method):
    # 完成アーカイブ自体もリンクを許可しない。
    with safe_file(path.parent, path.name) as source:
        if method == 'zstd':
            executable = shutil.which('zstd')
            if not executable:
                raise SafetyError('このアーカイブの復元にはzstdが必要です（gzipアーカイブは標準機能で対応）')
            process = subprocess.Popen([executable, '-q', '-d', '-c'], stdin=source,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                    yield archive
                # TAR末尾後も圧縮フレームのチェックサムまで読み切る。
                while process.stdout.read(MIB):
                    pass
                error = process.stderr.read()
                if process.wait() != 0:
                    raise SafetyError('zstd展開失敗: ' + error.decode(errors='replace')[:300])
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
                process.stdout.close()
                process.stderr.close()
        elif method == 'gzip':
            with gzip.GzipFile(fileobj=source, mode='rb') as stream:
                with tarfile.open(fileobj=stream, mode='r|') as archive:
                    yield archive
                while stream.read(MIB):
                    pass
        else:
            raise SafetyError('未対応の圧縮方式')


def write_json(path, value):
    with path.open('x', encoding='utf-8') as f:
        os.chmod(path, 0o600)
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load_manifest(path, allow_partial=False):
    path = Path(os.path.abspath(path))
    secure_directory(path.parent)
    if not allow_partial and any(p.endswith('.partial') for p in path.parts):
        raise SafetyError('未完成の作業領域は完成アーカイブとして扱いません')
    if path.stat().st_size > 50_000_000:
        raise SafetyError('アーカイブmanifestが大きすぎます')
    with safe_file(path.parent, path.name) as f:
        m = json.load(f)
    valid_status = m.get('status') == 'VERIFIED' and m.get('verification', {}).get('passed')
    if allow_partial:
        valid_status = valid_status or m.get('status') == 'VERIFYING'
    if m.get('schema') != SCHEMA or not valid_status:
        raise SafetyError('完成・検証済みmanifestではありません')
    if m.get('method') not in ('zstd', 'gzip') or not SHA.fullmatch(m.get('archive_sha256', '')):
        raise SafetyError('アーカイブ情報が不正です')
    archive_name = relative(m['archive_file'])
    if '/' in archive_name:
        raise SafetyError('アーカイブはmanifestと同じディレクトリに必要です')
    seen = set()
    for row in m['entries']:
        name = target_relative(row['path'])
        if name in seen or row['kind'] not in ('file', 'directory'):
            raise SafetyError('重複・不正なアーカイブ項目')
        seen.add(name)
        if row['kind'] == 'file' and (not SHA.fullmatch(row['sha256']) or not isinstance(row['bytes'], int) or row['bytes'] < 0):
            raise SafetyError('元ファイル検査情報が不正')
        if not 0 <= row['mode'] <= 0o777:
            raise SafetyError('特殊なアクセス権は復元しません')
        if phase_of(name) != m['phase']:
            raise SafetyError('manifest内でPhaseが一致しません')
    if not m['entries'] or not m['items']:
        raise SafetyError('空のアーカイブmanifest')
    item_paths = []
    covered = set()
    for item in m['items']:
        n = target_relative(item['path'])
        if item['classification'] not in ('ARCHIVE', 'PRUNE') or n in item_paths:
            raise SafetyError('対象一覧が不正')
        if any(n.startswith(p + '/') or p.startswith(n + '/') for p in item_paths):
            raise SafetyError('対象範囲が重複')
        item_paths.append(n)
        if n not in seen:
            raise SafetyError('対象がアーカイブ内に存在しません')
        covered.update(x for x in seen if x == n or x.startswith(n + '/'))
    if covered != seen:
        raise SafetyError('対象一覧と収録ファイルが一致しません')
    return m, path.parent / archive_name


def verify_archive(manifest_path, destination=None, allow_partial=False):
    m, path = load_manifest(manifest_path, allow_partial=allow_partial)
    digest, archive_sig = file_hash(path.parent, path.name)
    if digest != m['archive_sha256'] or path.stat().st_size != m['archive_bytes']:
        raise SafetyError('アーカイブSHA-256/サイズ不一致')
    expected = {r['path']: r for r in m['entries']}
    seen = set()
    with tar_reader(path, m['method']) as archive:
        for member in archive:
            name = target_relative(member.name)
            if name not in expected or name in seen:
                raise SafetyError('未登録/重複したTAR項目: ' + name)
            row = expected[name]
            if ((row['kind'] == 'file' and not member.isfile())
                    or (row['kind'] == 'directory' and not member.isdir()) or member.size != row['bytes']):
                raise SafetyError('リンク・特殊項目・サイズ不一致: ' + name)
            seen.add(name)
            if member.isdir():
                if destination:
                    with parent_fd(destination, name, create=True) as (fd, leaf):
                        os.mkdir(leaf, 0o700, dir_fd=fd)
                continue
            h = hashlib.sha256()
            with contextlib.ExitStack() as stack:
                source = stack.enter_context(archive.extractfile(member))
                output = None
                if destination:
                    fd, leaf = stack.enter_context(parent_fd(destination, name, create=True))
                    out_fd = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                    output = stack.enter_context(os.fdopen(out_fd, 'wb'))
                for block in iter(lambda: source.read(MIB), b''):
                    h.update(block)
                    if output:
                        output.write(block)
                if output:
                    output.flush()
                    os.fsync(output.fileno())
                    for attr, value in row.get('xattrs', {}).items():
                        set_xattr(output.fileno(), attr, base64.b64decode(value, validate=True))
                    os.fchmod(output.fileno(), row['mode'])
                    os.utime(output.fileno(), ns=(row['mtime_ns'], row['mtime_ns']))
            if h.hexdigest() != row['sha256']:
                raise SafetyError('展開後SHA-256不一致: ' + name)
    if seen != set(expected):
        raise SafetyError('アーカイブに不足があります')
    final_digest, final_sig = file_hash(path.parent, path.name)
    if final_digest != digest or final_sig != archive_sig:
        raise SafetyError('検証中にアーカイブが変更・置換されました')
    if destination:
        for row in sorted(m['entries'], key=lambda r: len(r['path']), reverse=True):
            if row['kind'] == 'directory':
                with parent_fd(destination, row['path']) as (fd, leaf):
                    handle = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    for attr, value in row.get('xattrs', {}).items():
                        set_xattr(handle, attr, base64.b64decode(value, validate=True))
                    os.fchmod(handle, row['mode'])
                    os.utime(handle, ns=(row['mtime_ns'], row['mtime_ns']))
                finally:
                    os.close(handle)
    return m


def archive_phase(audit, phase, archive_dir=None, method='auto', include_regenerable=False, paths=()):
    if audit.errors:
        raise SafetyError('参照監査エラーがあるため圧縮を開始しません')
    if not phase and not paths:
        raise SafetyError('Phaseまたはパス範囲の指定が必要です')
    allowed = ('ARCHIVE', 'PRUNE') if include_regenerable else ('ARCHIVE',)
    paths = [target_relative(n) for n in paths]
    items = [i for i in audit.items if (not phase or i['phase'] == phase) and i['classification'] in allowed
             and (not paths or any(i['path'] == n or i['path'].startswith(n + '/') for n in paths))]
    if not items:
        raise SafetyError('指定範囲に圧縮可能な候補がありません: ' + str(phase or paths))
    selected_phases = {i['phase'] for i in items}
    if len(selected_phases) != 1:
        raise SafetyError('一度に保管する対象は単一Phase/範囲に限定してください')
    phase = next(iter(selected_phases))
    # 明示的に追加したPRUNEもアーカイブを経由する。直接削除モードは提供しない。
    require_idle(audit.root, [m for i in items for m in i['members']])
    destination = Path(os.path.abspath(os.path.expanduser(str(archive_dir or audit.root.parent / (audit.root.name + '-artifact-archives')))))
    if destination == audit.root or audit.root in destination.parents:
        raise SafetyError('アーカイブ保存先はリポジトリ外に指定してください')
    destination = secure_directory(destination, create=True)
    method = ('zstd' if shutil.which('zstd') else 'gzip') if method == 'auto' else method
    if method == 'zstd' and not shutil.which('zstd'):
        raise SafetyError('zstd未導入です。--compression gzipで標準ライブラリ方式を利用できます')
    total = sum(i['bytes'] for i in items)
    required = int((total + sum(i['file_count'] for i in items) * 10240) * 1.1) + 64 * MIB
    before = dict(repository=shutil.disk_usage(audit.root).free, archive=ensure_space(destination, required))
    rows = snapshot(audit, items)
    metadata_bytes = len(json.dumps(rows).encode()) + len(json.dumps(items).encode())
    if metadata_bytes > 40 * MIB:
        raise SafetyError('保管manifestが大きくなるため--pathで対象範囲を分割してください')
    ensure_space(destination, required + metadata_bytes * 3)
    identity = hashlib.sha256(json.dumps([str(audit.root), phase, method, rows], sort_keys=True).encode()).hexdigest()[:24]
    final = destination / (phase + '_' + identity)
    if final.exists():
        verify_archive(final / 'archive_manifest.json')
        check_sources(audit.root, rows, items)
        return dict(status='ALREADY_VERIFIED', manifest=str(final / 'archive_manifest.json'), files_modified=False)
    partial = destination / ('.' + final.name + '.' + uuid.uuid4().hex + '.partial')
    partial.mkdir(mode=0o700)
    payload = partial / ('payload.tar.zst' if method == 'zstd' else 'payload.tar.gz')
    # ここ以降で失敗しても.partialしか残らず、元データには一切触れない。
    with tar_writer(payload, method) as archive:
        for row in rows:
            info = tarfile.TarInfo(row['path'])
            info.mode = row['mode']
            info.mtime = row['mtime_ns'] / 1e9
            if row['kind'] == 'directory':
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                info.size = row['bytes']
                with safe_file(audit.root, row['path']) as stream:
                    if signature(os.fstat(stream.fileno())) != row['signature']:
                        raise SafetyError('圧縮前に元ファイルが変更: ' + row['path'])
                    archive.addfile(info, stream)
                    if signature(os.fstat(stream.fileno())) != row['signature']:
                        raise SafetyError('圧縮中に元ファイルが変更: ' + row['path'])
    check_sources(audit.root, rows, items)
    audit.assert_evidence_unchanged()
    digest, _ = file_hash(partial, payload.name)
    manifest = dict(schema=SCHEMA, status='VERIFYING', repository=str(audit.root), phase=phase,
                    created_utc=dt.datetime.now(dt.timezone.utc).isoformat(), method=method,
                    archive_file=payload.name, archive_sha256=digest, source_bytes=total,
                    archive_bytes=payload.stat().st_size, entries=rows, items=items,
                    policy=dict(older_than_days=audit.older, prune_after_days=audit.prune_days,
                                active_phases=sorted(audit.active)),
                    directory_references={n: audit.refs[n] for n in audit.directory_refs
                        if any(i['path'] == n or i['path'].startswith(n + '/') for i in items)},
                    verification=dict(passed=False, method='全TAR項目を展開ストリームでSHA-256照合'),
                    free_before=before, free_after=dict(repository=shutil.disk_usage(audit.root).free,
                                                        archive=shutil.disk_usage(destination).free),
                    original_files_deleted=False,
                    restore='python3 scripts/artifact_cleanup.py --restore --archive-manifest <このmanifest> --confirm',
                    references_note='過去のmanifestは変更しない。元パスが不在なら本アーカイブから復元してから既存検証を実行する')
    manifest_path = partial / 'archive_manifest.json'
    write_json(manifest_path, manifest)
    try:
        verify_archive(manifest_path, allow_partial=True)
    except BaseException:
        manifest_path.rename(partial / 'UNVERIFIED_manifest.json')
        raise
    check_sources(audit.root, rows, items)
    audit.assert_evidence_unchanged()
    manifest['status'] = 'VERIFIED'
    manifest['verification']['passed'] = True
    manifest['free_after'] = dict(repository=shutil.disk_usage(audit.root).free,
                                  archive=shutil.disk_usage(destination).free)
    completed_manifest = partial / 'archive_manifest.verified.json'
    write_json(completed_manifest, manifest)
    completed_manifest.replace(manifest_path)
    sync_dir(partial)
    partial.rename(final)
    sync_dir(destination)
    return dict(status='VERIFIED', manifest=str(final / manifest_path.name), method=method,
                source_bytes=total, archive_bytes=manifest['archive_bytes'], original_files_deleted=False,
                free_before=before, free_after=manifest['free_after'],
                free_change_bytes=manifest['free_after']['repository'] - before['repository'])


def validate_prune(audit, manifest):
    if Path(manifest['repository']).resolve() != audit.root:
        raise SafetyError('元リポジトリと一致しません')
    if audit.errors:
        raise SafetyError('現在の参照関係を検査できません')
    current = {i['path']: i for i in audit.items}
    selected = []
    absent = []
    for item in manifest['items']:
        name = item['path']
        if name not in current:
            if os.path.lexists(audit.root / name):
                raise SafetyError('対象を分類できません: ' + name)
            absent.append(name)
            continue
        found = current[name]
        if found['classification'] not in ('ARCHIVE', 'PRUNE'):
            raise SafetyError('現在の分類が削除を禁止: ' + name + ' (' + found['reason'] + ')')
        selected.append(found)
    # 一部だけ消えたtraceや分類変更を黙認しない。
    expected = [r for r in manifest['entries'] if any(r['path'] == i['path'] or r['path'].startswith(i['path'] + '/') for i in selected)]
    check_sources(audit.root, expected, selected)
    audit.verify_references([r['path'] for r in expected if r['kind'] == 'file'])
    return selected, expected, absent


def prune_archive(audit, manifest_path):
    manifest = verify_archive(manifest_path)
    selected, rows, absent = validate_prune(audit, manifest)
    if not selected:
        return dict(status='ALREADY_ABSENT', files_deleted=0, absent=absent)
    require_idle(audit.root, [r['path'] for r in rows])
    audit.assert_evidence_unchanged()
    before = shutil.disk_usage(audit.root).free
    receipt_id = uuid.uuid4().hex
    receipt_dir = secure_directory(Path(manifest_path).absolute().parent)
    pending_receipt = receipt_dir / ('.prune_receipt_' + receipt_id + '.pending')
    write_json(pending_receipt, dict(status='PENDING', manifest=str(Path(manifest_path).absolute()), free_before=before))
    # 削除前に同じファイルシステム内の退避領域へ移動。途中失敗時も復元できる。
    transaction = 'build/.artifact_cleanup_transaction_' + uuid.uuid4().hex
    with parent_fd(audit.root, transaction, create=True) as (fd, leaf):
        os.mkdir(leaf, 0o700, dir_fd=fd)
    quarantine = audit.root / transaction
    moved = []
    journal = dict(status='STAGING', manifest=str(Path(manifest_path).absolute()), items=[i['path'] for i in selected])
    write_json(quarantine / 'transaction.json', journal)
    try:
        check_sources(audit.root, rows, selected)
        for item in selected:
            name = item['path']
            with parent_fd(audit.root, name) as (src_fd, src_leaf), parent_fd(quarantine, name, create=True) as (dst_fd, dst_leaf):
                os.rename(src_leaf, dst_leaf, src_dir_fd=src_fd, dst_dir_fd=dst_fd)
            moved.append(name)
        check_sources(quarantine, rows, selected, after_rename=True)
        if any(os.path.lexists(audit.root / i['path']) for i in selected):
            raise SafetyError('退避後に元パスが再作成されました。退避データを保持します')
        require_idle(quarantine, [r['path'] for r in rows])
        # 外部アーカイブが移動中に壊れた場合も元パスへ戻す。
        verify_archive(manifest_path)
        audit.assert_evidence_unchanged(exclude={r['path'] for r in rows})
    except BaseException:
        for name in reversed(moved):
            with parent_fd(quarantine, name) as (src_fd, src_leaf), parent_fd(audit.root, name, create=True) as (dst_fd, dst_leaf):
                if os.path.lexists(audit.root / name):
                    raise SafetyError('元パスが再作成されました。退避データを保持: ' + str(quarantine))
                os.rename(src_leaf, dst_leaf, src_dir_fd=src_fd, dst_dir_fd=dst_fd)
        raise
    # ここからのI/O障害・強制終了では残りを退避領域に保持。全内容はアーカイブからも復元可。
    selected_paths = {i['path'] for i in selected}
    for row in sorted(rows, key=lambda r: len(PurePosixPath(r['path']).parts), reverse=True):
        owner = row['path']
        while owner not in selected_paths:
            owner = owner.rpartition('/')[0]
            if not owner:
                raise SafetyError('退避項目に対応する元パスがありません')
        if os.path.lexists(audit.root / owner):
            raise SafetyError('削除中に元パスが再作成されました。残りの退避データを保持: ' + str(quarantine))
        with parent_fd(quarantine, row['path']) as (fd, leaf):
            if row['kind'] == 'file':
                digest, sig = file_hash(quarantine, row['path'])
                if digest != row['sha256'] or sig[:4] != row['signature'][:4]:
                    raise SafetyError('削除直前の変更。退避先を保持: ' + str(quarantine))
                os.unlink(leaf, dir_fd=fd)
            else:
                os.rmdir(leaf, dir_fd=fd)
    # 自分が作成した空の親とjournalのみ除去。任意の再帰削除は使わない。
    (quarantine / 'transaction.json').unlink()
    for base, dirs, files in os.walk(quarantine, topdown=False):
        if files:
            raise SafetyError('退避先に未登録ファイルを検出: ' + base)
        os.rmdir(base)
    after = shutil.disk_usage(audit.root).free
    result = dict(status='PRUNED', files_deleted=sum(r['kind'] == 'file' for r in rows),
                  source_logical_bytes=sum(r['bytes'] for r in rows),
                  source_allocated_bytes=sum(i['allocated_bytes'] for i in selected),
                  free_before=before, free_after=after, actual_free_change_bytes=after - before,
                  note='空き容量差はAPFS/他プロセスの影響を含む。論理削除量と一致する保証はない', absent=absent)
    write_json(receipt_dir / ('prune_receipt_' + receipt_id + '.json'), result)
    pending_receipt.unlink()
    return result


def restore_archive(root, manifest_path, restore_dir=None):
    manifest = verify_archive(manifest_path)
    destination = secure_directory(restore_dir or root, create=True)
    if destination != root and (destination == root / '.git' or root / '.git' in destination.parents):
        raise SafetyError('.gitへの復元は禁止です')
    tracked = set(os.fsdecode(n) for n in git(root, 'ls-files', '-z').split(b'\0') if n)
    for item in manifest['items']:
        name = item['path']
        if any(n == name or n.startswith(name + '/') for n in tracked):
            raise SafetyError('Git追跡対象へは復元しません: ' + name)
        # 先に全対象を検査する。既存ファイル・既存パッケージは一切上書きしない。
        if os.path.lexists(destination / name):
            raise SafetyError('復元先に既存の対象があります: ' + name)
        # 既存親にシンボリックリンクがあれば停止。
        current = destination
        for part in PurePosixPath(name).parts[:-1]:
            current /= part
            if current.is_symlink():
                raise SafetyError('復元先の親がシンボリックリンク: ' + str(current))
    attr_bytes = sum(len(v) * 3 // 4 for r in manifest['entries'] for v in r.get('xattrs', {}).values())
    before = ensure_space(destination, manifest['source_bytes'] + attr_bytes + len(manifest['entries']) * 10240 + 64 * MIB)
    stage = destination / ('.artifact_restore_' + uuid.uuid4().hex + '.partial')
    stage.mkdir(mode=0o700)
    # 全ファイルを新しい隔離領域へ展開し、SHA一致後に元の相対パスへ移す。
    verify_archive(manifest_path, stage)
    for row in manifest['entries']:
        if row['kind'] == 'file' and file_hash(stage, row['path'])[0] != row['sha256']:
            raise SafetyError('復元したファイルのSHAが不一致')
    for item in manifest['items']:
        name = item['path']
        with parent_fd(stage, name) as (src_fd, src_leaf), parent_fd(destination, name, create=True) as (dst_fd, dst_leaf):
            # ファイルはlinkの排他的作成、パッケージは予約ディレクトリ内へ個別に公開。
            row = next(r for r in manifest['entries'] if r['path'] == name)
            if row['kind'] == 'file':
                os.link(src_leaf, dst_leaf, src_dir_fd=src_fd, dst_dir_fd=dst_fd, follow_symlinks=False)
                os.unlink(src_leaf, dir_fd=src_fd)
            else:
                os.mkdir(dst_leaf, 0o700, dir_fd=dst_fd)
                for r in sorted((r for r in manifest['entries'] if r['path'].startswith(name + '/')), key=lambda r: r['path']):
                    with parent_fd(destination, r['path'], create=True) as (out_fd, leaf):
                        if r['kind'] == 'directory':
                            os.mkdir(leaf, 0o700, dir_fd=out_fd)
                        else:
                            with parent_fd(stage, r['path']) as (in_fd, in_leaf):
                                os.link(in_leaf, leaf, src_dir_fd=in_fd, dst_dir_fd=out_fd, follow_symlinks=False)
                                os.unlink(in_leaf, dir_fd=in_fd)
                # directory metadataは展開時と同様に元の値へ戻す。
                for r in sorted((r for r in manifest['entries'] if r['kind'] == 'directory' and (r['path'] == name or r['path'].startswith(name + '/'))), key=lambda r: len(r['path']), reverse=True):
                    with parent_fd(destination, r['path']) as (out_fd, leaf):
                        handle = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=out_fd)
                    try:
                        for attr, value in r.get('xattrs', {}).items():
                            set_xattr(handle, attr, base64.b64decode(value, validate=True))
                        os.fchmod(handle, r['mode'])
                        os.utime(handle, ns=(r['mtime_ns'], r['mtime_ns']))
                    finally:
                        os.close(handle)
    for base, dirs, files in os.walk(stage, topdown=False):
        if files:
            raise SafetyError('展開作業領域にファイルが残っています: ' + base)
        os.rmdir(base)
    after = shutil.disk_usage(destination).free
    return dict(status='RESTORED', destination=str(destination), files=sum(r['kind'] == 'file' for r in manifest['entries']),
                free_before=before, free_after=after, actual_free_change_bytes=after - before)


def human(size):
    return f'{size / GIB:10.3f} GiB ({size:,} bytes)'


def print_report(report, dry_run=False, phase=None, details=False, top=50):
    print('TimeStretchLab Artifact Cleanup\n')
    print('容量（論理サイズ / ファイル割当量。GiB=1,073,741,824 bytes）:')
    for name, row in {**report['repository'], **report['storage']}.items():
        print(f"  {name}: {human(row['bytes'])} / {row['allocated_bytes'] / GIB:.3f} GiB")
    for title, key in [('分類', 'classification'), ('Git状態', 'git_status'), ('種類', 'kinds'), ('Phase別順位', 'phases'), ('拡張子別順位', 'extensions')]:
        print('\n' + title + ':')
        for name, row in list(report[key].items())[:top]:
            print(f"  {name:24s} {human(row['bytes'])}  {row['files']:,}ファイル")
    print('\n上位ファイル:')
    for row in report['top_files'][:top]:
        print('  ' + human(row['bytes']) + '  ' + row['path'])
    print('\n上位ディレクトリ（親子の容量は重複・合算禁止）:')
    for row in report['top_directories'][:top]:
        print('  ' + human(row['bytes']) + '  ' + row['path'])
    saving = report['estimated_savings']
    print('\n圧縮候補の元サイズ: ' + human(saving['archive_source_bytes']))
    print('同一容量プール内で圧縮後に原本を削除する場合の標本推定: ' + human(saving['compression_sample_estimate_bytes']))
    print('再生成可能候補（アーカイブ必須）: ' + human(saving['prune_source_bytes']))
    print('今すぐ削除できる容量: 0 bytes（検証済みアーカイブ未指定）')
    print('空き容量: ' + human(report['disk']['free']))
    print('推定は実測削減量ではありません。APFSのクローン・スナップショット・他処理により空き増加は異なります。')
    print('読み取り専用監査では全成果物の既存SHAを再計算しません。圧縮/削除前に既存SHAとサイズを必ず照合します。')
    if dry_run or details:
        print('\n対象一覧（traceはパッケージ単位）:')
        for row in report['items']:
            if phase and row['phase'] != phase:
                continue
            if not details and row['classification'] not in ('ARCHIVE', 'PRUNE'):
                continue
            print(f"  {row['classification']:7s} {human(row['bytes'])} [{row['git_status']}] {row['path']}\n    {row['reason']}（経過{row['age_days']}日、参照元{len(row['references'])}件）")
    if report['errors']:
        print('\n監査未完了・変更系操作を停止:')
        for error in report['errors'][:30]:
            print('  ' + error)
        print(f"  合計{len(report['errors'])}件。詳細は--jsonで確認できます。")
    if report['missing_references']:
        print(f"\n期待SHAがある資料参照のうち現物が見つからない記録: {len(report['missing_references'])}件（詳細JSONを確認）")
    print('\n状態: ' + ('DRY RUN' if dry_run else 'REPORT') + ' / 成果物の変更なし')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    for mode in ('report', 'dry-run', 'archive', 'verify', 'prune', 'restore'):
        modes.add_argument('--' + mode, action='store_true')
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--phase')
    parser.add_argument('--path', action='append', default=[], help='圧縮範囲をリポジトリ相対パスで限定（複数指定可）')
    parser.add_argument('--archive-dir', type=Path)
    parser.add_argument('--archive-manifest', type=Path)
    parser.add_argument('--restore-dir', type=Path)
    parser.add_argument('--compression', choices=('auto', 'zstd', 'gzip'), default='auto')
    parser.add_argument('--include-regenerable', action='store_true', help='--archiveに再生成可能候補も明示的に追加')
    parser.add_argument('--older-than-days', type=float, default=7)
    parser.add_argument('--prune-after-days', type=float, default=30)
    parser.add_argument('--active-phase', action='append', default=[])
    parser.add_argument('--details', action='store_true')
    parser.add_argument('--top', type=int, default=50)
    parser.add_argument('--json', type=Path, help='明示した新規ファイルへ詳細JSONを保存（既存ファイルは上書きしない）')
    args = parser.parse_args(argv)
    try:
        if args.older_than_days < 0 or args.prune_after_days < args.older_than_days or not 1 <= args.top <= 50:
            raise SafetyError('日数/順位上限の指定が不正')
        if args.archive or args.prune or args.restore:
            if not args.confirm:
                raise SafetyError('変更系操作には--confirmが必要です')
        if args.archive and not (args.phase or args.path):
            raise SafetyError('--archiveには明示的な--phaseまたは--pathが必要です')
        if args.phase and not re.fullmatch(r'phase\d+[a-z]?(?:_[A-Za-z0-9]+)*', args.phase):
            raise SafetyError('--phaseの形式が不正です')
        if (args.prune or args.restore or args.verify) and not args.archive_manifest:
            raise SafetyError('--archive-manifestが必要です')
        if (args.prune or args.restore) and (args.phase or args.path or args.include_regenerable):
            raise SafetyError('削除・復元はmanifest全体が対象です。--phase/--pathによる部分指定はできません')
        if args.verify:
            m = verify_archive(args.archive_manifest)
            print(json.dumps(dict(status='VERIFIED', files=len(m['entries']), archive_sha256=m['archive_sha256']), ensure_ascii=False, indent=2))
        elif args.restore:
            with exclusive(ROOT):
                result = restore_archive(ROOT, args.archive_manifest, args.restore_dir)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.archive or args.prune:
            with exclusive(ROOT):
                audit = Audit(ROOT, args.older_than_days, args.prune_after_days, active_phases=args.active_phase)
                result = archive_phase(audit, args.phase, args.archive_dir, args.compression, args.include_regenerable, args.path) if args.archive else prune_archive(audit, args.archive_manifest)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            audit = Audit(ROOT, args.older_than_days, args.prune_after_days, active_phases=args.active_phase)
            report = audit.summary()
            print_report(report, args.dry_run, args.phase, args.details, args.top)
            if args.json:
                output = args.json.absolute()
                try:
                    output.relative_to(ROOT / '.git')
                except ValueError:
                    pass
                else:
                    raise SafetyError('.gitにはレポートを保存できません')
                # 追跡済みファイル/既存資料はxモードで上書き拒否。
                secure_directory(output.parent)
                write_json(output, report)
                print('詳細JSON: ' + str(output))
            if audit.errors:
                return 2
        return 0
    except (SafetyError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as error:
        print('安全のため処理を中止: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
