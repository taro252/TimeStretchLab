#!/usr/bin/env python3
"""Join an xctrace thread-state export to profiled DSP blocks by wall time/TID."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from bisect import bisect_right
from datetime import datetime
from pathlib import Path

from lxml import etree


def collect_states(xml: Path, target_tid: int):
    starts: dict[str, int] = {}
    states: dict[str, str] = {}
    threads: dict[str, int] = {}
    rows = []
    for _, row in etree.iterparse(str(xml), events=("end",), tag="row"):
        cells = list(row)
        if len(cells) < 4:
            row.clear()
            continue
        start, thread, state, duration = cells[:4]
        if start.get("id") and start.text:
            starts[start.get("id")] = int(start.text)
        if state.get("id") and state.text:
            states[state.get("id")] = state.text
        if thread.get("id"):
            tid = thread.find("tid")
            if tid is not None and tid.text:
                threads[thread.get("id")] = int(tid.text)
        tid = threads.get(thread.get("ref") or thread.get("id"))
        if tid == target_tid:
            at = starts.get(start.get("ref") or start.get("id"))
            name = states.get(state.get("ref") or state.get("id"))
            if at is not None and name and duration.text:
                rows.append((at, at + int(duration.text), name))
        row.clear()
        while row.getprevious() is not None:
            del row.getparent()[0]
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("toc", type=Path)
    parser.add_argument("states", type=Path)
    parser.add_argument("blocks", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    trace_start = etree.parse(str(args.toc)).findtext(".//start-date")
    if not trace_start:
        raise SystemExit("Trace start date missing")
    trace_start_ns = int(datetime.fromisoformat(trace_start).timestamp() * 1e9)
    blocks = list(csv.DictReader(args.blocks.open()))
    if not blocks:
        raise SystemExit("No profiled blocks")
    tid = int(blocks[0]["thread_id"])
    intervals = collect_states(args.states, tid)
    if not intervals:
        raise SystemExit(f"No thread state for TID {tid}")
    intervals.sort(key=lambda item: item[0])
    begins = [item[0] for item in intervals]
    rows = []
    for block in blocks:
        first = int(block["start_unix_ns"]) - trace_start_ns
        last = int(block["end_unix_ns"]) - trace_start_ns
        totals = defaultdict(int)
        for index in range(max(0, bisect_right(begins, first) - 1), len(intervals)):
            begin, end, state = intervals[index]
            if begin >= last:
                break
            overlap = max(0, min(last, end) - max(first, begin))
            if overlap:
                totals[state] += overlap
        covered = sum(totals.values())
        rows.append(dict(output_start=block["output_start"],
                         block_wall_ms=float(block.get("worker_cycle_wall_s",
                                                       block.get("cycle_wall_s", 0))) * 1000,
                         block_cpu_ms=float(block.get("worker_cycle_cpu_s",
                                                      block.get("cycle_cpu_s", 0))) * 1000,
                         dsp_compute_wall_ms=float(block.get("dsp_compute_wall_s",
                                                             block.get("dsp_wall_s", 0))) * 1000,
                         dsp_compute_cpu_ms=float(block.get("dsp_compute_cpu_s",
                                                            block.get("dsp_cpu_s", 0))) * 1000,
                         trace_start_ms=first / 1e6, trace_end_ms=last / 1e6,
                         trace_coverage_ms=covered / 1e6,
                         trace_unclassified_ms=max(0, last-first-covered) / 1e6,
                         **{f"{name.lower()}_ms": totals[name] / 1e6
                            for name in ("Running", "Runnable", "Preempted", "Interrupted",
                                         "Blocked", "Unknown")}))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"tid": tid, "thread_states": len(intervals),
                      "largest_block": max(rows, key=lambda row: row["block_wall_ms"]),
                      "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
