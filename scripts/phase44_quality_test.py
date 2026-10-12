#!/usr/bin/env python3
"""The injected underrun must be detected, never accepted as audio PASS."""
import os
import subprocess
import sys
from pathlib import Path

from phase44_quality import failures

root = Path(__file__).resolve().parents[1]
binary = root / "build/phase40_paced_sim"
source = root / "results/phase31/input/mix.wav"
command = [str(binary), str(source), "0.4", "2.0", "1.0", "C", "512",
           "16384", "12288", "2048", "0", str(root / "build/phase44_quality.csv"),
           "safe-density"]

for injected in (False, True):
    environment = os.environ.copy()
    environment.pop("PHASE44_FORCE_UNDERRUN", None)
    if injected:
        environment["PHASE44_FORCE_UNDERRUN"] = "1"
    result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                            env=environment)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines()
                  if "=" in line)
    problems = failures(values, result.returncode)
    if bool(problems) != injected or (result.returncode != 0) != injected:
        print(result.stdout, result.stderr, file=sys.stderr)
        raise SystemExit(f"quality gate failed injected={injected}: {problems}")
    print("fault_detection=PASS" if injected else "normal_audio_quality=PASS")
    if not injected:
        for key in ("missing_frames", "underrun_calls", "rejected_writes",
                    "callback_overruns", "worker_errors"):
            changed = dict(values, **{key: "1"})
            assert failures(changed), f"{key} escaped the quality gate"
        for key, value in (("request_state", "Incomplete"),
                           ("eos_drained", "0"),
                           ("presented_timeline", "0")):
            changed = dict(values, **{key: value})
            assert failures(changed), f"{key} escaped the quality gate"

# Invalid or absent measurements must also fail closed.
assert failures({})
