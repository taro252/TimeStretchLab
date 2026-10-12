#!/usr/bin/env python3
"""Mac-only diagnostic: rejected worker request must not strand the schedule."""
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
command = [str(root / "build/phase43_play"),
           str(root / "results/phase31/input/mix.wav"), "0.4",
           str(root / "results/phase44/reject_continue_schedule.csv")]
for policy, expected_exit in (("strict", 4), ("continue", 0)):
    environment = os.environ.copy()
    environment.update(PHASE43_SILENT="1", PHASE43_REJECT_POLICY=policy,
                       PHASE44_FORCE_NO_SAFE_FIRST="1")
    result = subprocess.run(command, cwd=root, env=environment,
                            capture_output=True, text=True)
    output = root / "results/phase44" / f"reject_{policy}.log"
    output.write_text(result.stdout + result.stderr)
    if result.returncode != expected_exit or "request_result=1 state=Rejected" not in result.stdout:
        raise SystemExit(f"{policy}: unexpected rejection behavior; see {output}")
    if policy == "continue" and (
            "request_result=2 state=Completed" not in result.stdout or
            "eos_drained=1" not in result.stdout or
            "underrun_frames=0" not in result.stdout):
        raise SystemExit(f"{policy}: subsequent request did not complete; see {output}")
    print(f"{policy}: expected exit {expected_exit}, rejection handled")
