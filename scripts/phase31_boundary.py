#!/usr/bin/env python3
"""Reproduce the 0.49x research / frozen 0.50x quality boundary."""
import csv
import hashlib
from pathlib import Path
import subprocess

from phase31_synthetic_metrics import clicks

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase31"
RENDER = ROOT / "build/phase31_render"
METRICS = ROOT / "build/wav_metrics"


def summary(path):
    output = subprocess.run((METRICS, path), text=True, capture_output=True,
                            check=True).stdout
    return dict(item.split("=", 1) for item in output.split() if "=" in item)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


rows = []
for source in ("mix", "vocal", "click"):
    input_path = OUT / "input" / f"{source}.wav"
    low = OUT / "raw" / f"{source}_B_049.wav"
    baseline = OUT / "raw" / f"{source}_A_050.wav"
    if not input_path.exists() or not baseline.exists():
        raise RuntimeError("Run phase31_study.py --render-only first")
    subprocess.run((RENDER, input_path, low, "0.49", "B"), check=True,
                   capture_output=True, text=True)
    for speed, mode, path in (("0.49", "B", low), ("0.50", "A", baseline)):
        details = summary(path)
        result = {"source": source, "speed": speed, "mode": mode,
                  "sha256": sha(path), "frames": details["frames"],
                  "rms": details["rms"], "peak": details["peak"],
                  "side_mid_ratio": details["side_mid_ratio"],
                  "lr_correlation": details["lr_correlation"]}
        if source == "click":
            result.update(clicks(path, float(speed)))
        rows.append(result)
with (OUT / "boundary.csv").open("w", newline="") as stream:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
print(f"Boundary diagnostics: {len(rows)} rows")
