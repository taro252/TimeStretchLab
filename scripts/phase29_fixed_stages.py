#!/usr/bin/env python3
"""Compare Phase 29 fixed-speed stage digests with frozen Phase 13 streaming."""
import csv
from pathlib import Path
import subprocess
import tempfile

from phase29_study import FIXED, NAMES, OUT, ROOT, digest, input_path, write_csv


def fields(output: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def main() -> None:
    rows = []
    with (OUT / "fixed_regression.csv").open(newline="") as stream:
        frozen_rows = {(row["source"], row["speed"]): row for row in csv.DictReader(stream)}
    with tempfile.TemporaryDirectory(prefix="phase29_stages_") as directory:
        for name in NAMES:
            source = input_path(name)
            for speed in FIXED:
                label = f"fixed_{name}_{speed.replace('.', '')}"
                output = Path(directory) / f"{label}.wav"
                result = subprocess.run((str(ROOT / "build/phase13_stream"),
                                         str(source), str(output), "16384", speed),
                                        text=True, capture_output=True)
                if result.returncode:
                    raise RuntimeError(f"{label}: {result.stderr}")
                old = fields(result.stdout)
                new = fields((OUT / "diagnostics" / f"{label}.txt").read_text())
                compared = ("low_fft", "low_phase", "low_ifft", "low_ola",
                            "mid_fft", "mid_phase", "mid_ifft", "mid_ola",
                            "high_fft", "high_phase", "high_ifft", "high_ola",
                            "low_fir", "high_fir")
                if any(old[field] != new[field] for field in compared):
                    raise RuntimeError(f"Stage digest mismatch: {label}")
                if old["fir_output"] != new["output_fir"]:
                    raise RuntimeError(f"Output FIR mismatch: {label}")
                if old["time_map_hash"] != new["map_hash"]:
                    raise RuntimeError(f"TimeMap hash mismatch: {label}")
                golden = frozen_rows[(name, speed)]
                if digest(output) != golden["golden_sha256"]:
                    raise RuntimeError(f"Phase 13 bytes changed: {label}")
                rows.append(dict(source=name, speed=speed,
                                 time_map_hash=new["map_hash"],
                                 fft_phase_ifft_ola="identical",
                                 low_high_fir="identical",
                                 final_wav="identical"))
                print(label, "all stages identical", flush=True)
    write_csv(OUT / "fixed_stage_regression.csv", rows)


if __name__ == "__main__":
    main()
