#!/usr/bin/env python3
"""Synthetic configuration change: safe stop and user-controlled engine rebuild."""
import csv
import os
import subprocess
from pathlib import Path
from phase45_store import new_run, parse_log, save_result

root = Path(__file__).resolve().parents[1]
out = root / "results/phase45/route"
for resume in (False, True):
    path, identifier, at = new_run(out, "resume" if resume else "stop")
    environment = os.environ.copy()
    environment.update(PHASE43_SILENT="1", PHASE45_ROUTE_AFTER_SECONDS="0.5",
                       PHASE45_LIVE_EVENTS=str(path / "callbacks.csv"))
    environment.pop("PHASE45_ROUTE_AUTO_RESUME_TEST", None)
    if resume: environment["PHASE45_ROUTE_RESUME"] = "1"
    else: environment.pop("PHASE45_ROUTE_RESUME", None)
    result = subprocess.run([str(root / "build/phase43_play"),
        str(root / "results/phase31/input/mix.wav"), "0.4",
        str(root / "results/phase43/smoke_schedule.csv")], cwd=root, env=environment,
        input="\n" if resume else "", capture_output=True, text=True, timeout=60)
    (path / "playback.log").write_text(result.stdout + result.stderr)
    values = parse_log(result.stdout)
    assert result.returncode != 0, "Route runs must not masquerade as normal realtime PASS"
    assert values["route_changed"] == "1"
    assert values["active_callbacks_after_stop"] == "0" and values["worker_stopped"] == "1"
    assert values["callback_cpp_allocations"] == "0" and values["underrun_frames"] == "0"
    if resume:
        assert values["route_resume_count"] == "1" and values["eos_drained"] == "1"
        assert values["presented_frames"] == values["output_length"]
        events = list(csv.DictReader((path / "callbacks.csv").open()))
        saved = int(values["saved_output_frame"])
        assert any(int(e["pcm_before"]) == saved for e in events), "Resume coordinate rewound"
    else:
        assert values["eos_drained"] == "0" and values["stop_reason"] == "RouteChanged"
        assert int(values["saved_output_frame"]) > 0
    row = dict(run_id=identifier, run_time=at, resume=int(resume),
               lifecycle_test="PASS", normal_audio_quality="FAIL", exit_code=result.returncode)
    row.update(values); save_result(out, path, row)
    print("route lifecycle detection PASS", "resume" if resume else "safe stop", flush=True)
