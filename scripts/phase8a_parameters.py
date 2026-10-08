#!/usr/bin/env python3
"""Small, prespecified parameter study; do not auto-select a winner."""
import csv
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase8a/parameters"
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "diagnostics").mkdir(exist_ok=True)
rows = []
for section in ("female_2", "male_2"):
    source = ROOT / "results/phase7" / f"{section}_input.wav"
    for window, search in ((2048, 256), (2048, 512), (2048, 768),
                           (1536, 512), (3072, 512)):
        label = f"{section}_w{window}_s{search}"
        output = OUT / f"{label}.wav"
        diagnostic = OUT / "diagnostics" / f"{label}.csv"
        args = [str(ROOT / "build/wsola_stretch"), str(source), str(output),
                "--speed", "0.5", "--window", str(window), "--hop", "512",
                "--search", str(search), "--debug-csv", str(diagnostic)]
        result = subprocess.run(args, check=True, text=True, capture_output=True)
        fields = dict(item.split("=", 1) for item in result.stdout.split())
        rows.append({"section": section, "window": window, "hop": 512,
                     "search": search, "output": str(output), **fields})
        print(label, fields, flush=True)
with (OUT / "manifest.csv").open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=rows[0].keys(), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
