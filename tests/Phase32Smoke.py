#!/usr/bin/env python3
"""Frozen research baseline and one-factor diagnostic guard."""
import hashlib
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def call(*args, success=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=90)
    if (result.returncode == 0) != success:
        raise RuntimeError(f'{args}: {result.stderr}')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    old, new = sys.argv[1:]
    with tempfile.TemporaryDirectory(prefix='phase32-') as temp:
        root = Path(temp)
        source = root / 'click.wav'
        frames = 48000 * 2
        pcm = bytearray()
        for i in range(frames):
            sample = (0.8 if i % 24000 == 12000 else
                      0.12 * math.sin(2 * math.pi * 437.3 * i / 48000))
            pcm += struct.pack('<ff', sample, sample)
        source.write_bytes(b'RIFF' + struct.pack('<I', 36 + len(pcm)) +
                           b'WAVEfmt ' + struct.pack('<IHHIIHH', 16, 3, 2,
                                                     48000, 384000, 8, 32) +
                           b'data' + struct.pack('<I', len(pcm)) + pcm)
        quarter_digest = None
        for speed in ('0.25', '0.30', '0.50'):
            previous, current = root / 'previous.wav', root / 'current.wav'
            call(old, source, previous, speed, 'B')
            call(new, source, current, speed, 'baseline', 'stems')
            if digest(previous) != digest(current):
                raise RuntimeError(f'Phase 31 baseline changed at {speed}')
            if speed == '0.25':
                quarter_digest = digest(current)
            for band in ('low', 'mid', 'high'):
                if not current.with_name(f'current_{band}.wav').exists():
                    raise RuntimeError(f'Missing {band} synthesis output')
        call(new, source, root / 'no_lock.wav', '0.25', 'no_lock')
        call(new, source, root / 'no_reset.wav', '0.25', 'no_reset')
        call(new, source, root / 'no_propagation.wav', '0.25', 'no_propagation')
        if digest(root / 'no_lock.wav') == quarter_digest or \
           digest(root / 'no_reset.wav') == quarter_digest:
            raise RuntimeError('Phase-lock ablation had no effect')
        call(new, source, root / 'invalid.wav', '0.20', 'baseline', success=False)
    print('Phase 32: baseline byte match; stems; one-factor phase diagnostics')


if __name__ == '__main__':
    main()
