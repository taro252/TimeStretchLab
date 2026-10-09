#!/usr/bin/env python3
"""Freeze the Phase 12 Experimental 3500 offline output as raw WAV references.

WAVs are intentionally ignored by Git. The manifest records hashes and metrics,
and a later run verifies existing files without silently replacing them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import shutil
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase12/golden"
SOURCES = {
    "mix": ROOT / "results/phase53/real/mix_input.wav",
    "vocal": ROOT / "results/phase53/real/female_input.wav",
    "bass": ROOT / "results/phase53/real/bass_input.wav",
    "drums": ROOT / "results/phase101/real/drums_input.wav",
    "guitar": ROOT / "results/phase101/real/guitar_input.wav",
}
SPEEDS = ("0.50", "0.75", "1.00")
ARGS = (
    "--phase-locking", "on", "--transient", "on",
    "--adaptive-time-map", "on", "--precise-anchoring", "on",
    "--stereo-coherence", "on", "--quality", "experimental",
    "--low-crossover-hz", "250", "--high-crossover-hz", "3500",
    "--chunked", "on", "--chunk-size", "16384",
)


def run(args: list[str]) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fields(line: str) -> dict[str, str]:
    return dict(item.split("=", 1) for item in line.split() if "=" in item)


def loudness(path: pathlib.Path) -> dict[str, str]:
    process = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
         "loudnorm=I=-18:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
        check=True, capture_output=True, text=True,
    )
    match = re.search(r'\{\s*"input_i".*?\}', process.stderr, re.S)
    if match is None:
        raise RuntimeError(f"FFmpeg loudness measurement failed: {path}")
    return json.loads(match.group())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace existing reference WAVs")
    args = parser.parse_args()
    manifest = OUT / "manifest.csv"
    if manifest.exists() and not args.force:
        with manifest.open(newline="") as file:
            saved = list(csv.DictReader(file))
        if len(saved) != len(SOURCES) * len(SPEEDS):
            raise RuntimeError("Incomplete golden manifest")
        for row in saved:
            for path_key, hash_key in (("input_path", "input_sha256"),
                                       ("output_path", "output_sha256")):
                path = ROOT / row[path_key]
                if sha256(path) != row[hash_key]:
                    raise RuntimeError(f"Golden reference hash mismatch: {path}")
        print(f"Verified {len(saved)} golden WAVs and their frozen inputs", flush=True)
        return
    inputs = OUT / "input"
    raw = OUT / "raw"
    inputs.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, source in SOURCES.items():
        frozen = inputs / f"{name}.wav"
        if not frozen.exists():
            shutil.copyfile(source, frozen)
        elif sha256(frozen) != sha256(source):
            raise RuntimeError(f"Frozen input differs from its source: {frozen}")
        input_hash = sha256(frozen)
        input_metrics = fields(run([str(ROOT / "build/wav_metrics"), str(frozen)]))
        input_frames = int(input_metrics["frames"])
        for speed in SPEEDS:
            label = speed.replace(".", "")
            path = raw / f"{name}_{label}.wav"
            if path.exists() and not args.force:
                raise RuntimeError(f"Partial golden set: use --force to rebuild: {path}")
            line = run([str(ROOT / "build/timestretch"), str(frozen), str(path),
                        "--speed", speed, *ARGS])
            dsp = fields(line)
            metrics = fields(run([str(ROOT / "build/wav_metrics"), str(path)]))
            expected = round(input_frames / float(speed))
            if int(metrics["frames"]) != expected or metrics["finite"] != "yes":
                raise RuntimeError(f"Invalid golden WAV: {path}")
            level = loudness(path)
            row = {
                "name": name, "speed": speed, "source_path": str(source.relative_to(ROOT)),
                "input_path": str(frozen.relative_to(ROOT)), "input_sha256": input_hash,
                "input_frames": input_frames, "sample_rate": metrics["rate"],
                "channels": metrics["channels"], "output_path": str(path.relative_to(ROOT)),
                "output_sha256": sha256(path), "output_frames": metrics["frames"],
                "expected_frames": expected, "peak_sample": metrics["peak"],
                "rms": metrics["rms"], "integrated_lufs": level["input_i"],
                "true_peak_dbtp": level["input_tp"], "finite": metrics["finite"],
                "processing_seconds": dsp["processing_seconds"],
                "cpu_seconds": dsp["cpu_seconds"],
                "max_rss_bytes": dsp["max_rss_bytes"],
                "event_count": dsp["event_count"],
                "time_map_hash": dsp["time_map_hash"],
                "anchored_event_count": dsp["anchored_event_count"],
            }
            rows.append(row)
            print(f"{name} {speed}: {metrics['frames']} frames "
                  f"peak={metrics['peak']} LUFS={level['input_i']} "
                  f"sha256={row['output_sha256']}", flush=True)
    with manifest.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
