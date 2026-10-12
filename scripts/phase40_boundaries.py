#!/usr/bin/env python3
"""Join planner frontiers with unchanged transient events and compensation ranges."""
import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase40"
rows = []
events_by_source = {}
for source in ("mix", "vocal", "bass", "drums", "guitar"):
    result = subprocess.run([str(ROOT / "build/phase38_events"),
                             str(ROOT / "results/phase31/input" / f"{source}.wav"),
                             "2.0", "B"], cwd=ROOT, text=True, capture_output=True, check=True)
    events_by_source[source] = list(csv.DictReader(result.stdout.splitlines()))

for plan in csv.DictReader((OUT / "comparison.csv").open(newline="")):
    if plan["reference"]!="match":
        continue
    events = events_by_source[plan["source"]]
    mutable = int(plan["first_mutable_frame"])
    applied = int(plan["first_safe_frame"])
    preceding = [event for event in events if int(event["peak_frame"])<=mutable]
    following = [event for event in events if int(event["peak_frame"])>mutable]
    previous_peak = int(preceding[-1]["peak_frame"]) if preceding else 0
    next_peak = int(following[0]["peak_frame"]) if following else -1
    protected = [event for event in events if
                 int(event["onset_frame"])-2<=applied<=max(
                     int(event["end_frame"]), int(event["peak_frame"]))+5]
    next_protected = [event for event in events if
                      int(event["onset_frame"])-2>applied]
    near = protected[0] if protected else (next_protected[0] if next_protected else None)
    rows.append(dict(source=plan["source"], **{"from":plan["from"]},
                     to=plan["to"],planner=plan["planner"],
                     requested_output=plan["requested_output"],
                     published_output=plan["published"],
                     processed_fence_output=plan["fence"],
                     current_compensation_start_frame=previous_peak,
                     current_compensation_end_frame=next_peak,
                     next_protection_start_frame=(max(0,int(near["onset_frame"])-2)
                                                  if near else -1),
                     next_protection_end_frame=(max(int(near["end_frame"]),
                                                    int(near["peak_frame"]))+5
                                                if near else -1),
                     anchor_confident=int(near["anchor_confident"]) if near else -1,
                     first_mutable_frame=mutable,first_safe_frame=applied,
                     actual_applied_output=plan["applied_output"],
                     completion_output=plan["completion_output"],
                     first_changed_pcm=plan["first_changed_pcm"]))

with (OUT / "boundaries.csv").open("w",newline="") as file:
    writer=csv.DictWriter(file,fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print(len(rows),"planner/event boundary rows")
