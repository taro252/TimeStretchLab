#!/usr/bin/env python3
"""Map-aligned noise-burst envelope measurements (diagnostic, not a quality verdict)."""
import csv
import subprocess
from pathlib import Path

import numpy as np

from phase32_study import read

root = Path(__file__).resolve().parents[1]
out = root / "results/phase39"
rate = 48000


def map_points(command):
    result = subprocess.run([str(x) for x in command], capture_output=True,
                            text=True, check=True, cwd=root)
    rows = list(csv.DictReader(result.stdout.splitlines()))
    return (np.array([float(x["input_sample"]) for x in rows]),
            np.array([float(x["output_sample"]) for x in rows]))


def values(audio, mapped):
    power = np.mean(audio.astype(np.float64) ** 2, axis=1)
    left = max(0, int(mapped - rate * .04))
    right = min(len(power), int(mapped + rate * .08))
    smooth = np.convolve(power[left:right], np.ones(48) / 48, "same")
    peak = float(np.max(smooth, initial=0))
    rising = np.flatnonzero(smooth >= .1 * peak)
    onset = left + int(rising[0]) if len(rising) else left
    crest = left + int(np.argmax(smooth)) if len(smooth) else left

    def energy(center, ms):
        first = max(0, int(round(center)))
        last = min(len(power), first + int(round(ms * rate / 1000)))
        return float(np.sum(power[first:last]))

    return dict(mapped=round(mapped), onset=onset, crest=crest,
                onset_minus_map_ms=(onset-mapped)*1000/rate,
                peak_rms=float(np.sqrt(peak)),
                first_5ms=energy(onset, 5), first_10ms=energy(onset, 10),
                first_20ms=energy(onset, 20), first_50ms=energy(onset, 50),
                mapped_20ms=energy(mapped, 20),
                pre_20ms=energy(onset-rate*.02, 20))


rows = []
for source in ("white_burst", "pink_burst"):
    input_wav = root / f"results/phase32/input/{source}.wav"
    variable = out / f"artificial/{source}_100_to_200.wav"
    fixed = root / f"results/phase37/raw/{source}_B_200.wav"
    _, variable_audio = read(variable)
    _, fixed_audio = read(fixed)
    maps = {
        "variable": map_points([root / "build/phase39_reference", input_wav, "-", "1.0",
                                out / f"artificial_plans/{source}_100_to_200.csv"]),
        "fixed_B_200": map_points([root / "build/phase37_render", input_wav,
                                   "-", "2.0", "B"]),
    }
    for input_seconds in (.6, 2.5, 4.4):
        position = input_seconds * rate
        for mode, audio in (("variable", variable_audio), ("fixed_B_200", fixed_audio)):
            x, y = maps[mode]
            data = values(audio, float(np.interp(position, x, y)))
            rows.append(dict(source=source, input_seconds=input_seconds, mode=mode, **data))
with (out / "noise_envelope.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print("Measured", len(rows), "noise-burst windows")
