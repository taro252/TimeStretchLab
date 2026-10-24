#!/usr/bin/env python3
"""native08 driverの有限監督。正常時は従来のdirect-child wait4のみ。

取消時だけ同UIDのlibproc一覧とKERN_PROCARGS2を調べ、継承した一意tokenまたは
確認済み親子関係で自分の子孫を捕捉する。開始sec/usec+UIDを照合し、信号は
カーネルaudit_token版APIだけを使う。os.kill/killpgへのfallbackはしない。
SIGSTOP/TERM/CONT/KILLは異常終了の回収専用で、音声callback試験条件ではない。
権限/identity/不在が未確認ならcleanup_confirmed=falseで次jobを禁止する。
"""
import ctypes
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
TOKEN_KEY = 'TS_NATIVE08_SUPERVISOR_TOKEN'
MAX_PROCESSES = 1024


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def identity(path):
    path = Path(path).resolve()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': digest}


def save(path, value):
    path = Path(path)
    temp = path.with_name('.' + path.name + '.tmp')
    need(not temp.exists(), '監督metadata一時pathが既存')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


class BsdInfo(ctypes.Structure):
    # SDK sys/proc_info.h: proc_bsdinfo, MAXCOMLEN=16, PROC_PIDTBSDINFO=3.
    _fields_ = ([(name, ctypes.c_uint32) for name in
                 ('flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid',
                  'rgid', 'svuid', 'svgid', 'reserved')]
                + [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
                + [(name, ctypes.c_uint32) for name in ('nfiles', 'pgid', 'pjobc', 'tdev', 'tpgid')]
                + [('nice', ctypes.c_int32), ('start_sec', ctypes.c_uint64), ('start_usec', ctypes.c_uint64)])


class AuditToken(ctypes.Structure):
    _fields_ = [('val', ctypes.c_uint32 * 8)]


class DarwinProcesses:
    """公開SDK ABI。動作確認は別の音声なしdummyで行う。"""
    def __init__(self):
        need(sys.platform == 'darwin' and ctypes.sizeof(BsdInfo) == 136, 'Darwin proc_bsdinfo ABIが必要')
        self.uid = os.getuid()
        need(self.uid == os.geteuid() and self.uid != 0, '非rootかつ実/実効UID一致が必要')
        self.proc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self.system = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        self.bsm = ctypes.CDLL('/usr/lib/libbsm.dylib', use_errno=True)
        self.proc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        self.proc.proc_pidinfo.restype = ctypes.c_int
        self.proc.proc_listpids.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_int]
        self.proc.proc_listpids.restype = ctypes.c_int
        self.proc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        self.proc.proc_pidpath.restype = ctypes.c_int
        self.proc.proc_signal_with_audittoken.argtypes = [AuditToken, ctypes.c_int]
        self.proc.proc_signal_with_audittoken.restype = ctypes.c_int
        self.system.task_name_for_pid.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
        self.system.task_name_for_pid.restype = ctypes.c_int
        self.system.task_info.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self.system.task_info.restype = ctypes.c_int
        self.system.mach_port_deallocate.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        self.system.mach_port_deallocate.restype = ctypes.c_int
        self.system.sysctl.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
        self.system.sysctl.restype = ctypes.c_int
        for name in ('audit_token_to_euid', 'audit_token_to_ruid', 'audit_token_to_pid', 'audit_token_to_pidversion'):
            function = getattr(self.bsm, name)
            function.argtypes = [AuditToken]
            function.restype = ctypes.c_int if name.endswith(('pid', 'pidversion')) else ctypes.c_uint32
        self.self_port = ctypes.c_uint32.in_dll(self.system, 'mach_task_self_').value

    def info(self, pid):
        value = BsdInfo()
        ctypes.set_errno(0)
        count = self.proc.proc_pidinfo(pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value))
        if count == 0 and ctypes.get_errno() in (0, errno.ESRCH, errno.ENOENT):
            return None
        need(count == ctypes.sizeof(value), 'proc_pidinfo未確認: ' + str((pid, count, ctypes.get_errno())))
        return {k: int(getattr(value, k)) for k in
                ('pid', 'ppid', 'uid', 'ruid', 'pgid', 'status', 'start_sec', 'start_usec')}

    @staticmethod
    def same(first, second):
        return first is not None and second is not None and all(first[k] == second[k] for k in
                ('pid', 'uid', 'ruid', 'start_sec', 'start_usec'))

    def token(self, pid):
        port, count, token = ctypes.c_uint32(), ctypes.c_uint32(8), AuditToken()
        code = self.system.task_name_for_pid(self.self_port, pid, ctypes.byref(port))
        need(code == 0 and port.value != 0, 'task_name_for_pid未確認: ' + str((pid, code)))
        try:
            code = self.system.task_info(port.value, 15, ctypes.byref(token), ctypes.byref(count))
            need(code == 0 and count.value == 8, 'TASK_AUDIT_TOKEN未確認: ' + str((pid, code)))
        finally:
            self.system.mach_port_deallocate(self.self_port, port.value)
        need(self.bsm.audit_token_to_pid(token) == pid
             and self.bsm.audit_token_to_euid(token) == self.bsm.audit_token_to_ruid(token) == self.uid,
             'audit token PID/UID不一致。他ユーザーへ信号しない')
        return token

    def capture(self, pid):
        before = self.info(pid)
        if before is None:
            return None
        need(before['uid'] == before['ruid'] == self.uid and pid > 1 and pid != os.getpid(),
             '自分の子孫だけが捕捉対象')
        if before['status'] == 5:
            return {**before, 'audit_token': None, 'pidversion': None}
        token = self.token(pid)
        need(self.same(before, self.info(pid)), '捕捉中のPID identity変更')
        return {**before, 'audit_token': list(token.val),
                'pidversion': self.bsm.audit_token_to_pidversion(token)}

    def send(self, record, sig, events):
        current = self.info(record['pid'])
        if current is None:
            return False
        need(self.same(record, current), 'PID再利用を検出。新processへ信号しない')
        if current['status'] == 5:
            return False  # zombieへ信号せず親のreap/不在を待つ。
        need(record['audit_token'] is not None, '生存processのaudit tokenなし')
        token = AuditToken((ctypes.c_uint32 * 8)(*record['audit_token']))
        ctypes.set_errno(0)
        code = self.proc.proc_signal_with_audittoken(token, sig)
        error = ctypes.get_errno()
        events.append({'pid': record['pid'], 'start_sec': record['start_sec'],
                       'start_usec': record['start_usec'], 'signal': signal.Signals(sig).name,
                       'returncode': code, 'errno': error})
        if code != 0:
            # ESRCHは元identityが消えた場合だけ許す。再利用PIDは未回収として扱う。
            need(self.info(record['pid']) is None,
                 'audit-token signal未確認: ' + str((record['pid'], sig, code, error)))
        return code == 0

    def own_pids(self):
        # PROC_UID_ONLY=4。非対象UIDの引数/環境は読まない。
        size = self.proc.proc_listpids(4, self.uid, None, 0)
        need(0 < size < 800000, 'proc UID一覧size不明')
        for _ in range(3):
            capacity = size + 4096
            data = ctypes.create_string_buffer(capacity)
            count = self.proc.proc_listpids(4, self.uid, data, capacity)
            need(0 <= count <= capacity and count % 4 == 0, 'proc UID一覧不明')
            if count < capacity:
                result = [x for x in (ctypes.c_int * (count // 4)).from_buffer_copy(data.raw[:count]) if x > 1]
                need(len(result) <= 8192, '同UID process一覧が有限上限8192を超えた')
                return result
            size = capacity * 2
        raise RuntimeError('proc UID一覧が安定しない')

    def has_marker(self, pid, marker):
        # CTL_KERN=1/KERN_PROCARGS2=49。環境全体は保存しない。
        mib = (ctypes.c_int * 3)(1, 49, pid)
        size = ctypes.c_size_t()
        ctypes.set_errno(0)
        code = self.system.sysctl(mib, 3, None, ctypes.byref(size), None, 0)
        if code != 0:
            remaining = self.info(pid)
            if remaining is None or remaining['status'] == 5:
                return False
        need(code == 0 and 4 < size.value <= 2 * 1024 * 1024, 'process引数size未確認')
        data = ctypes.create_string_buffer(size.value)
        code = self.system.sysctl(mib, 3, data, ctypes.byref(size), None, 0)
        if code != 0:
            remaining = self.info(pid)
            if remaining is None or remaining['status'] == 5:
                return False
        need(code == 0, 'process環境が読めず所有を否定できない')
        # 完全なNUL区切りenvエントリだけを照合。ログ/引数の部分一致は使わない。
        return (TOKEN_KEY + '=' + marker).encode() in data.raw[:size.value].split(b'\0')

    def executable(self, pid):
        data = ctypes.create_string_buffer(4096)
        count = self.proc.proc_pidpath(pid, data, len(data))
        if count > 0:
            return data.value.decode(errors='surrogateescape')
        current = self.info(pid)
        need(current is None or current['status'] == 5, '生存processの実行pathが未確認: ' + str(pid))
        return None


def assert_managed_quiescent(base):
    """jobの外側だけでB管理実行体を検査。一般アプリや他UIDは対象外。"""
    backend, conflicts = DarwinProcesses(), []
    base = Path(base).resolve()
    for pid in backend.own_pids():
        if pid == os.getpid():
            continue
        path = backend.executable(pid)
        if path and Path(path).resolve().is_relative_to(base):
            info = backend.info(pid)
            if info is not None:
                conflicts.append({**info, 'executable': path})
    need(not conflicts, 'B管理実行体が生存。排他未確認: ' + json.dumps(conflicts))
    return {'method': 'libproc UID-only snapshot + executable path', 'conflicts': [],
            'scope': 'B-managed executable only; parent separately confirms CPU18/build completion'}


def execute(command, log, timeout, metadata=None):
    """run_pairs.executeと互換の戻り値。cleanup未確認ならnext_job_allowed=false。"""
    need(math.isfinite(timeout) and timeout > 0, '有限timeoutが必要')
    backend = DarwinProcesses()
    # 権限/APIを子起動前にself signal0で検査。安全でないos.kill fallbackはない。
    probe = backend.token(os.getpid())
    need(backend.proc.proc_signal_with_audittoken(probe, 0) == 0, 'audit-token signal API未使用可')
    log = Path(log)
    meta = Path(metadata) if metadata else log.with_suffix(log.suffix + '.SUPERVISOR.json')
    need(not meta.exists() and not log.exists(), '監督出力は新規のみ')
    marker = secrets.token_hex(32)
    report = {'schema': 'native08-driver-supervisor-v1', 'status': 'RUNNING', 'command': list(command),
              'normal_path': 'direct child wait4 WNOHANG/50ms only; no periodic process enumeration',
              'marker_sha256': hashlib.sha256(marker.encode()).hexdigest(), 'events': [], 'captured': [],
              'cleanup_confirmed': None, 'all_signals_are_abnormal_cleanup_only': True}
    save(meta, report)
    begin, usage, status, child, root = time.monotonic(), None, None, None, None
    wait_end = None
    timed_out, interrupted, abnormal = False, False, None
    try:
        with log.open('w') as stream:
            child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True,
                                     env={**os.environ, TOKEN_KEY: marker})
            # 一度だけ直接childの開始identityを記録。通常中のtree走査は行わない。
            root = backend.capture(child.pid)
            report['root'] = root
            while True:
                pid, status, usage = os.wait4(child.pid, os.WNOHANG)
                if pid:
                    wait_end = time.monotonic()
                    break
                if time.monotonic() - begin >= timeout:
                    timed_out = True
                    abnormal = 'TIMEOUT'
                    break
                time.sleep(.05)
    except KeyboardInterrupt as error:
        interrupted, abnormal = True, 'INTERRUPTED: ' + str(error)
    except BaseException as error:
        abnormal = type(error).__name__ + ': ' + str(error)
    if abnormal is not None:
        report.update(status='INCOMPLETE', abnormal_reason=abnormal)
        old_handlers = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            tracked, errors = {}, []
            if child is not None and root is not None:
                tracked[child.pid] = {**root, 'ownership': 'direct-child', 'depth': 0}
            else:
                errors.append('直接childの開始identityなし。完全回収を認定しない')
            root_time = (root['start_sec'], root['start_usec']) if root else (0, 0)

            def scan(stop_new=True):
                table, scan_deadline = {}, time.monotonic() + 2
                for pid in backend.own_pids():
                    need(time.monotonic() < scan_deadline, '取消process一覧の2秒上限')
                    if pid == os.getpid():
                        continue
                    info = backend.info(pid)
                    if info is not None and info['uid'] == info['ruid'] == backend.uid:
                        table[pid] = info
                # 任意session/reparent済みも継承markerで所有を証明する。
                discovered = set()
                for pid, info in table.items():
                    need(time.monotonic() < scan_deadline, '取消所有者照合の2秒上限')
                    if pid in tracked or (info['start_sec'], info['start_usec']) < root_time:
                        continue
                    parent = tracked.get(info['ppid'])
                    lineage = parent is not None and backend.same(parent, table.get(info['ppid']))
                    marked = backend.has_marker(pid, marker) if info['status'] != 5 else False
                    if lineage or marked:
                        need(len(tracked) < MAX_PROCESSES, '子孫上限を越えた。監査未完了')
                        item = backend.capture(pid)
                        if item is not None:
                            tracked[pid] = {**item, 'ownership': 'parent-identity' if lineage else 'inherited-unique-marker',
                                            'depth': parent['depth'] + 1 if lineage else 1}
                            discovered.add(pid)
                            if stop_new:
                                backend.send(tracked[pid], signal.SIGSTOP, report['events'])
                return table, discovered

            # rootを先に停止し、新forkを抑えながら有限回treeを固定する。
            if root is not None:
                backend.send(tracked[child.pid], signal.SIGSTOP, report['events'])
            stable, frozen, freeze_deadline = 0, False, time.monotonic() + 5
            for _ in range(40):
                table, added = scan()
                live = [item for item in tracked.values() if backend.same(item, table.get(item['pid']))]
                stopped = all(table[item['pid']]['status'] in (4, 5) for item in live)
                stable = stable + 1 if not added and stopped else 0
                if stable >= 2:
                    frozen = True
                    break
                if time.monotonic() >= freeze_deadline:
                    break
                time.sleep(.05)
            if not frozen:
                errors.append('新fork停止/tree安定を有限時間内に確認できない')
            # 子からTERM→CONT、最後に親。親のwait/join cleanupに猶予を残す。
            ordered = lambda: sorted(tracked.values(), key=lambda item: (-item['depth'], item['pid']))
            for item in ordered():
                backend.send(item, signal.SIGTERM, report['events'])
                backend.send(item, signal.SIGCONT, report['events'])
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                table, added = scan()
                for pid in added:
                    backend.send(tracked[pid], signal.SIGTERM, report['events'])
                    backend.send(tracked[pid], signal.SIGCONT, report['events'])
                if child is not None and usage is None:
                    pid, value, used = os.wait4(child.pid, os.WNOHANG)
                    if pid:
                        status, usage = value, used
                if all(backend.info(pid) is None for pid in tracked):
                    break
                time.sleep(.05)
            # 残存は再び停止して収集し、identityを毎回確認して個別KILLする。
            kill_deadline = time.monotonic() + 5
            while time.monotonic() < kill_deadline:
                table, _ = scan()
                for item in ordered():
                    backend.send(item, signal.SIGSTOP, report['events'])
                scan()
                for item in ordered():
                    backend.send(item, signal.SIGKILL, report['events'])
                if child is not None and usage is None:
                    pid, value, used = os.wait4(child.pid, os.WNOHANG)
                    if pid:
                        status, usage = value, used
                if all(backend.info(pid) is None for pid in tracked):
                    break
                time.sleep(.05)
            final_table, added = scan()
            remaining = [item for item in tracked.values() if backend.info(item['pid']) is not None]
            report.update(captured=list(tracked.values()), errors=errors, remaining=remaining,
                          marker_or_descendant_final_new_pids=sorted(added), freeze_confirmed=frozen,
                          direct_child_reaped=usage is not None,
                          cleanup_confirmed=bool(root) and frozen and not errors and usage is not None and not remaining and not added)
        except BaseException as error:
            report.update(cleanup_confirmed=False, cleanup_error=type(error).__name__ + ': ' + str(error))
            if 'tracked' in locals():
                report['captured'] = list(tracked.values())
                # 一部の列挙/環境読取が失敗しても、既に所有identityが確定したprocessは
                # 停止したまま残さず有限のbest-effort回収を行う。未捕捉分は認定しない。
                failures = []
                for item in sorted(tracked.values(), key=lambda item: -item['depth']):
                    try:
                        backend.send(item, signal.SIGKILL, report['events'])
                    except BaseException as failure:
                        failures.append(type(failure).__name__ + ': ' + str(failure))
                deadline = time.monotonic() + 3
                while child is not None and usage is None and time.monotonic() < deadline:
                    try:
                        pid, value, used = os.wait4(child.pid, os.WNOHANG)
                        if pid:
                            status, usage = value, used
                            break
                    except ChildProcessError as failure:
                        failures.append(str(failure))
                        break
                    time.sleep(.05)
                report.update(best_effort_errors=failures, direct_child_reaped=usage is not None)
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
    else:
        report.update(status='NORMAL_EXIT', direct_child_reaped=True, cleanup_confirmed=True,
                      cleanup_not_needed=True)
    if child is not None and status is not None and usage is not None:
        child.returncode = os.waitstatus_to_exitcode(status)
    returncode = child.returncode if child is not None else None
    report.update(returncode=returncode, timeout=timed_out, interrupted=interrupted,
                  next_job_allowed=abnormal is None and usage is not None,
                  all_cancelled_executions_are_nonPASS=abnormal is not None)
    save(meta, report)
    return {'returncode': returncode, 'timeout': timed_out, 'interrupted': interrupted,
            'wall_s': (wait_end if wait_end is not None else time.monotonic()) - begin,
            'process_user_s': usage.ru_utime if usage else None,
            'process_system_s': usage.ru_stime if usage else None,
            'whole_process_cpu_s': usage.ru_utime + usage.ru_stime if usage else None,
            'max_rss_native_units': usage.ru_maxrss if usage else None,
            'max_rss_units': 'bytes on macOS; KiB on Linux',
            'voluntary_context_switches': usage.ru_nvcsw if usage else None,
            'involuntary_context_switches': usage.ru_nivcsw if usage else None,
            'log': identity(log) if log.is_file() else None, 'supervisor': identity(meta),
            'cleanup_confirmed': report['cleanup_confirmed'], 'next_job_allowed': report['next_job_allowed'],
            'abnormal_reason': abnormal}
