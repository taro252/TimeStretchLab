#!/usr/bin/env python3
"""Run short silent AVAudioEngine trials for all required directions and sources."""
import csv
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("mix", "vocal", "bass", "drums", "guitar")
PAIRS = (("0.50", "0.70"), ("0.70", "0.50"), ("0.60", "0.80"),
         ("0.80", "0.60"), ("0.75", "0.70"), ("0.70", "0.75"),
         ("0.90", "1.00"), ("1.00", "0.90"))


def main():
    rows = []
    with tempfile.TemporaryDirectory(prefix="phase30-mac-") as temp:
        schedule = Path(temp) / "schedule.csv"
        for source in SOURCES:
            for initial, target in PAIRS:
                schedule.write_text("output_seconds,target_speed\n1.0," + target + "\n")
                command = (str(ROOT / "build/phase30_play"),
                           str(ROOT / f"results/phase12/golden/input/{source}.wav"),
                           initial, str(schedule), "6")
                result = subprocess.run(command, text=True, capture_output=True,
                                        env={**os.environ, "PHASE30_SILENT": "1"},
                                        timeout=30)
                if result.returncode:
                    raise RuntimeError(f"{source} {initial}->{target}: "
                                       f"{result.stdout}\n{result.stderr}")
                data = dict(line.split("=", 1) for line in result.stdout.splitlines()
                            if "=" in line and not line.startswith("change="))
                row = {"source": source, "initial": initial, "target": target,
                       **data}
                rows.append(row)
                if int(data["underrun_frames"]) or int(data["fifo_rejected_writes"]) or \
                   int(data["callback_deadline_misses"]) or \
                   int(data["callback_format_errors"]) or \
                   int(data["callback_cpp_allocations"]):
                    raise AssertionError(f"Realtime safety counter: {row}")
                print(source, initial, target, data["apply_latency_median_ms"],
                      flush=True)
    path = ROOT / "results/phase30/mac_matrix.csv"
    names = list(dict.fromkeys(name for row in rows for name in row))
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
