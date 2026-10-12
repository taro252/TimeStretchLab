#!/usr/bin/env python3
"""Read-only verification of the frozen 25 Golden WAVs and Phase 36 copies."""
import csv
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase42/golden_audit.csv"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


rows = []
for manifest in ("results/phase12/golden/manifest.csv", "results/phase28/golden/manifest.csv"):
    with (ROOT / manifest).open() as stream:
        for entry in csv.DictReader(stream):
            if entry["speed"] not in ("0.50", "0.60", "0.70", "0.75", "0.80"):
                continue
            golden = ROOT / entry["output_path"]
            copied = ROOT / "results/phase36/raw" / f'golden_{entry["name"]}_{entry["speed"].replace(".", "")}.wav'
            expected = entry["output_sha256"]
            got_golden = sha(golden)
            got_stream = sha(copied)
            equal = expected == got_golden == got_stream
            rows.append(dict(source=entry["name"], speed=entry["speed"],
                             expected_sha256=expected, golden_sha256=got_golden,
                             stream_sha256=got_stream, equal=int(equal)))
            if not equal:
                raise RuntimeError(f"Golden mismatch: {golden}")
if len(rows) != 25:
    raise RuntimeError(f"Expected 25 records, found {len(rows)}")
OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
print("25/25 frozen Golden and stream copies match")
