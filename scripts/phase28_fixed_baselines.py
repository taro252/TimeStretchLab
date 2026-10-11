#!/usr/bin/env python3
"""Generate or verify separate Phase 28 fixed-speed raw DSP references."""

from __future__ import annotations

import csv
import argparse
import hashlib
import math
import pathlib
import struct
import subprocess
import tempfile
import wave

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase28/golden"
NAMES = ("mix", "vocal", "bass", "drums", "guitar")
SPEEDS = ("0.60", "0.70", "0.80")
DSP_ARGS = (
    "--phase-locking", "on", "--transient", "on",
    "--adaptive-time-map", "on", "--precise-anchoring", "on",
    "--stereo-coherence", "on", "--quality", "experimental",
    "--low-crossover-hz", "250", "--high-crossover-hz", "3500",
    "--chunked", "on", "--chunk-size", "16384",
)


def sha(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(args: list[str]) -> str:
    process = subprocess.run(args, text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError(f"{args[0]} failed ({process.returncode}): {process.stderr.strip()}")
    return process.stdout.strip()


def fields(output: str) -> dict[str, str]:
    return dict(item.split("=", 1) for item in output.split() if "=" in item)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regenerate-check", action="store_true",
                        help="rerun the offline DSP and verify every frozen output")
    parser.add_argument("--legacy-check", action="store_true",
                        help="verify 0.50/0.75 streaming bytes against Phase 12")
    parser.add_argument("--block-check", action="store_true",
                        help="verify new-speed output is independent of output block size")
    parser.add_argument("--short-check", action="store_true",
                        help="compare offline/streaming on a 2048-frame impulse")
    args = parser.parse_args()
    manifest = OUT / "manifest.csv"
    if manifest.exists():
        with manifest.open(newline="") as file:
            rows = list(csv.DictReader(file))
        if len(rows) != len(NAMES) * len(SPEEDS):
            raise RuntimeError("Incomplete Phase 28 manifest")
        for row in rows:
            for kind in ("input", "output"):
                path = ROOT / row[f"{kind}_path"]
                if sha(path) != row[f"{kind}_sha256"]:
                    raise RuntimeError(f"Frozen {kind} SHA-256 mismatch: {path}")
        if args.regenerate_check:
            with tempfile.TemporaryDirectory(prefix="phase28_recheck_") as directory:
                for row in rows:
                    regenerated = pathlib.Path(directory) / pathlib.Path(row["output_path"]).name
                    run([str(ROOT / "build/timestretch"),
                         str(ROOT / row["input_path"]), str(regenerated),
                         "--speed", row["speed"], *DSP_ARGS])
                    if sha(regenerated) != row["output_sha256"]:
                        raise RuntimeError(f"DSP regeneration mismatch: {row['output_path']}")
                    print(f"Regenerated {row['name']} {row['speed']}: identical", flush=True)
        if args.legacy_check:
            with tempfile.TemporaryDirectory(prefix="phase28_legacy_") as directory:
                for name in NAMES:
                    source = ROOT / "results/phase12/golden/input" / f"{name}.wav"
                    for speed in ("0.50", "0.75"):
                        label = speed.replace(".", "")
                        target = ROOT / "results/phase12/golden/raw" / f"{name}_{label}.wav"
                        generated = pathlib.Path(directory) / target.name
                        run([str(ROOT / "build/phase13_stream"), str(source),
                             str(generated), "16384", speed])
                        if sha(generated) != sha(target):
                            raise RuntimeError(f"Legacy Golden mismatch: {target}")
                        print(f"Legacy {name} {speed}: identical", flush=True)
        if args.block_check:
            with tempfile.TemporaryDirectory(prefix="phase28_block_") as directory:
                source = ROOT / "results/phase12/golden/input/mix.wav"
                target = next(row for row in rows if row["name"] == "mix" and
                              row["speed"] == "0.70")
                for block in (8192, 65536):
                    generated = pathlib.Path(directory) / f"mix_{block}.wav"
                    run([str(ROOT / "build/phase13_stream"), str(source),
                         str(generated), str(block), "0.70"])
                    if sha(generated) != target["output_sha256"]:
                        raise RuntimeError(f"Block {block} changed output")
                    print(f"Block {block}: identical", flush=True)
        if args.short_check:
            with tempfile.TemporaryDirectory(prefix="phase28_short_") as directory:
                source = pathlib.Path(directory) / "short.wav"
                with wave.open(str(source), "wb") as writer:
                    writer.setnchannels(1)
                    writer.setsampwidth(2)
                    writer.setframerate(48000)
                    writer.writeframes(struct.pack("<2048h", 16000, *([0] * 2047)))
                for speed in SPEEDS:
                    offline = pathlib.Path(directory) / f"offline_{speed}.wav"
                    streaming = pathlib.Path(directory) / f"stream_{speed}.wav"
                    run([str(ROOT / "build/timestretch"), str(source), str(offline),
                         "--speed", speed, *DSP_ARGS])
                    run([str(ROOT / "build/phase13_stream"), str(source),
                         str(streaming), "8192", speed])
                    if sha(offline) != sha(streaming):
                        raise RuntimeError(f"Short input mismatch: {speed}")
                    print(f"Short input {speed}: identical", flush=True)
        print(f"Verified {len(rows)} frozen Phase 28 references and inputs", flush=True)
        return

    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str | int]] = []
    with tempfile.TemporaryDirectory(prefix="phase28_stream_") as directory:
        for name in NAMES:
            source = ROOT / "results/phase12/golden/input" / f"{name}.wav"
            input_info = fields(run([str(ROOT / "build/wav_metrics"), str(source)]))
            input_hash = sha(source)
            for speed in SPEEDS:
                label = speed.replace(".", "")
                output = OUT / "raw" / f"{name}_{label}.wav"
                streaming = pathlib.Path(directory) / output.name
                if output.exists():
                    raise RuntimeError(f"Partial Phase 28 set; inspect before replacing: {output}")
                try:
                    offline_info = fields(run([
                        str(ROOT / "build/timestretch"), str(source), str(output),
                        "--speed", speed, *DSP_ARGS,
                    ]))
                    stream_info = fields(run([
                        str(ROOT / "build/phase13_stream"), str(source),
                        str(streaming), "16384", speed,
                    ]))
                    wav_info = fields(run([str(ROOT / "build/wav_metrics"), str(output)]))
                    expected = math.floor(int(input_info["frames"]) / float(speed) + 0.5)
                    if int(wav_info["frames"]) != expected or wav_info["finite"] != "yes":
                        raise RuntimeError(f"Length or finite check failed: {output}")
                    offline_hash, streaming_hash = sha(output), sha(streaming)
                    if offline_hash != streaming_hash:
                        raise RuntimeError(
                            f"Offline/streaming bytes differ: {output}; "
                            f"offline={offline_hash} streaming={streaming_hash}; "
                            f"offline_map={offline_info.get('time_map_hash')} "
                            f"stream_map={stream_info.get('time_map_hash')}"
                        )
                    rows.append({
                        "name": name, "speed": speed,
                        "time_ratio": format(1.0 / float(speed), ".17g"),
                        "input_path": str(source.relative_to(ROOT)),
                        "input_sha256": input_hash,
                        "input_frames": int(input_info["frames"]),
                        "output_path": str(output.relative_to(ROOT)),
                        "output_sha256": offline_hash,
                        "output_frames": int(wav_info["frames"]),
                        "sample_rate": int(wav_info["rate"]),
                        "channels": int(wav_info["channels"]),
                        "peak": wav_info["peak"],
                        "time_map_hash": offline_info.get("time_map_hash", ""),
                        "event_count": offline_info.get("event_count", ""),
                        "anchored_event_count": offline_info.get("anchored_event_count", ""),
                        "offline_seconds": offline_info.get("processing_seconds", ""),
                        "offline_peak_rss_bytes": offline_info.get("max_rss_bytes", ""),
                        "stream_time_map_hash": stream_info.get("time_map_hash", ""),
                        "byte_identical": "yes",
                    })
                    print(f"{name} {speed}: {offline_hash} byte-identical", flush=True)
                except Exception:
                    output.unlink(missing_ok=True)
                    raise
    with manifest.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
