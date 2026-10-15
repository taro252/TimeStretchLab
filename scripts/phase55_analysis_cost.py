"""Measure frozen full analyses of separate prefixes, not an incremental engine."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
from phase55_study import ROOT

parser = argparse.ArgumentParser(__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
prefix_dir = ROOT / 'results/phase55/short/boundary_3_2_44100_4'
inputs = [prefix_dir / f'prefix_{j}.wav' for j in range(3)] + [prefix_dir / 'full.wav',
          ROOT / 'results/phase55/input/mix_290_pcm16.wav']
records = []
for index, path in enumerate(inputs):
    for attempt in range(5):
        proc = subprocess.run([str(ROOT / 'build/phase54_startup_probe'), str(path), str(path),
                               'prepare-only', '.5'], text=True, capture_output=True, timeout=120)
        (args.output / f'{index}_{attempt}.log').write_text(proc.stdout + proc.stderr)
        if proc.returncode:
            raise RuntimeError('Analysis cost probe failed')
        stages, values = {}, {}
        for line in proc.stdout.splitlines():
            if ',' in line and not line.startswith('stage,'):
                label, *fields = line.split(',')
                stages[label] = list(map(float, fields))
            elif '=' in line:
                key, value = line.split('=', 1)
                values[key] = value
        records.append(dict(input=str(path.relative_to(ROOT)), attempt=attempt,
                            analysis_seconds=stages['transient_analysis'][0],
                            analysis_thread_cpu_seconds=stages['transient_analysis'][1],
                            prepare_seconds=stages['cold_prepare'][0],
                            prepare_process_cpu_seconds=stages['cold_prepare'][2],
                            peak_rss_bytes=stages['cold_prepare'][3],
                            analysis_bytes=int(values['analysis_bytes'])))
summary = []
for path in inputs:
    rows = [r for r in records if r['input'] == str(path.relative_to(ROOT))]
    row = dict(input=str(path.relative_to(ROOT)), n=len(rows))
    for metric in ('analysis_seconds', 'analysis_thread_cpu_seconds', 'prepare_seconds',
                   'prepare_process_cpu_seconds', 'peak_rss_bytes', 'analysis_bytes'):
        values = [r[metric] for r in rows]
        row[metric] = dict(median=statistics.median(values), maximum=max(values),
                           population_stddev=statistics.pstdev(values))
    summary.append(row)
(args.output / 'raw.json').write_text(json.dumps(records, indent=2) + '\n')
(args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
