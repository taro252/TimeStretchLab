#!/usr/bin/env python3
"""Temporarily change the actual output rate; always restore it afterwards."""
import os
import subprocess
import time
from pathlib import Path
from phase45_store import new_run, parse_log, save_result

root = Path(__file__).resolve().parents[1]
helper = root / "build/phase45_device_rate"
original = subprocess.run([str(helper)], capture_output=True, text=True, check=True)
before = parse_log(original.stdout)
rate = int(float(before["sample_rate"]))
if rate not in (44100, 48000): raise SystemExit("Unsupported current rate: no device change made")
target = 44100 if rate == 48000 else 48000
out = root / "results/phase45/device_change"
path, identifier, at = new_run(out, "actual_rate")
environment = dict(os.environ, PHASE43_SILENT="1")
process = subprocess.Popen([str(root / "build/phase43_play"),
    str(root / "results/phase31/input/mix.wav"), "0.4", "-"],
    cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    time.sleep(2)
    changed = subprocess.run([str(helper), str(target)], capture_output=True, text=True)
    (path / "rate_change.log").write_text(original.stdout + changed.stdout + changed.stderr)
    stdout, stderr = process.communicate(timeout=20)
finally:
    if process.poll() is None:
        process.terminate();process.wait(timeout=10)
    restored = subprocess.run([str(helper), str(rate)], capture_output=True, text=True)
    (path / "rate_restore.log").write_text(restored.stdout + restored.stderr)
    if restored.returncode: raise RuntimeError("Could not restore output rate")
values = parse_log(stdout)
(path / "playback.log").write_text(stdout + stderr)
if changed.returncode: raise SystemExit("Device rejected rate change; not validated")
assert process.returncode != 0 and values["stop_reason"] == "RouteChanged"
assert values["eos_drained"] == "0" and values["route_changed"] == "1"
assert values["active_callbacks_after_stop"] == "0" and values["worker_stopped"] == "1"
row = dict(run_id=identifier, run_time=at, original_rate=rate, temporary_rate=target,
           lifecycle_test="PASS", normal_audio_quality="FAIL", exit_code=process.returncode)
row.update(values);save_result(out, path, row)
print("Actual output-rate change: safe stop PASS; original rate restored")
