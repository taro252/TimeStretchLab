#!/usr/bin/env python3
"""Independent PCM replay and immutable-prefix audit for the Phase 42 guard."""
from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path

import numpy as np
from phase32_study import read, wav

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase42"
CASES = [
    ("040_100", .4, "1.0:1.0"), ("040_150", .4, "1.0:1.5"),
    ("040_200", .4, "1.0:2.0"), ("045_200", .45, "1.0:2.0"),
    ("050_200", .5, "1.0:2.0"), ("100_200", 1, "1.0:2.0"),
    ("200_100", 2, "1.0:1.0"), ("200_050", 2, "1.0:0.5"),
    ("200_040", 2, "1.0:0.4"), ("150_040", 1.5, "1.0:0.4"),
    ("multi_1", .4, "1.0:2.0,3.0:0.4"),
    ("multi_2", .4, "1.0:1.0,3.0:2.0"),
    ("multi_3", 2, "1.0:0.75,3.0:0.4"),
    ("multi_4", .5, "1.0:2.0,3.0:0.5"),
    ("multi_5", .4, "1.0:0.75,3.0:1.5,5.0:2.0"),
]


def run(args):
    completed = subprocess.run(list(map(str, args)), cwd=ROOT, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))}\n{completed.stdout}\n{completed.stderr}")
    return dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    rows = []
    fixed_cache = {}
    for source in ("mix", "drums", "vocal", "guitar", "bass"):
        selected = CASES if source == "mix" else CASES[:10] if source == "drums" else [CASES[2], CASES[8]]
        input_wav = ROOT / f"results/phase31/input/{source}.wav"
        for label, initial, schedule in selected:
            name = f"{source}_{label}"
            raw = OUT / "raw" / f"{name}.wav"
            reference = OUT / "reference" / f"{name}.wav"
            plan = OUT / "plans" / f"{name}.csv"
            for path in (raw, reference, plan):
                path.parent.mkdir(parents=True, exist_ok=True)
            metrics = run([ROOT / "build/phase39_sim", input_wav, raw, initial,
                           schedule, 512, plan, 2048, "C", "safe-density"])
            run([ROOT / "build/phase39_reference", input_wav, reference,
                 initial, plan, "C", "safe-density"])
            equal = digest(raw) == digest(reference)
            if not equal:
                raise AssertionError(f"Independent offline PCM mismatch: {name}")
            rate, audio = read(raw)
            if not np.isfinite(audio).all():
                raise AssertionError(f"Nonfinite PCM: {name}")
            plans = list(csv.DictReader(plan.open()))
            key = (source, initial)
            if key not in fixed_cache:
                fixed = OUT / "fixed" / f"{source}_{initial:.2f}.wav"
                fixed.parent.mkdir(parents=True, exist_ok=True)
                run([ROOT / "build/phase39_sim", input_wav, fixed,
                     initial, "-", 512])
                fixed_cache[key] = read(fixed)[1]
            published = int(plans[0]["published"])
            prefix_equal = np.array_equal(audio[:published], fixed_cache[key][:published])
            if not prefix_equal:
                raise AssertionError(f"Published PCM changed: {name}")
            if source in ("mix", "drums") and label == "040_200":
                phase41 = ROOT / f"results/phase41/{source}_040_to_200_C_delay_density.wav"
                records = {item["name"]: item for item in
                           csv.DictReader((ROOT / "results/phase41/manifest.csv").open())}
                expected = records[f"{source}_delay_density"]["sha256"]
                if digest(raw) != expected or (phase41.exists() and digest(raw) != digest(phase41)):
                    raise AssertionError(f"Phase 41 delayed-density regression: {source}")
            if source in ("mix", "drums", "vocal", "guitar", "bass") and label in ("040_200", "200_040"):
                center = int(plans[0]["applied_output"])
                excerpt = np.array(audio[max(0, center - rate):min(len(audio), center + 3 * rate)]
                                   * np.float32(.4), dtype=np.float32)
                wav(OUT / "audition" / f"{name}_gain040.wav", excerpt, rate)
            rows.append(dict(case=name, source=source, speed=initial, schedule=schedule,
                             requests=len(plans), frames=len(audio), sha256=digest(raw),
                             offline_exact=int(equal), published_exact=int(prefix_equal),
                             peak=float(np.max(np.abs(audio))),
                             plan_ms=metrics.get("plan_cpu_ms"),
                             worker_max_s=metrics.get("max_worker_chunk_seconds"),
                             rss_bytes=metrics.get("peak_rss_bytes"),
                             density_input=";".join(p["density_input"] for p in plans),
                             density_weight_min=min((float(p[x]) for p in plans for x in
                                                    ("density_weight_low", "density_weight_mid", "density_weight_high")
                                                    if float(p[x]) > 0), default=0)))
            print(name, "exact", equal, "frames", len(audio), flush=True)
    with (OUT / "validation.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
