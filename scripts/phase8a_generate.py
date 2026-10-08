#!/usr/bin/env python3
"""Reproduce the Phase 8A WSOLA A/B WAVs from Phase 7's fixed sections."""
import csv
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/phase7"
TARGET = ROOT / "results/phase8a"
EXECUTABLE = ROOT / "build/wsola_stretch"
JOBS = [f"{voice}_{index}" for voice in ("female", "male") for index in (1, 2, 3)]
JOBS += ["vibrato", "vowel", "mix_short", "drums_1"]

def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    short_mix = TARGET / "mix_short_input.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i",
                    str(SOURCE / "mix_1_input.wav"), "-t", "15",
                    "-c:a", "pcm_f32le", str(short_mix)], check=True)
    rows = []
    for name in JOBS:
        artificial = name in ("vibrato", "vowel")
        source = SOURCE / "artificial" if artificial else SOURCE
        input_wav = short_mix if name == "mix_short" else source / f"{name}_input.wav"
        if not input_wav.exists():
            raise FileNotFoundError(input_wav)
        for speed, speed_code in ((0.75, "075"), (0.50, "050")):
            output = TARGET / f"{name}_{speed_code}_wsola.wav"
            diagnostics = TARGET / "diagnostics" / f"{name}_{speed_code}.csv"
            baseline = (TARGET if name == "mix_short" else source) / f"{name}_{speed_code}_off.wav"
            if name == "mix_short":
                pv_cmd = [str(ROOT / "build/timestretch"), str(input_wav),
                          str(baseline), "--speed", str(speed), "--phase-locking", "on",
                          "--partial-tracking", "off", "--pvsola", "off",
                          "--transient", "on", "--adaptive-time-map", "on",
                          "--precise-anchoring", "on", "--stereo-coherence", "on",
                          "--quality", "high", "--chunked", "on"]
                subprocess.run(pv_cmd, check=True, capture_output=True, text=True)
            cmd = [str(EXECUTABLE), str(input_wav), str(output), "--speed", str(speed),
                   "--window", "2048", "--hop", "512", "--search", "512",
                   "--debug-csv", str(diagnostics)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(name, speed_code, result.stdout.strip(), flush=True)
            fields = dict(item.split("=", 1) for item in result.stdout.strip().split())
            rows.append({"section": name, "speed": speed, "input": str(input_wav),
                         "phase53": str(baseline), "wsola": str(output),
                         "diagnostics": str(diagnostics), **fields})
    with (TARGET / "manifest.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

if __name__ == "__main__":
    sys.exit(main())
