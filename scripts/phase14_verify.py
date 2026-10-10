#!/usr/bin/env python3
"""Run Phase 14's simulated callback and check unadjusted raw WAV bytes."""
import csv
import hashlib
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLD = ROOT / "results/phase12/golden"
OUT = ROOT / "results/phase14"
EXE = ROOT / "build/phase14_sim"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(name, callback):
    if name == "anchor_click":
        # The exact source path is stored in the frozen diagnostic manifest.
        import json
        anchor = json.loads((GOLD / "anchor_diagnostic.json").read_text())
        source = ROOT / anchor["input_path"]
        golden = GOLD / "anchor_click_050.wav"
    else:
        source = GOLD / "input" / f"{name}.wav"
        golden = GOLD / "raw" / f"{name}_050.wav"
    output = OUT / "raw" / f"{name}_callback{callback}.wav"
    process = subprocess.run([str(EXE), str(source), str(output), str(callback)],
                             check=True, text=True, capture_output=True)
    fields = dict(line.split("=", 1) for line in process.stdout.strip().splitlines())
    identical = sha(golden) == sha(output)
    return dict(name=name, callback_frames=callback, golden_sha256=sha(golden),
                output_sha256=sha(output), byte_identical=identical, **fields)


def main():
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    (OUT / "diagnostics").mkdir(parents=True, exist_ok=True)
    rows = []
    for name in ("mix", "vocal", "bass", "drums", "guitar", "anchor_click"):
        for callback in ((64, 128, 256, 512, 1024, 2048, 4096) if name == "mix" else (512,)):
            row = run(name, callback)
            rows.append(row)
            print(name, callback, "equal" if row["byte_identical"] else "DIFFER", flush=True)
    with (OUT / "diagnostics" / "verification.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    if not all(row["byte_identical"] for row in rows):
        raise SystemExit("Golden byte comparison failed")


if __name__ == "__main__":
    main()
