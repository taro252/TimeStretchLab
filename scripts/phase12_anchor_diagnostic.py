#!/usr/bin/env python3
"""Freeze one click-train reference that exercises precise anchoring."""

from __future__ import annotations

import argparse
import json

from phase12_golden import ARGS, OUT, ROOT, fields, loudness, run, sha256


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="replace the diagnostic WAV")
    args = parser.parse_args()
    input_path = ROOT / "results/phase101/artificial/click_train_input.wav"
    output_path = OUT / "anchor_click_050.wav"
    manifest = OUT / "anchor_diagnostic.json"
    if manifest.exists() and not args.force:
        data = json.loads(manifest.read_text())
        if (sha256(input_path) != data["input_sha256"] or
                sha256(output_path) != data["output_sha256"]):
            raise RuntimeError("Anchor diagnostic hash mismatch")
        print("Verified precise-anchor click reference", flush=True)
        return
    line = run([str(ROOT / "build/timestretch"), str(input_path), str(output_path),
                "--speed", "0.50", *ARGS])
    dsp = fields(line)
    metrics = fields(run([str(ROOT / "build/wav_metrics"), str(output_path)]))
    if (int(metrics["frames"]) != 960000 or metrics["finite"] != "yes" or
            int(dsp["anchored_event_count"]) < 1):
        raise RuntimeError("Precise anchoring was not exercised")
    data = {
        "role": "auxiliary precise-anchor regression; outside the five-source golden set",
        "input_path": str(input_path.relative_to(ROOT)),
        "input_sha256": sha256(input_path),
        "output_path": str(output_path.relative_to(ROOT)),
        "output_sha256": sha256(output_path),
        "speed": 0.5,
        "sample_rate": int(metrics["rate"]),
        "channels": int(metrics["channels"]),
        "frames": int(metrics["frames"]),
        "peak_sample": float(metrics["peak"]),
        "integrated_lufs": loudness(output_path)["input_i"],
        "event_count": int(dsp["event_count"]),
        "anchored_event_count": int(dsp["anchored_event_count"]),
        "time_map_hash": dsp["time_map_hash"],
    }
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Anchored {data['anchored_event_count']} events; "
          f"sha256={data['output_sha256']}", flush=True)


if __name__ == "__main__":
    main()
