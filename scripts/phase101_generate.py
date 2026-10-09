"""Deterministic short transient signals for Phase 10.1 A/B measurements."""
from __future__ import annotations

import math
import pathlib
import random
import struct
import wave

RATE = 48_000
FRAMES = RATE * 10
ROOT = pathlib.Path(__file__).resolve().parents[1] / "results/phase101/artificial"
ROOT.mkdir(parents=True, exist_ok=True)


def render(kind: str) -> None:
    rng = random.Random(101)
    output = bytearray()
    left = [0.0] * FRAMES
    if kind == "impulse":
        left[RATE * 2 + 311] = 0.9
        left[RATE * 6 + 733] = 0.8
    elif kind == "click_train":
        for at in range(RATE // 2, FRAMES, RATE // 2):
            left[at + 113] = 0.85
    elif kind == "artificial_drum":
        for beat in range(1, 20):
            at = beat * RATE // 2
            for j in range(min(RATE // 5, FRAMES - at)):
                time = j / RATE
                if beat % 2:
                    left[at + j] += 0.6 * math.exp(-time * 26) * math.sin(
                        2 * math.pi * (65 * time + 35 * time * time)
                    )
                else:
                    left[at + j] += 0.24 * math.exp(-time * 35) * rng.uniform(-1, 1)
    elif kind == "short_noise_burst":
        for at in (RATE * 2 + 137, RATE * 5 + 401, RATE * 8 + 59):
            for j in range(RATE // 50):
                left[at + j] = 0.4 * rng.uniform(-1, 1)
    elif kind == "decaying_noise":
        for at in (RATE * 2 + 137, RATE * 5 + 401, RATE * 8 + 59):
            previous = 0.0
            for j in range(RATE // 2):
                value = rng.uniform(-1, 1)
                high = value - previous
                previous = value
                left[at + j] = 0.3 * high * math.exp(-j / (RATE * 0.085))
    for value in left:
        value = max(-1.0, min(1.0, value))
        sample = round(value * 32767)
        output.extend(struct.pack("<hh", sample, sample))
    with wave.open(str(ROOT / f"{kind}_input.wav"), "wb") as file:
        file.setnchannels(2)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(output)


if __name__ == "__main__":
    for name in (
        "impulse", "click_train", "artificial_drum", "short_noise_burst", "decaying_noise"
    ):
        render(name)
