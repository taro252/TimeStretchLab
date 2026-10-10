#!/usr/bin/env python3
"""Measure Phase 14 on repeated frozen MIX; callback runs in accelerated simulation."""
import csv
import json
import pathlib
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase14"
EXE = ROOT / "build/phase14_sim"


def main():
    rows = []
    (OUT / "diagnostics").mkdir(parents=True, exist_ok=True)
    journal = OUT / "diagnostics" / "benchmark.jsonl"
    journal.write_text("")
    for seconds in (180, 300, 600, 900):
        source = OUT / "benchmark" / f"mix_repeat_{seconds}.wav"
        start = time.monotonic()
        process = subprocess.run([str(EXE), str(source), "-", "512"],
                                 check=True, text=True, capture_output=True)
        row = dict(input_duration_seconds=seconds,
                   simulated_output_duration_seconds=seconds * 2,
                   wall_seconds=round(time.monotonic() - start, 6),
                   **dict(line.split("=", 1) for line in process.stdout.strip().splitlines()))
        rows.append(row)
        with journal.open("a") as target:
            target.write(json.dumps(row) + "\n")
        print(seconds, "seconds:", row["wall_seconds"], "wall,",
              row["peak_rss_bytes"], "peak RSS", flush=True)
    with (OUT / "diagnostics" / "benchmark.csv").open("w", newline="") as target:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
