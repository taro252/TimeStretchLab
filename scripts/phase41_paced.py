#!/usr/bin/env python3
"""Paced simulated callback checks for the delayed-density research candidate."""
import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase41/paced"
OUT.mkdir(parents=True, exist_ok=True)
rows = []
for source in ("mix", "drums"):
    input_wav = ROOT / f"results/phase31/input/{source}.wav"
    conditions = [(n, 0, 1) for n in (64, 128, 256, 512, 1024)] + \
        [(512, 70, repeat) for repeat in range(1, 4)]
    for block, load, repeat in conditions:
        name = f"{source}_{block}_{load}_{repeat}"
        command = [str(ROOT / "build/phase40_paced_sim"), str(input_wav), "0.4", "2.0",
                   "1.0", "C", str(block), "16384", "12288", "2048", str(load),
                   str(OUT / f"{name}_plan.csv"), "delay-density"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        (OUT / f"{name}.log").write_text(result.stdout+result.stderr)
        metrics = dict(line.split("=",1) for line in result.stdout.splitlines() if "=" in line)
        rows.append(dict(case=name,source=source,load_percent=load,
                         repeat=repeat,exit=result.returncode,**metrics))
        print(name, "exit", result.returncode, "missing", metrics.get("missing_frames"),
              flush=True)
with (OUT / "summary.csv").open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=sorted(set().union(*(row.keys() for row in rows))), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
