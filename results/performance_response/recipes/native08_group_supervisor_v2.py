#!/usr/bin/env python3
"""固定Python driverを新session/groupに閉じ込める有限監督v2。

旧audit-token API版とは別recipe。通常はwaitid(WNOWAIT)だけでleaderを待ち、
終了/取消boundaryにだけpsを使う。leaderを最後のwait4まで未回収に保ち、
PGID再利用を防ぐ。全active group memberが0と確認できなければ次job禁止。
bootstrapの制約はこのrepoの監査済みdriver専用で、敵対コード用sandboxではない。
"""
import errno
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = Path(__file__).with_name('native08_group_bootstrap_v2') / 'sitecustomize.py'
BOOTSTRAP_SHA = '5318efc2ab0988580fb355eb331561d902ac2f023607224349608f3aa85e7b26'
KEYS = ('TS_NATIVE08_GROUP_TOKEN', 'TS_NATIVE08_GROUP_LEADER', 'TS_NATIVE08_GROUP_PARENT',
        'TS_NATIVE08_GROUP_RECORDS', 'TS_NATIVE08_GROUP_ROOT')


class SigInfo(ctypes.Structure):
    # ローカルSDK sys/signal.hのarm64 siginfo_t（104bytes）。
    _fields_ = [(k, ctypes.c_int) for k in ('si_signo', 'si_errno', 'si_code', 'si_pid')]
    _fields_ += [('si_uid', ctypes.c_uint), ('si_status', ctypes.c_int), ('si_addr', ctypes.c_void_p),
                ('si_value', ctypes.c_uint64), ('si_band', ctypes.c_long), ('pad', ctypes.c_ulong * 7)]


class RetainedWait:
    def __init__(self):
        need(ctypes.sizeof(SigInfo) == 104 and ctypes.sizeof(ctypes.c_void_p) == 8, 'Darwin siginfo ABI不一致')
        self.lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        self.function = self.lib.waitid
        self.function.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(SigInfo), ctypes.c_int]
        self.function.restype = ctypes.c_int

    def observe(self, pid):
        result = SigInfo()
        ctypes.set_errno(0)
        # SDK: P_PID=1,WEXITED=4,WNOWAIT=32,WNOHANG=1。
        code = self.function(1, pid, ctypes.byref(result), 4 | 32 | 1)
        if code != 0:
            error = ctypes.get_errno()
            if error == errno.ECHILD:
                raise ChildProcessError(error, 'waitid: not a child')
            raise OSError(error, 'waitid(WNOWAIT) failed')
        return result if result.si_pid else None


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
    need(not temp.exists(), 'metadata一時出力が既存')
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def cpp_escape_audit(roots):
    """nativeはgroup/sessionを変えない。唯一のspawnはattr=nullptrを完全綴り確認。"""
    forbidden = re.compile(r'\b(setsid|setpgid|setpgrp|daemon|fork|vfork|forkpty|posix_spawnp|'
                           r'posix_spawnattr_setpgroup|posix_spawnattr_setflags|system|popen|syscall)\s*\(')
    supported = 'posix_spawn(&pid,command.front().c_str(),&actions,nullptr,arguments.data(),environ)'
    results = []
    for root in roots:
        root = Path(root).resolve()
        need((root / 'src').is_dir() and (root / 'tests').is_dir(), '完全native source rootが必要')
        files, spawns = [], []
        for folder in ('src', 'tests'):
            for path in sorted((root / folder).rglob('*')):
                if not path.is_file() or path.suffix not in ('.h', '.hpp', '.cpp', '.mm', '.c', '.m'):
                    continue
                body = path.read_text()
                need(forbidden.search(body) is None, '未対応native離脱/launcher: ' + str(path))
                for found in re.finditer(r'\bposix_spawn\s*\(', body):
                    statement = body[found.start():body.find(';', found.start())]
                    need(re.sub(r'\s+', '', statement) == supported, '未対応posix_spawn属性: ' + str(path))
                    spawns.append({'path': str(path), 'line': body[:found.start()].count('\n') + 1,
                                   'attributes_nullptr_group_inherited': True})
                files.append(identity(path))
        results.append({'root': str(root), 'files': files, 'spawn_sites': spawns,
                        'escape_calls_found': 0, 'scope': 'repo C/C++/ObjC source; system services are not descendants'})
    return results


