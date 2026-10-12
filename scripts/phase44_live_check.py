#!/usr/bin/env python3
"""Run independent macOS callback playback and fail closed on audio faults."""
import argparse
import csv
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--source", choices=("mix", "drums"), default="mix")
parser.add_argument("--minutes", default="3,5,10")
parser.add_argument("--stress", action="store_true")
parser.add_argument("--audible", action="store_true")
parser.add_argument("--output", type=Path, default=root / "results/phase44/live")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
rows = []
for minutes in (int(value) for value in args.minutes.split(",")):
    source = (root / "results/phase14/benchmark" / f"mix_repeat_{minutes * 60}.wav"
              if args.source == "mix" else root / "results/phase40/long_input" /
              f"drums_repeat_{minutes * 60}.wav")
    schedule = root / "results/phase43/smoke_schedule.csv"
    command = [str(root / "build/phase43_play"), str(source), "0.4", str(schedule)]
    environment = os.environ.copy()
    if args.audible:
        environment.pop("PHASE43_SILENT", None)
    else:
        environment["PHASE43_SILENT"] = "1"
    if args.stress:
        environment["PHASE43_STRESS"] = "1"
    result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                            env=environment)
    tag = f"{args.source}_{minutes}m_{'stress' if args.stress else 'normal'}"
    (args.output / f"{tag}.log").write_text(result.stdout + result.stderr)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines()
                  if line.count("=") == 1)
    problems = []
    if result.returncode:
        problems.append(f"exit={result.returncode}")
    for key in ("underrun_frames", "fifo_rejected_writes", "callback_deadline_misses",
                "callback_cpp_allocations", "callback_format_errors"):
        if values.get(key) != "0":
            problems.append(f"{key}={values.get(key, 'unmeasured')}")
    if values.get("eos_drained") != "1":
        problems.append("eos_not_drained")
    if values.get("observed_completions") != values.get("requested_changes"):
        problems.append("speed_change_incomplete")
    if values.get("presented_audio_timeline_frames") != values.get("output_length"):
        problems.append("presentation_length_mismatch")
    rows.append(dict(source=args.source, input_minutes=minutes, stress=int(args.stress),
                     audible=int(args.audible), quality="FAIL" if problems else "PASS",
                     failures=";".join(problems), exit_code=result.returncode, **values))
    print(tag, rows[-1]["quality"], rows[-1]["failures"], flush=True)
with (args.output / "summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(row.keys() for row in rows))))
    writer.writeheader()
    writer.writerows(rows)
if any(row["quality"] == "FAIL" for row in rows):
    raise SystemExit("Mac callback audio quality FAIL; see live summary")
