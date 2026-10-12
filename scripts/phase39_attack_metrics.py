#!/usr/bin/env python3
"""Event-aligned attack comparison; history differs, so results are diagnostic."""
import csv
import subprocess
from pathlib import Path

import numpy as np

from phase32_study import read

root = Path(__file__).resolve().parents[1]
out = root / "results/phase39"


def table(command):
    result = subprocess.run([str(item) for item in command], cwd=root,
                            text=True, capture_output=True, check=True)
    return list(csv.DictReader(result.stdout.splitlines()))


def positions(rows):
    return (np.array([float(row["input_sample"]) for row in rows]),
            np.array([float(row["output_sample"]) for row in rows]))


def smoothed_power(audio, samples):
    power = np.mean(audio.astype(np.float64) ** 2, axis=1)
    prefix = np.concatenate(([0.], np.cumsum(power)))
    result = np.empty_like(power)
    half = samples // 2
    indices = np.arange(len(power))
    first = np.maximum(0, indices-half)
    last = np.minimum(len(power), first+samples)
    result[:] = (prefix[last]-prefix[first]) / np.maximum(last-first, 1)
    return result


def attack(power, mapped, rate):
    left = max(0, int(mapped-rate*.035))
    right = min(len(power), int(mapped+rate*.035))
    if right<=left:
        return None
    peak = left+int(np.argmax(power[left:right]))
    threshold = power[peak]*.5
    first = last = peak
    while first>left and power[first-1]>=threshold:
        first-=1
    while last+1<right and power[last+1]>=threshold:
        last+=1
    return dict(peak_rms=float(np.sqrt(power[peak])),
                width_ms=(last-first+1)*1000/rate,
                peak_minus_map_ms=(peak-mapped)*1000/rate)


rows = []
for source, input_wav, variable, fixed, plans in (
    ("mix", root / "results/phase12/golden/input/mix.wav",
     out / "variable/mix_45s_100_to_200.wav", out / "variable/mix_45s_fixed_200.wav",
     out / "plans/mix_45s_100_to_200.csv"),
    ("drums", root / "results/phase31/input/drums.wav",
     out / "variable/drums_100_to_200.wav", root / "results/phase37/raw/drums_B_200.wav",
     out / "plans/drums_100_to_200.csv"),
):
    rate, var_audio = read(variable)
    _, fixed_audio = read(fixed)
    var_power = smoothed_power(var_audio, max(1,round(rate*.001)))
    fix_power = smoothed_power(fixed_audio, max(1,round(rate*.001)))
    plan = next(csv.DictReader(plans.open(newline="")))
    earliest = int(plan["completion_output"])
    var_map = positions(table([root / "build/phase39_reference", input_wav, "-", "1.0", plans]))
    fix_map = positions(table([root / "build/phase37_render", input_wav, "-", "2.0", "B"]))
    events = table([root / "build/phase38_events", input_wav, "2.0", "B"])
    for event in events:
        input_peak = int(event["peak_frame"])*1024
        var_mapped = float(np.interp(input_peak, *var_map))
        if var_mapped < earliest+rate*.1:
            continue
        fix_mapped = float(np.interp(input_peak, *fix_map))
        var = attack(var_power, var_mapped, rate)
        ref = attack(fix_power, fix_mapped, rate)
        if not var or not ref or ref["peak_rms"]<=1e-9:
            continue
        half=round(rate*.02)
        va=round(var_mapped)
        fa=round(fix_mapped)
        if va<half or fa<half or va+half>=len(var_audio) or fa+half>=len(fixed_audio):
            continue
        sample_difference=float(np.max(np.abs(
            var_audio[va-half:va+half].astype(np.float64)-
            fixed_audio[fa-half:fa+half].astype(np.float64))))
        rows.append(dict(source=source, event=event["event"], input_peak=input_peak,
                         variable_mapped=round(var_mapped), fixed_mapped=round(fix_mapped),
                         peak_ratio=var["peak_rms"]/ref["peak_rms"],
                         width_ratio=var["width_ms"]/max(ref["width_ms"],1e-9),
                         max_sample_difference_40ms=sample_difference,
                         relative_peak_position_ms=var["peak_minus_map_ms"]-
                         ref["peak_minus_map_ms"]))
with (out / "attack_metrics.csv").open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print("Measured", len(rows), "post-transition events")
