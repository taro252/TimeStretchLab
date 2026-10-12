#!/usr/bin/env python3
"""Objective attack, tail, phase, stereo and band diagnostics for Phase 32."""
import csv
import math
from pathlib import Path

import numpy as np

from phase32_study import OUT, read


def rms(x):
    return float(np.sqrt(np.mean(np.square(x.astype(np.float64))))) if x.size else 0.0


def envelope(x, rate, milliseconds=20):
    step = max(1, round(rate * milliseconds / 1000 / 2))
    length = 2 * step
    mono = np.mean(x, axis=1)
    count = max(0, (len(mono) - length) // step + 1)
    if count == 0:
        return np.empty(0), np.empty(0)
    # Cumulative sum avoids a huge overlapping-window copy.
    power = np.r_[0.0, np.cumsum(np.square(mono, dtype=np.float64))]
    starts = np.arange(count) * step
    values = np.sqrt((power[starts + length] - power[starts]) / length)
    times = (starts + length / 2) / rate
    return times, values


def attack(x, rate, speed, onsets):
    mono = np.mean(x, axis=1)
    errors, peaks, widths, pre, early = [], [], [], [], []
    for onset in onsets:
        center = onset / speed
        lo = max(0, int((center - 0.03) * rate))
        hi = min(len(mono), int((center + 0.08) * rate))
        if hi <= lo:
            continue
        index = lo + np.argmax(np.abs(mono[lo:hi]))
        peak = abs(mono[index])
        errors.append(1000 * (index / rate - center))
        peaks.append(peak)
        left = index
        right = index
        while left > 0 and abs(mono[left - 1]) >= peak / np.sqrt(2):
            left -= 1
        while right + 1 < len(mono) and abs(mono[right + 1]) >= peak / np.sqrt(2):
            right += 1
        widths.append(1000 * (right - left + 1) / rate)
        p0, p1 = max(0, int((center - 0.02) * rate)), max(0, int(center * rate))
        e0, e1 = p1, min(len(mono), int((center + 0.02) * rate))
        pre.append(float(np.mean(mono[p0:p1] ** 2)) if p1 > p0 else 0)
        early.append(float(np.mean(mono[e0:e1] ** 2)) if e1 > e0 else 0)
    return (max(map(abs, errors), default=0), min(peaks, default=0),
            max(peaks, default=0), float(np.mean(widths)) if widths else 0,
            float(np.mean(pre)) if pre else 0,
            float(np.mean(early)) if early else 0)


def tail(x, rate, speed):
    times, values = envelope(x, rate)
    # Isolated synthetic decay: skip attack and floor; fit exponential in dB.
    phase = times - 0.6 / speed
    mask = (phase >= 0.08 / speed) & (phase <= 0.45 / speed)
    if np.count_nonzero(mask) < 10:
        return float('nan'), float('nan'), float('nan')
    db = 20 * np.log10(np.maximum(values[mask], 1e-10))
    slope, intercept = np.polyfit(times[mask], db, 1)
    ripple = float(np.std(db - (slope * times[mask] + intercept)))
    return float(slope), ripple, float(np.mean(db))


def variation(x, rate, start=1.0, duration=3.0):
    mono = np.mean(x, axis=1)
    section = mono[int(start * rate):min(len(mono), int((start + duration) * rate))]
    size, hop = 2048, 512
    if len(section) < size + hop:
        return float('nan'), float('nan')
    frames = np.lib.stride_tricks.sliding_window_view(section, size)[::hop]
    spectra = np.fft.rfft(frames * np.hanning(size), axis=1)
    power = np.abs(spectra)
    # Weighted log-spectrum variation catches timbre wobble without treating
    # low-energy noise bins as equally important as strong tonal bins.
    log = np.log(np.maximum(power, 1e-6))
    difference = np.abs(np.diff(log, axis=0))
    weights = np.minimum(power[1:], power[:-1])
    spectral = float(np.sum(difference * weights) / max(np.sum(weights), 1e-12))
    complex_coherence = np.sum(spectra[1:] * np.conj(spectra[:-1]), axis=1)
    norm = np.linalg.norm(spectra[1:], axis=1) * np.linalg.norm(spectra[:-1], axis=1)
    coherence = float(np.mean(np.abs(complex_coherence) / np.maximum(norm, 1e-12)))
    return spectral, coherence


def phase_jitter(x, rate, f0):
    mono = np.mean(x, axis=1)
    mono = mono[rate:min(len(mono), 4 * rate)]
    size, hop = 4096, 512
    if len(mono) < size + hop:
        return float('nan')
    frames = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop]
    spectra = np.fft.rfft(frames * np.hanning(size), axis=1)
    residuals = []
    for harmonic in range(1, 6):
        bin_index = round(f0 * harmonic * size / rate)
        if bin_index >= spectra.shape[1]:
            break
        phase = np.unwrap(np.angle(spectra[:, bin_index]))
        increments = np.diff(phase)
        expected = 2 * math.pi * f0 * harmonic * hop / rate
        residual = np.angle(np.exp(1j * (increments - expected)))
        residuals.append(float(np.std(residual)))
    return float(np.mean(residuals)) if residuals else float('nan')


