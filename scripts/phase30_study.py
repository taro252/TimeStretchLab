#!/usr/bin/env python3
"""Reproduce Phase 30 fixed and one-change PCM comparisons without altering Golden."""
import argparse
import csv
import filecmp
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("mix", "vocal", "bass", "drums", "guitar")
FIXED = ("0.50", "0.60", "0.70", "0.75", "0.80")
PAIRS = (("0.50", "0.70"), ("0.70", "0.50"), ("0.60", "0.80"),
         ("0.80", "0.60"), ("0.75", "0.70"), ("0.70", "0.75"),
         ("0.90", "1.00"), ("1.00", "0.90"))


def run(executable, source, initial, target, seconds, output, golden=None):
    command = [str(executable), str(source), initial, target, str(seconds),
               str(output)]
    if golden is not None:
        command.append(str(golden))
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=900)
    if result.returncode:
        raise RuntimeError(f"{command}: {result.stdout}\n{result.stderr}")
    data = dict(line.split("=", 1) for line in result.stdout.splitlines()
                if "=" in line)
    data["wall_seconds"] = f"{time.monotonic() - started:.4f}"
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixed", action="store_true")
    parser.add_argument("--switch", action="store_true")
    args = parser.parse_args()
    if not (args.fixed or args.switch):
        args.fixed = args.switch = True
    executable = ROOT / "build/phase30_playback_tests"
    destination = ROOT / "results/phase30"
    destination.mkdir(parents=True, exist_ok=True)
    inputs = ROOT / "results/phase12/golden/input"
    golden12 = ROOT / "results/phase12/golden/raw"
    golden28 = ROOT / "results/phase28/golden/raw"
    with tempfile.TemporaryDirectory(prefix="phase30-") as temporary:
        output = Path(temporary) / "comparison.wav"
        if args.fixed:
            rows = []
            for source in SOURCES:
                for speed in FIXED:
                    code = speed.replace(".", "")
                    golden = (golden12 if speed in ("0.50", "0.75")
                              else golden28) / f"{source}_{code}.wav"
                    data = run(executable, inputs / f"{source}.wav",
                               speed, speed, -1, output, golden)
                    same = filecmp.cmp(output, golden, shallow=False)
                    rows.append({"source": source, "speed": speed,
                                 "byte_identical": int(same), **data})
                    print("fixed", source, speed, "bytes", int(same), flush=True)
                    if not same:
                        raise AssertionError(f"Golden bytes differ: {source} {speed}")
            write(destination / "fixed.csv", rows)
        if args.switch:
            rows = []
            for source in SOURCES:
                for initial, target in PAIRS:
                    data = run(executable, inputs / f"{source}.wav",
                               initial, target, 4.0, output)
                    rows.append({"source": source, "initial": initial,
                                 "target": target, **data})
                    print("switch", source, initial, target,
                          "identical", data["pcm_identical"], flush=True)
            write(destination / "switch.csv", rows)


def write(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
