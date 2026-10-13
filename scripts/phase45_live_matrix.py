#!/usr/bin/env python3
"""Serial real-device runs: no competing validation jobs during the normal cases."""
import argparse
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--minutes', default='3,5,10')
parser.add_argument('--sources', default='mix,drums')
parser.add_argument('--loads', default='normal,stress')
args = parser.parse_args()
failed = False
for source in args.sources.split(','):
    for load in args.loads.split(','):
        schedule = root / 'results/phase45' / ('repeated.csv' if load == 'stress' else 'forward.csv')
        command = ['python3', str(root / 'scripts/phase44_live_check.py'), '--source', source,
                   '--minutes', args.minutes, '--schedule', str(schedule),
                   '--output', str(root / 'results/phase45/live')]
        if load == 'stress': command.append('--stress')
        print('live_batch_start', source, load, args.minutes, flush=True)
        result = subprocess.run(command, cwd=root)
        failed |= result.returncode != 0
if failed: raise SystemExit('Some device runs FAIL; retained in cumulative summary')
