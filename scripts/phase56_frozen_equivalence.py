"""Check the timing-enhanced oracle against the pre-implementation binary."""
import hashlib
import json
from pathlib import Path
import subprocess
from phase55_study import ROOT

out = ROOT / 'results/phase56/frozen_equivalence'
out.mkdir(exist_ok=False)
rows = []
for name, path in [('mix_290s', ROOT / 'results/phase55/input/mix_290_pcm16.wav'),
                   ('chain_300s', ROOT / 'results/phase56/long/chain_300s.wav')]:
    hashes = []
    for executable in ('reference', 'reference_scope'):
        destination = ROOT / 'build/phase56_frozen' / f'{name}_{executable}.bin'
        result = subprocess.run([str(ROOT / 'build/phase56_frozen' / executable), str(path), str(destination)], capture_output=True, text=True, check=True)
        (out / f'{name}_{executable}.log').write_text(result.stdout + result.stderr)
        hashes.append(hashlib.sha256(destination.read_bytes()).hexdigest())
    assert hashes[0] == hashes[1]
    rows.append(dict(input=str(path), reference_sha256=hashes[0], timing_reference_sha256=hashes[1], PASS=True))
(out / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
print('Frozen reference vs timing-only oracle: 2/2 exact')
