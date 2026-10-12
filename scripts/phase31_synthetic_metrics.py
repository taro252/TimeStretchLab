#!/usr/bin/env python3
"""Read-only synthetic attack, pitch, stereo and modulation measurements."""
from array import array
import cmath
import csv
import math
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "results/phase31"


def load(path):
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(path)
    offset = 12
    rate = channels = None
    samples = None
    while offset + 8 <= len(data):
        name = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        payload = data[offset + 8:offset + 8 + size]
        if name == b"fmt ":
            code, channels, rate = struct.unpack_from("<HHI", payload)
            if code != 3 or channels != 2:
                raise ValueError("Expected stereo float32")
        if name == b"data":
            samples = array("f")
            samples.frombytes(payload)
        offset += 8 + size + (size & 1)
    return rate, samples


def sine(path):
    rate, x = load(path)
    # Exclude beginning and end transients from steady-tone measurements.
    frames = len(x) // 2
    margin = min(rate * 2, max(rate // 2, frames // 4))
    first = margin
    last = min(frames - margin, first + rate * 3)
    times = []
    last_value = x[2 * first]
    for i in range(first + 1, last):
        current = x[2 * i]
        if last_value <= 0 < current:
            times.append(i - last_value / (current - last_value))
        last_value = current
    frequency = (len(times) - 1) * rate / (times[-1] - times[0]) if len(times) > 2 else 0
    rms = []
    step = rate // 10
    for begin in range(first, last - step + 1, step):
        power = sum(x[2 * j] ** 2 for j in range(begin, begin + step)) / step
        rms.append(math.sqrt(power))
    modulation_db = 20 * math.log10(max(rms) / min(rms)) if rms and min(rms) > 0 else float("inf")
    width = min(rate, last - first)
    phase_l = sum(x[2 * i] * cmath.exp(-2j * math.pi * frequency * (i - first) / rate)
                  for i in range(first, first + width))
    phase_r = sum(x[2 * i + 1] * cmath.exp(-2j * math.pi * frequency * (i - first) / rate)
                  for i in range(first, first + width))
    ipd = abs(cmath.phase(phase_l * phase_r.conjugate()))
    def goertzel(harmonic):
        coefficient = 2 * math.cos(2 * math.pi * frequency * harmonic / rate)
        previous = older = 0.0
        for i in range(first, first + width):
            value = x[2 * i] + coefficient * previous - older
            older, previous = previous, value
        return max(0.0, previous * previous + older * older
                   - coefficient * previous * older)
    fundamental = goertzel(1)
    harmonics = sum(goertzel(k) for k in (2, 3, 4))
    harmonic_db = 10 * math.log10(max(harmonics, 1e-20) / max(fundamental, 1e-20))
    longest_zero = current_zero = 0
    for i in range(first, last):
        if abs(x[2 * i]) < 1e-7 and abs(x[2 * i + 1]) < 1e-7:
            current_zero += 1
            longest_zero = max(longest_zero, current_zero)
        else:
            current_zero = 0
    return {"frequency_hz": frequency, "rms_modulation_db": modulation_db,
            "ipd_rad": ipd, "harmonics_2_to_4_db": harmonic_db,
            "longest_zero_run_ms": longest_zero * 1000 / rate}


def clicks(path, speed):
    rate, x = load(path)
    count = 12
    errors = []
    widths = []
    peaks = []
    doubled = 0
    for event in range(count):
        expected = round((12000 + 24000 * event) / speed)
        left = max(0, expected - rate // 10)
        right = min(len(x) // 2, expected + rate // 10)
        if right <= left:
            raise RuntimeError("Missing click window")
        index = max(range(left, right), key=lambda i: abs(x[2 * i]))
        peak = abs(x[2 * index])
        peaks.append(peak)
        errors.append((index - expected) * 1000 / rate)
        start = end = index
        while start > left and abs(x[2 * (start - 1)]) >= peak * 0.5:
            start -= 1
        while end + 1 < right and abs(x[2 * (end + 1)]) >= peak * 0.5:
            end += 1
        widths.append((end - start + 1) * 1000 / rate)
        if any(abs(x[2 * i]) > peak * 0.5
               for i in range(left, right)
               if abs(i - index) > rate * 0.005):
            doubled += 1
    return {"click_count": count, "max_timing_error_ms": max(map(abs, errors)),
            "mean_attack_width_ms": sum(widths) / len(widths),
            "min_attack_peak": min(peaks), "max_attack_peak": max(peaks),
            "events_with_secondary_energy": doubled}


def main():
    rows = []
    for row in csv.DictReader((TARGET / "audio.csv").open()):
        if row["source"] not in ("sine", "click"):
            continue
        path = ROOT / row["path"]
        details = sine(path) if row["source"] == "sine" else clicks(path, float(row["speed"]))
        rows.append({"source": row["source"], "mode": row["mode"],
                     "speed": row["speed"], **details})
    names = ["source", "mode", "speed", "frequency_hz", "rms_modulation_db",
             "ipd_rad", "harmonics_2_to_4_db", "longest_zero_run_ms",
             "click_count", "max_timing_error_ms",
             "mean_attack_width_ms", "min_attack_peak", "max_attack_peak",
             "events_with_secondary_energy"]
    with (TARGET / "synthetic.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=names, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Measured {len(rows)} synthetic WAVs")


if __name__ == "__main__":
    main()
