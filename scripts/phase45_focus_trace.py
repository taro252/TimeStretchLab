#!/usr/bin/env python3
"""Attach a short System Trace around the observed ~90s native shortfall."""
import argparse
import os
import subprocess
import time
from pathlib import Path
from phase45_store import new_run, parse_log, save_result
from phase45_verdict import live_failures

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--repeat', type=int, default=2)
args = parser.parse_args()
out = root / 'results/phase45/focus_trace'
failed = False
for _ in range(args.repeat):
    path, identifier, at = new_run(out, 'drums_3m_high')
    env = dict(os.environ, PHASE43_STRESS='1', PHASE43_SILENT='1',
               PHASE45_LIVE_EVENTS=str(path / 'callbacks.csv'),
               PHASE45_LIVE_WORKERS=str(path / 'workers.csv'),
               PHASE45_LIVE_PLAN_CSV=str(path / 'replay.csv'))
    with (path / 'playback.log').open('x') as log:
        process = subprocess.Popen([str(root / 'build/phase43_play'),
            str(root / 'results/phase40/long_input/drums_repeat_180.wav'), '0.4',
            str(root / 'results/phase45/repeated.csv')], env=env, cwd=root,
            stdout=log, stderr=subprocess.STDOUT)
        time.sleep(80)
        trace_code = -1
        if process.poll() is None:
            trace = subprocess.run(['/usr/bin/arch', '-arm64', '/usr/bin/xcrun', 'xctrace', 'record', '--template', 'System Trace',
                '--time-limit', '35s', '--window', '35s', '--output', str(path / 'system.trace'),
                '--attach', str(process.pid)], cwd=root, capture_output=True, text=True, timeout=100)
            (path / 'xctrace.log').write_text(trace.stdout + trace.stderr)
            trace_code = trace.returncode
            trace_errors = '[Error]' in trace.stdout + trace.stderr or 'Recording failed' in trace.stdout + trace.stderr
        else: trace_errors = True
        try: code = process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.terminate();process.wait(timeout=10);code=124
    values = parse_log((path / 'playback.log').read_text())
    errors = live_failures(values, code)
    row = dict(run_id=identifier, run_time=at, source='drums', input_minutes=3,
        stress=1, diagnostic=1, attach_after_seconds=80, exit_code=code,
        trace_exit=trace_code, trace_recording_status='FAILED' if trace_errors else 'RECORDED_NEEDS_EXPORT_VALIDATION',
        quality='FAIL' if errors else 'PASS', failures=';'.join(errors))
    row.update(values);save_result(out, path, row)
    failed |= bool(errors) or trace_errors
    print(identifier, row['quality'], row['failures'], flush=True)
if failed: raise SystemExit('Native focused trace has audio FAIL; evidence retained')
