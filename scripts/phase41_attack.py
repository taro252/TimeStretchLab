#!/usr/bin/env python3
"""Compare attack height, half-height width and position under the same TimeMap."""
import csv
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase32_study import read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase41"
SOURCE = ROOT / "results/phase31/input/mix.wav"
PLAN = OUT / "plan_delay_density.csv"


def table(*args):
    proc = subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True,
                          capture_output=True, text=True)
    return list(csv.DictReader(proc.stdout.splitlines()))


def attack(audio, mapped, rate):
    mono = np.max(np.abs(audio), axis=1)
    start = max(0, round(mapped - .015*rate))
    end = min(len(audio), round(mapped + .015*rate))
    index = start + int(np.argmax(mono[start:end]))
    peak = float(mono[index])
    left = right = index
    while left > start and mono[left-1] >= peak*.5:
        left -= 1
    while right+1 < end and mono[right+1] >= peak*.5:
        right += 1
    return index, peak, (right-left+1)*1000/rate


map_rows = table(ROOT / "build/phase39_reference", SOURCE, "-", "0.4", PLAN, "C",
                 "delay-density")
x = np.array([float(row["input_sample"]) for row in map_rows])
y = np.array([float(row["output_sample"]) for row in map_rows])
events = table(ROOT / "build/phase38_events", SOURCE, "2.0", "B")
rate, original = read(ROOT / "results/phase40/mix_040_to_200_C.wav")
_, delayed = read(OUT / "mix_040_to_200_C_delay_density.wav")
rows = []
for event in events:
    input_peak = int(event["peak_frame"])*1024
    mapped = float(np.interp(input_peak, x, y))
    if mapped < 100000 or mapped > 200000:
        continue
    a = attack(original, mapped, rate)
    b = attack(delayed, mapped, rate)
    rows.append(dict(event=event["event"],input_peak=input_peak,
                     mapped_output=round(mapped),original_peak=a[1],delayed_peak=b[1],
                     delayed_to_original_peak=b[1]/max(a[1],1e-12),
                     original_width_ms=a[2],delayed_width_ms=b[2],
                     peak_shift_ms=(b[0]-a[0])*1000/rate))
with (OUT / "attacks.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
print(len(rows), "transition attacks")
