#!/usr/bin/env python3
"""Independent high-speed map/variable-hop/FIFO regression."""
import csv
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args, valid=True):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if (result.returncode == 0) != valid:
        raise AssertionError((args, result.returncode, result.stdout, result.stderr))
    return result.stdout


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).digest()


def main(sim, reference, root):
    root = Path(root)
    source = root / "results/phase31/input/click.wav"
    baseline = root / "results/phase37/raw/click_B_150.wav"
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        fixed64 = directory / "fixed64.wav"
        fixed4096 = directory / "fixed4096.wav"
        run(sim, source, fixed64, "1.5", "-", "64")
        run(sim, source, fixed4096, "1.5", "-", "4096")
        assert sha(fixed64) == sha(fixed4096) == sha(baseline)
        changed = directory / "changed.wav"
        offline = directory / "offline.wav"
        plan = directory / "plan.csv"
        text = run(sim, source, changed, "1.0", "0.5:2.0", "512", plan)
        assert "underrun=0" in text and "rejected_writes=0" in text
        run(reference, source, offline, "1.0", plan)
        assert sha(changed) == sha(offline)
        with plan.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 1
        assert int(rows[0]["applied_output"]) > int(rows[0]["published"])
        run(sim, source, directory / "bad.wav", "0.25", "-", "512", valid=False)
    print("Phase 39 smoke: fixed byte match, callback partition, transition reference, FIFO and validation OK")


if __name__ == "__main__":
    main(*sys.argv[1:])
