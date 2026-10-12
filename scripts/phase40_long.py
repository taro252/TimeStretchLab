#!/usr/bin/env python3
"""3/5/10 minute EOS and worker wall/CPU profiling for Phase 40 C."""
import csv
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase40"


def repeated_drums(seconds):
    original = ROOT / "results/phase31/input/drums.wav"
    destination = OUT / "long_input" / f"drums_repeat_{seconds}.wav"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    with original.open("rb") as file:
        header, data = file.read(44), file.read()
    channels = struct.unpack_from("<H", header, 22)[0]
    rate = struct.unpack_from("<I", header, 24)[0]
    original_frames = len(data)//(4*channels)
    frames = seconds*rate
    bytes_count = frames*channels*4
    assert bytes_count < 2**32-36
    header = bytearray(header)
    struct.pack_into("<I", header, 4, 36+bytes_count)
    struct.pack_into("<I", header, 40, bytes_count)
    with destination.open("wb") as output:
        output.write(header)
        for _ in range(frames//original_frames):
            output.write(data)
        output.write(data[:(frames%original_frames)*channels*4])
    return destination


rows = []
for source in ("mix", "drums"):
    for seconds in (180, 300, 600):
        path = (ROOT / f"results/phase14/benchmark/mix_repeat_{seconds}.wav"
                if source == "mix" else repeated_drums(seconds))
        plan = OUT / "plans" / f"long_{source}_{seconds}_C.csv"
        result = subprocess.run([str(ROOT / "build/phase39_sim"), str(path), "-",
                                 "1.0", "1.0:2.0", "512", str(plan), "2048", "C"],
                                cwd=ROOT, text=True, capture_output=True)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        values.update(source=source, input_seconds=seconds,
                      exit_code=result.returncode, error=result.stderr.strip())
        rows.append(values)
        print(source, seconds, result.returncode,
              values.get("max_worker_chunk_seconds"),
              values.get("max_worker_cpu_seconds"), flush=True)

fields = list(dict.fromkeys(key for row in rows for key in row))
with (OUT / "long.csv").open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
