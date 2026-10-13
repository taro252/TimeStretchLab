#!/usr/bin/env python3
"""Correlate native callback shortfalls/stock with worker publication cycles."""
import argparse
import csv
import json
from bisect import bisect_right
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path)
args = parser.parse_args()
path = args.directory
callbacks = list(csv.DictReader((path / 'callbacks.csv').open()))
workers = list(csv.DictReader((path / 'workers.csv').open()))
ends = [int(row['end_unix_ns']) for row in workers]
events = []
for row in callbacks:
    wanted, received = int(row['wanted']), int(row['received'])
    if received >= wanted: continue
    at = int(row['callback_start_unix_ns'])
    index = bisect_right(ends, at)
    worker = workers[index] if index < len(workers) else {}
    events.append(dict(callback_unix_ns=at, callback_tid=row['thread_id'],
        pcm_before=row['pcm_before'], available=row['available_before'], missing=wanted-received,
        last_publication_unix_ns=row['last_publication_unix_ns'],
        next_publication_unix_ns=worker.get('end_unix_ns', 'unmeasured'),
        worker_output_start=worker.get('output_start', 'unmeasured'),
        worker_tid=worker.get('thread_id', 'unmeasured'),
        cycle_wall_s=worker.get('cycle_wall_s', 'unmeasured'),
        cycle_cpu_s=worker.get('cycle_cpu_s', 'unmeasured')))
with (path / 'supply_events.json').open('w') as stream:
    json.dump(events, stream, indent=2)
peak = max(workers, key=lambda row: float(row['cycle_wall_s']))
stock = [int(row['available_before']) for row in callbacks if
         int(peak['start_unix_ns']) <= int(row['callback_start_unix_ns']) <= int(peak['end_unix_ns'])]
result = dict(peak_worker=peak, callbacks_in_peak_period=len(stock),
              minimum_fifo_in_peak=min(stock, default=None), shortage_callbacks=len(events),
              missing_frames=sum(row['missing'] for row in events))
(path / 'peak_period.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
