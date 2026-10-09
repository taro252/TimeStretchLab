#!/usr/bin/env python3
"""Create separate, safe-level listening copies of Phase 12 golden WAVs."""

from __future__ import annotations

import argparse
import csv

from phase12_golden import OUT, ROOT, fields, loudness, run, sha256


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace listening copies")
    args = parser.parse_args()
    path = OUT / "audition_manifest.csv"
    if path.exists() and not args.force:
        with path.open(newline="") as file:
            saved = list(csv.DictReader(file))
        if len(saved) != 15:
            raise RuntimeError("Incomplete audition manifest")
        for row in saved:
            if sha256(ROOT / row["audition_path"]) != row["audition_sha256"]:
                raise RuntimeError(f"Listening copy changed: {row['audition_path']}")
        print("Verified 15 separate listening WAVs", flush=True)
        return
    with (OUT / "manifest.csv").open(newline="") as file:
        golden = list(csv.DictReader(file))
    if len(golden) != 15:
        raise RuntimeError("Golden manifest must contain 15 WAVs")
    directory = OUT / "audition"
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for original in golden:
        source = ROOT / original["output_path"]
        if sha256(source) != original["output_sha256"]:
            raise RuntimeError(f"Golden WAV changed: {source}")
        gain = round(-18.0 - float(original["integrated_lufs"]), 2)
        output = directory / f"{original['name']}_{original['speed'].replace('.', '')}.wav"
        if output.exists() and not args.force:
            raise RuntimeError(f"Partial audition set: use --force: {output}")
        run(["ffmpeg", "-v", "error", "-y", "-i", str(source),
             "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_f32le", str(output)])
        metrics = fields(run([str(ROOT / "build/wav_metrics"), str(output)]))
        level = loudness(output)
        if (int(metrics["frames"]) != int(original["output_frames"]) or
                metrics["finite"] != "yes" or float(metrics["peak"]) >= 1 or
                float(level["input_tp"]) >= 0):
            raise RuntimeError(f"Unsafe listening copy: {output}")
        row = {
            "name": original["name"], "speed": original["speed"],
            "golden_path": original["output_path"],
            "golden_sha256": original["output_sha256"],
            "audition_path": str(output.relative_to(ROOT)),
            "audition_sha256": sha256(output), "gain_db": f"{gain:.2f}",
            "audition_lufs": level["input_i"],
            "audition_true_peak_dbtp": level["input_tp"],
            "audition_sample_peak": metrics["peak"],
            "frames": metrics["frames"],
        }
        rows.append(row)
        print(f"{row['name']} {row['speed']}: gain={gain:.2f} dB "
              f"LUFS={level['input_i']} peak={metrics['peak']}", flush=True)
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
