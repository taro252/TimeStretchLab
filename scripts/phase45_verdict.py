"""Independent raw-PCM, supply, and consumer-clock verdicts. Fail closed."""
import math


def integer(values, key):
    value = int(values[key])
    if value < 0:
        raise ValueError(key)
    return value


def classify(values, pcm_verified, process_exit=0):
    errors = []
    try:
        counts = {key: integer(values, key) for key in (
            "missing_frames", "underrun_calls", "rejected_writes", "worker_errors",
            "callback_overruns", "major_wakeups", "expired_callback_slots",
            "completion_deadline_misses", "nonfinite_samples", "output_frames",
            "pcm_consumed", "presented_timeline", "expired_presentation_frames")}
        if counts["output_frames"] == 0:
            raise ValueError("output_frames")
    except (KeyError, ValueError, TypeError):
        return dict(PCM_CORRECTNESS="FAIL", SUPPLY_INTEGRITY="INDETERMINATE",
                    CALLBACK_TIMING="FAIL", SIMULATION_VALIDITY="INVALID",
                    OVERALL_REALTIME="FAIL", verdict_errors="required_measurement_missing")
    timing_valid = not any(counts[key] for key in (
        "major_wakeups", "expired_callback_slots", "completion_deadline_misses"))
    callback_pass = timing_valid and counts["callback_overruns"] == 0
    raw_valid = (bool(pcm_verified) and counts["nonfinite_samples"] == 0 and
                 counts["worker_errors"] == 0 and
                 counts["pcm_consumed"] == counts["output_frames"] and
                 values.get("eos_drained") == "1")
    supply_fault = any(counts[key] for key in (
        "missing_frames", "underrun_calls", "rejected_writes", "worker_errors"))
    supply_fault |= (values.get("request_state") != "Completed" or
                     values.get("eos_drained") != "1" or
                     counts["pcm_consumed"] != counts["output_frames"])
    explained_timeline = (counts["pcm_consumed"] + counts["missing_frames"] +
                          counts["expired_presentation_frames"])
    supply_fault |= counts["presented_timeline"] != explained_timeline
    supply = "FAIL" if supply_fault else "PASS" if timing_valid else "INDETERMINATE"
    overall = ("FAIL" if not raw_valid or supply_fault else
               "INDETERMINATE" if not timing_valid else
               "FAIL" if not callback_pass else "PASS")
    # Timing-invalid runs deliberately return nonzero. An otherwise passing
    # record with a failed process must never be promoted to realtime PASS.
    if process_exit != 0 and overall == "PASS":
        overall = "FAIL"
        errors.append("measurement_process_failed")
    return dict(PCM_CORRECTNESS="PASS" if raw_valid else "FAIL",
                SUPPLY_INTEGRITY=supply,
                CALLBACK_TIMING="PASS" if callback_pass else "FAIL",
                SIMULATION_VALIDITY="VALID" if timing_valid else "INVALID",
                OVERALL_REALTIME=overall, verdict_errors=";".join(errors))


def live_failures(values, process_exit):
    """Device callback checks; absent pairs never compare equal by accident."""
    failures = []
    if values.get('duplicate_scalar_fields'):
        failures.append('duplicate_measurements')
    if process_exit != 0:
        failures.append(f"exit={process_exit}")
    try:
        counts = {key: integer(values, key) for key in (
            "underrun_frames", "fifo_rejected_writes", "callback_deadline_misses",
            "callback_cpp_allocations", "callback_format_errors", "route_changed",
            "interrupted", "eos_drained", "requested_changes", "observed_completions",
            "presented_frames", "presented_audio_timeline_frames", "output_length",
            "worker_errors", "output_device_id", "output_device_channels", "input_frames", "dsp_channels")}
        for key in ("underrun_frames", "fifo_rejected_writes", "callback_deadline_misses",
                    "callback_cpp_allocations", "callback_format_errors", "route_changed",
                    "interrupted", "worker_errors"):
            if counts[key]:
                failures.append(f"{key}={counts[key]}")
        if counts["eos_drained"] != 1 or values.get("stop_reason") != "EOS":
            failures.append("not_normal_eos")
        if counts["requested_changes"] != counts["observed_completions"]:
            failures.append("speed_change_incomplete")
        if counts["output_length"] <= 0 or any(counts[key] != counts["output_length"]
                for key in ("presented_frames", "presented_audio_timeline_frames")):
            failures.append("presentation_length_mismatch")
        for key in ("output_device_rate", "dsp_sample_rate", "device_presentation_latency_ms"):
            number = float(values[key])
            if not math.isfinite(number) or number < 0 or (key.endswith("rate") and number == 0):
                failures.append(f"invalid_{key}")
        if counts["output_device_id"] == 0 or counts["output_device_channels"] == 0:
            failures.append("invalid_device")
        if counts["input_frames"] == 0 or counts["dsp_channels"] not in (1, 2):
            failures.append("invalid_input_format")
        if values["format_acquired"] != "1" or values["device_acquired"] != "1":
            failures.append("device_or_format_unacquired")
        if values["callback_allocation_counter_enabled"] != "1":
            failures.append("allocation_unmeasured")
    except (KeyError, ValueError, TypeError):
        failures.append("required_measurement_missing_or_invalid")
    return failures
