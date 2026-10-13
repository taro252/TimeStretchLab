#!/usr/bin/env python3
"""Paced supply experiments plus independent post-run PCM reference replay."""
import argparse
import os
import subprocess
from pathlib import Path
from phase45_store import new_run, parse_log, save_result
from phase45_verdict import classify

ROOT = Path(__file__).resolve().parents[1]


def run(source, output, initial="0.4", target="2.0", callback=512, dsp=2048,
        lead=12288, load=0, qos=False, wake_ms=0, underrun=False, label="A",
        late_limit=1, request_seconds=1):
    path, run_id, at = new_run(output, label)
    environment = os.environ.copy()
    for key in ("PHASE44_FORCE_UNDERRUN", "PHASE44_WORKER_QOS", "PHASE45_WAKE_DELAY_MS",
                "PHASE45_WORKER_STALL_MS"):
        environment.pop(key, None)
    environment["PHASE44_TRACE_EVENTS"] = "1"
    environment["PHASE45_LATE_PERIOD_LIMIT"] = str(late_limit)
    if qos: environment["PHASE44_WORKER_QOS"] = "1"
    if wake_ms: environment["PHASE45_WAKE_DELAY_MS"] = str(wake_ms)
    if underrun: environment["PHASE45_WORKER_STALL_MS"] = "500"
    plan = path / "plan.csv"
    command = [ROOT / "build/phase40_paced_sim", source, initial, target, str(request_seconds),
               "C", str(callback), "16384", str(lead), str(dsp), str(load), plan, "safe-density"]
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True,
                            cwd=ROOT, env=environment, timeout=2400)
    (path / "simulation.log").write_text(result.stdout + result.stderr)
    values = parse_log(result.stdout)
    reference = path / "reference.wav"
    ref = subprocess.run([str(ROOT / "build/phase39_reference"), str(source), str(reference),
                          initial, str(plan) + ".replay.csv", "C", "safe-density"],
                         capture_output=True, text=True, cwd=ROOT, timeout=1800)
    (path / "reference.log").write_text(ref.stdout + ref.stderr)
    checked = {}
    hash_exit = -1
    if ref.returncode == 0:
        hashed = subprocess.run([str(ROOT / "build/phase45_pcm_hash"), str(reference)],
                                capture_output=True, text=True, cwd=ROOT)
        checked = parse_log(hashed.stdout)
        hash_exit = hashed.returncode
        (path / "reference_hash.log").write_text(hashed.stdout + hashed.stderr)
    verified = (ref.returncode == 0 and hash_exit == 0 and checked.get('nonfinite') == '0' and
                checked.get("pcm_sha256") is not None and
                values.get("pcm_sha256") == checked["pcm_sha256"] and
                int(values.get("pcm_consumed", -1)) == int(checked.get("frames", -2)))
    row = dict(run_id=run_id, run_time=at, source=str(source), label=label,
               initial_speed=initial, target_speed=target, callback_config=callback,
               dsp_config=dsp, lead_config=lead, load_config=load, qos_requested=int(qos),
               injected_wake_ms=wake_ms, injected_underrun=int(underrun), exit_code=result.returncode,
               reference_exit=ref.returncode, pcm_reference_verified=int(verified))
    row.update(values)
    row.update(classify(values, verified, result.returncode))
    save_result(output, path, row)
    print(run_id, row["OVERALL_REALTIME"], row["SUPPLY_INTEGRITY"],
          row["SIMULATION_VALIDITY"], flush=True)
    return row, path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "results/phase45/paced")
    parser.add_argument("--initial", default="0.4")
    parser.add_argument("--target", default="2.0")
    parser.add_argument("--callback", type=int, default=512)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--load", type=float, default=0)
    parser.add_argument("--candidate", choices=("A", "B", "C", "D"), default="A")
    parser.add_argument("--wake-ms", type=float, default=0)
    parser.add_argument("--underrun", action="store_true")
    parser.add_argument("--late-limit", type=float, default=1)
    args = parser.parse_args()
    rows = []
    for _ in range(args.repeat):
        row, _ = run(args.input, args.output, args.initial, args.target, args.callback,
                     dsp=1024 if args.candidate == "C" else 2048,
                     lead=14336 if args.candidate == "D" else 12288,
                     qos=args.candidate == "B", load=args.load, wake_ms=args.wake_ms,
                     underrun=args.underrun, label=args.candidate, late_limit=args.late_limit)
        rows.append(row)
    if any(row["OVERALL_REALTIME"] != "PASS" for row in rows): raise SystemExit(1)


if __name__ == "__main__": main()
