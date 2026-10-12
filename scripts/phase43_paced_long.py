#!/usr/bin/env python3
"""Absolute-clock long playback simulation; underruns become zero-filled audio."""
import csv
import os
import subprocess
from pathlib import Path
from phase44_quality import failures

root = Path(__file__).resolve().parents[1]
out = Path(os.environ.get("PHASE44_PACED_OUT", root / "results/phase44/paced"))
out.mkdir(parents=True, exist_ok=True)
rows = []
durations = tuple(int(item) for item in os.environ.get(
    "PHASE44_MINUTES", "3,5,10").split(","))
source_name = os.environ.get("PHASE44_SOURCE", "mix")
if source_name not in ("mix", "drums"):
    raise SystemExit("PHASE44_SOURCE must be mix or drums")
for minutes in durations:
    source = (root / "results/phase14/benchmark" / f"mix_repeat_{minutes * 60}.wav"
              if source_name == "mix" else root / "results/phase40/long_input" /
              f"drums_repeat_{minutes * 60}.wav")
    callback = os.environ.get("PHASE44_CALLBACK", "512")
    fifo = os.environ.get("PHASE44_FIFO", "16384")
    lead = os.environ.get("PHASE44_LEAD", "12288")
    dsp = os.environ.get("PHASE44_DSP_BLOCK", "2048")
    load = os.environ.get("PHASE44_LOAD", "0")
    command = [str(root / "build/phase40_paced_sim"), str(source), "0.4", "2.0",
               "1.0", "C", callback, fifo, lead, dsp, load,
               str(out / f"{source_name}_{minutes}m_plan.csv"), "safe-density"]
    environment = os.environ.copy()
    if os.environ.get("PHASE44_PROFILE", "1") == "1":
        environment["PHASE44_TRACE_EVENTS"] = "1"
    else:
        environment.pop("PHASE44_TRACE_EVENTS", None)
    result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                            env=environment)
    (out / f"{source_name}_{minutes}m.log").write_text(result.stdout + result.stderr)
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    problems = failures(values, result.returncode)
    rows.append(dict(source=source_name,input_minutes=minutes,
                     callback_config=callback,fifo_config=fifo,lead_config=lead,
                     dsp_config=dsp,load_config=load,
                     qos_requested=int("PHASE44_WORKER_QOS" in environment),
                     profiling_requested=int("PHASE44_TRACE_EVENTS" in environment),
                     exit_code=result.returncode,
                     audio_quality="FAIL" if problems else "PASS",
                     failure_reasons=";".join(problems), **values))
    print(minutes, "minutes:", "exit", result.returncode,
          "missing", values.get("missing_frames"),
          "worker_cycle_max", values.get("max_worker_cycle_seconds"),
          "audio_quality", rows[-1]["audio_quality"], flush=True)
with (out / "summary.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=sorted(set().union(*(row.keys() for row in rows))))
    writer.writeheader()
    writer.writerows(rows)
if len(rows) != len(durations) or any(row["audio_quality"] != "PASS" for row in rows):
    raise SystemExit("Long paced audio quality FAIL; see summary.csv")
