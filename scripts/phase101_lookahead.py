"""Finite-lookahead comparison on the five deterministic transient signals."""
from __future__ import annotations

import pathlib

from phase101_evaluate import (BUILD, OUT, command, csv_events, events_for,
                               match_events, read_wav, transient_metrics, write_csv)


def main() -> None:
    rows = []
    for name in ("impulse", "click_train", "artificial_drum", "short_noise_burst", "decaying_noise"):
        input_path = OUT / "artificial" / f"{name}_input.wav"
        _, rate = read_wav(input_path)
        offline = csv_events(OUT / f"{name}_offline_events.csv")
        for speed in (.75, .5):
            for budget in (64, 128, 192):
                tag = "075" if speed == .75 else "050"
                directory = OUT / "lookahead"
                directory.mkdir(exist_ok=True)
                output = directory / f"{name}_{tag}_{budget}.wav"
                events = directory / f"{name}_{tag}_{budget}_events.csv"
                stats = command(BUILD / "realtime_stretch", input_path, output,
                                "--speed", speed, "--mode", "transient",
                                "--lookahead-ms", budget, "--events-csv", events)
                audio, _ = read_wav(output)
                comparison = match_events(offline, csv_events(events), rate)
                metrics = transient_metrics(audio, rate,
                                            [sample / speed for sample in events_for(name)])
                lookahead_frames = __import__("math").ceil(rate * budget / 1000 / 1024)
                base = 6144 if speed == .5 else 8192
                rows.append({"name": name, "speed": speed, "lookahead_ms": budget,
                             "lookahead_samples": lookahead_frames * 1024,
                             "minimum_startup_samples": base + lookahead_frames * 1024,
                             "minimum_startup_ms": (base + lookahead_frames * 1024) / rate * 1000,
                             **comparison, **metrics,
                             "processing_seconds": stats["processing_seconds"],
                             "peak_rss_bytes": stats["peak_rss_bytes"]})
        print(name, flush=True)
    write_csv(OUT / "lookahead_study.csv", rows)


if __name__ == "__main__":
    main()
