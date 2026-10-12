#!/usr/bin/env python3
"""Reproducible Phase 39 fixed/transition byte comparisons.

The WAVs are local research data; only CSV summaries are intended for Git.
"""
from __future__ import annotations

import csv
import hashlib
import struct
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
OUT = ROOT / "results/phase39"
INPUT = ROOT / "results/phase31/input"


def invoke(args: list[str]) -> str:
    done = subprocess.run([str(x) for x in args], cwd=ROOT, text=True,
                          capture_output=True, check=False)
    if done.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))}: {done.stderr.strip()}")
    return done.stdout


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fixed() -> None:
    rows = []
    speeds = {"040": "0.40", "045": "0.45", "049": "0.49",
              "050": "0.50", "060": "0.60", "070": "0.70",
              "075": "0.75", "080": "0.80", "100": "1.00",
              "110": "1.10", "125": "1.25", "150": "1.50",
              "175": "1.75", "200": "2.00"}
    for source in ("mix", "vocal", "bass", "drums", "guitar"):
        for key, speed in speeds.items():
            if key in ("040", "045", "049"):
                reference = ROOT / f"results/phase34/raw/{source}_B_{key}.wav"
            elif key in ("100", "110", "125", "150", "175", "200"):
                reference = ROOT / f"results/phase37/raw/{source}_B_{key}.wav"
            elif key in ("050", "075"):
                reference = ROOT / f"results/phase12/golden/raw/{source}_{key}.wav"
            else:
                reference = ROOT / f"results/phase28/golden/raw/{source}_{key}.wav"
            if not reference.exists():
                raise FileNotFoundError(reference)
            output = OUT / "fixed" / f"{source}_{key}.wav"
            output.parent.mkdir(parents=True, exist_ok=True)
            input_wav = (ROOT / f"results/phase12/golden/input/{source}.wav"
                         if key in ("050", "060", "070", "075", "080")
                         else INPUT / f"{source}.wav")
            invoke([BUILD / "phase39_sim", input_wav,
                    output, speed, "-", "512"])
            result = "match" if digest(output) == digest(reference) else "mismatch"
            with output.open("rb") as stream:
                header = stream.read(44)
            channels = struct.unpack_from("<H", header, 22)[0]
            frames = (output.stat().st_size-44)//(4*channels)
            rows.append((source, speed, result, digest(output), digest(reference),
                         frames))
            print("fixed", source, speed, result, flush=True)
    with (OUT / "fixed.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("source", "speed", "result", "actual_sha256", "reference_sha256", "frames"))
        writer.writerows(rows)


def transitions() -> None:
    rows = []
    cases = (("1.00", "1.50"), ("1.50", "1.00"),
             ("1.00", "2.00"), ("2.00", "1.00"),
             ("0.75", "1.50"), ("1.50", "0.75"),
             ("0.40", "2.00"), ("2.00", "0.40"))
    for source in ("mix", "vocal", "bass", "drums", "guitar"):
        for initial, target in cases:
            name = f"{source}_{initial.replace('.', '')}_to_{target.replace('.', '')}"
            wav = OUT / "variable" / f"{name}.wav"
            ref = OUT / "reference" / f"{name}.wav"
            plan = OUT / "plans" / f"{name}.csv"
            for path in (wav, ref, plan):
                path.parent.mkdir(parents=True, exist_ok=True)
            try:
                details = invoke([BUILD / "phase39_sim", INPUT / f"{source}.wav",
                                  wav, initial, f"1.0:{target}", "512", plan])
            except RuntimeError as error:
                rows.append((source, initial, target, "rejected", "", "", "", "", "", "", "", ""))
                print("transition", name, "rejected", str(error), flush=True)
                continue
            invoke([BUILD / "phase39_reference", INPUT / f"{source}.wav",
                    ref, initial, plan])
            with plan.open(newline="") as stream:
                records = list(csv.DictReader(stream))
            if len(records) != 1:
                raise RuntimeError(f"Expected one plan: {name}")
            result = "match" if digest(wav) == digest(ref) else "mismatch"
            rows.append((source, initial, target, result,
                         records[0]["requested_output"], records[0]["applied_output"],
                         records[0]["completion_output"], records[0]["planning_fence"],
                         records[0]["plan_ms"],
                         next(line for line in details.splitlines()
                              if line.startswith("frames=")),
                         digest(wav), digest(ref)))
            print("transition", name, result, flush=True)
    with (OUT / "transitions.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("source", "from", "to", "result", "request_output",
                         "applied_output", "completion_output", "planning_fence",
                         "plan_ms", "frames", "actual_sha256", "reference_sha256"))
        writer.writerows(rows)


def artificial() -> None:
    sources = {
        "click": INPUT / "click.wav",
        "sine": INPUT / "sine.wav",
        "harmonic": ROOT / "results/phase32/input/harmonic.wav",
        "white_burst": ROOT / "results/phase32/input/white_burst.wav",
        "pink_burst": ROOT / "results/phase32/input/pink_burst.wav",
        "decay_noise": ROOT / "results/phase32/input/decay_noise.wav",
        "dense_click": ROOT / "results/phase37/input/dense_click.wav",
    }
    rows = []
    for source, input_wav in sources.items():
        for initial, target in (("1.00", "2.00"), ("2.00", "0.40")):
            name = f"{source}_{initial.replace('.', '')}_to_{target.replace('.', '')}"
            wav = OUT / "artificial" / f"{name}.wav"
            ref = OUT / "artificial_reference" / f"{name}.wav"
            plan = OUT / "artificial_plans" / f"{name}.csv"
            for path in (wav, ref, plan):
                path.parent.mkdir(parents=True, exist_ok=True)
            try:
                invoke([BUILD / "phase39_sim", input_wav, wav, initial,
                        f"0.5:{target}", "512", plan])
                invoke([BUILD / "phase39_reference", input_wav, ref, initial, plan])
                status = "match" if digest(wav) == digest(ref) else "mismatch"
            except RuntimeError:
                status = "rejected"
            rows.append((source, initial, target, status))
            print("artificial", name, status, flush=True)
    with (OUT / "artificial.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("source", "from", "to", "result"))
        writer.writerows(rows)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("fixed", "transitions", "artificial"):
        raise SystemExit("Usage: phase39_verify.py fixed|transitions|artificial")
    {"fixed": fixed, "transitions": transitions, "artificial": artificial}[sys.argv[1]]()
