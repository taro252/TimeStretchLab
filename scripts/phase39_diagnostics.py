#!/usr/bin/env python3
"""Phase 39 PCM safety and audition diagnostics; never modifies DSP output."""
from __future__ import annotations

import csv
import subprocess
from pathlib import Path

import numpy as np
from phase32_study import read as read_float, wav as write_float

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase39"
BUILD = ROOT / "build"


def read(path: Path):
    rate, audio = read_float(path)
    if audio.dtype != np.float32:
        raise ValueError(f"Expected float32: {path}")
    return rate, np.atleast_2d(audio).reshape(-1, 1 if audio.ndim == 1 else audio.shape[1])


def fixed(source: str, speed: str) -> Path:
    path = OUT / "fixed_short" / f"{source}_{speed.replace('.', '')}.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(BUILD / "phase39_sim"),
                        str(ROOT / "results/phase31/input" / f"{source}.wav"),
                        str(path), speed, "-", "512"], check=True, capture_output=True)
    return path


def stereo(audio):
    if audio.shape[1] != 2:
        return (float("nan"), float("nan"))
    left, right = audio[:, 0].astype(np.float64), audio[:, 1].astype(np.float64)
    mid, side = (left + right) * .5, (left - right) * .5
    ratio = np.sqrt(np.mean(side * side)) / max(np.sqrt(np.mean(mid * mid)), 1e-20)
    corr = np.corrcoef(left, right)[0, 1] if np.std(left) and np.std(right) else float("nan")
    return float(ratio), float(corr)


def main():
    rows = []
    audition = OUT / "audition"
    audition.mkdir(parents=True, exist_ok=True)
    with (OUT / "transitions.csv").open(newline="") as file:
        plans = list(csv.DictReader(file))
    for plan in plans:
        if plan["result"] != "match":
            continue
        source, initial, target = plan["source"], plan["from"], plan["to"]
        name = f"{source}_{initial.replace('.', '')}_to_{target.replace('.', '')}"
        rate, audio = read(OUT / "variable" / f"{name}.wav")
        _, baseline = read(fixed(source, initial))
        applied = int(plan["applied_output"])
        with (OUT / "plans" / f"{name}.csv").open(newline="") as stream:
            frontier = next(csv.DictReader(stream))
        published = int(frontier["published"])
        prefix = min(published, len(audio), len(baseline))
        equal = bool(np.array_equal(audio[:prefix], baseline[:prefix]))
        common = min(len(audio), len(baseline))
        differing = np.flatnonzero(np.any(audio[:common] != baseline[:common], axis=1))
        first_difference = int(differing[0]) if differing.size else -1
        finite = bool(np.isfinite(audio).all())
        center = min(len(audio) - 1, max(1, applied))
        half = round(rate * .1)
        before = audio[max(0, center-half):center]
        after = audio[center:min(len(audio), center+half)]
        short = audio[max(0, center-2*half):min(len(audio), center+2*half)]
        derivative = np.abs(np.diff(short.astype(np.float64), axis=0))
        local_p99 = float(np.percentile(derivative, 99)) if derivative.size else 0.
        boundary = float(np.max(np.abs(audio[center].astype(np.float64)-
                                       audio[center-1].astype(np.float64))))
        before_side, before_corr = stereo(before)
        after_side, after_corr = stereo(after)
        rows.append(dict(source=source, initial=initial, target=target,
                         frames=len(audio), finite=finite,
                         peak=float(np.max(np.abs(audio))),
                         published_frames=prefix, published_equal=equal,
                         first_difference=first_difference,
                         first_diff_minus_applied=first_difference-applied,
                         first_diff_minus_published=first_difference-published,
                         boundary_derivative=boundary,
                         local_derivative_p99=local_p99,
                         before_side_mid=before_side, after_side_mid=after_side,
                         before_correlation=before_corr, after_correlation=after_corr))
        if source in ("mix", "drums", "vocal") and (initial, target) in (
                ("1.00", "1.50"), ("1.50", "1.00"),
                ("1.00", "2.00"), ("0.40", "2.00")):
            start = max(0, center-round(rate*.6))
            stop = min(len(audio), center+round(rate*1.2))
            write_float(audition / f"{name}_gain045.wav",
                        np.asarray(audio[start:stop]*np.float32(.45), dtype=np.float32), rate)
            fixed_stop = min(len(baseline), stop)
            write_float(audition / f"{name}_initial_fixed_gain045.wav",
                        np.asarray(baseline[start:fixed_stop]*np.float32(.45),
                                   dtype=np.float32), rate)
        print(name, "prefix", equal, "finite", finite, flush=True)
    with (OUT / "diagnostics.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
