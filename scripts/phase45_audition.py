#!/usr/bin/env python3
"""Same fixed playback gain, five isolated known-file listening checks."""
import argparse
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--silent', action='store_true')
args = parser.parse_args()
failed = False
for source in ('mix', 'drums', 'vocal', 'guitar', 'bass'):
    print('試聴素材:', source, '0.40→2.00（要求は入力開始後の出力1秒）', flush=True)
    command = ['python3', str(root / 'scripts/phase44_live_check.py'), '--source', source,
               '--input', str(root / f'results/phase31/input/{source}.wav'), '--minutes', '1',
               '--schedule', str(root / 'results/phase45/forward.csv'),
               '--output', str(root / 'results/phase45/audition')]
    if not args.silent: command.append('--audible')
    result = subprocess.run(command, cwd=root)
    failed |= result.returncode != 0
if failed: raise SystemExit('Audition callback validation FAIL; see retained summary')
