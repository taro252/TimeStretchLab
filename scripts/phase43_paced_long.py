#!/usr/bin/env python3
"""Compatibility CLI; Phase 45 keeps clock validity and PCM replay independent."""
import os
from pathlib import Path
from phase45_paced import ROOT, run

out = Path(os.environ.get('PHASE44_PACED_OUT', ROOT / 'results/phase45/paced'))
source_name = os.environ.get('PHASE44_SOURCE', 'mix')
if source_name not in ('mix', 'drums'): raise SystemExit('Unknown source')
failed = False
for minutes in map(int, os.environ.get('PHASE44_MINUTES', '3,5,10').split(',')):
    source = ROOT / ('results/phase14/benchmark' if source_name == 'mix' else 'results/phase40/long_input') / f'{source_name}_repeat_{minutes*60}.wav'
    row, _ = run(source, out,
        callback=int(os.environ.get('PHASE44_CALLBACK', '512')),
        dsp=int(os.environ.get('PHASE44_DSP_BLOCK', '2048')),
        lead=int(os.environ.get('PHASE44_LEAD', '12288')),
        load=float(os.environ.get('PHASE44_LOAD', '0')),
        qos='PHASE44_WORKER_QOS' in os.environ,
        label='legacy_BCD')
    failed |= row['OVERALL_REALTIME'] != 'PASS'
    print(minutes, 'minutes', row['OVERALL_REALTIME'], flush=True)
if failed: raise SystemExit('Realtime FAIL/INDETERMINATE; cumulative summary retained')
