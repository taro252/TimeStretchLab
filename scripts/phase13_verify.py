#!/usr/bin/env python3
"""Verify fixed-speed Phase 13 against immutable Phase 12 raw Golden WAVs."""
import csv
import hashlib
import json
import pathlib
import re
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "results/phase12/golden"
OUT = ROOT / "results/phase13"
EXE = ROOT / "build/phase13_stream"
COMPARE = ROOT / "build/wav_compare"
NAMES = ("mix", "vocal", "bass", "drums", "guitar")
BLOCKS = (8192, 16384)
STAGES = tuple(f"{r}_{s}" for r in ("low", "mid", "high")
               for s in ("fft", "phase", "ifft", "ola")) + ("low_fir", "high_fir", "fir_output")


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(name, block):
    destination = OUT / "raw" / f"{name}_050_block{block}.wav"
    start = time.monotonic()
    process = subprocess.run([str(EXE), str(GOLDEN / "input" / f"{name}.wav"),
                              str(destination), str(block)], check=True,
                             capture_output=True, text=True)
    seconds = time.monotonic() - start
    fields = dict(line.split("=", 1) for line in process.stdout.strip().splitlines())
    return destination, fields, seconds


def main():
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    (OUT / "diagnostics").mkdir(parents=True, exist_ok=True)
    with (GOLDEN / "manifest.csv").open(newline="") as source:
        manifest = {row["name"]: row for row in csv.DictReader(source)
                    if row["speed"] == "0.50"}
    rows = []
    failures = []
    for name in NAMES:
        golden = GOLDEN / "raw" / f"{name}_050.wav"
        expected = manifest[name]
        if sha(golden) != expected["output_sha256"]:
            raise RuntimeError(f"Golden hash changed: {name}")
        if sha(GOLDEN / "input" / f"{name}.wav") != expected["input_sha256"]:
            raise RuntimeError(f"Input hash changed: {name}")
        first_fields = None
        for block in BLOCKS:
            output, fields, seconds = run(name, block)
            comparison = subprocess.run([str(COMPARE), str(golden), str(output)],
                                        check=True, capture_output=True, text=True).stdout.strip()
            maximum = float(re.search(r"max_difference=([\d.]+)", comparison).group(1))
            stage_match = first_fields is None or all(fields[key] == first_fields[key]
                                                       for key in STAGES)
            map_match = fields["time_map_hash"] == expected["time_map_hash"]
            frame_match = fields["output_frames"] == expected["output_frames"]
            hash_match = sha(output) == expected["output_sha256"]
            passed = all((maximum < 1e-5, stage_match, map_match,
                          frame_match, hash_match))
            if not passed:
                failures.append((name, block))
            rows.append(dict(name=name, block_frames=block, output_frames=fields["output_frames"],
                             time_map_hash=fields["time_map_hash"], golden_sha256=sha(golden),
                             output_sha256=sha(output), max_abs_difference=maximum,
                             stage_digests_match=stage_match, golden_hash_match=hash_match,
                             time_map_match=map_match, output_length_match=frame_match,
                             seconds=round(seconds, 3), passed=passed))
            if first_fields is None:
                first_fields = fields
                (OUT / "diagnostics" / f"{name}_050_stage_hashes.json").write_text(
                    json.dumps({key: fields[key] for key in (*STAGES, "time_map_hash")}, indent=2)
                    + "\n")
            print(name, block, f"max={maximum:.10g}",
                  f"stages={'equal' if stage_match else 'DIFFER'}",
                  f"golden={'equal' if hash_match else 'DIFFER'}", flush=True)
    anchor = json.loads((GOLDEN / "anchor_diagnostic.json").read_text())
    anchor_input = ROOT / anchor["input_path"]
    anchor_golden = GOLDEN / "anchor_click_050.wav"
    if sha(anchor_input) != anchor["input_sha256"] or sha(anchor_golden) != anchor["output_sha256"]:
        raise RuntimeError("Anchor input or Golden hash changed")
    anchor_stages = None
    for block in BLOCKS:
        output = OUT / "raw" / f"anchor_click_050_block{block}.wav"
        start = time.monotonic()
        process = subprocess.run([str(EXE), str(anchor_input), str(output), str(block)],
                                 check=True, capture_output=True, text=True)
        seconds = time.monotonic() - start
        fields = dict(line.split("=", 1) for line in process.stdout.strip().splitlines())
        comparison = subprocess.run([str(COMPARE), str(anchor_golden), str(output)],
                                    check=True, capture_output=True, text=True).stdout.strip()
        maximum = float(re.search(r"max_difference=([\d.]+)", comparison).group(1))
        stage_match = anchor_stages is None or all(fields[key] == anchor_stages[key]
                                                   for key in STAGES)
        passed = (maximum < 1e-5 and stage_match and
                  sha(output) == anchor["output_sha256"] and
                  fields["time_map_hash"] == anchor["time_map_hash"] and
                  fields["output_frames"] == str(anchor["frames"]))
        if not passed:
            failures.append(("anchor_click", block))
        rows.append(dict(name="anchor_click", block_frames=block,
                         output_frames=fields["output_frames"],
                         time_map_hash=fields["time_map_hash"],
                         golden_sha256=anchor["output_sha256"], output_sha256=sha(output),
                         max_abs_difference=maximum, stage_digests_match=stage_match,
                         golden_hash_match=sha(output) == anchor["output_sha256"],
                         time_map_match=fields["time_map_hash"] == anchor["time_map_hash"],
                         output_length_match=fields["output_frames"] == str(anchor["frames"]),
                         seconds=round(seconds, 3), passed=passed))
        if anchor_stages is None:
            anchor_stages = fields
        print("anchor_click", block, f"max={maximum:.10g}",
              f"stages={'equal' if stage_match else 'DIFFER'}",
              f"golden={'equal' if sha(output) == anchor['output_sha256'] else 'DIFFER'}",
              flush=True)
    with (OUT / "diagnostics" / "verification.csv").open("w", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    if failures:
        raise SystemExit(f"Phase 13 verification failed: {failures}")


if __name__ == "__main__":
    main()
