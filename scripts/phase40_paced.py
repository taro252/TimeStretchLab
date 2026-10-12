#!/usr/bin/env python3
"""Timed audio-consumer trials.  Missing PCM is zero-filled by the simulator."""
import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase40"
SIM = ROOT / "build/phase40_paced_sim"
INPUT = ROOT / "results/phase31/input"

cases = []
for source in ("mix", "drums"):
    for block in (64, 128, 256, 512, 1024):
        cases.append((source, block, 0, 16384, 12288, 1))
    for repetition in range(2, 6):
        cases.append((source, 512, 0, 16384, 12288, repetition))
    for repetition in range(1, 4):
        cases.append((source, 512, 70, 16384, 12288, repetition))
    cases.append((source, 512, 0, 32768, 28672, 1))

rows = []
for source, block, load, fifo, lead, repetition in cases:
    command = [SIM, INPUT / f"{source}.wav", "1.0", "2.0", "1.0", "C",
               block, fifo, lead, 2048, load]
    completed = subprocess.run([str(value) for value in command], cwd=ROOT,
                               capture_output=True, text=True)
    result = dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
    result.update(source=source, repetition=repetition, load_percent=load,
                  fifo_frames=fifo, lead_frames=lead, exit_code=completed.returncode,
                  error=completed.stderr.strip())
    rows.append(result)
    print(source, block, load, fifo, repetition,
          "missing", result.get("missing_frames", "?"),
          "worker", result.get("max_worker_wall_seconds", "?"), flush=True)

fields = list(dict.fromkeys(key for row in rows for key in row))
with (OUT / "paced.csv").open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
