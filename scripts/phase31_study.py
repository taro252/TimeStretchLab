#!/usr/bin/env python3
"""Independent extended-speed geometry and diagnostic WAV study.

The frozen DSP, Golden WAV, and macOS playback code are never edited here.
Private input audio and diagnostic WAVs remain outside Git via *.wav ignore.
"""
import argparse
import csv
import hashlib
from pathlib import Path
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase31"
SOURCES = ("mix", "vocal", "bass", "drums", "guitar", "click", "sine")
LOW = ("0.25", "0.30", "0.35", "0.40", "0.45")
HIGH = ("1.10", "1.25", "1.50", "1.75", "2.00")
BASE = ("0.50", "0.75", "0.90", "1.00")


def source_path(name):
    if name in ("click", "sine"):
        return ROOT / f"results/phase29/input/{name}.wav"
    return ROOT / f"results/phase12/golden/input/{name}.wav"


def chunks(path):
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"Not a RIFF WAV: {path}")
    offset = 12
    result = {}
    while offset + 8 <= len(data):
        name = data[offset:offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        result[name] = data[offset + 8:offset + 8 + size]
        offset += 8 + size + (size & 1)
    return result


def trim_float_wav(source, target, seconds=10):
    parts = chunks(source)
    fmt = parts[b"fmt "]
    code, channels, rate, _, block, bits = struct.unpack_from("<HHIIHH", fmt)
    if code != 3 or bits != 32 or channels not in (1, 2) or block != channels * 4:
        raise ValueError(f"Expected mono/stereo float32: {source}")
    pcm = parts[b"data"][:min(len(parts[b"data"]), rate * block * seconds)]
    header = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
              + struct.pack("<IHHIIHH", 16, 3, channels, rate,
                            rate * block, block, 32)
              + b"data" + struct.pack("<I", len(pcm)))
    payload = header + pcm
    if target.exists() and target.read_bytes() != payload:
        raise RuntimeError(f"Research clip changed: {target}")
    target.write_bytes(payload)
    return rate, len(pcm) // block


def key_value(output):
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def run(command):
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError(f"{' '.join(map(str, command))}\n{result.stderr}")
    return key_value(result.stdout), time.monotonic() - started


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--maps-only", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    if args.maps_only and args.render_only:
        parser.error("Choose one study mode")
    for folder in (OUT, OUT / "input", OUT / "raw", OUT / "metrics"):
        folder.mkdir(parents=True, exist_ok=True)
    feasibility = ROOT / "build/phase31_feasibility"
    renderer = ROOT / "build/phase31_render"
    metric_tool = ROOT / "build/wav_metrics"
    if not args.render_only:
        for name in SOURCES:
            source = source_path(name)
            table = OUT / "metrics" / f"{name}.csv"
            print("map", name, flush=True)
            result = subprocess.run((feasibility, source, table), capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
    if args.maps_only:
        return
    rows = []
    for name in SOURCES:
        source = source_path(name)
        clip = OUT / "input" / f"{name}.wav"
        rate, frames = trim_float_wav(source, clip)
        for speed in LOW + BASE + HIGH:
            mode = "B" if speed in LOW else "A"
            wav = OUT / "raw" / f"{name}_{mode}_{speed.replace('.', '')}.wav"
            print("render", name, mode, speed, flush=True)
            rendered, elapsed = run((renderer, clip, wav, speed, mode))
            summary = subprocess.run((metric_tool, wav), capture_output=True, text=True,
                                     check=True).stdout
            metrics = dict(token.split("=", 1) for token in summary.split()
                           if "=" in token)
            rows.append({"source": name, "mode": mode, "speed": speed,
                         "input_rate": rate, "input_frames": frames,
                         "input_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
                         "output_sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
                         "path": str(wav.relative_to(ROOT)),
                         "elapsed_wall_seconds": f"{elapsed:.6f}",
                         **rendered, **metrics})
            if metrics.get("finite") != "yes":
                raise RuntimeError(f"Non-finite samples: {wav}")
            if int(rendered["output_frames"]) != round(frames / float(speed)):
                raise RuntimeError(f"Incorrect output length: {wav}")
        with (OUT / "audio.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys(),
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    print(f"Rendered {len(rows)} diagnostic WAVs", flush=True)


if __name__ == "__main__":
    main()
