#!/usr/bin/env python3
"""Long Phase 39 EOS, FIFO, CPU and RSS benchmark without keeping PCM."""
import csv
import struct
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
rows = []
for seconds in (180, 300, 600):
    path = root / f"results/phase14/benchmark/mix_repeat_{seconds}.wav"
    header = path.open("rb").read(44)
    channels = struct.unpack_from("<H", header, 22)[0]
    rate = struct.unpack_from("<I", header, 24)[0]
    input_frames = (path.stat().st_size - 44) // (4 * channels)
    command = [str(root / "build/phase39_sim"), str(path), "-", "1.0",
               "1.0:2.0", "512", str(root / f"results/phase39/long_{seconds}.csv")]
    done = subprocess.run(command, text=True, capture_output=True, cwd=root)
    if done.returncode:
        raise RuntimeError(f"{seconds}s: {done.stderr}")
    values = dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)
    if values["changes"] != "1" or values["underrun"] != "0" or values["rejected_writes"] != "0":
        raise RuntimeError(f"{seconds}s: FIFO/change failure {values}")
    rows.append(dict(input_seconds=input_frames / rate, input_frames=input_frames,
                     output_frames=values["frames"], wall_seconds=values["wall_seconds"],
                     user_cpu_seconds=values["user_cpu_seconds"],
                     peak_rss_bytes=values["peak_rss_bytes"],
                     max_worker_chunk_seconds=values["max_worker_chunk_seconds"],
                     p95_worker_chunk_seconds=values["p95_worker_chunk_seconds"],
                     max_callback_seconds=values["max_callback_seconds"],
                     fifo_high_water=values["fifo_high_water"],
                     underrun=values["underrun"], rejected_writes=values["rejected_writes"]))
    print(rows[-1], flush=True)
with (root / "results/phase39/long.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
