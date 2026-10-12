#!/usr/bin/env python3
"""Check actual synthesis-hop bounds for every Phase 39 speed history."""
import csv
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "results/phase39"
rows = []
with (out / "transitions.csv").open(newline="") as file:
    transitions = list(csv.DictReader(file))
for entry in transitions:
    source, initial, target = entry["source"], entry["from"], entry["to"]
    name = f"{source}_{initial.replace('.', '')}_to_{target.replace('.', '')}"
    command = [str(root / "build/phase39_reference"),
               str(root / f"results/phase31/input/{source}.wav"), "--hops", initial,
               str(out / "plans" / f"{name}.csv")]
    completed = subprocess.run(command, capture_output=True, text=True, cwd=root)
    if completed.returncode:
        raise RuntimeError(f"{name}: {completed.stderr}")
    for resolution, minimum, maximum in csv.reader(completed.stdout.splitlines()):
        rows.append((name, resolution, minimum, maximum))
    print(name, completed.stdout.strip().replace("\n", " "), flush=True)
with (out / "hops.csv").open("w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(("case", "resolution", "min_hop", "max_hop"))
    writer.writerows(rows)
