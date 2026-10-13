#!/usr/bin/env python3
"""Locate first raw PCM change from the same live TimeMap, then join host timestamps."""
import argparse
import csv
import json
import re
import subprocess
from pathlib import Path
from phase45_store import parse_log

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("run", type=Path)
parser.add_argument("input", type=Path)
args = parser.parse_args()
run = args.run
values = parse_log((run / "playback.log").read_text())
initial = values["initial_speed"]
reference, fixed = run / "same_history.wav", run / "fixed_initial.wav"
commands = [
    [root / "build/phase39_reference", args.input, reference, initial, run / "replay.csv", "C", "safe-density"],
    [root / "build/phase39_sim", args.input, fixed, initial, "-", "512", run / "fixed_plan.csv",
     "2048", "C", "safe-density"],
]
for index, command in enumerate(commands):
    result = subprocess.run(list(map(str, command)), cwd=root, capture_output=True, text=True)
    (run / f"operation_reference_{index}.log").write_text(result.stdout + result.stderr)
    if result.returncode: raise SystemExit("Operation reference failed")
hashed = subprocess.run([str(root / "build/phase45_pcm_hash"), str(reference), str(fixed)],
                        capture_output=True, text=True, check=True)
first = int(parse_log(hashed.stdout)["first_changed_pcm_frame"])
events = list(csv.DictReader((run / "callbacks.csv").open()))
event = next(row for row in events if int(row["pcm_before"]) <= first <
             int(row["pcm_before"]) + int(row["received"]))
change = next(line for line in (run / "playback.log").read_text().splitlines() if line.startswith("change="))
fields = dict(re.findall(r"(\w+)=([^ ]+)", change))
operation = int(fields["operation_mach_ns"])
arrival = int(event["callback_start_mach_ns"])
latency = (arrival-operation) / 1e6
offset = (first-int(event["pcm_before"]))*1000/float(values["dsp_sample_rate"])
output = dict(first_changed_pcm_frame=first, map_applied_frame=int(fields["applied_output"]),
              user_operation_mach_ns=operation, pcm_callback_start_mach_ns=arrival,
              operation_to_pcm_callback_ms=latency,
              accept_to_worker_ms=float(values["accept_to_worker_ms"]),
              worker_to_plan_ms=float(values["worker_to_plan_ms"]),
              map_apply_callback_ms=float(fields["apply_callback_ms"]),
              device_latency_ms=float(values["device_presentation_latency_ms"]),
              callback_sample_offset_ms=offset,
              estimated_audible_change_ms=latency+offset+float(values["device_presentation_latency_ms"]),
              method="same live history offline replay; matched callback range; device-latency estimate")
(run / "operation.json").write_text(json.dumps(output, indent=2))
print(json.dumps(output))
