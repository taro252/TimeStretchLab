#!/usr/bin/env python3
"""Independent Phase 40 planner comparison; WAVs remain local and ignored."""
from __future__ import annotations

import csv
import hashlib
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase40"
INPUT = ROOT / "results/phase31/input"
BUILD = ROOT / "build"


def run(*args: object) -> str:
    result = subprocess.run([str(x) for x in args], cwd=ROOT,
                            text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def first_changed(a: Path, b: Path) -> int:
    with a.open("rb") as left, b.open("rb") as right:
        header = left.read(44)
        right.read(44)
        channels = struct.unpack_from("<H", header, 22)[0]
        position = 0
        while True:
            x, y = left.read(channels * 4), right.read(channels * 4)
            if not x or not y:
                return position
            if x != y:
                return position
            position += 1


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "plans").mkdir(exist_ok=True)
    rows = []
    for source in ("mix", "vocal", "bass", "drums", "guitar"):
        input_wav = INPUT / f"{source}.wav"
        for initial, target in (("1.00", "2.00"), ("0.40", "2.00"),
                                ("2.00", "0.40")):
            fixed = OUT / f"{source}_{initial.replace('.', '')}_fixed.wav"
            run(BUILD / "phase39_sim", input_wav, fixed, initial, "-", 512)
            for method in "ABC":
                tag = f"{source}_{initial.replace('.', '')}_to_{target.replace('.', '')}_{method}"
                output = OUT / f"{tag}.wav"
                reference = OUT / f"{tag}_reference.wav"
                plan = OUT / "plans" / f"{tag}.csv"
                try:
                    stats = run(BUILD / "phase39_sim", input_wav, output,
                                initial, f"1.0:{target}", 512, plan, 2048, method)
                    with plan.open(newline="") as f:
                        metric = next(csv.DictReader(f))
                    hops = run(BUILD / "phase39_reference", input_wav,
                               "--hops", initial, plan, method)
                    run(BUILD / "phase39_reference", input_wav, reference,
                        initial, plan, method)
                    digest_equal = sha(output) == sha(reference)
                    changed = first_changed(output, fixed)
                    published = int(metric["published"])
                    requested = int(metric["requested_output"])
                    applied = int(metric["applied_output"])
                    row = (source, initial, target, method, "match" if digest_equal else "mismatch",
                           requested, published, int(metric["planning_fence"]),
                           int(metric["first_mutable_frame"]), int(metric["first_safe_frame"]),
                           int(metric["next_event_frame"]), int(metric["protection_end_frame"]),
                           applied, int(metric["completion_output"]), changed,
                           int(changed >= published), (applied-requested)/48.0,
                           int(metric["safe_frames_used"]), int(metric["held_frames"]),
                           int(metric["protected_events_skipped"]) if "protected_events_skipped" in metric
                           else 0, metric["plan_ms"],
                           "|".join(hops.strip().splitlines()),
                           next((line.split("=", 1)[1] for line in stats.splitlines()
                                 if line.startswith("frames=")), ""))
                except Exception as error:  # explicit failure record
                    row = (source, initial, target, method, f"error:{error}",
                           *(("",) * 18))
                rows.append(row)
                print(*row[:5], flush=True)
    with (OUT / "comparison.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(("source", "from", "to", "planner", "reference",
                         "requested_output", "published", "fence", "first_mutable_frame",
                         "first_safe_frame", "next_event_frame", "protection_end_frame",
                         "applied_output", "completion_output", "first_changed_pcm",
                         "published_prefix_unchanged", "coordinate_delay_ms", "safe_frames",
                         "held_frames", "events_skipped", "plan_ms", "hops", "output_frames"))
        writer.writerows(rows)


if __name__ == "__main__":
    main()
