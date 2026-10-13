#!/usr/bin/env python3
"""Fault-detection tests: injected failures are NOT realtime audio passes."""
import tempfile
import csv
import os
from contextlib import nullcontext
from pathlib import Path
from phase45_paced import ROOT, run
from phase45_verdict import classify

normal = dict(missing_frames="0", underrun_calls="0", rejected_writes="0",
              worker_errors="0", callback_overruns="0", major_wakeups="0",
              expired_callback_slots="0", completion_deadline_misses="0",
              nonfinite_samples="0", output_frames="100", pcm_consumed="100",
              presented_timeline="100", expired_presentation_frames="0",
              eos_drained="1", request_state="Completed")
assert classify(normal, True)["OVERALL_REALTIME"] == "PASS"
assert classify(normal, True, process_exit=2)["OVERALL_REALTIME"] == "FAIL"
late = dict(normal, major_wakeups="1", expired_callback_slots="1",
            expired_presentation_frames="10", presented_timeline="110")
result = classify(late, True)
assert result["SUPPLY_INTEGRITY"] == "INDETERMINATE"
assert result["SIMULATION_VALIDITY"] == "INVALID"
assert result["OVERALL_REALTIME"] == "INDETERMINATE"
short = dict(normal, missing_frames="10", underrun_calls="1", presented_timeline="110")
assert classify(short, True)["SUPPLY_INTEGRITY"] == "FAIL"
both = dict(late, missing_frames="10", underrun_calls="1", presented_timeline="120")
assert classify(both, True)["SUPPLY_INTEGRITY"] == "FAIL"
assert classify(both, True)["SIMULATION_VALIDITY"] == "INVALID"
assert classify({}, True)["OVERALL_REALTIME"] != "PASS"

retained = os.environ.get('PHASE45_TEST_OUTPUT')
context = nullcontext(retained) if retained else tempfile.TemporaryDirectory(dir=ROOT / 'build', prefix='phase45_gate_')
with context as temporary:
    for wake, underrun in ((0, False), (100, False), (0, True), (100, True)):
        row, path = run(ROOT / "results/phase31/input/mix.wav", Path(temporary),
                     callback=1024, wake_ms=wake, underrun=underrun,
                     label=f"wake{wake}_underrun{int(underrun)}")
        assert row["PCM_CORRECTNESS"] == "PASS", row
        if wake:
            assert row["SIMULATION_VALIDITY"] == "INVALID", row
            assert int(row["expired_callback_slots"]) > 0, row
        if underrun:
            assert row["SUPPLY_INTEGRITY"] == "FAIL", row
            assert int(row["missing_frames"]) > 0, row
            events = list(csv.DictReader((path / 'plan.csv.underruns.csv').open()))
            assert any(int(event['available']) < int(event['wanted']) for event in events), row
        if wake or underrun:
            assert row["OVERALL_REALTIME"] != "PASS" and row["exit_code"] != 0, row
        else:
            # OS scheduling may invalidate a run; the harness must expose it.
            assert (row["OVERALL_REALTIME"] == "PASS") == (row["exit_code"] == 0), row
print("fault_detection=PASS; injected runs are quality FAIL/INDETERMINATE")
