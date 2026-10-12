#!/usr/bin/env python3
"""Event-aligned attack checks after the Phase 40 C transition."""
import csv
import subprocess
from pathlib import Path

import numpy as np
from phase32_study import read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase40"
rows = []


def command(*arguments):
    value = subprocess.run([str(a) for a in arguments], cwd=ROOT,
                           capture_output=True, text=True, check=True)
    return list(csv.DictReader(value.stdout.splitlines()))


def map_position(table, sample):
    x = np.array([float(item["input_sample"]) for item in table])
    y = np.array([float(item["output_sample"]) for item in table])
    return float(np.interp(sample, x, y))


def attack(audio, position, rate):
    mono = np.max(np.abs(audio), axis=1)
    center = round(position)
    start = max(0, center-round(.015*rate))
    end = min(len(mono), center+round(.015*rate))
    if end<=start:
        return None
    index = start+int(np.argmax(mono[start:end]))
    value = float(mono[index])
    threshold = value*.5
    left = right = index
    while left>start and mono[left-1]>=threshold:
        left-=1
    while right+1<end and mono[right+1]>=threshold:
        right+=1
    return index, value, (right-left+1)*1000/rate


for source in ("mix", "drums"):
    input_wav = ROOT / f"results/phase31/input/{source}.wav"
    plan = OUT / "plans" / f"{source}_100_to_200_C.csv"
    variable = OUT / f"{source}_100_to_200_C.wav"
    fixed = ROOT / f"results/phase37/raw/{source}_B_200.wav"
    rate, variable_audio = read(variable)
    _, fixed_audio = read(fixed)
    varmap = command(ROOT / "build/phase39_reference", input_wav,
                     "-", "1.0", plan, "C")
    fixmap = command(ROOT / "build/phase37_render", input_wav,
                     "-", "2.0", "B")
    events = command(ROOT / "build/phase38_events", input_wav, "2.0", "B")
    completion = int(next(csv.DictReader(plan.open(newline="")))["completion_output"])
    for event in events:
        input_peak = int(event["peak_frame"])*1024
        at_variable = map_position(varmap, input_peak)
        if at_variable < completion+rate*.1:
            continue
        at_fixed = map_position(fixmap, input_peak)
        a = attack(variable_audio, at_variable, rate)
        b = attack(fixed_audio, at_fixed, rate)
        if not a or not b or b[1]<1e-5:
            continue
        rows.append(dict(source=source, event=event["event"], input_peak=input_peak,
                         mapped_variable=round(at_variable), mapped_fixed=round(at_fixed),
                         peak_ratio=a[1]/b[1], width_ratio=a[2]/max(b[2],1e-9),
                         relative_peak_position_ms=(a[0]-at_variable-b[0]+at_fixed)*1000/rate))

with (OUT / "attack.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["source"])
    writer.writeheader()
    writer.writerows(rows)
print("post-transition attacks", len(rows))
