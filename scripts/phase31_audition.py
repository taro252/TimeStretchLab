#!/usr/bin/env python3
"""Create equal fixed-gain listening copies, leaving raw DSP WAV untouched."""
from array import array
import csv
import hashlib
from pathlib import Path
import struct

from phase31_study import chunks

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "results/phase31"
DEST = TARGET / "audition"
DEST.mkdir(parents=True, exist_ok=True)
GAIN = 0.5
FILES = (
    "mix_B_025", "mix_B_049", "mix_A_050", "mix_A_200",
    "vocal_B_025", "vocal_B_049", "vocal_A_050", "vocal_A_200",
    "drums_B_025", "drums_A_050", "drums_A_200",
    "click_B_025", "click_B_049", "click_A_050", "click_A_200",
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


rows = []
for stem in FILES:
    source = TARGET / "raw" / f"{stem}.wav"
    parts = chunks(source)
    code, channels, rate, _, block, bits = struct.unpack_from("<HHIIHH", parts[b"fmt "])
    if (code, bits, block) != (3, 32, channels * 4):
        raise ValueError(f"Expected float32 WAV: {source}")
    signal = array("f")
    signal.frombytes(parts[b"data"])
    if not signal:
        raise ValueError(f"Empty audio: {source}")
    raw_peak = max(map(abs, signal))
    for i in range(len(signal)):
        signal[i] *= GAIN
    payload = signal.tobytes()
    wav = (b"RIFF" + struct.pack("<I", 36 + len(payload)) + b"WAVEfmt "
           + struct.pack("<IHHIIHH", 16, 3, channels, rate,
                         rate * block, block, 32)
           + b"data" + struct.pack("<I", len(payload)) + payload)
    destination = DEST / f"{stem}_gain050.wav"
    destination.write_bytes(wav)
    rows.append({"source": stem, "sample_rate": rate, "frames": len(signal) // channels,
                 "gain": GAIN, "raw_peak": raw_peak, "audition_peak": max(map(abs, signal)),
                 "raw_sha256": sha(source), "audition_sha256": sha(destination),
                 "audition_path": str(destination.relative_to(ROOT))})
with (TARGET / "audition.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
print(f"Created {len(rows)} fixed-headroom listening copies")
