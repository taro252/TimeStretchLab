#!/usr/bin/env python3
"""Fast, self-contained fixed/switch PCM regression for the Phase 29 CLI."""
import csv
import hashlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]}: {result.stderr}")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    phase13, phase29 = sys.argv[1:3]
    with tempfile.TemporaryDirectory(prefix="phase29_test_") as tmp:
        root = Path(tmp)
        source = root / "click.wav"
        frames = 48000 * 4
        data = bytearray()
        for i in range(frames):
            value = 0.8 if i % 24000 == 12000 else 0.0
            data.extend(struct.pack("<ff", value, value))
        source.write_bytes(
            b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 3, 2, 48000, 384000, 8, 32)
            + b"data" + struct.pack("<I", len(data)) + data)
        empty = root / "empty.csv"
        empty.write_text("input_sample,target_speed\n")
        for speed in ("0.50", "0.60", "0.70", "0.75", "0.80"):
            reference = root / f"reference_{speed}.wav"
            candidate = root / f"candidate_{speed}.wav"
            run(phase13, str(source), str(reference), "16384", speed)
            run(phase29, str(source), str(candidate), speed, str(empty),
                str(root / f"fixed_{speed}"))
            if digest(reference) != digest(candidate):
                raise RuntimeError(f"Fixed {speed} differs")
        for initial, target in (("0.50", "0.70"), ("0.70", "0.50")):
            schedule = root / f"switch_{initial}.csv"
            schedule.write_text(f"input_sample,target_speed\n96000,{target}\n")
            first = root / f"first_{initial}.wav"
            second = root / f"second_{initial}.wav"
            run(phase29, str(source), str(first), initial, str(schedule),
                str(root / f"first_{initial}"), "8192")
            run(phase29, str(source), str(second), initial, str(schedule),
                str(root / f"second_{initial}"), "65536")
            if digest(first) != digest(second):
                raise RuntimeError("Output partition changes PCM")
            with (root / f"first_{initial}.plans.csv").open() as stream:
                plan = next(csv.DictReader(stream))
            published = int(plan["published_output"])
            if plan["outcome"] != "0":
                raise RuntimeError(f"Transition not applied: {plan}")
            fixed = (root / f"reference_{initial}.wav").read_bytes()
            switched = first.read_bytes()
            if switched[44:44+published*8] != fixed[44:44+published*8]:
                raise RuntimeError("Published raw PCM changed")
            if len(switched) != 44 + int.from_bytes(switched[40:44], "little"):
                raise RuntimeError("Incorrect EOS WAV length")
        for bad in ("0.49", "1.01", "nan"):
            result = subprocess.run((phase29, str(source), str(root / "bad.wav"),
                                     bad, str(empty), str(root / "bad")),
                                    capture_output=True)
            if result.returncode == 0:
                raise RuntimeError(f"Invalid speed accepted: {bad}")
        print("Phase 29: 5 fixed byte matches; both switch directions partition/prefix/EOS; invalid speeds")


if __name__ == "__main__":
    main()
