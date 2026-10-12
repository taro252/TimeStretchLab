#!/usr/bin/env python3
"""Absolute-clock callback-size sweep with strict quality verdicts."""
import csv
import subprocess
from pathlib import Path

from phase44_quality import failures

root = Path(__file__).resolve().parents[1]
out = root / "results/phase44/sweep"
out.mkdir(parents=True, exist_ok=True)
rows = []
for frames in (64, 128, 256, 512, 1024):
    command = [str(root / "build/phase40_paced_sim"),
               str(root / "results/phase31/input/mix.wav"), "0.4", "2.0", "1.0",
               "C", str(frames), "16384", "12288", "2048", "0",
               str(out / f"callback_{frames}_plan.csv"), "safe-density"]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    (out / f"callback_{frames}.log").write_text(result.stdout + result.stderr)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines()
                  if "=" in line)
    problems = failures(values, result.returncode)
    rows.append(dict(callback_config=frames, audio_quality="FAIL" if problems else "PASS",
                     failure_reasons=";".join(problems), exit_code=result.returncode,
                     **values))
    print(frames, rows[-1]["audio_quality"], flush=True)
with (out / "summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(row.keys() for row in rows))))
    writer.writeheader()
    writer.writerows(rows)
if any(row["audio_quality"] == "FAIL" for row in rows):
    raise SystemExit("Callback-size audio quality FAIL")