def preflight(command, source_roots):
    need(sys.platform == 'darwin' and os.getuid() == os.geteuid() and os.getuid() != 0, '非root Darwinのみ')
    need(all(hasattr(os, key) for key in ('WNOHANG', 'wait4', 'getsid', 'getpgid')),
         'waitid/WNOWAIT等が不足。子起動前拒否')
    # 実子は作らず、WNOWAIT optionが受理されることを確認する。
    try:
        RetainedWait().observe(os.getpid())
        raise RuntimeError('selfがwaitableになった不正状態')
    except ChildProcessError:
        pass
    need(not any(os.environ.get(k) for k in (*KEYS, 'PYTHONPATH', 'PYTHONHOME', 'DYLD_INSERT_LIBRARIES', 'DYLD_LIBRARY_PATH')),
         'ambient監督/Python/loader overrideを拒否')
    need(isinstance(command, (list, tuple)) and len(command) >= 3
         and Path(command[0]).resolve() == Path(sys.executable).resolve()
         and command[1] == '-B' and not str(command[2]).startswith('-') and Path(command[2]).is_file(),
         '外側CLIは同一Python -B driver.py ...のみ')
    need(identity(BOOTSTRAP)['sha256'] == BOOTSTRAP_SHA, '固定bootstrap SHA不一致')
    return cpp_escape_audit(source_roots)


def process_table():
    # 正常wait loopからは呼ばない。開始/終了boundaryまたは取消のときだけ。
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,uid=,stat=,lstart=,comm='],
                            capture_output=True, text=True, timeout=10)
    need(result.returncode == 0 and not result.stderr.strip(), 'ps一覧の取得を確認できない')
    rows = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 10)
        need(len(fields) == 11 and all(x.isdigit() for x in fields[:4]), 'ps形式不明')
        rows.append({'pid': int(fields[0]), 'ppid': int(fields[1]), 'pgid': int(fields[2]),
                     'uid': int(fields[3]), 'state': fields[4], 'started': ' '.join(fields[5:10]), 'comm': fields[10]})
    return rows


def assert_managed_quiescent(base):
    base = str(Path(base).resolve()) + '/'
    found = [row for row in process_table() if row['uid'] == os.getuid()
             and row['pid'] != os.getpid() and row['state'][0] != 'Z' and row['comm'].startswith(base)]
    need(not found, 'B管理nativeが生存: ' + json.dumps(found))
    return {'method': 'boundary ps pid/ppid/pgid/uid/state/lstart/comm', 'B_managed_active': [],
            'scope': 'parent separately confirms additional CPU18/build completion'}


