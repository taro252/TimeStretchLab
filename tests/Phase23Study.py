#!/usr/bin/env python3
"""Reproduce Phase 23 fixed Golden checks and independent switched WAVs."""
import array
import csv
import filecmp
import math
import os
from pathlib import Path
import struct
import subprocess
import sys


def create_float_wav(path, frames, kind):
    rate = 48000
    samples = array.array("f")
    for i in range(frames):
        if kind == "click":
            sample = 0.8 if i % 24000 == 12000 else 0.0
            samples.extend((sample, sample))
        else:
            phase = 2 * math.pi * 437.3 * i / rate
            samples.extend((0.2 * math.sin(phase), 0.2 * math.sin(phase + math.pi / 4)))
    data = samples.tobytes()
    with path.open("wb") as output:
        output.write(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE")
        output.write(b"fmt " + struct.pack("<IHHIIHH", 16, 3, 2, rate,
                                              rate * 8, 8, 32))
        output.write(b"data" + struct.pack("<I", len(data)))
        output.write(data)


def metadata(path):
    with path.open("rb") as stream:
        if stream.read(4) != b"RIFF":
            raise RuntimeError(f"Not RIFF: {path}")
        stream.seek(12)
        channels = rate = bits = byte_count = None
        while True:
            chunk = stream.read(8)
            if len(chunk) != 8:
                break
            name, size = struct.unpack("<4sI", chunk)
            position = stream.tell()
            if name == b"fmt ":
                fmt = stream.read(16)
                _, channels, rate, _, _, bits = struct.unpack("<HHIIHH", fmt)
            elif name == b"data":
                byte_count = size
            stream.seek(position + size + (size & 1))
        if None in (channels, rate, bits, byte_count):
            raise RuntimeError(f"Incomplete WAV: {path}")
    return byte_count // (channels * bits // 8), rate


def run(command, trace):
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    trace.write_text(completed.stdout)
    return dict(line.split("=", 1) for line in completed.stdout.splitlines()
                if "=" in line)


def link(target, destination):
    destination.unlink(missing_ok=True)
    destination.symlink_to(os.path.relpath(target, destination.parent))


def main():
    root = Path(sys.argv[1]).resolve()
    output = root / "results/phase23"
    tool = root / "build/phase23_audio"
    phase13 = root / "build/phase13_stream"
    (output / "input").mkdir(parents=True, exist_ok=True)
    (output / "raw").mkdir(exist_ok=True)
    (output / "diagnostics").mkdir(exist_ok=True)
    (output / "audition").mkdir(exist_ok=True)
    (output / "baseline").mkdir(exist_ok=True)
    create_float_wav(output / "input/click.wav", 48000 * 6, "click")
    create_float_wav(output / "input/sine.wav", 48000 * 8, "sine")
    rows = []
    for name in ("mix", "vocal", "bass", "drums", "guitar", "click", "sine"):
        input_path = (root / "results/phase12/golden/input" / f"{name}.wav"
                      if name not in ("click", "sine") else output / "input" / f"{name}.wav")
        frames, rate = metadata(input_path)
        audition = output / "audition" / name
        audition.mkdir(exist_ok=True)
        references = {}
        for mode, speed in (("050", "0.50"), ("075", "0.75")):
            reference = (root / "results/phase12/golden/raw" / f"{name}_{mode}.wav"
                         if name not in ("click", "sine")
                         else output / "baseline" / f"{name}_{mode}.wav")
            if name in ("click", "sine"):
                run([str(phase13), str(input_path), str(reference), "16384", speed],
                    output / "diagnostics" / f"{name}_{mode}_phase13.txt")
            candidate = output / "raw" / f"{name}_fixed_{mode}.wav"
            info = run([str(tool), str(input_path), str(candidate), mode,
                        str(output / "diagnostics" / f"{name}_{mode}.csv")],
                       output / "diagnostics" / f"{name}_{mode}.txt")
            if not filecmp.cmp(candidate, reference, shallow=False):
                raise RuntimeError(f"Fixed Golden differs: {name} {mode}")
            candidate.unlink()
            references[mode] = reference
            rows.append((name, mode, frames, info["output_frames"],
                         "byte-identical", info["dsp_seconds"], info["peak_rss_kib"],
                         info["peak"], info["timemap_hash"]))
        request = round(frames * 0.5)
        candidate = output / "raw" / f"{name}_switch.wav"
        info = run([str(tool), str(input_path), str(candidate), "switch",
                    str(output / "diagnostics" / f"{name}_switch.csv"), str(request)],
                   output / "diagnostics" / f"{name}_switch.txt")
        rows.append((name, "switch", frames, info["output_frames"], "variable",
                     info["dsp_seconds"], info["peak_rss_kib"], info["peak"],
                     info["timemap_hash"]))
        link(references["050"], audition / "A_fixed_050.wav")
        link(references["075"], audition / "B_fixed_075.wav")
        link(candidate, audition / "C_switch.wav")
        print(name, "fixed=byte-identical", "switch_frames=" + info["output_frames"],
              "request=" + str(request), flush=True)
    with (output / "run_summary.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("source", "mode", "input_frames", "output_frames", "fixed_match",
                         "dsp_seconds", "peak_rss_kib", "peak", "timemap_hash"))
        writer.writerows(rows)


if __name__ == "__main__":
    main()
