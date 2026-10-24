#!/usr/bin/env python3
"""音声なしdummyだけでtimeout/SIGTERM/INTの別session孫回収を確認する。

実行例: arm64 Python -B recipes/test_native08_driver_supervisor.py --output B/supervisor_dummy_01
音声・製品binary・buildは使わない。今回は作成/ASTのみ。主担当が排他後に実行する。
3固定case。各driver→child→leafはすべて別session、leafはTERM無視でKILLも必要。
driver側にcleanup handlerを持たせず、親終了後のreparentされた孫も確認する。
fixtureのself-signal以外は本監督のaudit-token付き信号だけを使用する。
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
import native08_driver_supervisor as s

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'build/performance_response_20261023_01'
CASES = ('timeout', 'SIGTERM', 'SIGINT')


def interrupted(signum, frame):
    raise KeyboardInterrupt('dummy supervisor self signal ' + str(signum))


def worker(kind, out):
    # normal-thread dummy。製品/callbackへのgateやsignalではない。
    backend = s.DarwinProcesses()
    if kind == 'leaf':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    s.save(out / (kind + '_READY.json'), {**backend.info(os.getpid()), 'session': os.getsid(0), 'kind': kind})
    if kind in ('driver', 'child'):
        next_kind = 'child' if kind == 'driver' else 'leaf'
        subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--worker', next_kind,
                          '--output', str(out)], start_new_session=True)
    # 掛け捨て無限loopを作らない。失敗fixtureも最大30秒で自然終了する。
    time.sleep(30)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', choices=('driver', 'child', 'leaf'))
    args = parser.parse_args()
    out = args.output.resolve()
    s.need(out.is_relative_to(BASE) and out != BASE, '新規B出力のみ')
    if args.worker:
        return worker(args.worker, out)
    out.mkdir(parents=True, exist_ok=False)
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    s.save(out / 'EXPECTED.json', {'schema': 'native08-supervisor-dummy-v1', 'expected_cases': 3,
           'all_expected_ids': list(CASES), 'driver': s.identity(__file__), 'supervisor': s.identity(s.__file__),
           'product_binary_used': False, 'audio_used': False, 'normal_measurement_or_RT_approval': False})
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
                    s.need(time.monotonic() < deadline, 'dummy leaf起動が5秒以内に成立しない')
                if cancelled.wait(.1):
                    return
                sig = signal.SIGTERM if name == 'SIGTERM' else signal.SIGINT
                sent.append(signal.Signals(sig).name)
                # この生存中の自分だけへのsignal。PID再利用/他PIDを対象にしない。
                os.kill(os.getpid(), sig)
            except BaseException as error:
                timer_errors.append(type(error).__name__ + ': ' + str(error))

        timer = threading.Thread(target=self_signal, daemon=True) if name != 'timeout' else None
        execution, error, report = None, None, {}
        try:
            if timer:
                timer.start()
            command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', 'driver', '--output', str(case)]
            execution = s.execute(command, case / 'driver.log', 2.5 if name == 'timeout' else 10)
            report = json.loads(Path(execution['supervisor']['path']).read_text())
        except BaseException as failure:
            error = type(failure).__name__ + ': ' + str(failure)
        finally:
            cancelled.set()
            if timer:
                timer.join(timeout=1)
        fixture = {}
        for kind in ('driver', 'child', 'leaf'):
            path = case / (kind + '_READY.json')
            if path.is_file():
                fixture[kind] = json.loads(path.read_text())
        captured = {r['pid']: r for r in report.get('captured', [])}
        absent = False
        try:
            backend = s.DarwinProcesses()
            absent = bool(fixture) and all(backend.info(item['pid']) is None for item in fixture.values())
        except BaseException as failure:
            error = type(failure).__name__ + ': ' + str(failure)
        complete_fixture = (set(fixture) == {'driver', 'child', 'leaf'} and
                            len({v['session'] for v in fixture.values()}) == 3)
        identities_match = complete_fixture and all(v['pid'] in captured and backend.same(v, captured[v['pid']])
                                                   for v in fixture.values())
        trigger = bool(execution) and (execution['timeout'] is True if name == 'timeout' else
                                      execution['interrupted'] is True and sent == [name])
        good = (error is None and not timer_errors and (timer is None or not timer.is_alive())
                and trigger and complete_fixture and identities_match and absent
                and execution['cleanup_confirmed'] is True and execution['next_job_allowed'] is False
                and report.get('status') == 'INCOMPLETE' and report.get('direct_child_reaped') is True
                and report.get('all_cancelled_executions_are_nonPASS') is True
                and any(e['signal'] == 'SIGKILL' and e['pid'] == fixture['leaf']['pid'] for e in report.get('events', [])))
        rows.append({'id': name, 'status': 'PASS' if good else 'FAIL_OR_INCOMPLETE', 'execution': execution,
                     'fixture': fixture, 'all_fixture_PIDs_absent': absent, 'captured_start_identities_match': identities_match,
                     'error': error, 'timer_errors': timer_errors, 'self_signal': sent})
        s.save(out / 'SUMMARY.json', {'status': 'IN_PROGRESS', 'expected_cases': 3, 'executed_cases': len(rows), 'rows': rows})
        if not good:
            # 未回収なら次fixtureも起動しない。元異常結果は保存する。
            break
    good = len(rows) == 3 and all(row['status'] == 'PASS' for row in rows)
    s.save(out / 'SUMMARY.json', {'status': 'PASS' if good else 'INCOMPLETE_OR_FAIL', 'expected_cases': 3,
           'executed_cases': len(rows), 'passed_cases': sum(r['status'] == 'PASS' for r in rows), 'rows': rows,
           'scope': '音声なし監督cleanupだけ。cancelled product trialのPASSやRT承認ではない。'})
    return 0 if good else 2


if __name__ == '__main__':
    raise SystemExit(main())
