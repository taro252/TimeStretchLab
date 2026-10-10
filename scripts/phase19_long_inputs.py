#!/usr/bin/env python3
"""Create local, ignored duration probes from a user-supplied PCM16 MIX WAV."""
import argparse
import pathlib
import wave


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("output_directory", type=pathlib.Path)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.source), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        rate = source.getframerate()
        if channels not in (1, 2) or width != 2 or rate not in (44100, 48000):
            raise ValueError("Expected mono/stereo PCM16 at 44.1 or 48 kHz")
        for seconds in (30, 60, 180, 300):
            source.rewind()
            target_frames = seconds * rate
            path = args.output_directory / f"mix_input_{seconds}s.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(channels)
                output.setsampwidth(width)
                output.setframerate(rate)
                remaining = target_frames
                while remaining:
                    block = source.readframes(min(65536, remaining))
                    frames = len(block) // (channels * width)
                    if frames == 0:
                        output.writeframesraw(bytes(min(65536, remaining) * channels * width))
                        remaining -= min(65536, remaining)
                    else:
                        output.writeframesraw(block)
                        remaining -= frames
            print(f"{path}: {target_frames} frames at {rate} Hz")


if __name__ == "__main__":
    main()
