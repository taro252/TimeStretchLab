#!/usr/bin/env python3
"""Check fixed PCM partition invariance and live variable-speed replay."""
import csv
import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(block, target, path):
    env = {**os.environ, "PHASE30_TEST_BLOCK": str(block)}
    output = subprocess.run((str(ROOT / "build/phase30_playback_tests"),
                             str(ROOT / "results/phase29/input/sine.wav"),
                             "0.70", target, "2.0" if target != "0.70" else "-1",
                             str(path)), env=env, check=True, text=True,
                            capture_output=True).stdout
    data = dict(row.split("=", 1) for row in output.splitlines() if "=" in row)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"block_frames": block, "target": target, "sha256": digest, **data}


def main():
    rows = []
    with tempfile.TemporaryDirectory(prefix="phase30-partition-") as temp:
        for block in (1024, 2048, 4096):
            for target in ("0.70", "0.50"):
                row = run(block, target, Path(temp) / "out.wav")
                rows.append(row)
                print(block, target, row["sha256"], flush=True)
    fixed = [row["sha256"] for row in rows if row["target"] == "0.70"]
    if len(set(fixed)) != 1:
        raise AssertionError("Fixed-speed PCM depends on DSP block size")
    output = ROOT / "results/phase30/partition.csv"
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
