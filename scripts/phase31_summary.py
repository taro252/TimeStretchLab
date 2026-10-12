#!/usr/bin/env python3
"""Aggregate measured Phase 31 geometry without inferring subjective quality."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "results/phase31"
files = sorted((TARGET / "metrics").glob("*.csv"))
if len(files) != 7:
    raise RuntimeError("Seven source geometry tables are required")
rows = [row for path in files for row in csv.DictReader(path.open())]
speeds = sorted({float(row["speed"]) for row in rows})
out = []
for speed in speeds:
    subset = [row for row in rows if float(row["speed"]) == speed]
    by_mode = {mode: [row for row in subset if row["mode"] == mode]
               for mode in "ABC"}
    def hop_ratio(mode):
        return max(int(row["hop_max"]) / int(row["window"])
                   for row in by_mode[mode])
    def minimum_weight(mode):
        return min(float(row["min_hann2_weight_worst_gap"])
                   for row in by_mode[mode])
    out.append({
        "speed": f"{speed:.2f}",
        "ratio": f"{1 / speed:.12g}",
        "nominal_low_hop": f"{2048 / speed:.2f}",
        "nominal_mid_hop": f"{1024 / speed:.2f}",
        "nominal_high_hop": f"{256 / speed:.2f}",
        "A_max_hop_over_window": f"{hop_ratio('A'):.6f}",
        "A_outside_window_intervals": sum(int(row["ge_window"])
                                          for row in by_mode["A"]),
        "A_min_hann2_weight": f"{minimum_weight('A'):.9g}",
        "B_max_hop_over_window": f"{hop_ratio('B'):.6f}",
        "B_min_hann2_weight": f"{minimum_weight('B'):.9g}",
        "C_max_hop_over_window": f"{hop_ratio('C'):.6f}",
        "C_min_hann2_weight": f"{minimum_weight('C'):.9g}",
        "B_max_frame_multiplier": f"{max(int(row['frames']) /
                                         max(1, int(next(a['frames'] for a in by_mode['A']
                                                         if a['source'] == row['source'] and
                                                         a['resolution'] == row['resolution'])))
                                         for row in by_mode['B']):.3f}",
        "C_max_frame_multiplier": f"{max(int(row['frames']) /
                                         max(1, int(next(a['frames'] for a in by_mode['A']
                                                         if a['source'] == row['source'] and
                                                         a['resolution'] == row['resolution'])))
                                         for row in by_mode['C']):.3f}",
        "event_protection_changed": any(row["protection_changed"] == "1"
                                        for row in by_mode["A"]),
        "anchor_changed": any(row["anchor_changed"] == "1"
                              for row in by_mode["A"]),
    })
with (TARGET / "geometry_summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=out[0].keys(), lineterminator="\n")
    writer.writeheader()
    writer.writerows(out)
print(f"Summarized {len(rows)} rows at {len(speeds)} speeds")
