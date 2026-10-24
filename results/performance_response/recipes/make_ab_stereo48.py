"""既存stereo44.1k/300秒素材からAB性能試験専用Float32/48k素材を生成する。

製品入力の変換経路ではない。旧新両clientと凍結oracleへ同じ生成物を渡す。
既知FastLocal品質/Interactive120には元の44.1k素材を引き続き使う。
"""
import argparse
import math
from pathlib import Path
import struct
import subprocess
import run_pairs as common

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--input', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
root = Path(__file__).resolve().parents[3]
out = a.output.resolve()
common.require(out.is_relative_to(root / 'build'), 'generated input belongs under build/')
out.mkdir(parents=True, exist_ok=False)
source = common.wav_identity(a.input, 44100, 2)
converter = common.identity('/usr/bin/afconvert')
wav = out / 'music_48000_2_300s.wav'
cmd = [converter['path'], '-f', 'WAVE', '-d', 'LEF32@48000', '-c', '2', '-r', '127', '--src-complexity', 'bats', source['path'], str(wav)]
result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
(out / 'afconvert.log').write_text(result.stdout + result.stderr)
record = {'status': 'INCOMPLETE', 'driver': common.identity(__file__), 'helper': common.identity(common.__file__),
          'source': source, 'converter': converter, 'command': cmd, 'returncode': result.returncode,
          'scope': 'new AB performance fixture only; not original quality/Interactive120 input'}
common.save(out / 'MANIFEST.json', record)
common.require(result.returncode == 0, 'afconvert failed')
record['input'] = common.wav_identity(wav, 48000, 2)
with wav.open('rb') as f:
    f.seek(12)
    while True:
        header = f.read(8)
        common.require(len(header) == 8, 'missing data')
        kind, count = struct.unpack('<4sI', header)
        if kind == b'data':
            remain = count
            while remain:
                block = f.read(min(remain, 65536))
                common.require(len(block) > 0 and len(block) % 4 == 0, 'truncated float data')
                common.require(all(math.isfinite(x[0]) for x in struct.iter_unpack('<f', block)), 'nonfinite input')
                remain -= len(block)
            break
        f.seek(count + (count & 1), 1)
record.update(status='PASS', finite_samples=48000 * 300 * 2, log=common.identity(out / 'afconvert.log'))
common.require(common.identity(source['path'])['sha256'] == source['sha256'] and common.identity(converter['path']) == converter, 'source/converter changed')
common.save(out / 'MANIFEST.json', record)
print(out / 'MANIFEST.json')
