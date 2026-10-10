#!/usr/bin/env python3
"""Playback-stage only AB for 256-frame seek fade; Golden WAV is read-only."""
import array
import csv
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase18/attack_ab"
GAIN = 0.5


def read_float_wav(path):
    with path.open("rb") as stream:
        header = stream.read(44)
        if header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError("Expected canonical WAV")
        code, channels, rate = struct.unpack_from("<HHI", header, 20)
        if code != 3 or channels != 2:
            raise ValueError("Expected stereo float WAV")
        samples = array.array("f")
        samples.frombytes(stream.read())
        return rate, samples


def write_float_wav(path, rate, values):
    data = values.tobytes()
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " +
              struct.pack("<IHHIIHH", 16, 3, 2, rate, rate * 8, 8, 32) +
              b"data" + struct.pack("<I", len(data)))
    path.write_bytes(header + data)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    diagnostic_path = ROOT / "results/phase17/diagnostics/fade_attacks.csv"
    if not diagnostic_path.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts/phase17_fade_study.py")], check=True)
    diagnostics = list(csv.DictReader(diagnostic_path.open()))
    for name in ("drums", "mix"):
        rate, signal = read_float_wav(ROOT / f"results/phase12/golden/raw/{name}_050.wav")
        positions = [int(r["seek_output_frame"]) for r in diagnostics
                     if r["source"] == name and r["alignment"] == "2ms_before_peak"
                     and int(r["rank"]) in (1, 3, 5)]
        versions = {length: array.array("f") for length in (0, 64, 128, 256)}
        for start in positions:
            silence = array.array("f", [0.0]) * (round(rate * 0.1) * 2)
            for output in versions.values():
                output.extend(silence)
            length = round(rate * 0.45)
            for i in range(length):
                for channel in range(2):
                    value = GAIN * signal[(start + i) * 2 + channel]
                    for fade_length, output in versions.items():
                        factor = min(1.0, i / (fade_length - 1)) if fade_length else 1.0
                        output.append(value * factor)
            gap = array.array("f", [0.0]) * (round(rate * 0.2) * 2)
            for output in versions.values():
                output.extend(gap)
        for fade_length, output in versions.items():
            filename = f"{name}_{'raw_seek' if fade_length == 0 else 'fade' + str(fade_length)}_playback.wav"
            write_float_wav(OUT / filename, rate, output)
        print(f"{name}: {positions}, fade_samples=[0,64,128,256], playback_gain={GAIN}")


if __name__ == "__main__":
    main()
