"""Derive a 290s PCM16 fixture from the existing 10s MIX, without modifying it."""
import array
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from phase55_study import ROOT, write_wav

source = ROOT / 'results/phase31/input/mix.wav'
destination = ROOT / 'results/phase55/input'
destination.mkdir(exist_ok=False)
raw = source.read_bytes()
encoding, channels, rate = struct.unpack_from('<HHI', raw, 20)
assert (encoding, channels, rate) == (3, 2, 44100)
assert raw[36:40] == b'data' and struct.unpack_from('<I', raw, 40)[0] == len(raw) - 44
samples = array.array('f', raw[44:])
if sys.byteorder != 'little':
    samples.byteswap()
assert all(math.isfinite(v) and abs(v * .25) < 1 for v in samples)
quantized = array.array('h', (round(v * .25 * 32767) for v in samples))
if sys.byteorder != 'little':
    quantized.byteswap()
motif = quantized.tobytes()
size = 290 * rate * channels * 2
payload = (motif * math.ceil(size / len(motif)))[:size]
path = destination / 'mix_290_pcm16.wav'
write_wav(path, rate, channels, 1, payload)
manifest = dict(path=str(path.relative_to(ROOT)), source=str(source.relative_to(ROOT)),
                source_sha256=hashlib.sha256(raw).hexdigest(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                seconds=290, channels=channels, rate=rate, encoding=1,
                recipe='repeat source float32 samples after round(sample * 0.25 * 32767) PCM16 quantization; no clipping',
                natural_290_second_recording=False)
(destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest, indent=2))