def execute(command, log, timeout, metadata=None, source_roots=None):
    """従来execute schema互換。正常direct child wait4だけでusageを回収する。"""
    need(math.isfinite(timeout) and timeout > 0, '有限timeoutが必要')
    source_roots = source_roots if source_roots is not None else [ROOT]
    audit = preflight(command, source_roots)
    retained = RetainedWait()
    log = Path(log).resolve()
    meta = Path(metadata).resolve() if metadata else log.with_suffix(log.suffix + '.SUPERVISOR_V2.json')
    records = meta.with_suffix('.events')
    private_bootstrap = meta.with_suffix('.bootstrap')
    need(log.is_relative_to(ROOT / 'build') and not log.exists() and not meta.exists() and not records.exists()
         and not private_bootstrap.exists(), '新規build出力のみ')
    records.mkdir()
    # 後続Pythonに-Bが無い場合も、sitecustomizeの未検証pycを生成/利用しない。
    # 原recipeをchmodせず、新B内へSHA固定copyを作り非rootに対して読取専用とする。
    private_bootstrap.mkdir()
    copied_bootstrap = private_bootstrap / 'sitecustomize.py'
    copied_bootstrap.write_bytes(BOOTSTRAP.read_bytes())
    copied_bootstrap.chmod(0o444)
    private_bootstrap.chmod(0o555)
    need(identity(copied_bootstrap)['sha256'] == BOOTSTRAP_SHA and not os.access(private_bootstrap, os.W_OK),
         '固定bootstrap copy/書込み禁止の確認失敗')
    marker = secrets.token_hex(32)
    token_sha = hashlib.sha256(marker.encode()).hexdigest()
    report = {'schema': 'native08-group-supervisor-v2', 'status': 'RUNNING', 'command': list(command),
              'bootstrap': identity(BOOTSTRAP), 'private_bootstrap': identity(copied_bootstrap),
              'private_bootstrap_dir_mode': '0555', 'private_bootstrap_file_mode': '0444', 'source_escape_audit': audit,
              'normal_wait': 'waitid(WNOWAIT|WNOHANG), 50ms; no periodic ps',
              'environment_delta': {KEYS[0]: {'sha256': token_sha}, KEYS[1]: '0→direct child PID',
                  KEYS[2]: str(os.getpid()), KEYS[3]: str(records), KEYS[4]: str(ROOT), 'PYTHONPATH': str(private_bootstrap)},
              'scope': 'group intervention means whole driver INCOMPLETE, never a callback/product-fault trial',
              'signals': [], 'group_boundaries': [], 'cleanup_confirmed': False}
    save(meta, report)
    child, usage, status, wait_end = None, None, None, None
    timed, interrupted, abnormal, error = False, False, None, None
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    def interrupted_handler(signum, frame):
        raise KeyboardInterrupt('supervisor signal ' + str(signum))

    for sig in previous_handlers:
        signal.signal(sig, interrupted_handler)
    begin = time.monotonic()
    try:
        with log.open('w') as stream:
            env = {**os.environ, KEYS[0]: marker, KEYS[1]: '0', KEYS[2]: str(os.getpid()),
                   KEYS[3]: str(records), KEYS[4]: str(ROOT), 'PYTHONPATH': str(private_bootstrap)}
            child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, env=env)
            leader = child.pid
            need(leader > 1 and leader != os.getpgrp() and os.getpgid(leader) == os.getsid(leader) == leader,
                 '一意な外側session/group leaderが不明')
            report['leader'] = leader
            while True:
                observed = retained.observe(leader)
                if observed is not None:
                    need(observed.si_pid == leader, '別childのwaitid結果')
                    wait_end = time.monotonic()
                    report['waitid_observed'] = {k: getattr(observed, k, None) for k in ('si_pid', 'si_uid', 'si_code', 'si_status')}
                    break
                if time.monotonic() - begin >= timeout:
                    timed, abnormal = True, 'TIMEOUT'
                    break
                time.sleep(.05)
    except KeyboardInterrupt as failure:
        interrupted, abnormal = True, 'INTERRUPTED: ' + str(failure)
    except BaseException as failure:
        abnormal = type(failure).__name__ + ': ' + str(failure)
    # この先は測定終了/取消boundary。追加signalで回収処理を飛ばさない。
    for sig in previous_handlers:
        signal.signal(sig, signal.SIG_IGN)
    try:
        def group():
            need(child is not None and child.returncode is None, 'leaderを先にreapしてはいけない')
            rows = [row for row in process_table() if row['pgid'] == child.pid]
            need(all(row['uid'] == os.getuid() for row in rows), '異UID group memberを検出。signal拒否')
            report['group_boundaries'].append({'at_s': time.monotonic() - begin, 'members': rows})
            return [row for row in rows if not row['state'].startswith('Z')]

        def send(sig):
            # leaderは最後のwait4まで未回収なので、このPGIDを他試行が再利用できない。
            active = group()
            if active:
                need(child.pid != os.getpgrp(), '自分自身のgroupをsignalしてはいけない')
                os.killpg(child.pid, sig)
                report['signals'].append({'pgid': child.pid, 'signal': signal.Signals(sig).name,
                                           'at_s': time.monotonic() - begin, 'member_PIDs': [row['pid'] for row in active]})

        events = [json.loads(path.read_text()) for path in sorted(records.glob('*.json'))]
        bootstrap_ok = (child is not None and any(e.get('kind') == 'INIT' and e.get('pid') == child.pid
                        and e.get('direct_driver') is True for e in events)
                        and all(e.get('leader') == child.pid and e.get('pgid') == child.pid and e.get('sid') == child.pid
                                and e.get('uid') == os.getuid() and e.get('bootstrap_sha256') == BOOTSTRAP_SHA
                                and e.get('token_sha256') == token_sha for e in events))
        inner_abort = any(e.get('kind') in ('ABORT', 'REFUSED_ESCAPE') for e in events)
        if not bootstrap_ok:
            abnormal = abnormal or 'BOOTSTRAP_HANDSHAKE_INCOMPLETE'
        if inner_abort:
            abnormal = abnormal or 'INNER_GROUP_ABORT_OR_UNSUPPORTED_ESCAPE'
        active = group() if child is not None else []
        if active and abnormal is None:
            abnormal = 'ACTIVE_DESCENDANTS_AFTER_LEADER_EXIT'
        if child is not None and abnormal is not None and active:
            send(signal.SIGSTOP)
            freeze_deadline = time.monotonic() + 3
            while time.monotonic() < freeze_deadline:
                active = group()
                if all(row['state'].startswith(('T', 'Z')) for row in active):
                    break
                time.sleep(.05)
            need(all(row['state'].startswith(('T', 'Z')) for row in active), 'group全停止を確認できない')
            send(signal.SIGTERM)
            send(signal.SIGCONT)
            deadline = time.monotonic() + 3
            while group() and time.monotonic() < deadline:
                time.sleep(.05)
            if group():
                send(signal.SIGKILL)
                deadline = time.monotonic() + 3
                while group() and time.monotonic() < deadline:
                    time.sleep(.05)
        active = group() if child is not None else []
        need(not active, 'active子孫0を確認できない。leaderをreapせず後続禁止')
        if child is not None:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            need(pid == child.pid and usage is not None, 'direct childの最後のwait4回収が未確認')
            child.returncode = os.waitstatus_to_exitcode(status)
        need(identity(BOOTSTRAP)['sha256'] == BOOTSTRAP_SHA, 'bootstrapが実行中に変更された')
        need(identity(copied_bootstrap)['sha256'] == BOOTSTRAP_SHA
             and not (private_bootstrap / '__pycache__').exists(), '固定bootstrap copy/pyc状態が変化した')
        events = [json.loads(path.read_text()) for path in sorted(records.glob('*.json'))]
        need(all(e.get('bootstrap_sha256') == BOOTSTRAP_SHA and e.get('token_sha256') == token_sha
                 and e.get('leader') == child.pid and e.get('pgid') == child.pid and e.get('sid') == child.pid
                 and e.get('uid') == os.getuid() for e in events),
             'bootstrap event identityが不一致')
        inner_abort = any(e.get('kind') in ('ABORT', 'REFUSED_ESCAPE') for e in events)
        if inner_abort:
            abnormal = abnormal or 'INNER_GROUP_ABORT_OR_UNSUPPORTED_ESCAPE'
        report.update(cleanup_confirmed=child is not None and usage is not None, direct_child_reaped=usage is not None,
                      all_active_group_members_zero=True, bootstrap_handshake_valid=bootstrap_ok,
                      inner_abort=inner_abort, bootstrap_events=[identity(path) for path in sorted(records.glob('*.json'))])
    except BaseException as failure:
        error = type(failure).__name__ + ': ' + str(failure)
        abnormal = abnormal or error
        # 同一UID/保持中groupの確認ができる範囲だけbest-effort KILLする。
        try:
            if child is not None and child.returncode is None:
                send(signal.SIGKILL)
                report['best_effort_KILL_sent'] = True
        except BaseException as secondary:
            report['best_effort_error'] = type(secondary).__name__ + ': ' + str(secondary)
        report.update(cleanup_confirmed=False, error=error, direct_child_reaped=usage is not None)
    finally:
        report.update(status='NORMAL_EXIT' if abnormal is None else 'INCOMPLETE', abnormal_reason=abnormal,
                      timeout=timed, interrupted=interrupted, returncode=child.returncode if child is not None else None,
                      next_job_allowed=abnormal is None and report['cleanup_confirmed'] is True,
                      all_intervened_trials_are_nonPASS=abnormal is not None)
        save(meta, report)
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return {'returncode': child.returncode if child is not None else None, 'timeout': timed, 'interrupted': interrupted,
            'wall_s': (wait_end if wait_end is not None else time.monotonic()) - begin,
            'process_user_s': usage.ru_utime if usage else None, 'process_system_s': usage.ru_stime if usage else None,
            'whole_process_cpu_s': usage.ru_utime + usage.ru_stime if usage else None,
            'max_rss_native_units': usage.ru_maxrss if usage else None, 'max_rss_units': 'bytes on macOS',
            'voluntary_context_switches': usage.ru_nvcsw if usage else None,
            'involuntary_context_switches': usage.ru_nivcsw if usage else None,
            'log': identity(log) if log.is_file() else None, 'supervisor': identity(meta),
            'cleanup_confirmed': report['cleanup_confirmed'], 'next_job_allowed': report['next_job_allowed'],
            'abnormal_reason': abnormal}
