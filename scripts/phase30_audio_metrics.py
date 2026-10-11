#!/usr/bin/env python3
"""Measure Phase 30 synthetic click/sine transitions against replayed PCM."""
import csv
import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from phase29_analyze import click_peaks, frequency, spectral_stereo
from phase29_study import wav

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (("0.50", "0.70"), ("0.70", "0.50"), ("0.60", "0.80"),
         ("0.80", "0.60"), ("0.75", "0.70"), ("0.70", "0.75"),
         ("0.90", "1.00"), ("1.00", "0.90"))


def main():
    rows = []
    with tempfile.TemporaryDirectory(prefix="phase30-metrics-") as temp:
        output = Path(temp) / "capture.wav"
        for source in ("click", "sine"):
            for initial, target in PAIRS:
                command = (str(ROOT / "build/phase30_playback_tests"),
                           str(ROOT / f"results/phase29/input/{source}.wav"),
                           initial, target, "2.0", str(output))
                result = subprocess.run(command, check=True, capture_output=True,
                                        text=True, timeout=120)
                data = dict(line.split("=", 1) for line in result.stdout.splitlines()
                            if "=" in line)
                samples, rate = wav(output)
                applied = int(data["applied_output"])
                start = min(len(samples), applied + rate // 4)
                end = min(len(samples), start + rate * 2)
                region = np.asarray(samples[start:end], dtype=np.float64)
                stereo = spectral_stereo(region) if len(region) >= 4096 else (math.nan, math.nan)
                mono = np.mean(region, axis=1)
                derivative = np.abs(np.diff(mono))
                around = np.asarray(samples[max(1, applied - 512):
                                            min(len(samples), applied + 512)],
                                    dtype=np.float64)
                local_step = float(np.max(np.abs(np.diff(np.mean(around, axis=1)))))
                row = {"source": source, "initial": initial, "target": target,
                       "output_frames": len(samples), "applied_output": applied,
                       "peak": float(np.max(np.abs(samples))),
                       "finite": int(np.isfinite(samples).all()),
                       "local_max_step": local_step,
                       "region_step_p99": float(np.percentile(derivative, 99)),
                       "frequency_hz": frequency(region, rate) if source == "sine"
                       else math.nan,
                       "click_count": len(click_peaks(np.asarray(samples), rate))
                       if source == "click" else 0,
                       "ipd_rms": stereo[0], "ild_rms_db": stereo[1],
                       "pcm_identical": data["pcm_identical"]}
                if not row["finite"] or row["pcm_identical"] != "1":
                    raise AssertionError(f"Invalid synthetic output: {row}")
                rows.append(row)
                print(source, initial, target, row["frequency_hz"], flush=True)
    output = ROOT / "results/phase30/synthetic_metrics.csv"
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
