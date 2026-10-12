#!/usr/bin/env python3
"""Compare burst energy at ideal, mapped, and measured onset positions."""
import csv
import math
import subprocess
from pathlib import Path

import numpy as np

from phase32_study import read
from phase37_study import ROOT, SOURCES

OUT = ROOT / 'results/phase38'
RATE = 48000
EVENTS = (.6, 2.5, 4.4)
PYTHON_EPSILON = 1e-30


def mono_energy(audio):
    # Average channel power, not an L+R downmix that can cancel stereo noise.
    return np.mean(np.square(audio.astype(np.float64)), axis=1)


def smooth_power(power, size):
    return np.convolve(power, np.ones(size, dtype=np.float64) / size, 'same')


def energy(power, start, milliseconds, rate=RATE):
    first = max(0, int(round(start)))
    last = min(len(power), first + int(round(milliseconds * rate / 1000)))
    return float(np.sum(power[first:last], dtype=np.float64)) if last > first else 0.


def rms(power, start, milliseconds):
    length = max(1, int(round(milliseconds * RATE / 1000)))
    return math.sqrt(energy(power, start, milliseconds) / length)


def position(power, ideal, left_ms, right_ms):
    left = max(0, round(ideal + left_ms * RATE / 1000))
    right = min(len(power), round(ideal + right_ms * RATE / 1000))
    smoothed = smooth_power(power[left:right], round(.001 * RATE))
    # Noise bursts have a gradual Hann onset. Report a sustained 10% rise
    # relative to the local 1 ms RMS maximum, plus the smoothed energy crest.
    peak = float(np.max(smoothed, initial=0))
    threshold = .01 * peak
    above = smoothed >= threshold
    candidate = np.convolve(above.astype(np.int16), np.ones(144, np.int16), 'valid')
    onset = left + int(np.argmax(candidate >= 144)) if np.any(candidate >= 144) else -1
    max_energy = left + int(np.argmax(smoothed)) if len(smoothed) else -1
    return onset, max_energy, math.sqrt(peak)


def event_rows(path, speed, mode):
    dump = subprocess.run((str(ROOT / 'build/phase38_events'), str(path),
                           speed, mode), capture_output=True, text=True, check=True)
    return list(csv.DictReader(dump.stdout.splitlines()))


def map_points(path, speed, mode):
    dump = subprocess.run((str(ROOT / 'build/phase37_render'), str(path), '-',
                           speed, mode), capture_output=True, text=True, check=True)
    points = list(csv.DictReader(dump.stdout.splitlines()))
    return (np.array([int(q['input_sample']) for q in points]),
            np.array([int(q['output_sample']) for q in points]))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    event_metadata = []
    for source in ('white_burst', 'pink_burst', 'decay_noise'):
        path = SOURCES[source]
        rate, original = read(path)
        if rate != RATE:
            raise RuntimeError('Unexpected synthetic input sample rate')
        source_power = mono_energy(original)
        for speed in ('1.50', '2.00'):
            speed_value = float(speed)
            for mode in 'AB':
                map_input, map_output = map_points(path, speed, mode)
                events = event_rows(path, speed, mode)
                rate, output = read(ROOT / 'results/phase37/raw' /
                                    f'{source}_{mode}_{speed.replace(".", "")}.wav')
                power = mono_energy(output)
                for index, onset_seconds in enumerate(EVENTS):
                    nominal_input = round(onset_seconds * RATE)
                    measured_input, input_crest, _ = position(
                        source_power, nominal_input, -5, 120)
                    ideal = nominal_input / speed_value
                    mapped = float(np.interp(measured_input, map_input, map_output))
                    actual, actual_crest, envelope_peak = position(
                        power, ideal, -50, 180)
                    full_begin = ideal - 50 * RATE / 1000
                    full_end = ideal + 220 * RATE / 1000
                    total_energy = energy(power, full_begin, 270)
                    matched = min(events, key=lambda e: abs(
                        int(e['peak_frame']) * 1024 - nominal_input))
                    event_metadata.append(dict(source=source, speed=speed,
                        mode=mode, burst=index, **matched))
                    row = dict(source=source, speed=speed, mode=mode,
                        burst=index, input_nominal=nominal_input,
                        input_measured_onset=measured_input,
                        input_peak=input_crest,
                        ideal_output=round(ideal),
                        mapped_measured_input_onset=round(mapped),
                        measured_output_onset=actual,
                        measured_output_crest=actual_crest,
                        envelope_peak=envelope_peak,
                        onset_offset_from_ideal_ms=(actual-ideal)*1000/RATE,
                        onset_offset_from_map_ms=(actual-mapped)*1000/RATE,
                        crest_offset_from_ideal_ms=(actual_crest-ideal)*1000/RATE,
                        total_energy=total_energy,
                        peak=float(np.max(np.abs(output[max(0,round(ideal)-2400):
                            min(len(output),round(ideal)+10560)]))),
                        input_total_energy=energy(source_power, nominal_input-2400,270),
                        anchor_confident=matched['anchor_confident'],
                        anchor_offset=matched['anchor_offset'],
                        event_peak_frame=matched['peak_frame'],
                        mapped_event_peak=matched['mapped_peak_sample'],
                        ideal_event_peak=matched['ideal_output_sample'])
                    for label, center in (('ideal', ideal), ('mapped', mapped),
                                          ('observed', actual)):
                        for duration in (5, 10, 20, 50):
                            value = energy(power, center, duration)
                            row[f'{label}_{duration}ms_energy'] = value
                            row[f'{label}_{duration}ms_rms'] = rms(power, center, duration)
                    row['pre_echo_energy'] = energy(power, actual-40*RATE/1000, 35)
                    row['post_echo_energy'] = energy(power, actual+120*RATE/1000, 80)
                    row['observed_20ms_to_total'] = (
                        row['observed_20ms_energy'] / max(total_energy, PYTHON_EPSILON))
                    rows.append(row)
    for name, values in (('burst_diagnostics.csv', rows),
                         ('burst_events.csv', event_metadata)):
        with (OUT / name).open('w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=values[0].keys(), lineterminator='\n')
            writer.writeheader()
            writer.writerows(values)
    print(f'{len(rows)} burst diagnostics, {len(event_metadata)} event rows')


if __name__ == '__main__':
    main()
