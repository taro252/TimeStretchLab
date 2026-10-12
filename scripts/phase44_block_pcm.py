#!/usr/bin/env python3
"""Compare the raw PCM for two DSP publication block sizes."""
import hashlib
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "results/phase44/block_pcm"
out.mkdir(parents=True, exist_ok=True)
hashes = {}
for block in (1024, 2048):
    wav = out / f"mix_{block}.wav"
    command = [str(root / "build/phase39_sim"),
               str(root / "results/phase31/input/mix.wav"), str(wav), "0.4",
               "1.0:2.0", "512", str(out / f"plan_{block}.csv"), str(block),
               "C", "safe-density"]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    (out / f"run_{block}.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(f"block {block} failed; see log")
    hashes[block] = hashlib.sha256(wav.read_bytes()).hexdigest()
if hashes[1024] != hashes[2048]:
    raise SystemExit(f"Block PCM differs: {hashes}")
print(f"1024/2048 raw PCM identical: {hashes[1024]}")
