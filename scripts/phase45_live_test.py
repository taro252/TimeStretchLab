#!/usr/bin/env python3
import json
import os
import tempfile
from pathlib import Path
from phase45_store import new_run, save_result, parse_log
from phase45_verdict import live_failures

valid = {key: "0" for key in ("underrun_frames", "fifo_rejected_writes",
          "callback_deadline_misses", "callback_cpp_allocations", "callback_format_errors",
          "route_changed", "interrupted", "worker_errors")}
valid.update(eos_drained="1", stop_reason="EOS", requested_changes="2",
             observed_completions="2", presented_frames="1234",
             presented_audio_timeline_frames="1234", output_length="1234",
             output_device_id="7", output_device_channels="2", output_device_rate="48000",
             dsp_sample_rate="44100", device_presentation_latency_ms="1.0",
             dsp_channels="2", input_frames="22050",
             format_acquired="1", device_acquired="1", callback_allocation_counter_enabled="1")
valid.update(host_timestamp_valid_callbacks='20',host_timestamp_missing_callbacks='0',
             host_timestamp_backwards='0',host_timestamp_cadence_errors='0',
             host_timestamp_offset_outliers='0',
             sample_timestamp_errors='0',hal_window_deadline_misses='0',
             host_continuity_tolerance_ns='100000',
             min_callback_start_minus_host_ns='-5000000',max_callback_start_minus_host_ns='-1000000')
assert not live_failures(valid, 0)
for key in valid:
    missing = dict(valid); missing.pop(key)
    assert live_failures(missing, 0), key
for key in ("presented_frames", "presented_audio_timeline_frames", "observed_completions"):
    assert live_failures(dict(valid, **{key: "999"}), 0), key
for key in ("output_device_rate", "dsp_sample_rate", "device_presentation_latency_ms"):
    assert live_failures(dict(valid, **{key: "nan"}), 0), key
assert live_failures({}, 0)
assert live_failures(valid, 1)
assert live_failures(dict(valid, route_changed="1"), 0)
assert live_failures(dict(valid, **parse_log('underrun_frames=1\nunderrun_frames=0')), 0)
with tempfile.TemporaryDirectory() as temporary:
    for name in ("mix", "drums"):
        path, identifier, at = new_run(os.path.relpath(temporary), name)
        assert path.is_absolute()
        save_result(temporary, path, dict(run_id=identifier, source=name, run_time=at))
    import csv
    rows = list(csv.DictReader((Path(temporary) / "summary.csv").open()))
    assert {row["source"] for row in rows} == {"mix", "drums"}
    assert len({row["run_id"] for row in rows}) == 2
print("missing fields, mismatch, route stop and retained summaries PASS")
