"""Reproducible Phase 5.3 / Phase 10 / Phase 10.1 short-signal comparison.

Run with a Python that has NumPy installed. WAVs remain ignored by Git; CSV
summaries and the source script are versioned.
"""
from __future__ import annotations

import csv
import math
import pathlib
import random
import shutil
import struct
import subprocess

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase101"
BUILD = ROOT / "build"
RATE = 48_000


def command(*args: object) -> dict[str, str]:
    result = subprocess.run([str(arg) for arg in args], check=True, capture_output=True, text=True)
    return dict(item.split("=", 1) for item in result.stdout.split() if "=" in item)


def read_wav(path: pathlib.Path) -> tuple[np.ndarray, int]:
    data = path.read_bytes()
    pos, fmt, channels, rate = 12, 0, 0, 0
    while pos + 8 <= len(data):
        name = data[pos:pos + 4]
        length = struct.unpack_from("<I", data, pos + 4)[0]
        pos += 8
        if name == b"fmt ":
            fmt, channels, rate = struct.unpack_from("<HHI", data, pos)
        if name == b"data":
            if fmt == 3:
                result = np.frombuffer(data, dtype="<f4", count=length // 4, offset=pos)
            elif fmt == 1:
                result = np.frombuffer(data, dtype="<i2", count=length // 2, offset=pos).astype(np.float32) / 32768
            else:
                raise ValueError(f"Unsupported WAV format {fmt}: {path}")
            return result.reshape(-1, channels), rate
        pos += length + (length & 1)
    raise ValueError(f"Missing WAV data: {path}")


def events_for(name: str) -> list[int]:
    if name == "impulse":
        return [2 * RATE + 311, 6 * RATE + 733]
    if name == "click_train":
        return [n * RATE // 2 + 113 for n in range(1, 20)]
    if name == "artificial_drum":
        return [n * RATE // 2 for n in range(1, 20)]
    if name in ("short_noise_burst", "decaying_noise"):
        return [2 * RATE + 137, 5 * RATE + 401, 8 * RATE + 59]
    return []


def median(values: list[float]) -> float:
    return float(np.median(values)) if values else float("nan")


def transient_metrics(audio: np.ndarray, rate: int, expected: list[float]) -> dict[str, float]:
    envelope = np.max(np.abs(audio), axis=1)
    smooth = np.convolve(envelope, np.ones(max(1, rate // 1000)) / max(1, rate // 1000), "same")
    peak_errors, rise, first20, preecho, decay3, decay10 = [], [], [], [], [], []
    peaks = []
    for event in expected:
        center = round(event)
        lo = max(0, center - round(rate * 0.05))
        hi = min(len(envelope), center + round(rate * 0.05))
        if hi <= lo:
            continue
        peak = lo + int(np.argmax(envelope[lo:hi]))
        peaks.append(peak)
        peak_errors.append((peak - event) / rate * 1000)
        first20.append(float(np.mean(audio[center:min(len(audio), center + round(rate * .02))] ** 2)))
        preecho.append(float(np.mean(audio[max(0, center - round(rate * .02)):center] ** 2)))
        window = smooth[max(0, peak - round(rate * .02)):peak + 1]
        if len(window):
            threshold10, threshold90 = smooth[peak] * .1, smooth[peak] * .9
            crossings10 = np.flatnonzero(window >= threshold10)
            crossings90 = np.flatnonzero(window >= threshold90)
            if len(crossings10) and len(crossings90):
                rise.append(max(0, crossings90[0] - crossings10[0]) / rate * 1000)
        tail = smooth[peak:min(len(smooth), peak + round(rate * .15))]
        for threshold, values in ((10 ** (-3 / 20), decay3), (10 ** (-10 / 20), decay10)):
            crossings = np.flatnonzero(tail <= smooth[peak] * threshold)
            if len(crossings):
                values.append(crossings[0] / rate * 1000)
    interval = []
    for i in range(1, len(peaks)):
        interval.append(abs((peaks[i] - peaks[i - 1]) - (expected[i] - expected[i - 1])) / rate * 1000)
    return {
        "median_peak_error_ms": median(peak_errors),
        "median_abs_peak_error_ms": median([abs(x) for x in peak_errors]),
        "max_interval_error_ms": max(interval, default=float("nan")),
        "rise_10_90_ms": median(rise),
        "first20_energy": median(first20),
        "preecho_energy": median(preecho),
        "decay_3db_ms": median(decay3),
        "decay_10db_ms": median(decay10),
    }


def stereo_metrics(audio: np.ndarray) -> dict[str, float]:
    result = {
        "rms": float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))),
        "peak": float(np.max(np.abs(audio))),
        "finite": int(bool(np.all(np.isfinite(audio)))),
    }
    if audio.shape[1] == 2:
        mid = .5 * (audio[:, 0].astype(np.float64) + audio[:, 1])
        side = .5 * (audio[:, 0].astype(np.float64) - audio[:, 1])
        result["side_mid"] = float(np.sqrt(np.mean(side * side)) /
                                   max(1e-12, np.sqrt(np.mean(mid * mid))))
        result["lr_correlation"] = float(np.corrcoef(audio[:, 0], audio[:, 1])[0, 1])
    else:
        result["side_mid"] = float("nan")
        result["lr_correlation"] = float("nan")
    return result


def csv_events(path: pathlib.Path) -> list[int]:
    with path.open(newline="") as file:
        return [int(row["peakFrame"]) * 1024 for row in csv.DictReader(file)]


def match_events(reference: list[int], candidate: list[int], rate: int) -> dict[str, float]:
    available = set(range(len(reference)))
    errors = []
    for event in candidate:
        choices = [(abs(event - reference[i]), i) for i in available]
        if choices:
            distance, index = min(choices)
            if distance <= .02 * rate:
                errors.append(distance / rate * 1000)
                available.remove(index)
    return {
        "offline_count": len(reference), "realtime_count": len(candidate),
        "precision": len(errors) / max(1, len(candidate)),
        "recall": len(errors) / max(1, len(reference)),
        "median_error_ms": median(errors),
        "p90_error_ms": float(np.percentile(errors, 90)) if errors else float("nan"),
    }


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, keys)
        writer.writeheader()
        writer.writerows(rows)


def prepare_inputs() -> dict[str, pathlib.Path]:
    artificial = OUT / "artificial"
    real = OUT / "real"
    real.mkdir(parents=True, exist_ok=True)
    result = {name: artificial / f"{name}_input.wav" for name in (
        "impulse", "click_train", "artificial_drum", "short_noise_burst", "decaying_noise"
    )}
    for name in ("bass", "mix", "drums", "guitar"):
        path = real / f"{name}_input.wav"
        if not path.exists():
            command("ffmpeg", "-y", "-loglevel", "error", "-ss", "30", "-i",
                    pathlib.Path.home() / "Downloads" / f"{name}.wav", "-t", "10",
                    "-c:a", "pcm_f32le", path)
        result[name] = path
    for name, source in (("female_vocal", "female_1"), ("male_vocal", "male_1")):
        path = real / f"{name}_input.wav"
        if not path.exists():
            saved = ROOT / "results/phase9a" / f"{source}_input.wav"
            if saved.exists():
                shutil.copyfile(saved, path)
            else:
                phase7 = ROOT / "results/phase7" / f"{source}_input.wav"
                original = pathlib.Path.home() / "Downloads" / (
                    "vocal.wav" if name == "female_vocal" else "vocal-male.wav")
                arguments = ["ffmpeg", "-y", "-loglevel", "error"]
                if phase7.exists():
                    arguments += ["-i", phase7]
                else:
                    arguments += ["-ss", "30", "-i", original, "-t", "10"]
                command(*arguments, "-ac", "1", "-c:a", "pcm_f32le", path)
        result[name] = path
    return result


def main() -> None:
    inputs = prepare_inputs()
    audio_rows, transient_rows, event_rows, performance_rows, blind_rows = [], [], [], [], []
    for name, input_path in inputs.items():
        input_audio, rate = read_wav(input_path)
        offline_events = OUT / f"{name}_offline_events.csv"
        command(BUILD / "phase101_offline_events", input_path, offline_events)
        reference = csv_events(offline_events)
        for speed in (.75, .5):
            tag = "075" if speed == .75 else "050"
            paths = {}
            for mode in ("phase53", "linear", "transient"):
                path = OUT / "ab" / f"{name}_{tag}_{mode}.wav"
                path.parent.mkdir(parents=True, exist_ok=True)
                if mode == "phase53":
                    stats = command(BUILD / "timestretch", input_path, path,
                        "--speed", speed, "--phase-locking", "on", "--transient", "on",
                        "--adaptive-time-map", "on", "--precise-anchoring", "on",
                        "--stereo-coherence", "on", "--quality", "high", "--chunked", "on")
                else:
                    arguments = [BUILD / "realtime_stretch", input_path, path,
                                 "--speed", speed, "--mode", mode]
                    if mode == "transient":
                        event_path = OUT / f"{name}_{tag}_realtime_events.csv"
                        arguments += ["--lookahead-ms", 128, "--events-csv", event_path]
                    stats = command(*arguments)
                paths[mode] = path
                audio, output_rate = read_wav(path)
                assert output_rate == rate and len(audio) == round(len(input_audio) / speed)
                audio_rows.append({"name": name, "speed": speed, "mode": mode,
                                   "frames": len(audio), **stereo_metrics(audio)})
                if events_for(name):
                    positions = [sample / speed for sample in events_for(name)]
                    transient_rows.append({"name": name, "speed": speed, "mode": mode,
                                           **transient_metrics(audio, rate, positions)})
                performance_rows.append({"name": name, "speed": speed, "mode": mode, **stats})
            realtime_events = csv_events(OUT / f"{name}_{tag}_realtime_events.csv")
            event_rows.append({"name": name, "speed": speed,
                               **match_events(reference, realtime_events, rate)})
            blind_dir = OUT / "blind" / f"{name}_{tag}"
            blind_dir.mkdir(parents=True, exist_ok=True)
            order = list(paths)
            random.Random(f"phase101-{name}-{tag}").shuffle(order)
            for label, mode in zip("ABC", order):
                target = blind_dir / f"{label}.wav"
                shutil.copyfile(paths[mode], target)
                blind_rows.append({"name": name, "speed": speed, "label": label,
                                   "mode": mode, "path": str(target)})
            print(name, speed, flush=True)
    for filename, rows in (("audio_metrics.csv", audio_rows),
                           ("transient_metrics.csv", transient_rows),
                           ("event_match.csv", event_rows),
                           ("performance.csv", performance_rows),
                           ("blind_key.csv", blind_rows)):
        write_csv(OUT / filename, rows)


if __name__ == "__main__":
    main()
