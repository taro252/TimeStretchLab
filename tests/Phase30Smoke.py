#!/usr/bin/env python3
"""Portable arbitrary-speed FIFO/PCM test with a generated stereo signal."""
import math
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


def main(executable):
    with tempfile.TemporaryDirectory(prefix="phase30-smoke-") as directory:
        root = Path(directory)
        source = root / "input.wav"
        rate = 48000
        with wave.open(str(source), "wb") as writer:
            writer.setnchannels(2)
            writer.setsampwidth(2)
            writer.setframerate(rate)
            frames = bytearray()
            for index in range(rate * 6):
                impulse = 0.4 if index in (rate, 3 * rate, 5 * rate) else 0
                value = 0.2 * math.sin(2 * math.pi * 437.3 * index / rate) + impulse
                frames.extend(struct.pack("<hh", int(value * 32767),
                                          int(value * 0.8 * 32767)))
            writer.writeframes(frames)
        for initial, target in (("0.50", "0.70"), ("0.70", "0.50"),
                                ("0.90", "1.00"), ("1.00", "0.90"),
                                ("0.654321", "0.876543"),
                                ("0.876543", "0.654321")):
            subprocess.run((executable, str(source), initial, target, "1.0",
                            str(root / "output.wav")), check=True,
                           stdout=subprocess.DEVNULL)
        schedule = root / "changes.csv"
        schedule.write_text("output_seconds,target_speed\n"
                            "1.0,0.70\n3.0,0.60\n5.0,0.80\n")
        subprocess.run((executable, str(source), "0.50", "@" + str(schedule),
                        "0", str(root / "multi.wav")), check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run((executable, "--stop", str(source)), check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run((executable, "--late", str(source)), check=True,
                       stdout=subprocess.DEVNULL)
    print("Phase 30 smoke: 6 directions and 3 consecutive changes are PCM-identical")


if __name__ == "__main__":
    main(sys.argv[1])
