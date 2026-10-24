"""固定recipe専用の同一group制約。一般のPython sandboxではない。

通常argv/native/DSPは変更しない。離脱要求を抑制し、内側killpgは所有中の
同一group childに限って試行全体の異常中断へ変換する。起動失敗時はsiteの
『例外を表示して継続』を許さず、target scriptより前にexit78する。
"""
import sys
sys.dont_write_bytecode = True
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import time
import weakref

TOKEN = 'TS_NATIVE08_GROUP_TOKEN'
LEADER = 'TS_NATIVE08_GROUP_LEADER'
PARENT = 'TS_NATIVE08_GROUP_PARENT'
RECORDS = 'TS_NATIVE08_GROUP_RECORDS'
ROOTKEY = 'TS_NATIVE08_GROUP_ROOT'
_killpg = os.killpg
_getpgid = os.getpgid
_getsid = os.getsid
_Popen = subprocess.Popen
_wait4 = os.wait4
_waitpid = os.waitpid
_spawn = {name: getattr(os, name) for name in ('posix_spawn', 'posix_spawnp') if hasattr(os, name)}
_owned = {}
_sequence = 0


def need(ok, message):
    if not ok:
        raise RuntimeError('native08 group bootstrap: ' + message)


def event(kind, **fields):
    global _sequence
    _sequence += 1
    path = _records / (kind + '_' + str(os.getpid()) + '_' + str(time.monotonic_ns()) + '_' + str(_sequence) + '.json')
    value = {'kind': kind, 'pid': os.getpid(), 'ppid': os.getppid(), 'uid': os.getuid(),
             'leader': _leader, 'pgid': os.getpgrp(), 'sid': _getsid(0),
             'token_sha256': _token_sha, 'bootstrap_sha256': _bootstrap_sha, **fields}
    with path.open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
    return path


def environment(original=None):
    result = dict(os.environ if original is None else original)
    need(all(isinstance(k, str) and isinstance(v, str) for k, v in result.items()), 'bytes/nonstring env未対応')
    expected = {TOKEN: _token, LEADER: str(_leader), PARENT: _parent, RECORDS: str(_records),
                ROOTKEY: str(_root), 'PYTHONPATH': str(_bootstrap_dir)}
    for key, value in expected.items():
        need(key not in result or result[key] == value, '監督envの書換えは未対応: ' + key)
        result[key] = value
    return result


def validate_command(command, env):
    need(isinstance(command, (list, tuple)) and command, 'shell/string argvは未対応')
    argv = [os.fspath(x) for x in command]
    need(all(isinstance(x, str) for x in argv), 'bytes argvは未対応')
    if Path(argv[0]).name == 'env':
        need(str(Path(argv[0]).resolve()) == '/usr/bin/env', '未対応env wrapper')
        index = 1
        while index < len(argv) and '=' in argv[index] and not argv[index].startswith('-'):
            key, value = argv[index].split('=', 1)
            need(key not in (TOKEN, LEADER, PARENT, RECORDS, ROOTKEY, 'PYTHONPATH') or env[key] == value,
                 'env wrapperが監督設定を変える')
            index += 1
        need(index < len(argv) and not argv[index].startswith('-'), 'env optionは未対応')
        validate_command(argv[index:], env)
        return
    executable = shutil.which(argv[0], path=env.get('PATH')) if '/' not in argv[0] else argv[0]
    need(executable is not None, '実行体の解決失敗')
    executable = Path(executable).resolve()
    mode = executable.stat().st_mode
    need(stat.S_ISREG(mode) and not mode & (stat.S_ISUID | stat.S_ISGID), 'setuid/setgid/非fileを拒否')
    name = executable.name.lower()
    if 'python' in name or executable == Path(sys.executable).resolve():
        need(executable == Path(sys.executable).resolve(), '異なるPythonは未対応')
        for arg in argv[1:]:
            if arg in ('-c', '-m') or not arg.startswith('-'):
                break
            need(not any(flag in arg[1:] for flag in ('S', 'I', 'E')), '-S/-I/-E bootstrap回避を拒否')
    else:
        need(executable.suffix != '.py' and name not in
             ('sh', 'bash', 'zsh', 'dash', 'fish', 'csh', 'tcsh', 'open', 'launchctl', 'osascript',
              'sudo', 'su', 'setsid', 'daemon', 'nohup'), '未対応launcher/離脱経路を拒否')
        allowed = (_root / 'build', Path('/usr/bin'), Path('/bin'), Path('/usr/sbin'), Path('/sbin'),
                   Path('/Library/Developer'), Path('/Applications/Xcode.app/Contents/Developer'))
        need(any(executable.is_relative_to(path) for path in allowed), '未監査native実行pathを拒否')


def remember(pid, process=None):
    need(_getpgid(pid) == _leader and _getsid(pid) == _leader, 'childが監督group/sessionから離脱した')
    _owned[pid] = {'process': weakref.ref(process) if process is not None else None}


def collected(pid):
    if pid > 0:
        _owned.pop(pid, None)


def wait4(pid, options):
    result = _wait4(pid, options)
    collected(result[0])
    return result


def waitpid(pid, options):
    result = _waitpid(pid, options)
    collected(result[0])
    return result


