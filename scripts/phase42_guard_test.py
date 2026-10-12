#!/usr/bin/env python3
"""Regression for safe density handoff and independent PCM replay."""
import csv
import hashlib
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    subprocess.run(list(map(str, args)), check=True, cwd=ROOT,
                   stdout=subprocess.DEVNULL)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with tempfile.TemporaryDirectory(prefix="phase42_guard_") as directory:
    temp = Path(directory)
    for source, initial, schedule in (("mix", .4, "1.0:2.0"),
                                      ("drums", .4, "1.0:2.0"),
                                      ("mix", 2., "1.0:0.4"),
                                      ("mix", .4, "1.0:2.0,3.0:0.4")):
        name = f"{source}_{initial}_{schedule.replace(':', '_').replace(',', '_')}"
        audio = ROOT / f"results/phase31/input/{source}.wav"
        rendered, reference, plan = (temp / f"{name}{suffix}" for suffix in
                                     ("_render.wav", "_reference.wav", "_plan.csv"))
        run((ROOT / "build/phase39_sim", audio, rendered, initial, schedule,
             512, plan, 2048, "C", "safe-density"))
        run((ROOT / "build/phase39_reference", audio, reference, initial,
             plan, "C", "safe-density"))
        assert sha(rendered) == sha(reference), name
        rows = list(csv.DictReader(plan.open()))
        for row in rows:
            if (float(row["from"]) < .5 <= float(row["target"]) or
                float(row["target"]) < .5 <= float(row["from"])):
                for band in ("low", "mid", "high"):
                    assert float(row[f"density_weight_{band}"]) >= .15
                    assert int(row["density_input"]) > int(row[f"last_{band}"])
        if source in ("mix", "drums") and initial == .4 and schedule == "1.0:2.0":
            records = {item["name"]: item for item in
                       csv.DictReader((ROOT / "results/phase41/manifest.csv").open())}
            assert sha(rendered) == records[f"{source}_delay_density"]["sha256"], name
            baseline = ROOT / f"results/phase41/{source}_040_to_200_C_delay_density.wav"
            if baseline.exists():
                assert sha(rendered) == sha(baseline), name
print("Phase 42 guard: 4/4 independent PCM, 2/2 Phase 41 byte matches")