def stable_tone(x, rate, expected):
    mono = np.mean(x, axis=1)
    section = mono[rate:min(len(mono), 4 * rate)]
    if len(section) < rate:
        return float('nan'), float('nan')
    spectrum = np.abs(np.fft.rfft(section * np.hanning(len(section))))
    freqs = np.fft.rfftfreq(len(section), 1 / rate)
    neighborhood = np.flatnonzero((freqs > expected * 0.90) & (freqs < expected * 1.10))
    k = neighborhood[np.argmax(spectrum[neighborhood])]
    log = np.log(np.maximum(spectrum[k - 1:k + 2], 1e-12))
    denominator = log[0] - 2 * log[1] + log[2]
    offset = (0.5 * (log[0] - log[2]) / denominator
              if abs(denominator) > 1e-12 else 0)
    if not np.isfinite(offset) or abs(offset) > 1:
        offset = 0
    frequency = (k + offset) * rate / len(section)
    times, env = envelope(x, rate, 50)
    use = (times >= 1) & (times < 4)
    db = 20 * np.log10(np.maximum(env[use], 1e-12))
    return float(frequency), float(np.percentile(db, 95) - np.percentile(db, 5))


def stereo(x):
    if x.shape[1] < 2:
        return 0.0, 1.0
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5
    return rms(side) / max(rms(mid), 1e-12), float(np.corrcoef(x.T)[0, 1])


def write_table(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = []
    stem_rows = []
    for path in sorted((OUT / 'raw').glob('*.wav')):
        if path.stem.endswith(('_low', '_mid', '_high')):
            continue
        speed_key = path.stem.rsplit('_', 1)[-1]
        speed = float(speed_key) / 100
        if speed not in (0.25, 0.30):
            continue
        key = path.stem[:-(len(speed_key) + 1)]
        mode = next(m for m in ('no_propagation', 'no_reset', 'no_lock', 'baseline')
                    if key.endswith('_' + m))
        source = key[:-(len(mode) + 1)]
        rate, audio = read(path)
        value = dict(source=source, speed=speed, mode=mode,
                     peak=float(np.max(np.abs(audio))), rms=rms(audio),
                     finite=bool(np.isfinite(audio).all()),
                     max_derivative=float(np.max(np.abs(np.diff(audio, axis=0)))))
        value['side_mid'], value['lr_correlation'] = stereo(audio)
        value['spectral_variation'], value['spectral_coherence'] = variation(audio, rate)
        if source in ('harmonic', 'sine'):
            value['harmonic_phase_jitter_rad'] = phase_jitter(audio, rate,
                                                              110 if source == 'harmonic' else 437.3)
            value['dominant_frequency_hz'], value['tone_envelope_range_db'] = stable_tone(
                audio, rate, 110 if source == 'harmonic' else 437.3)
        else:
            value['harmonic_phase_jitter_rad'] = ''
            value['dominant_frequency_hz'] = value['tone_envelope_range_db'] = ''
        if source == 'decay_noise':
            value['decay_db_per_second'], value['tail_ripple_db'], value['tail_mean_db'] = tail(audio, rate, speed)
        else:
            value['decay_db_per_second'] = value['tail_ripple_db'] = value['tail_mean_db'] = ''
        if source in ('click', 'decay_noise', 'white_burst', 'pink_burst'):
            onset = ([0.25 + 0.5 * i for i in range(12)] if source == 'click'
                     else [0.6, 2.5, 4.4])
            metrics = attack(audio, rate, speed, onset)
            for label, metric in zip(('attack_max_error_ms', 'attack_min_peak',
                                      'attack_max_peak', 'attack_mean_halfpower_width_ms',
                                      'pre20ms_power', 'first20ms_power'), metrics):
                value[label] = metric
        else:
            for label in ('attack_max_error_ms', 'attack_min_peak', 'attack_max_peak',
                          'attack_mean_halfpower_width_ms', 'pre20ms_power',
                          'first20ms_power'):
                value[label] = ''
        rows.append(value)
        for band in ('low', 'mid', 'high'):
            stem = path.with_name(path.stem + '_' + band + '.wav')
            if not stem.exists():
                continue
            sr, sound = read(stem)
            spec_var, spec_coh = variation(sound, sr)
            stem_rows.append(dict(source=source, speed=speed, mode=mode, band=band,
                                  rms=rms(sound), peak=float(np.max(np.abs(sound))),
                                  spectral_variation=spec_var, spectral_coherence=spec_coh,
                                  side_mid=stereo(sound)[0]))
    write_table(OUT / 'metrics.csv', rows)
    write_table(OUT / 'stems.csv', stem_rows)


if __name__ == '__main__':
    main()
