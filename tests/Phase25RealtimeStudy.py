#!/usr/bin/env python3
"""Repeatable macOS device measurements; raw DSP stays in the worker FIFO."""
import argparse
import csv
import os
import pathlib
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="build/phase25_play")
    parser.add_argument("--input-dir", default="results/phase12/golden/input")
    parser.add_argument("--output-dir", default="results/phase25/diagnostics")
    parser.add_argument("--sources", nargs="+", default=["mix", "vocal", "bass", "drums", "guitar"])
    parser.add_argument("--positions", nargs="+", type=float, default=[1.0, 3.0, 6.0])
    parser.add_argument("--profiles", nargs="+", default=["A", "BCD"])
    parser.add_argument("--stress", action="store_true")
    args = parser.parse_args()
    destination = pathlib.Path(args.output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    env = dict(os.environ, PHASE25_SILENT="1")
    if args.stress:
        env["PHASE25_STRESS"] = "1"
    for source in args.sources:
        path = pathlib.Path(args.input_dir) / (source + ".wav")
        for position in args.positions:
            for profile in args.profiles:
                command = [args.binary, str(path), str(position), str(position + 3), profile]
                result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)
                label = f"{source}_{position:g}_{profile}{'_stress' if args.stress else ''}"
                (destination / (label + ".log")).write_text(result.stdout + result.stderr)
                row = dict(source=source, request_seconds=position, profile=profile,
                           stress=int(args.stress), exit_code=result.returncode)
                for line in result.stdout.splitlines():
                    if "=" in line:
                        key, value = line.split("=", 1)
                        row[key] = value
                rows.append(row)
                print(label, "exit", result.returncode,
                      "callback_ms", row.get("applied_callback_after_request_ms"),
                      "underrun", row.get("underrun_frames"), flush=True)
                if result.returncode:
                    raise RuntimeError(f"{label} failed: {result.stderr.strip()}")
    output = destination / ("study_stress.csv" if args.stress else "study.csv")
    with output.open("w", newline="") as handle:
        fields = sorted(set().union(*(row.keys() for row in rows)))
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
