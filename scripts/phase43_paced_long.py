#!/usr/bin/env python3
"""Absolute-clock long playback simulation; underruns become zero-filled audio."""
import csv
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "results/phase43/paced"
out.mkdir(parents=True, exist_ok=True)
rows = []
for minutes in (3, 5, 10):
    source = root / f"results/phase14/benchmark/mix_repeat_{minutes * 60}.wav"
    command = [str(root / "build/phase40_paced_sim"), str(source), "0.4", "2.0",
               "1.0", "C", "512", "16384", "12288", "2048", "0",
               str(out / f"mix_{minutes}m_plan.csv"), "safe-density"]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    (out / f"mix_{minutes}m.log").write_text(result.stdout + result.stderr)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    rows.append(dict(input_minutes=minutes, exit_code=result.returncode, **values))
    print(minutes, "minutes:", "exit", result.returncode,
          "missing", values.get("missing_frames"),
          "worker_cycle_max", values.get("max_worker_cycle_seconds"), flush=True)
    if result.returncode:
        break
with (out / "summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(row.keys() for row in rows))))
    writer.writeheader()
    writer.writerows(rows)
if len(rows) != 3 or any(row["exit_code"] for row in rows):
    raise SystemExit("Long paced simulation incomplete; see logs")
