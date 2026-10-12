#!/usr/bin/env python3
"""Join callback shortfalls with the worker publication timeline."""
import argparse
import csv
import json
from bisect import bisect_right
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("plan_csv", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    workers = list(csv.DictReader(Path(str(args.plan_csv) + ".workers.csv").open()))
    events = list(csv.DictReader(Path(str(args.plan_csv) + ".underruns.csv").open()))
    callback_path = Path(str(args.plan_csv) + ".callbacks.csv")
    callbacks = list(csv.DictReader(callback_path.open())) if callback_path.exists() else []
    callback_positions = {int(row["callback"]): index
                          for index, row in enumerate(callbacks)}
    endings = [int(row["end_unix_ns"]) for row in workers]
    joined = []
    for event in events:
        at = int(event["unix_ns"])
        callback_position = callback_positions.get(int(event["callback"]))
        before = callbacks[max(0, callback_position - 12):callback_position + 1] \
            if callback_position is not None else []
        after = bisect_right(endings, at)
        next_worker = workers[after] if after < len(workers) else None
        previous = workers[after - 1] if after else None
        joined.append({
            "callback": int(event["callback"]),
            "callback_unix_ns": at,
            "missing_frames": int(event["missing"]),
            "available_frames": int(event["available"]),
            "available_previous_12": [int(row["available"]) for row in before],
            "since_last_publish_ms": (at - int(event["last_publication_ns"])) / 1e6,
            "until_next_publish_ms": (int(event["next_publication_ns"]) - at) / 1e6
            if int(event["next_publication_ns"]) else None,
            "wake_late_ms": float(event["wake_late_s"]) * 1e3,
            "callback_duration_ms": float(event["callback_s"]) * 1e3,
            "preceding_output_start": int(previous["output_start"]) if previous else None,
            "next_output_start": int(next_worker["output_start"]) if next_worker else None,
            "next_worker_cycle_wall_ms": float(next_worker["cycle_wall_s"]) * 1e3
            if next_worker else None,
            "next_worker_cycle_cpu_ms": float(next_worker["cycle_cpu_s"]) * 1e3
            if next_worker else None,
            "next_worker_fifo_wait_ms": float(next_worker["fifo_wait_s"]) * 1e3
            if next_worker else None,
            "next_worker_wav_ms": float(next_worker["wav_wall_s"]) * 1e3
            if next_worker else None,
            "next_worker_fft_ms": float(next_worker["fft_wall_s"]) * 1e3
            if next_worker else None,
            "next_worker_phase_ms": float(next_worker["phase_wall_s"]) * 1e3
            if next_worker else None,
            "next_worker_ola_ms": float(next_worker["ola_wall_s"]) * 1e3
            if next_worker else None,
            "next_worker_fir_ms": float(next_worker["fir_wall_s"]) * 1e3
            if next_worker else None,
            "next_worker_plan_ms": float(next_worker["plan_wall_s"]) * 1e3
            if next_worker else None,
            "next_worker_mutex_wait_ms": float(next_worker["mutex_wait_s"]) * 1e3
            if next_worker else None,
        })
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="") as stream:
            if joined:
                writer = csv.DictWriter(stream, fieldnames=joined[0].keys())
                writer.writeheader()
                writer.writerows(joined)
    print(json.dumps({"workers": len(workers), "callbacks": len(callbacks),
                      "underruns": joined}, indent=2))


if __name__ == "__main__":
    main()
