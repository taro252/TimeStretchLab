#!/usr/bin/env python3
"""Fail if allocation validity, full-cycle timing or OLA telemetry is misleading."""
import csv
import hashlib
import subprocess
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = Path(os.environ.get("PHASE45_MEASUREMENT_OUT", root / "results/phase43/measurement"))
out.mkdir(parents=True, exist_ok=True)
source = root / "results/phase31/input/mix.wav"
rows = {}
for label, executable in (("unmeasured", "phase39_sim"),
                          ("measured", "phase41_profile_sim")):
    wav = out / f"{label}.wav"
    profile = out / f"{label}_blocks.csv"
    command = [root / "build" / executable, source, wav, "0.4",
               "1.0:2.0,3.0:0.4,5.0:1.5", "512", out / f"{label}_plan.csv",
               "2048", "C", "safe-density", profile]
    run = subprocess.run(list(map(str, command)), cwd=root, capture_output=True, text=True)
    (out / f"{label}.log").write_text(run.stdout + run.stderr)
    if run.returncode:
        raise RuntimeError(f"{label}: {run.stderr}")
    block = list(csv.DictReader(profile.open()))
    if not block:
        raise AssertionError(f"{label}: no profiled blocks")
    expected = "1" if label == "measured" else "0"
    if any(row["allocation_counter_enabled"] != expected for row in block):
        raise AssertionError(f"{label}: counter validity flag")
    if label == "unmeasured" and any(row["cpp_new_calls"] != "unmeasured" for row in block):
        raise AssertionError("Unmeasured allocation shown as numeric")
    if label == "measured" and any(not row["cpp_new_calls"].isdigit() for row in block):
        raise AssertionError("Measured allocation missing numeric count")
    if any(float(row["worker_cycle_wall_s"]) + 1e-6 <
           float(row["dsp_compute_wall_s"]) for row in block):
        raise AssertionError("DSP computation exceeds complete worker cycle")
    guard = list(csv.DictReader(Path(str(profile) + ".guard.csv").open()))
    accepted = [row for row in guard if row["candidate_accepted"] == "1"]
    if not accepted:
        raise AssertionError("No accepted density guard candidate")
    if any(max(float(row[f"weight_error_{r}"]) for r in ("low", "mid", "high")) > 1e-4
           for row in accepted):
        raise AssertionError("Actual OLA weight differs from prediction")
    rows[label] = dict(sha256=hashlib.sha256(wav.read_bytes()).hexdigest(),
                       top_blocks=len(block), guard_accepted=len(accepted),
                       top20_cpp_new_calls=sum(int(row["cpp_new_calls"]) for row in block)
                       if label == "measured" else "unmeasured",
                       max_weight_error=max(float(row[f"weight_error_{r}"])
                                            for row in accepted for r in ("low", "mid", "high")))
if rows["unmeasured"]["sha256"] != rows["measured"]["sha256"]:
    raise AssertionError("Instrumentation changed raw PCM")
with (out / "summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=("mode", *rows["measured"].keys()))
    writer.writeheader()
    for mode, value in rows.items():
        writer.writerow(dict(mode=mode, **value))
print("allocation validity and actual OLA weights verified; PCM identical")
