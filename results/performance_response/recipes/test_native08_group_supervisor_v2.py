#!/usr/bin/env python3
"""音声/製品binaryなし。v2 group保持のtimeout/TERM/INT/内側killpgを検査。

arm64 Python -B recipes/test_native08_group_supervisor_v2.py --output B/group_supervisor_dummy_v2_01
全workerはPython sleepだけ。子/孫はPopenで別session+groupを要求するが、固定
bootstrapが抑制し、3PIDが同一group/sessionに残ることを確認する。
取消の停止/信号は異常回収専用であり、製品機能/RTの故障注入試験ではない。
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True
import native08_group_supervisor_v2 as s

BASE = s.ROOT / 'build/performance_response_20261023_01'
CASES = ('timeout', 'SIGTERM', 'SIGINT', 'inner_killpg')


def worker(kind, out, case):
    if kind == 'leaf':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    s.save(out / (kind + '_READY.json'), {'pid': os.getpid(), 'ppid': os.getppid(), 'uid': os.getuid(),
           'pgid': os.getpgrp(), 'sid': os.getsid(0), 'kind': kind})
    child = None
    if kind in ('driver', 'child'):
        following = 'child' if kind == 'driver' else 'leaf'
        child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--worker', following,
                 '--case', case, '--output', str(out)], start_new_session=True, process_group=0)
    if kind == 'driver' and case == 'inner_killpg':
        deadline = time.monotonic() + 5
        while not (out / 'leaf_READY.json').is_file():
            s.need(time.monotonic() < deadline, 'leaf起動5秒上限')
            time.sleep(.01)
        # inner common.executeと同じchild PID指定。bootstrapが外側group異常中断へ変換。
        os.killpg(child.pid, signal.SIGKILL)
    time.sleep(30)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', choices=('driver', 'child', 'leaf'))
    parser.add_argument('--case', choices=CASES)
    args = parser.parse_args()
    out = args.output.resolve()
    s.need(out.is_relative_to(BASE) and out != BASE, '新規B出力のみ')
    if args.worker:
        return worker(args.worker, out, args.case)
    out.mkdir(parents=True, exist_ok=False)
    s.save(out / 'EXPECTED.json', {'schema': 'native08-group-supervisor-dummy-v2', 'expected_cases': 4,
           'all_expected_ids': list(CASES), 'driver': s.identity(__file__), 'supervisor': s.identity(s.__file__),
           'bootstrap': s.identity(s.BOOTSTRAP), 'audio': False, 'product_binary': False,
           'scope': 'supervisor cleanup only; no native functional/PCM/RT approval'})
    rows = []
    for name in CASES:
        case = out / name
        case.mkdir()
        cancelled, sent, timer_errors = threading.Event(), [], []

        def self_signal():
            try:
                deadline = time.monotonic() + 5
                while not (case / 'leaf_READY.json').is_file():
                    if cancelled.wait(.01):
                        return
                    s.need(time.monotonic() < deadline, 'leaf起動5秒上限')
                if cancelled.wait(.1):
                    return
                sig = signal.SIGTERM if name == 'SIGTERM' else signal.SIGINT
                sent.append(signal.Signals(sig).name)
                os.kill(os.getpid(), sig)  # この生存中の自分だけ。外部PIDへのsignalではない。
            except BaseException as failure:
                timer_errors.append(type(failure).__name__ + ': ' + str(failure))

        timer = threading.Thread(target=self_signal, daemon=True) if name in ('SIGTERM', 'SIGINT') else None
        execution, report, error = None, {}, None
        try:
            if timer:
                timer.start()
            command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', 'driver',
                       '--case', name, '--output', str(case)]
            execution = s.execute(command, case / 'driver.log', 2.5 if name == 'timeout' else 10, source_roots=[s.ROOT])
            report = json.loads(Path(execution['supervisor']['path']).read_text())
        except BaseException as failure:
            error = type(failure).__name__ + ': ' + str(failure)
        finally:
            cancelled.set()
            if timer:
                timer.join(timeout=1)
        fixtures = {}
        for kind in ('driver', 'child', 'leaf'):
            path = case / (kind + '_READY.json')
            if path.is_file():
                fixtures[kind] = json.loads(path.read_text())
        events = []
        for item in report.get('bootstrap_events', []):
            events.append(json.loads(Path(item['path']).read_text()))
        leader = report.get('leader')
        confined = (set(fixtures) == {'driver', 'child', 'leaf'} and
                    all(row['pgid'] == row['sid'] == leader and row['uid'] == os.getuid() for row in fixtures.values()))
        suppressions = [e for e in events if e.get('kind') == 'SUPPRESSED_POPEN'
                        and e.get('requested', {}).get('start_new_session') is True
                        and e.get('requested', {}).get('process_group') == 0]
        trigger = bool(execution) and (execution['timeout'] is True if name == 'timeout' else
                  execution['interrupted'] is True and sent == [name] if name in ('SIGTERM', 'SIGINT') else
                  report.get('inner_abort') is True)
        good = (error is None and not timer_errors and (timer is None or not timer.is_alive())
                and trigger and confined and len(suppressions) >= 2
                and report.get('status') == 'INCOMPLETE' and report.get('all_intervened_trials_are_nonPASS') is True
                and report.get('all_active_group_members_zero') is True and report.get('direct_child_reaped') is True
                and execution['cleanup_confirmed'] is True and execution['next_job_allowed'] is False
                and report.get('bootstrap_handshake_valid') is True)
        rows.append({'id': name, 'status': 'PASS' if good else 'FAIL_OR_INCOMPLETE', 'execution': execution,
                     'fixtures': fixtures, 'same_group_session': confined, 'suppressed_independent_group_requests': len(suppressions),
                     'error': error, 'timer_errors': timer_errors, 'self_signal': sent})
        s.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_cases': 4, 'executed_cases': len(rows), 'rows': rows})
        if not good:
            break  # 未回収/未確認なら次dummyも禁止。
    good = len(rows) == 4 and all(row['status'] == 'PASS' for row in rows)
    s.save(out / 'SUMMARY.json', {'status': 'PASS' if good else 'INCOMPLETE_OR_FAIL', 'expected_cases': 4,
           'executed_cases': len(rows), 'passed_cases': sum(r['status'] == 'PASS' for r in rows), 'rows': rows,
           'scope': '音声なしgroup監督のみ。製品/RT/品質/公開承認ではない。'})
    return 0 if good else 2


if __name__ == '__main__':
    raise SystemExit(main())
