#!/usr/bin/env python3
"""Measure wall/CPU stalls in the guarded research worker without changing DSP."""
import csv
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase42/profiles"
OUT.mkdir(parents=True, exist_ok=True)


def run(source, minutes, profile, load, repeat):
    label = f"{source}_{minutes}m_{'on' if profile else 'off'}_{'load' if load else 'normal'}_{repeat}"
    audio = (ROOT / f"results/phase14/benchmark/mix_repeat_{minutes*60}.wav"
             if source == "mix" else ROOT / f"results/phase40/long_input/drums_repeat_{minutes*60}.wav")
    command = [ROOT / "build/phase39_sim", audio, "-", .4, "1.0:2.0", 512,
               OUT / f"{label}_plan.csv", 2048, "C", "safe-density"]
    if profile:
        command.append(OUT / f"{label}_top20.csv")
    burners = []
    try:
        if load:
            for _ in range(3):
                burners.append(subprocess.Popen(["yes"], stdout=subprocess.DEVNULL))
        begin = time.monotonic()
        proc = subprocess.run(list(map(str, command)), cwd=ROOT,
                              text=True, capture_output=True)
        elapsed = time.monotonic() - begin
    finally:
        for item in burners:
            item.terminate()
        for item in burners:
            item.wait()
    (OUT / f"{label}.log").write_text(proc.stdout + proc.stderr)
    stats = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    print(label, "exit", proc.returncode, "worker max", stats.get("max_worker_chunk_seconds"), flush=True)
    return dict(case=label, source=source, minutes=minutes, profile=int(profile),
                load=int(load), repeat=repeat, elapsed=elapsed, exit=proc.returncode,
                **stats)


rows = []
for source in ("mix", "drums"):
    for minutes in (3, 5, 10):
        rows.append(run(source, minutes, True, False, 1))
        rows.append(run(source, minutes, False, False, 1))
    for repeat in (1, 2):
        rows.append(run(source, 3, True, True, repeat))
        rows.append(run(source, 3, False, True, repeat))
with (OUT / "summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(row.keys() for row in rows))),
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
if any(int(row["exit"]) for row in rows):
    raise SystemExit("Worker profiling failed; see summary.csv")
