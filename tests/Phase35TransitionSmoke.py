#!/usr/bin/env python3
"""Independent, generated-audio safety test for the Phase 35 hop transition."""
import math
from array import array
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

def write_wav(path, audio, rate):
    channels = 2
    pcm = audio.tobytes()
    path.write_bytes(b'RIFF' + struct.pack('<I', 36 + len(pcm)) + b'WAVEfmt ' +
                     struct.pack('<IHHIIHH', 16, 3, channels, rate,
                                 rate * channels * 4, channels * 4, 32) +
                     b'data' + struct.pack('<I', len(pcm)) + pcm)


def read_wav(path, channels):
    data = path.read_bytes()
    assert data[:4] == b'RIFF' and data[8:12] == b'WAVE'
    assert (len(data)-44)%(channels*4)==0
    return data[44:]


def run(binary, root, input_file, name, initial, changes, block=16384):
    schedule = root / f'{name}.schedule.csv'
    schedule.write_text('input_sample,target_speed\n' + ''.join(
        f'{at},{speed:.2f}\n' for at, speed in changes))
    output = root / f'{name}.wav'
    result = subprocess.run([binary, str(input_file), str(output), f'{initial:.2f}',
                             str(schedule), str(root / name), str(block)],
                            capture_output=True, text=True, check=True)
    info = dict(row.split('=', 1) for row in result.stdout.splitlines() if '=' in row)
    return read_wav(output, 2), info


def main(binary):
    rate = 48000
    duration = 7
    signal = array('f', (.12 * math.sin(2 * math.pi * 437.3 * i/rate) +
                         .03 * math.sin(2 * math.pi * 880 * i/rate)
                         for i in range(rate * duration)))
    for when in (.9, 2.2, 3.6, 5.0):
        start = round(when * rate)
        for j in range(min(rate // 4, len(signal) - start)):
            signal[start+j] += .28 * math.exp(-j*24/rate)
    stereo = array('f')
    for i, sample in enumerate(signal):
        stereo.extend((sample, .75 * signal[i-3] if i>=3 else 0.0))
    with tempfile.TemporaryDirectory(prefix='phase35-smoke-') as temp:
        root = Path(temp)
        source = root / 'source.wav'
        write_wav(source, stereo, rate)
        fixed_b, _ = run(binary, root, source, 'fixed_b', .40, [])
        fixed_a, _ = run(binary, root, source, 'fixed_a', .50, [])
        for label, initial, target, fixed in (
            ('b_to_a', .40, .50, fixed_b),
            ('a_to_b', .50, .40, fixed_a),
        ):
            switched, info = run(binary, root, source, label, initial,
                                 [(2 * rate, target)])
            again, repeat = run(binary, root, source, label + '_block', initial,
                                [(2 * rate, target)], 8192)
            assert switched == again, label + ': block dependence'
            assert info['map_hash'] == repeat['map_hash']
            samples = array('f'); samples.frombytes(switched)
            assert all(math.isfinite(v) for v in samples), label + ': non-finite output'
            assert max(map(abs, samples)) < 2.0, label + ': abnormal peak'
            plan = (root / f'{label}.plans.csv').read_text().splitlines()[1].split(',')
            published = int(plan[3])
            assert switched[:published*8] == fixed[:published*8], \
                label + ': published prefix was changed'
            trace = (root / f'{label}.frames.csv').read_text().splitlines()[1:]
            for fft in (8192, 4096, 1024):
                selected = [list(map(int, row.split(',')[:7])) for row in trace
                            if row.startswith(str(fft) + ',')]
                distances = {row[3] for row in selected}
                assert fft // 8 in distances and fft // 4 in distances, \
                    label + ': no hop transition'
                assert all(right[2] > left[2] and right[4] > left[4]
                           for left, right in zip(selected, selected[1:])), \
                    label + ': non-monotonic frame positions'
                assert all(0 < row[5] < fft for row in selected), \
                    label + ': unsafe synthesis hop'
    print('Phase 35 generated-audio bidirectional, prefix, chunk and hop checks passed')


if __name__ == '__main__':
    main(sys.argv[1])
