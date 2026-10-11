#!/usr/bin/env python3
"""Phase 29 independent offline audio comparison; raw Golden files stay read-only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import pathlib
import struct
import subprocess
import tempfile
import time
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase29"
TOOL = ROOT / "build/phase29_audio"
NAMES = ("mix", "vocal", "bass", "drums", "guitar", "click", "sine")
PAIRS = (("0.50", "0.70"), ("0.70", "0.50"), ("0.60", "0.80"),
         ("0.80", "0.60"), ("0.75", "0.70"), ("0.70", "0.75"),
         ("0.90", "1.00"), ("1.00", "0.90"))
FIXED = ("0.50", "0.60", "0.70", "0.75", "0.80")


def digest(path: pathlib.Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def input_path(name: str) -> pathlib.Path:
    if name in ("click", "sine"):
        return OUT / "input" / f"{name}.wav"
    return ROOT / "results/phase12/golden/input" / f"{name}.wav"


def golden(name: str, speed: str) -> pathlib.Path:
    if name in ("click", "sine"):
        return OUT / "synthetic_fixed_ref" / f"{name}_{speed.replace('.', '')}.wav"
    phase = "phase12" if speed in ("0.50", "0.75") else "phase28"
    return ROOT / f"results/{phase}/golden/raw" / f"{name}_{speed.replace('.', '')}.wav"


def wav(path: pathlib.Path) -> tuple[np.memmap, int]:
    with path.open("rb") as stream:
        header = stream.read(12)
        if header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise RuntimeError(f"Unexpected RIFF/WAVE: {path}")
        fmt = None
        data_offset = data_size = None
        while True:
            chunk = stream.read(8)
            if len(chunk) != 8:
                break
            size = int.from_bytes(chunk[4:8], "little")
            position = stream.tell()
            if chunk[:4] == b"fmt ":
                fmt = stream.read(min(size, 16))
            elif chunk[:4] == b"data":
                data_offset, data_size = position, size
            stream.seek(position + size + (size & 1))
        if fmt is None or data_offset is None or len(fmt) < 16:
            raise RuntimeError(f"Missing WAV format/data: {path}")
    channels = int.from_bytes(fmt[2:4], "little")
    rate = int.from_bytes(fmt[4:8], "little")
    if fmt[0:2] != b"\x03\x00" or fmt[14:16] != b" \x00":
        raise RuntimeError(f"Expected IEEE float32 WAV: {path}")
    audio = np.memmap(path, dtype="<f4", mode="r", offset=data_offset,
                      shape=(data_size//4,))
    return audio.reshape(-1, channels), rate


def source_frames_rate(path: pathlib.Path) -> tuple[int, int]:
    audio, rate = wav(path)
    return len(audio), rate


def run(source: pathlib.Path, output: pathlib.Path, initial: str,
        changes: list[tuple[int, str]], label: str, block: int = 16384) -> dict[str, str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    prefix = OUT / "diagnostics" / label
    prefix.parent.mkdir(parents=True, exist_ok=True)
    schedule = OUT / "diagnostics" / f"{label}.schedule.csv"
    with schedule.open("w") as stream:
        stream.write("input_sample,target_speed\n")
        for position, target in changes:
            stream.write(f"{position},{target}\n")
    completed = subprocess.run((str(TOOL), str(source), str(output), initial,
                                str(schedule), str(prefix), str(block)),
                               text=True, capture_output=True)
    (OUT / "diagnostics" / f"{label}.txt").write_text(
        completed.stdout + completed.stderr)
    if completed.returncode:
        raise RuntimeError(f"{label}: {completed.stderr.strip()}")
    return dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)


def plan(label: str) -> list[dict[str, str]]:
    with (OUT / "diagnostics" / f"{label}.plans.csv").open(newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check_prefix(candidate: pathlib.Path, reference: pathlib.Path, frames: int) -> None:
    with candidate.open("rb") as left, reference.open("rb") as right:
        left.seek(44)
        right.seek(44)
        remaining = frames * 8
        while remaining:
            count = min(1 << 20, remaining)
            if left.read(count) != right.read(count):
                raise RuntimeError(f"Published PCM changed: {candidate}")
            remaining -= count


def waveform_metrics(candidate: pathlib.Path, reference: pathlib.Path,
                     published: int, applied: int, completion: int) -> dict:
    audio, rate = wav(candidate)
    initial, _ = wav(reference)
    if len(audio) < completion or published >= len(initial):
        raise RuntimeError("Map EOS or published boundary exceeds WAV")
    if not np.isfinite(audio).all():
        raise RuntimeError(f"NaN/Inf: {candidate}")
    check_prefix(candidate, reference, published)
    local = np.asarray(audio[max(0, applied-rate//10):min(len(audio), applied+rate//10)])
    derivative = np.max(np.abs(np.diff(local, axis=0)), axis=1)
    boundary = float(np.max(np.abs(audio[applied]-audio[applied-1])))
    width = max(1, rate//100)
    rms = [float(np.sqrt(np.mean(np.asarray(local[i:i+width], dtype=np.float64)**2)))
           for i in range(0, len(local)-width+1, width)]
    inserted = sum(rms[i] < 1e-7 and rms[i-1] > 1e-3 and rms[i+1] > 1e-3
                   for i in range(1, len(rms)-1))
    before = np.asarray(audio[max(0, applied-rate):max(0, applied-rate//5)])
    after = np.asarray(audio[min(len(audio), completion+rate//5):
                             min(len(audio), completion+rate)])

    def stereo(piece):
        if len(piece) < 2:
            return math.nan, math.nan
        l, r = piece[:, 0].astype(np.float64), piece[:, 1].astype(np.float64)
        mid, side = (l+r)*0.5, (l-r)*0.5
        corr = np.corrcoef(l, r)[0, 1] if np.std(l)*np.std(r) > 1e-12 else 0.0
        return float(corr), float(np.sqrt(np.mean(side*side)) /
                                  max(np.sqrt(np.mean(mid*mid)), 1e-12))

    bc, bs = stereo(before)
    ac, az = stereo(after)
    return dict(output_frames=len(audio), rate=rate, peak=float(np.max(np.abs(audio))),
                boundary_derivative=boundary,
                local_derivative_p99=float(np.percentile(derivative, 99)),
                local_derivative_max=float(np.max(derivative)),
                inserted_silence_windows=inserted,
                lr_corr_before=bc, lr_corr_after=ac,
                side_mid_before=bs, side_mid_after=az)


def audition_clip(source: pathlib.Path, destination: pathlib.Path,
                  center: int, seconds: float = 8.0) -> str:
    audio, rate = wav(source)
    half = int(rate * seconds / 2)
    start, end = max(0, center-half), min(len(audio), center+half)
    clip = np.asarray(audio[start:end] * np.float32(0.5), dtype="<f4")
    if float(np.max(np.abs(clip))) >= 1.0:
        raise RuntimeError("Audition gain still clips")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as writer:
        writer.setnchannels(audio.shape[1])
        writer.setsampwidth(4)
        writer.setframerate(rate)
        writer.writeframes(clip.tobytes())
    # wave writes PCM format tag; patch to IEEE float to preserve the sample format.
    with destination.open("r+b") as stream:
        stream.seek(20)
        stream.write(b"\x03\x00")
    return digest(destination)


def validate_manifests() -> None:
    for manifest in (ROOT / "results/phase12/golden/manifest.csv",
                     ROOT / "results/phase28/golden/manifest.csv"):
        with manifest.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            if row["name"] not in NAMES or row["speed"] not in FIXED:
                continue
            for kind in ("input", "output"):
                path = ROOT / row[f"{kind}_path"]
                if digest(path) != row[f"{kind}_sha256"]:
                    raise RuntimeError(f"Golden {kind} SHA mismatch: {path}")


def ensure_synthetic_inputs() -> None:
    directory = OUT / "input"
    directory.mkdir(parents=True, exist_ok=True)
    for name, frames in (("click", 48000*6), ("sine", 48000*8)):
        path = directory / f"{name}.wav"
        if path.exists():
            continue
        with path.open("wb") as stream:
            stream.write(b"RIFF" + struct.pack("<I", 36+frames*8) + b"WAVE")
            stream.write(b"fmt " + struct.pack("<IHHIIHH", 16, 3, 2,
                                                48000, 384000, 8, 32))
            stream.write(b"data" + struct.pack("<I", frames*8))
            for i in range(frames):
                if name == "click":
                    sample = 0.8 if i % 24000 == 12000 else 0.0
                    stream.write(struct.pack("<ff", sample, sample))
                else:
                    phase = 2*math.pi*437.3*i/48000
                    stream.write(struct.pack("<ff", 0.2*math.sin(phase),
                                             0.2*math.sin(phase+math.pi/4)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--long", action="store_true", help="also run 3/5/10 minute synthetic long inputs")
    parser.add_argument("--resume", action="store_true", help="reuse an already verified fixed_regression.csv")
    args = parser.parse_args()
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    ensure_synthetic_inputs()
    validate_manifests()
    fixed_rows = []
    with tempfile.TemporaryDirectory(prefix="phase29_fixed_") as temporary:
        directory = pathlib.Path(temporary)
        for name in (() if args.resume else NAMES):
            source = input_path(name)
            for speed in FIXED:
                reference = golden(name, speed)
                if not reference.exists():
                    if name not in ("click", "sine"):
                        raise RuntimeError(f"Missing Golden: {reference}")
                    reference.parent.mkdir(parents=True, exist_ok=True)
                    subprocess.run((str(ROOT / "build/phase13_stream"), str(source),
                                    str(reference), "16384", speed), check=True, capture_output=True)
                output = directory / f"{name}_{speed}.wav"
                label = f"fixed_{name}_{speed.replace('.', '')}"
                info = run(source, output, speed, [], label)
                if digest(output) != digest(reference):
                    raise RuntimeError(f"Fixed Golden byte mismatch: {name} {speed}")
                fixed_rows.append(dict(source=name, speed=speed,
                                       input_sha256=digest(source), golden_sha256=digest(reference),
                                       output_frames=info["output_frames"], map_hash=info["map_hash"],
                                       analysis_seconds=info["analysis_seconds"],
                                       dsp_seconds=info["dsp_seconds"],
                                       peak_rss_bytes=info["peak_rss_bytes"],
                                       byte_identical="yes"))
                print("fixed", name, speed, "byte-identical", flush=True)
    if fixed_rows:
        write_csv(OUT / "fixed_regression.csv", fixed_rows)
    elif not (OUT / "fixed_regression.csv").exists():
        raise RuntimeError("Resume requested without fixed regression result")
    switch_rows, audition_rows = [], []
    for name in NAMES:
        source = input_path(name)
        input_frames, rate = source_frames_rate(source)
        for initial, target in PAIRS:
            request = input_frames//2
            label = f"{name}_{initial.replace('.', '')}_to_{target.replace('.', '')}"
            output = OUT / "raw" / f"{label}.wav"
            info = run(source, output, initial, [(request, target)], label)
            change = plan(label)[0]
            if int(change["outcome"]) != 0:
                raise RuntimeError(f"Transition rejected: {label}: {change}")
            published, applied = int(change["published_output"]), int(change["applied_output"])
            complete = int(change["completion_output"])
            if initial in FIXED:
                reference = golden(name, initial)
            else:
                reference = OUT / "raw" / f"{name}_fixed_{initial.replace('.', '')}.wav"
                if not reference.exists():
                    run(source, reference, initial, [], f"fixed_{name}_{initial.replace('.', '')}")
            metrics = waveform_metrics(output, reference, published, applied, complete)
            switch_rows.append(dict(source=name, initial=initial, target=target,
                                    request_input=request, published_output=published,
                                    applied_output=applied, completion_output=complete,
                                    planning_ms=change["planning_ms"],
                                    map_bytes=change["map_bytes"],
                                    skipped_events=change["skipped_events"],
                                    map_hash=info["map_hash"],
                                    raw_sha256=digest(output),
                                    analysis_seconds=info["analysis_seconds"],
                                    dsp_seconds=info["dsp_seconds"],
                                    peak_rss_bytes=info["peak_rss_bytes"], **metrics))
            # Three short clips at one fixed playback gain, without changing raw DSP files.
            for mode, source_wav, center in (
                ("initial", reference, round(request / float(initial))),
                ("target", golden(name, target) if target in FIXED else None,
                 round(request / float(target))),
                ("switch", output, applied)):
                if source_wav is None:
                    source_wav = OUT / "raw" / f"{name}_fixed_{target.replace('.', '')}.wav"
                    if not source_wav.exists():
                        run(source, source_wav, target, [],
                            f"fixed_{name}_{target.replace('.', '')}")
                clip = OUT / "audition" / label / f"{mode}.wav"
                hash_value = audition_clip(source_wav, clip, center)
                audition_rows.append(dict(case=label, mode=mode,
                                          path=str(clip.relative_to(ROOT)), gain=0.5,
                                          sha256=hash_value))
            print("switch", label, "frames", info["output_frames"], flush=True)
        # Multiple consecutive changes, with sufficient separation for each transition.
        positions = [round(input_frames*fraction) for fraction in (0.20, 0.40, 0.60)]
        label = f"{name}_multi_050_070_060_080"
        info = run(source, OUT / "raw" / f"{label}.wav", "0.50",
                   list(zip(positions, ("0.70", "0.60", "0.80"))), label)
        for entry in plan(label):
            if int(entry["outcome"]) != 0:
                raise RuntimeError(f"Multi transition rejected: {label}: {entry}")
        check_prefix(OUT / "raw" / f"{label}.wav", golden(name, "0.50"),
                     int(plan(label)[0]["published_output"]))
        switch_rows.append(dict(source=name, initial="0.50", target="0.70/0.60/0.80",
                                request_input="/".join(map(str, positions)),
                                published_output=plan(label)[0]["published_output"],
                                applied_output=plan(label)[0]["applied_output"],
                                completion_output=plan(label)[-1]["completion_output"],
                                planning_ms=sum(float(p["planning_ms"]) for p in plan(label)),
                                map_bytes=plan(label)[-1]["map_bytes"],
                                skipped_events=sum(int(p["skipped_events"]) for p in plan(label)),
                                map_hash=info["map_hash"],
                                raw_sha256=digest(OUT / "raw" / f"{label}.wav"),
                                analysis_seconds=info["analysis_seconds"],
                                dsp_seconds=info["dsp_seconds"],
                                peak_rss_bytes=info["peak_rss_bytes"],
                                **waveform_metrics(OUT / "raw" / f"{label}.wav",
                                                   golden(name, "0.50"),
                                                   int(plan(label)[0]["published_output"]),
                                                   int(plan(label)[0]["applied_output"]),
                                                   int(plan(label)[0]["completion_output"]))))
        print("multi", name, info["output_frames"], flush=True)
    write_csv(OUT / "switch_metrics.csv", switch_rows)
    write_csv(OUT / "audition_manifest.csv", audition_rows)

    # Verify partition independence on a representative transient and tonal source.
    partition_rows = []
    for name in ("drums", "sine"):
        source = input_path(name)
        frames = len(wav(source)[0])
        reference = OUT / "raw" / f"{name}_050_to_070.wav"
        with tempfile.TemporaryDirectory(prefix="phase29_partition_") as directory:
            for block in (8192, 65536):
                candidate = pathlib.Path(directory) / f"{block}.wav"
                run(source, candidate, "0.50", [(frames//2, "0.70")],
                    f"partition_{name}_{block}", block)
                identical = digest(candidate) == digest(reference)
                if not identical:
                    raise RuntimeError(f"Partition-dependent PCM: {name} {block}")
                partition_rows.append(dict(source=name, block_frames=block,
                                           reference_sha256=digest(reference),
                                           byte_identical="yes"))
    write_csv(OUT / "partition_regression.csv", partition_rows)
    if args.long:
        long_study()


def long_study() -> None:
    source = input_path("mix")
    original, rate = wav(source)
    channels = original.shape[1]
    original_frames = len(original)
    rows = []
    for minutes in (3, 5, 10):
        with tempfile.TemporaryDirectory(prefix=f"phase29_long_{minutes}_") as directory:
            extended = pathlib.Path(directory) / "input.wav"
            frames = rate * 60 * minutes
            with wave.open(str(extended), "wb") as writer:
                writer.setnchannels(channels)
                writer.setsampwidth(4)
                writer.setframerate(rate)
                remaining = frames
                while remaining:
                    count = min(remaining, original_frames)
                    writer.writeframesraw(np.asarray(original[:count], dtype="<f4").tobytes())
                    remaining -= count
            with extended.open("r+b") as stream:
                stream.seek(20)
                stream.write(b"\x03\x00")
            output = pathlib.Path(directory) / "output.wav"
            label = f"long_{minutes}min"
            start = time.monotonic()
            info = run(extended, output, "0.50", [(frames//2, "0.70")], label)
            audio, _ = wav(output)
            if not np.isfinite(audio).all():
                raise RuntimeError(f"Long nonfinite {minutes} min")
            rows.append(dict(input_minutes=minutes, input_frames=frames,
                             output_frames=len(audio), output_sha256=digest(output),
                             map_hash=info["map_hash"],
                             planning_ms=plan(label)[0]["planning_ms"],
                             analysis_seconds=info["analysis_seconds"],
                             dsp_seconds=info["dsp_seconds"],
                             wall_seconds=time.monotonic()-start,
                             peak_rss_bytes=info["peak_rss_bytes"]))
            print("long", minutes, "minutes", info["output_frames"], flush=True)
    write_csv(OUT / "long_study.csv", rows)


if __name__ == "__main__":
    main()
