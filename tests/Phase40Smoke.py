#!/usr/bin/env python3
"""Phase 40 A/B/C planner safety, replay and immutable published PCM."""
import csv
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*command):
    completed = subprocess.run([str(x) for x in command],
                               capture_output=True, text=True)
    if completed.returncode:
        raise AssertionError((command, completed.stderr, completed.stdout))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).digest()


def first_changed(a, b):
    with open(a, "rb") as left, open(b, "rb") as right:
        left.read(44)
        right.read(44)
        index = 0
        while True:
            old, new = left.read(8), right.read(8)
            if not old or not new or old != new:
                return index
            index += 1


def main(sim, reference, source):
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        fixed = temp / "fixed.wav"
        run(sim, source, fixed, "1.0", "-", "512")
        fixed_c = temp / "fixed_c.wav"
        run(sim, source, fixed_c, "1.0", "-", "512", temp / "fixed.csv",
            "2048", "C")
        assert sha(fixed) == sha(fixed_c)
        for strategy in "ABC":
            output = temp / f"{strategy}.wav"
            offline = temp / f"{strategy}_offline.wav"
            plan = temp / f"{strategy}.csv"
            run(sim, source, output, "1.0", "0.5:2.0", "512", plan,
                "2048", strategy)
            run(reference, source, offline, "1.0", plan, strategy)
            assert sha(output) == sha(offline)
            metric = next(csv.DictReader(plan.open(newline="")))
            assert first_changed(output, fixed) >= int(metric["published"])
            assert int(metric["applied_output"]) >= int(metric["planning_fence"])
            run(reference, source, "--hops", "1.0", plan, strategy)
        slow = temp / "slow.wav"
        run(sim, source, slow, "0.4", "-", "512")
        output = temp / "slow_to_fast.wav"
        offline = temp / "slow_to_fast_offline.wav"
        plan = temp / "slow_to_fast.csv"
        run(sim, source, output, "0.4", "0.5:2.0", "512", plan,
            "2048", "C")
        run(reference, source, offline, "0.4", plan, "C")
        assert sha(output) == sha(offline)
        metric = next(csv.DictReader(plan.open(newline="")))
        assert first_changed(output, slow) >= int(metric["published"])
        run(reference, source, "--hops", "0.4", plan, "C")
    print("Phase 40: all strategies match offline, preserve published PCM and safe hops")


if __name__ == "__main__":
    main(*sys.argv[1:])
