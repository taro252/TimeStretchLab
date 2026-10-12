#!/usr/bin/env python3
"""Summarize Phase 40 controls without modifying their comparison WAVs."""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase41_acoustics import OUT, weight_stats

cases = {
    "040_to_100": (115006, 121235, True),
    "040_to_150": (115006, 124161, True),
    "040_to_200": (115006, 184935, True),
    "050_to_200": (92372, 148783, False),
    "100_to_200": (77824, 93050, False),
}
rows = []
for name, (applied, completed, changes_density) in cases.items():
    trace = OUT / f"map_mix_{name}_C.csv"
    points = list(csv.DictReader(trace.open()))
    weights = weight_stats(trace, applied, completed)
    for resolution, label in enumerate(("low", "mid", "high")):
        selected = [row for row in points if int(row["resolution"]) == resolution
                    and applied <= int(row["output_sample"]) < completed]
        hops = [int(row["actual_hop"]) for row in selected]
        swings = [abs(int(row["hop_change"])) for row in selected]
        rows.append(dict(case=name,resolution=label,density_changes=int(changes_density),
                         applied_output=applied,completion_output=completed,
                         min_hop=min(hops),max_hop=max(hops),max_hop_step=max(swings),
                         minimum_hann_squared_weight=weights[resolution][0],
                         min_overlapping_frames=weights[resolution][2]))
with (OUT / "controls.csv").open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=rows[0].keys(), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
print("wrote", len(rows), "resolution controls")
