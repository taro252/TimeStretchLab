#!/usr/bin/env python3
"""Measure one bidirectional speed request through the real macOS audio path."""
import argparse
import csv
import os
import pathlib
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="build/phase26_play")
    parser.add_argument("--input-dir", default="results/phase12/golden/input")
    parser.add_argument("--output-dir", default="results/phase26/diagnostics")
    parser.add_argument("--sources", nargs="+", default=["mix", "vocal", "bass", "drums", "guitar"])
    parser.add_argument("--positions", nargs="+", type=float, default=[3.0])
    parser.add_argument("--initial", nargs="+", default=["050", "075"])
    parser.add_argument("--profiles", nargs="+", default=["A", "BCD"])
    parser.add_argument("--stress", action="store_true")
    parser.add_argument("--name", default="study")
    args = parser.parse_args()
    destination = pathlib.Path(args.output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    rows = []
    environment = dict(os.environ, PHASE25_SILENT="1")
    if args.stress:
        environment["PHASE25_STRESS"] = "1"
    for source in args.sources:
        for position in args.positions:
            for initial in args.initial:
                for profile in args.profiles:
                    file = pathlib.Path(args.input_dir) / (source + ".wav")
                    command = [args.binary, str(file), initial, str(position),
                               str(position + 3), profile]
                    run = subprocess.run(command, capture_output=True, text=True,
                                         env=environment, timeout=60)
                    label = f"{source}_{position:g}_{initial}_{profile}{'_stress' if args.stress else ''}"
                    (destination / (label + ".log")).write_text(run.stdout + run.stderr)
                    row = dict(source=source, request_seconds=position,
                               initial=initial, profile=profile,
                               stress=int(args.stress), exit_code=run.returncode)
                    for line in run.stdout.splitlines():
                        if "=" in line:
                            key, value = line.split("=", 1)
                            row[key] = value
                    rows.append(row)
                    print(label, "exit", run.returncode,
                          "callback_ms", row.get("applied_callback_after_request_ms"),
                          "underrun", row.get("underrun_frames"), flush=True)
                    if run.returncode:
                        raise RuntimeError(f"{label}: {run.stderr.strip()}")
    output = destination / (args.name + ".csv")
    with output.open("w", newline="") as stream:
        fields = sorted(set().union(*(item.keys() for item in rows)))
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(output)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
