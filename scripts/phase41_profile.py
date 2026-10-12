#!/usr/bin/env python3
"""Repeat worker timing with a worker-only preallocated top-20 trace."""
import csv
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase41/profiles"
OUT.mkdir(parents=True, exist_ok=True)


def run_case(source, minutes, profile, load, repeat):
    name = f"{source}_{minutes}m_{'on' if profile else 'off'}_{'load' if load else 'normal'}_{repeat}"
    path = (ROOT / "results/phase14/benchmark" / f"mix_repeat_{minutes*60}.wav"
            if source == "mix" else ROOT / "results/phase40/long_input" /
            f"drums_repeat_{minutes*60}.wav")
    args = [str(ROOT / "build/phase39_sim"), str(path), "-", "0.4", "1.0:2.0",
            "512", str(OUT / f"{name}_plan.csv"), "2048", "C"]
    if profile:
        args.extend(("normal", str(OUT / f"{name}_top20.csv")))
    burners = []
    try:
        if load:
            for _ in range(3):
                burners.append(subprocess.Popen(["yes"], stdout=subprocess.DEVNULL))
        started = time.monotonic()
        proc = subprocess.run(args, text=True, capture_output=True, cwd=ROOT)
        elapsed = time.monotonic() - started
    finally:
        for item in burners:
            item.terminate()
        for item in burners:
            item.wait()
    (OUT / f"{name}.log").write_text(proc.stdout + proc.stderr)
    stats = dict(line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line)
    result = dict(case=name, source=source, minutes=minutes, profile=int(profile),
                  load=int(load), repeat=repeat, exit=proc.returncode,
                  elapsed=elapsed, **stats)
    print(name, "exit", proc.returncode, "max wall", stats.get("max_worker_chunk_seconds"),
          "max CPU", stats.get("max_worker_cpu_seconds"), flush=True)
    return result


def main():
    rows = []
    for source in ("mix", "drums"):
        for minutes in (3, 5, 10):
            rows.append(run_case(source, minutes, True, False, 1))
            rows.append(run_case(source, minutes, False, False, 1))
        rows.append(run_case(source, 3, True, True, 1))
        rows.append(run_case(source, 3, False, True, 1))
        rows.append(run_case(source, 3, True, False, 2))
    with (OUT / "summary.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=sorted(set().union(*(row.keys() for row in rows))), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
