#!/usr/bin/env python3
"""Numerical playback-only 256-frame seek fade study on frozen raw Golden PCM."""
import array
import csv
import pathlib
import struct

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase17/diagnostics/fade_attacks.csv"
FADE = 256


def wav(path):
    with path.open("rb") as stream:
        header = stream.read(44)
        if header[0:4] != b"RIFF" or header[8:12] != b"WAVE" or header[12:16] != b"fmt ":
            raise ValueError("Expected canonical float WAV")
        channels, rate = struct.unpack_from("<HI", header, 22)
        if struct.unpack_from("<H", header, 20)[0] != 3:
            raise ValueError("Expected float32 WAV")
        signal = array.array("f")
        signal.frombytes(stream.read())
        return channels, rate, signal


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in ("drums", "mix"):
        channels, rate, signal = wav(ROOT / f"results/phase12/golden/raw/{name}_050.wav")
        frames = len(signal) // channels
        # Largest 10 ms attack candidates in non-overlapping 0.35 s regions.
        candidates = []
        stride = round(rate * 0.35)
        for region in range(0, frames - FADE, stride):
            end = min(frames - FADE, region + stride)
            at = max(range(region, end), key=lambda i: max(abs(signal[i * channels + c]) for c in range(channels)))
            amplitude = max(abs(signal[at * channels + c]) for c in range(channels))
            candidates.append((amplitude, at))
        for rank, (amplitude, peak) in enumerate(sorted(candidates, reverse=True)[:10], 1):
            for shift, label in ((0, "at_peak"), (-round(rate * 0.002), "2ms_before_peak")):
                start = max(0, peak + shift)
                original = 0.0
                faded = 0.0
                for i in range(FADE):
                    gain = i / (FADE - 1)
                    for c in range(channels):
                        sample = signal[(start + i) * channels + c]
                        original += sample * sample
                        faded += sample * sample * gain * gain
                rows.append({"source": name, "rank": rank, "seek_output_frame": start,
                             "peak_amplitude": amplitude, "alignment": label,
                             "first_256_energy_ratio": faded / original if original else 0,
                             "first_256_rms_ratio": (faded / original) ** 0.5 if original else 0,
                             "fade_ms": FADE / rate * 1000})
    with OUT.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    for name in ("drums", "mix"):
        for alignment in ("at_peak", "2ms_before_peak"):
            subset = [r for r in rows if r["source"] == name and r["alignment"] == alignment]
            print(f"{name} {alignment}: rms_ratio_range="
                  f"{min(r['first_256_rms_ratio'] for r in subset):.3f}-"
                  f"{max(r['first_256_rms_ratio'] for r in subset):.3f}")


if __name__ == "__main__":
    main()
