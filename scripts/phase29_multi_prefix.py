#!/usr/bin/env python3
"""Verify every published PCM prefix during repeated speed changes."""
import csv
from pathlib import Path
import tempfile

from phase29_study import OUT, ROOT, check_prefix, digest, input_path, run, source_frames_rate, write_csv


def plan(label):
    with (OUT / "diagnostics" / f"{label}.plans.csv").open(newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    rows = []
    for name in ("mix", "drums"):
        source = input_path(name)
        count, _ = source_frames_rate(source)
        positions = [round(count*fraction) for fraction in (0.20, 0.40, 0.60)]
        targets = ("0.70", "0.60", "0.80")
        full_label = f"{name}_multi_050_070_060_080"
        complete = OUT / "raw" / f"{full_label}.wav"
        published = plan(full_label)
        with tempfile.TemporaryDirectory(prefix=f"phase29_multi_{name}_") as directory:
            previous = ROOT / "results/phase12/golden/raw" / f"{name}_050.wav"
            for change_count in (1, 2, 3):
                result = Path(directory) / f"{change_count}.wav"
                run(source, result, "0.50",
                    list(zip(positions[:change_count], targets[:change_count])),
                    f"multi_prefix_{name}_{change_count}")
                current = plan(f"multi_prefix_{name}_{change_count}")
                last = current[-1]
                fence = int(last["published_output"])
                check_prefix(result, previous, fence)
                rows.append(dict(source=name, change=change_count,
                                 published_output=fence,
                                 prefix_match_previous="yes"))
                previous = result
            check_prefix(complete, previous, int(published[-1]["published_output"]))
            if digest(complete) != digest(previous):
                raise RuntimeError(f"Repeated multi-change render is not deterministic: {name}")
            rows.append(dict(source=name, change="complete_against_three",
                             published_output=published[-1]["published_output"],
                             prefix_match_previous="yes"))
    write_csv(OUT / "multi_prefix.csv", rows)


if __name__ == "__main__":
    main()
