#!/usr/bin/env python3
"""Real-interval callback simulation for guarded density transitions."""
import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase42/paced"
OUT.mkdir(parents=True, exist_ok=True)
cases = []
for source in ("mix", "drums"):
    for before, after in ((.4, 2), (2, .4)):
        for callback in (64, 128, 256, 512, 1024):
            cases.append((source, before, after, callback, 0, 1))
for source in ("mix", "drums", "vocal", "bass", "guitar"):
    cases.append((source, .4, 2, 512, 70, 1))
    cases.append((source, 2, .4, 512, 70, 1))
for repeat in (2, 3):
    cases.append(("mix", .4, 2, 512, 70, repeat))
    cases.append(("drums", 2, .4, 512, 70, repeat))
rows = []
for source, before, after, callback, load, repeat in cases:
    label = f"{source}_{before:.2f}_{after:.2f}_{callback}_{load}_{repeat}"
    plan = OUT / f"{label}_plan.csv"
    command = [ROOT / "build/phase40_paced_sim",
               ROOT / f"results/phase31/input/{source}.wav", before, after, 1.0,
               "C", callback, 16384, 12288, 2048, load, plan, "safe-density"]
    proc = subprocess.run(list(map(str, command)), cwd=ROOT, capture_output=True, text=True)
    (OUT / f"{label}.log").write_text(proc.stdout + proc.stderr)
    stats = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    rows.append(dict(case=label, source=source, before=before, after=after,
                     callback=callback, load=load, repeat=repeat, exit=proc.returncode,
                     **stats))
    print(label, "exit", proc.returncode, "missing", stats.get("missing_frames"), flush=True)
with (OUT / "summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(row.keys() for row in rows))),
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
if any(int(row["exit"]) or int(row.get("missing_frames", "1")) or
       int(row.get("rejected_writes", "1")) or int(row.get("callback_overruns", "1"))
       for row in rows):
    raise SystemExit("Paced callback failures; see summary.csv")
