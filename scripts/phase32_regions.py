#!/usr/bin/env python3
"""Measure fixed regions and create same-gain blind audition clips."""
import csv
import hashlib
from pathlib import Path

import numpy as np

from phase32_metrics import envelope, rms, stereo, variation, write_table
from phase32_study import OUT, read, wav

REGIONS = {
    'drums_attack': ('drums', 3.77, 4.02),
    'drums_tail': ('drums', 4.05, 4.35),
    'mix_busy': ('mix', 2.9, 4.2),
    'mix_quiet': ('mix', 4.2, 4.8),
    'vocal_vowel': ('vocal', 3.2, 3.85),
}


def phase_wobble(audio, rate):
    mono = np.mean(audio, axis=1)
    size, hop = 2048, 512
    if len(mono) < size + hop:
        return float('nan')
    frames = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop]
    spectra = np.fft.rfft(frames * np.hanning(size), axis=1)
    power = np.abs(spectra)
    dominant = np.max(power, axis=0)
    selected = np.flatnonzero(dominant > max(dominant) * 0.15)
    if not len(selected):
        return float('nan')
    shifts = np.angle(spectra[1:, selected] * np.conj(spectra[:-1, selected]))
    # Remove each bin's circular mean: variation, not the mean frequency.
    means = np.angle(np.mean(np.exp(1j * shifts), axis=0))
    residual = np.angle(np.exp(1j * (shifts - means)))
    weight = np.minimum(power[1:, selected], power[:-1, selected])
    return float(np.sqrt(np.sum(weight * residual ** 2) / max(np.sum(weight), 1e-12)))


def main():
    rows, audition = [], []
    max_peak = 0.0
    for label, (source, begin, end) in REGIONS.items():
        for speed in (0.25, 0.30):
            for mode in ('baseline', 'no_lock', 'no_reset', 'no_propagation'):
                path = OUT / 'raw' / f'{source}_{mode}_{round(speed * 100):03d}.wav'
                if not path.exists():
                    continue
                rate, whole = read(path)
                a, b = round(begin / speed * rate), round(end / speed * rate)
                section = whole[a:b]
                if len(section) < 2048:
                    continue
                t, env = envelope(section, rate)
                log_env = 20 * np.log10(np.maximum(env, 1e-9))
                spec, coh = variation(section, rate, 0, len(section) / rate)
                for band in ('final', 'low', 'mid', 'high'):
                    if band == 'final':
                        signal = section
                    else:
                        stem = path.with_name(path.stem + '_' + band + '.wav')
                        if not stem.exists():
                            continue
                        _, audio = read(stem)
                        signal = audio[a:b]
                    bt, be = envelope(signal, rate)
                    bs, bc = variation(signal, rate, 0, len(signal) / rate)
                    side_mid, correlation = stereo(signal)
                    rows.append(dict(region=label, source=source, speed=speed,
                                     mode=mode, band=band, input_start=begin,
                                     input_end=end, output_start=a, output_end=b,
                                     rms=rms(signal), peak=float(np.max(np.abs(signal))),
                                     envelope_std_db=float(np.std(20 * np.log10(np.maximum(be, 1e-9)))),
                                     spectral_variation=bs, spectral_coherence=bc,
                                     phase_wobble_rad=phase_wobble(signal, rate),
                                     side_mid=side_mid, lr_correlation=correlation))
                # Same fixed listening gain, plus only a 3 ms edge ramp to avoid
                # a click created by cutting a nonzero waveform for audition.
                if speed != 0.25:
                    continue
                clip = section.copy() * np.float32(0.5)
                ramp = min(len(clip) // 2, round(rate * 0.003))
                if ramp:
                    fade = np.linspace(0, 1, ramp, dtype=np.float32)
                    clip[:ramp] *= fade[:, None]
                    clip[-ramp:] *= fade[::-1, None]
                result = OUT / 'audition' / f'{label}_{mode}_025_gain050.wav'
                wav(result, clip, rate)
                peak = float(np.max(np.abs(clip)))
                max_peak = max(peak, max_peak)
                audition.append(dict(region=label, mode=mode, speed=speed,
                                     source_raw=str(path.relative_to(OUT)),
                                     audition=str(result.relative_to(OUT)),
                                     input_start=begin, input_end=end,
                                     output_frames=len(clip), gain=0.5,
                                     edge_ramp_ms=3,
                                     peak=peak,
                                     sha256=hashlib.sha256(result.read_bytes()).hexdigest()))
    write_table(OUT / 'regions.csv', rows)
    write_table(OUT / 'audition.csv', audition)
    print(f'{len(rows)} region/band rows, {len(audition)} listening clips, peak={max_peak:.5f}')


if __name__ == '__main__':
    main()
