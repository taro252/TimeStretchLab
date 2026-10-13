#!/usr/bin/env python3
import argparse
import csv
from collections import defaultdict
from pathlib import Path
from statistics import median, mean
import math

parser = argparse.ArgumentParser()
parser.add_argument('summary', type=Path)
args = parser.parse_args()
groups = defaultdict(list)
for row in csv.DictReader(args.summary.open()):
    run_dir = args.summary.parent / 'runs' / row['run_id']
    callbacks = run_dir / 'plan.csv.callbacks.csv'
    if callbacks.exists():
        active = [int(event['available']) for event in csv.DictReader(callbacks.open())
                  if int(event['pcm_consumed']) + int(row['lead_config']) < int(row['output_frames'])]
        row['fifo_minimum_active'] = min(active, default=-1)
    workers = run_dir / 'plan.csv.workers.csv'
    if workers.exists():
        gaps = sorted(float(event['cycle_wall_s']) for event in csv.DictReader(workers.open())
                      if int(event['output_start']) > 0)
        if gaps:
            row['publication_gap_max'] = gaps[-1]
            row['publication_gap_p95'] = gaps[max(0, math.ceil(len(gaps)*0.95)-1)]
            row['publication_gap_p99'] = gaps[max(0, math.ceil(len(gaps)*0.99)-1)]
    key = (Path(row['source']).name, row['label'], row['load_config'], row['callback_config'])
    groups[key].append(row)
out = []
for key, rows in groups.items():
    number = lambda name: [float(row[name]) for row in rows if row.get(name) not in (None, '')]
    maximum = lambda name: max(number(name), default=-1)
    delays = sorted(number('applied_callback_delay_ms'))
    out.append(dict(source=key[0], candidate=key[1], load=key[2], callback=key[3], runs=len(rows),
        supply_fail_runs=sum(r['SUPPLY_INTEGRITY'] == 'FAIL' for r in rows),
        supply_fail_rate=sum(r['SUPPLY_INTEGRITY'] == 'FAIL' for r in rows)/len(rows),
        invalid_runs=sum(r['SIMULATION_VALIDITY'] == 'INVALID' for r in rows),
        valid_runs=sum(r['SIMULATION_VALIDITY'] == 'VALID' for r in rows),
        realtime_pass_runs=sum(r['OVERALL_REALTIME'] == 'PASS' for r in rows),
        pcm_match_runs=sum(r['PCM_CORRECTNESS'] == 'PASS' for r in rows),
        missing_total=sum(number('missing_frames')),
        max_publication_gap_ms=maximum('publication_gap_max')*1000,
        max_p95_gap_ms=maximum('publication_gap_p95')*1000,
        max_p99_gap_ms=maximum('publication_gap_p99')*1000,
        fifo_minimum=min(number('fifo_minimum'), default=-1), fifo_high_water=maximum('fifo_high_water'),
        fifo_minimum_active=min(number('fifo_minimum_active'), default=-1),
        max_wake_ms=maximum('max_wake_seconds')*1000,
        max_switch_delay_ms=maximum('applied_callback_delay_ms'),
        median_switch_delay_ms=median(delays) if delays else -1,
        p95_switch_delay_ms=delays[max(0, math.ceil(len(delays)*0.95)-1)] if delays else -1,
        mean_cpu_user_seconds=mean(number('cpu_user_seconds')) if number('cpu_user_seconds') else -1,
        mean_cpu_system_seconds=mean(number('cpu_system_seconds')) if number('cpu_system_seconds') else -1,
        max_rss_bytes=maximum('peak_rss_bytes')))
path = args.summary.with_name('grouped.csv')
with path.open('w', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=out[0].keys(), lineterminator='\n')
    writer.writeheader();writer.writerows(out)
print('groups', len(out), path)
