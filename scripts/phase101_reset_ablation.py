"""Reproduce the isolated Phase 10.1 all-bin phase-reset ablation.

Requires NumPy and the Phase 10.1 input WAVs already generated in this project.
Writes only to results/phase101_reset_ablation; old comparisons are untouched.
"""
from __future__ import annotations

import csv
import hashlib
import pathlib
import subprocess

import numpy as np

from phase101_evaluate import events_for, read_wav, stereo_metrics, transient_metrics

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase101_reset_ablation"
SOURCE = ROOT / "results/phase101"
EXECUTABLE = ROOT / "build/realtime_stretch"

INPUTS = {
    "click_train": SOURCE / "artificial/click_train_input.wav",
    "artificial_drum": SOURCE / "artificial/artificial_drum_input.wav",
    "short_noise_burst": SOURCE / "artificial/short_noise_burst_input.wav",
    "female_vocal": SOURCE / "real/female_vocal_input.wav",
    "male_vocal": SOURCE / "real/male_vocal_input.wav",
    "mix": SOURCE / "real/mix_input.wav",
    "pure_vowel": ROOT / "results/phase9a/pure_vowel_input.wav",
    "breathy_vowel": ROOT / "results/phase9a/breathy_vowel_input.wav",
}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def command(*args: object) -> dict[str, str]:
    result = subprocess.run([str(item) for item in args], check=True,
                            capture_output=True, text=True)
    return dict(item.split("=", 1) for item in result.stdout.split() if "=" in item)


def event_rows(path: pathlib.Path) -> list[dict[str, str]]:
    with path.open(newline="") as file:
        return list(csv.DictReader(file))


def voice_stability(audio: np.ndarray, rate: int) -> dict[str, float]:
    """Simple amplitude-variation proxy; not a perceptual wateriness score."""
    mono = np.mean(audio.astype(np.float64), axis=1)
    frame = max(1, round(rate * .05))
    count = len(mono) // frame
    if count < 3:
        return {"active_adjacent_rms_db_median": float("nan")}
    rms = np.sqrt(np.mean(mono[:count * frame].reshape(count, frame) ** 2, axis=1))
    active = rms > max(1e-6, .15 * float(np.max(rms)))
    changes = np.abs(20 * np.log10(np.maximum(rms[1:], 1e-10) /
                                   np.maximum(rms[:-1], 1e-10)))
    valid = active[1:] & active[:-1]
    return {"active_adjacent_rms_db_median":
            float(np.median(changes[valid])) if np.any(valid) else float("nan")}


def write_csv(path: pathlib.Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if not EXECUTABLE.exists():
        raise FileNotFoundError(f"Build the C++ project first: {EXECUTABLE}")
    metrics, manifest = [], []
    for name, input_path in INPUTS.items():
        if not input_path.exists():
            raise FileNotFoundError(f"Preserved comparison input missing: {input_path}")
        input_audio, rate = read_wav(input_path)
        for speed, tag in ((.5, "050"), (.75, "075")):
            outputs = {}
            for reset, label in ((True, "full"), (False, "reset_off")):
                path = OUT / "ab" / f"{name}_{tag}_{label}.wav"
                path.parent.mkdir(exist_ok=True)
                events = OUT / "events" / f"{name}_{tag}_{label}.csv"
                events.parent.mkdir(exist_ok=True)
                stats = command(EXECUTABLE, input_path, path, "--speed", speed,
                                "--mode", "transient", "--lookahead-ms", 128,
                                "--phase-reset", "on" if reset else "off",
                                "--events-csv", events)
                audio, output_rate = read_wav(path)
                expected = round(len(input_audio) / speed)
                if output_rate != rate or len(audio) != expected or not np.isfinite(audio).all():
                    raise AssertionError(f"Invalid output: {path}")
                outputs[label] = (audio, path, events, stats)
            full, full_path, full_events, full_stats = outputs["full"]
            ablated, ablated_path, ablated_events, ablated_stats = outputs["reset_off"]
            if event_rows(full_events) != event_rows(ablated_events):
                raise AssertionError(f"Event list changed: {name} {speed}")
            for field in ("events", "anchors", "debt_samples", "maximum_debt_samples"):
                if full_stats[field] != ablated_stats[field]:
                    raise AssertionError(f"Time map diagnostic changed: {name} {speed} {field}")
            previous = SOURCE / "ab" / f"{name}_{tag}_transient.wav"
            previous_match = sha256(previous) == sha256(full_path) if previous.exists() else ""
            if previous_match is False:
                raise AssertionError(f"Full mode changed from saved Phase 10.1 WAV: {previous}")
            difference = full.astype(np.float64) - ablated
            common_gain = min(1.0, .95 / max(float(np.max(np.abs(full))),
                                                float(np.max(np.abs(ablated))), 1e-12))
            if common_gain < 1.0:
                for label, (_, path, _, _) in outputs.items():
                    listening = OUT / "listening" / path.name
                    listening.parent.mkdir(exist_ok=True)
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                                    "-filter:a", f"volume={common_gain:.12f}",
                                    "-c:a", "pcm_f32le", str(listening)], check=True)
            row = {
                "name": name, "speed": speed, "frames": len(full), "channels": full.shape[1],
                "events": full_stats["events"], "anchors": full_stats["anchors"],
                "event_csv_identical": 1, "time_map_stats_identical": 1,
                "previous_full_byte_identical": previous_match,
                "common_listening_gain": common_gain,
                "max_sample_difference": float(np.max(np.abs(difference))),
                "rms_sample_difference": float(np.sqrt(np.mean(difference ** 2))),
            }
            for label, (audio, path, events, stats) in outputs.items():
                for key, value in stereo_metrics(audio).items():
                    row[f"{label}_{key}"] = value
                row[f"{label}_active_adjacent_rms_db_median"] = (
                    voice_stability(audio, rate)["active_adjacent_rms_db_median"])
                row[f"{label}_processing_seconds"] = stats["processing_seconds"]
                manifest.append({"name": name, "speed": speed, "mode": label,
                                 "input": str(input_path), "wav": str(path),
                                 "listening_wav": str(OUT / "listening" / path.name)
                                 if common_gain < 1.0 else str(path),
                                 "events_csv": str(events), "sha256": sha256(path)})
            positions = [sample / speed for sample in events_for(name)]
            if positions:
                for label, (audio, _, _, _) in outputs.items():
                    for key, value in transient_metrics(audio, rate, positions).items():
                        row[f"{label}_{key}"] = value
            metrics.append(row)
            print(f"{name} {speed}: max_difference={row['max_sample_difference']:.6g}", flush=True)
    write_csv(OUT / "comparison.csv", metrics)
    write_csv(OUT / "manifest.csv", manifest)


if __name__ == "__main__":
    main()
