#!/usr/bin/env python3
"""Research guard: reject unsafe A, recover coverage, preserve 0.50x boundary."""
import csv
import hashlib
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def run(*args, succeeds=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if (result.returncode == 0) != succeeds:
        raise RuntimeError(f"Unexpected exit {result.returncode}: {args}\n{result.stderr}")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    study, render = sys.argv[1:3]
    with tempfile.TemporaryDirectory(prefix="phase31-") as temporary:
        root = Path(temporary)
        source = root / "sine.wav"
        frames = 48000 * 2
        samples = bytearray()
        for i in range(frames):
            signal = 0.2 * math.sin(2 * math.pi * 437.3 * i / 48000)
            samples += struct.pack("<ff", signal, signal)
        source.write_bytes(b"RIFF" + struct.pack("<I", 36 + len(samples))
                           + b"WAVEfmt "
                           + struct.pack("<IHHIIHH", 16, 3, 2,
                                         48000, 384000, 8, 32)
                           + b"data" + struct.pack("<I", len(samples)) + samples)
        table = root / "study.csv"
        run(study, source, table)
        rows = list(csv.DictReader(table.open()))
        for resolution in "012":
            at25 = {r["mode"]: r for r in rows if r["speed"] == "0.25"
                    and r["resolution"] == resolution}
            if int(at25["A"]["ge_window"]) == 0:
                raise RuntimeError("0.25x frozen schedule did not expose OLA gap")
            if any(int(at25[mode]["ge_window"]) or
                   float(at25[mode]["min_hann2_weight_worst_gap"]) <= 0.01
                   for mode in "BC"):
                raise RuntimeError("Research schedule did not restore OLA coverage")
        click = root / "click.wav"
        clicks = bytearray()
        for i in range(frames):
            value = 0.8 if i % 24000 == 12000 else 0.0
            clicks += struct.pack("<ff", value, value)
        click.write_bytes(source.read_bytes()[:44] + clicks)
        click_table = root / "click.csv"
        run(study, click, click_table)
        click_rows = list(csv.DictReader(click_table.open()))
        low = next(r for r in click_rows if r["speed"] == "0.5" and
                   r["mode"] == "A" and r["resolution"] == "1")
        high = next(r for r in click_rows if r["speed"] == "1.5" and
                    r["mode"] == "A" and r["resolution"] == "1")
        if low["protection_changed"] != "1" or high["protection_changed"] != "0" or \
           high["anchor_changed"] != "0":
            raise RuntimeError("High-speed transient policy changed unexpectedly")
        run(render, source, root / "forbidden.wav", "0.25", "A", succeeds=False)
        run(render, source, root / "low.wav", "0.25", "B")
        run(render, source, root / "baseline.wav", "0.50", "A")
        run(render, source, root / "boundary.wav", "0.50", "B")
        if digest(root / "baseline.wav") != digest(root / "boundary.wav"):
            raise RuntimeError("0.50x boundary changed the frozen DSP output")
    print("Phase 31: unsafe 0.25x A rejected; B/C OLA coverage; 0.50x byte match")


if __name__ == "__main__":
    main()
