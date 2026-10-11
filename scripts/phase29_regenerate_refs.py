#!/usr/bin/env python3
"""Recreate Phase 12/28 references in a separate directory and verify their hashes.

The five licensed input WAVs must be restored privately before running this.
Nothing in the frozen Golden directories is modified.
"""
import argparse
import csv
import hashlib
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()

DSP_ARGS = ("--phase-locking", "on", "--transient", "on",
            "--adaptive-time-map", "on", "--precise-anchoring", "on",
            "--stereo-coherence", "on", "--quality", "experimental",
            "--low-crossover-hz", "250", "--high-crossover-hz", "3500",
            "--chunked", "on", "--chunk-size", "16384")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("private_input_dir", type=Path,
                        help="directory containing mix/vocal/bass/drums/guitar.wav")
    parser.add_argument("separate_output_dir", type=Path)
    parser.add_argument("--name", choices=("mix", "vocal", "bass", "drums", "guitar"),
                        help="verify one source first; default verifies all five")
    args = parser.parse_args()
    destination = args.separate_output_dir.resolve()
    for frozen in (ROOT / "results/phase12/golden", ROOT / "results/phase28/golden"):
        if destination == frozen or frozen in destination.parents:
            raise RuntimeError("Refusing to write inside a frozen Golden directory")
    args.separate_output_dir.mkdir(parents=True, exist_ok=True)
    verified = 0
    for manifest in (ROOT / "results/phase12/golden/manifest.csv",
                     ROOT / "results/phase28/golden/manifest.csv"):
        with manifest.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            if row["speed"] not in ("0.50", "0.60", "0.70", "0.75", "0.80"):
                continue
            if args.name is not None and row["name"] != args.name:
                continue
            source = args.private_input_dir / f"{row['name']}.wav"
            if not source.exists() or digest(source) != row["input_sha256"]:
                raise RuntimeError(f"Missing or incorrect private input: {source}")
            output = args.separate_output_dir / f"{row['name']}_{row['speed'].replace('.', '')}.wav"
            completed = subprocess.run((str(ROOT / "build/timestretch"),
                                        str(source), str(output), "--speed",
                                        row["speed"], *DSP_ARGS), capture_output=True, text=True)
            if completed.returncode:
                raise RuntimeError(f"Offline regeneration failed: {output}; {completed.stderr}")
            if digest(output) != row["output_sha256"]:
                raise RuntimeError(f"Regenerated output mismatch: {output}; {completed.stderr}")
            verified += 1
            print(f"{row['name']} {row['speed']}: SHA-256 identical", flush=True)
    print(f"Verified {verified} privately regenerated references")


if __name__ == "__main__":
    main()
