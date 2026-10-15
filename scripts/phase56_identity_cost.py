"""Isolate the unchanged Phase54 whole-content identity cost, without playback."""
import json
from pathlib import Path
import statistics
import subprocess
from phase55_study import ROOT

out = ROOT / 'results/phase56/identity_cost'
out.mkdir(exist_ok=False)
source = ROOT / 'results/phase55/input/mix_290_pcm16.wav'
rows = []
for attempt in range(5):
    p = subprocess.run([str(ROOT / 'build/phase54_startup_probe'), str(source), str(source), 'prepare-only', '.5'], capture_output=True, text=True, check=True)
    (out / f'{attempt}.log').write_text(p.stdout + p.stderr)
    values = {}
    for line in p.stdout.splitlines():
        if ',' in line and not line.startswith('stage,'):
            label, *numbers = line.split(',')
            values[label] = list(map(float, numbers))
    rows.append(dict(identity_seconds=values['identity_validation'][0], identity_thread_cpu_seconds=values['identity_validation'][1],
                     analysis_seconds=values['transient_analysis'][0], prepare_seconds=values['cold_prepare'][0]))
summary = {key: dict(median=statistics.median(r[key] for r in rows), maximum=max(r[key] for r in rows),
                      population_stddev=statistics.pstdev(r[key] for r in rows)) for key in rows[0]}
(out / 'raw.json').write_text(json.dumps(rows, indent=2) + '\n')
(out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
