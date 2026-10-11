#!/usr/bin/env python3
"""Repeat a local PCM music WAV to a chosen test length; no audio is committed."""
import argparse
import wave
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=int, default=600)
    args = parser.parse_args()
    if args.seconds <= 0:
        raise ValueError("seconds must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.source), "rb") as reader, wave.open(str(args.output), "wb") as writer:
        if reader.getcomptype() != "NONE":
            raise ValueError("source must be uncompressed PCM")
        writer.setparams(reader.getparams())
        remaining = reader.getframerate() * args.seconds
        width = reader.getnchannels() * reader.getsampwidth()
        while remaining:
            data = reader.readframes(min(65536, remaining))
            frames = len(data) // width
            if not frames:
                reader.rewind()
                continue
            writer.writeframesraw(data)
            remaining -= frames
    print(f"{args.output}: {args.seconds} seconds")


if __name__ == "__main__":
    main()