class ConfinedPopen(_Popen):
    def __init__(self, args, *positional, **kwargs):
        need(not positional and not kwargs.get('shell') and kwargs.get('executable') is None,
             'positional Popen/shell/executable overrideは未対応')
        need(kwargs.get('preexec_fn') is None and all(kwargs.get(k) is None for k in
             ('user', 'group', 'extra_groups')), 'preexec/credentials変更を拒否')
        env = environment(kwargs.get('env'))
        validate_command(args, env)
        requested = {'start_new_session': kwargs.get('start_new_session', False),
                     'process_group': kwargs.get('process_group')}
        if requested['start_new_session'] or requested['process_group'] not in (None, -1, _leader):
            event('SUPPRESSED_POPEN', requested=requested)
        kwargs['start_new_session'] = False
        if 'process_group' in kwargs:
            kwargs['process_group'] = -1
        kwargs['env'] = env
        super().__init__(args, **kwargs)
        remember(self.pid, self)


def spawn_wrapper(function):
    def spawn(path, argv, env, **kwargs):
        actual = environment(env)
        validate_command(argv, actual)
        need(os.fspath(path) == os.fspath(argv[0]), 'posix_spawn path/argv0 overrideは未対応')
        need(not kwargs.get('resetids'), 'posix_spawn credentials変更を拒否')
        requested = {'setsid': kwargs.get('setsid', False), 'setpgroup': kwargs.get('setpgroup')}
        if requested['setsid'] or requested['setpgroup'] not in (None, _leader):
            event('SUPPRESSED_SPAWN', requested=requested)
        kwargs['setsid'] = False
        kwargs['setpgroup'] = _leader
        pid = function(path, argv, actual, **kwargs)
        remember(pid)
        return pid
    return spawn


def reject_escape(*args, **kwargs):
    event('REFUSED_ESCAPE', operation='direct session/group/fork/exec/credentials mutation')
    raise RuntimeError('native08: direct離脱/直接fork/exec/credentials操作は未対応')


def killpg(pgid, sig):
    need(isinstance(pgid, int) and isinstance(sig, int), 'killpg整数だけを許可')
    need(os.getpgrp() == _leader and _getsid(0) == _leader, '自分のgroupが変化した')
    if pgid not in (0, _leader):
        owned = _owned.get(pgid)
        need(owned is not None, 'killpg対象は自分の未回収childだけ')
        reference = owned['process']
        process = reference() if reference is not None else None
        need(reference is None or (process is not None and process.returncode is None), '回収済みchild PIDを拒否')
        need(_getpgid(pgid) == _leader and _getsid(pgid) == _leader, '対象childが別group/session')
    if sig != 0:
        event('ABORT', requested_target=pgid, requested_signal=int(sig),
              scope='inner killpg converted to whole-driver abnormal interruption; not a product test verdict')
    return _killpg(_leader, sig)


def install():
    global _token, _token_sha, _leader, _parent, _records, _root, _bootstrap_dir, _bootstrap_sha
    _token = os.environ.get(TOKEN, '')
    need(len(_token) == 64 and all(c in '0123456789abcdef' for c in _token), '監督token不明')
    need(os.getuid() == os.geteuid() and os.getgid() == os.getegid() and os.getuid() != 0, '非root同一credentialsが必要')
    _parent = os.environ.get(PARENT, '')
    _leader = int(os.environ.get(LEADER, '-1'))
    if _leader == 0:
        need(_parent.isdigit() and os.getppid() == int(_parent), '外側direct-childだけがleaderを設定できる')
        _leader = os.getpid()
    need(_leader > 1 and os.getpgrp() == _leader and _getsid(0) == _leader, '同一session/groupが必要')
    _root = Path(os.environ[ROOTKEY]).resolve()
    _records = Path(os.environ[RECORDS]).resolve()
    need(_records.is_dir() and _records.is_relative_to(_root / 'build'), '新規build内の監督recordが必要')
    _bootstrap_dir = Path(__file__).resolve().parent
    need(os.environ.get('PYTHONPATH') == str(_bootstrap_dir), '固定bootstrap pathだけを許可')
    _bootstrap_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    _token_sha = hashlib.sha256(_token.encode()).hexdigest()
    os.environ[LEADER] = str(_leader)
    subprocess.Popen = ConfinedPopen
    os.wait4, os.waitpid, os.killpg = wait4, waitpid, killpg
    for name, function in _spawn.items():
        setattr(os, name, spawn_wrapper(function))
    for name in ('setsid', 'setpgid', 'setpgrp', 'fork', 'forkpty', 'execv', 'execve', 'execvp', 'execvpe',
                 'execl', 'execle', 'execlp', 'execlpe', 'setuid', 'seteuid', 'setreuid', 'setgid', 'setegid',
                 'setregid', 'setgroups'):
        if hasattr(os, name):
            setattr(os, name, reject_escape)
    event('INIT', start_new_session_suppressed=True, direct_driver=os.getpid() == _leader)


try:
    install()
except BaseException as error:
    sys.stderr.write('native08 bootstrap refused before target: ' + type(error).__name__ + ': ' + str(error) + '\n')
    sys.stderr.flush()
    os._exit(78)
