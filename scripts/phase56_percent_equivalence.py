"""Extract seven common columns from the 161-speed v2 legacy oracle.
The original pre-incremental v1 oracle remains independent and unchanged.
"""
import hashlib
import json
import struct
import subprocess
from phase55_study import ROOT

out = ROOT / 'results/phase56/percent_frozen_equivalence'
out.mkdir(exist_ok=False)
rows = []
for name, path in [('mix_290s', ROOT / 'results/phase55/input/mix_290_pcm16.wav'),
                   ('chain_300s', ROOT / 'results/phase56/long/chain_300s.wav')]:
    blobs = []
    for executable in ('reference', 'reference_percent'):
        destination = ROOT / 'build/phase56_frozen' / f'{name}_{executable}.bin'
        result = subprocess.run([str(ROOT / 'build/phase56_frozen' / executable), str(path), str(destination)], capture_output=True, text=True, check=True)
        (out / f'{name}_{executable}.log').write_text(result.stdout + result.stderr)
        blobs.append(destination.read_bytes())
    b = blobs[1]
    pos = 8 + 5 * 8
    for item_bytes in (56, 40, 40):
        count, = struct.unpack_from('<Q', b, pos)
        pos += 8 + count * item_bytes
    prefix = b[8:pos]
    count, = struct.unpack_from('<Q', b, pos)
    pos += 8
    speeds = struct.unpack_from(f'<{count}Q', b, pos)
    pos += count * 8
    maps = {}
    for speed in speeds:
        length, = struct.unpack_from('<Q', b, pos)
        maps[speed] = b[pos:pos + 8 + length * 8]
        pos += 8 + length * 8
    assert pos == len(b) and len(maps) == 161
    extracted = prefix + b''.join(maps[speed] for speed in (400000, 500000, 750000, 1000000, 1250000, 1500000, 2000000))
    assert blobs[0] == extracted
    rows.append(dict(input=str(path), original_sha256=hashlib.sha256(blobs[0]).hexdigest(),
                     extracted_seven_sha256=hashlib.sha256(extracted).hexdigest(),
                     percent_reference_sha256=hashlib.sha256(b).hexdigest(), speed_count=count, PASS=True))
(out / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
print('Original frozen v1 vs extracted 7 / 161 v2 legacy oracle: 2/2 exact')
