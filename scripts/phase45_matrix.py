#!/usr/bin/env python3
"""Repeat the same schedule for BCD candidates, preserve every verdict/run."""
import argparse
from pathlib import Path
from phase45_paced import ROOT, run

parser = argparse.ArgumentParser()
parser.add_argument('--sources', default='mix,drums')
parser.add_argument('--minutes', default='3')
parser.add_argument('--candidates', default='A,B,C,D')
parser.add_argument('--loads', default='0,70')
parser.add_argument('--repeat', type=int, default=2)
parser.add_argument('--callbacks', default='512')
parser.add_argument('--output', type=Path, default=ROOT / 'results/phase45/matrix')
args = parser.parse_args()
failed = False
for source_name in args.sources.split(','):
    for minutes in map(int, args.minutes.split(',')):
        source = ROOT / ('results/phase14/benchmark' if source_name == 'mix' else 'results/phase40/long_input') / f'{source_name}_repeat_{minutes*60}.wav'
        for callback in map(int, args.callbacks.split(',')):
            for load in map(float, args.loads.split(',')):
                # Interleave candidates within each repeat, avoid measuring all
                # A cases at one system load and all B cases at another.
                for repeat in range(args.repeat):
                    for candidate in args.candidates.split(','):
                        row, _ = run(source, args.output, callback=callback,
                            dsp=1024 if candidate == 'C' else 2048,
                            lead=14336 if candidate == 'D' else 12288,
                            qos=candidate == 'B', load=load, label=candidate)
                        failed |= row['OVERALL_REALTIME'] != 'PASS'
                        print('matrix_progress', source_name, minutes, callback, load,
                              repeat+1, candidate, flush=True)
if failed: raise SystemExit('Matrix has FAIL/INDETERMINATE; every run retained')
