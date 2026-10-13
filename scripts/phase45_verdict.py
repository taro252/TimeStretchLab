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
        host = host_failures(values)
        failures.extend(host)
    except (KeyError, ValueError, TypeError):
        failures.append("required_measurement_missing_or_invalid")
    return failures


def host_failures(values):
    """Future HAL timestamps are legitimate; require continuity evidence."""
    errors = []
    try:
        counts = {key: integer(values, key) for key in (
            'host_timestamp_valid_callbacks', 'host_timestamp_missing_callbacks',
            'host_timestamp_backwards', 'host_timestamp_cadence_errors',
            'host_timestamp_offset_outliers',
            'sample_timestamp_errors', 'hal_window_deadline_misses')}
        if counts['host_timestamp_valid_callbacks'] == 0:
            errors.append('host_timestamp_unmeasured')
        errors.extend(f'{key}={value}' for key,value in counts.items()
                      if key != 'host_timestamp_valid_callbacks' and value)
        tolerance = float(values['host_continuity_tolerance_ns'])
        if not math.isfinite(tolerance) or tolerance <= 0:
            errors.append('invalid_host_tolerance')
        for key in ('min_callback_start_minus_host_ns','max_callback_start_minus_host_ns'):
            int(values[key]) # Signed values, including future host time, are evidence only.
    except (KeyError, ValueError, TypeError):
        errors.append('host_measurement_missing_or_invalid')
    return errors


def native_verdict(values, process_exit):
    all_errors = live_failures(values, process_exit)
    host_errors = host_failures(values)
    try:budget_error=integer(values,'callback_deadline_misses')!=0
    except (KeyError,ValueError,TypeError):budget_error=True
    host_keys = ('host_timestamp_', 'sample_timestamp_', 'hal_window_',
                 'host_measurement_', 'invalid_host_')
    audio_errors = [e for e in all_errors if not e.startswith(host_keys) and
                    not e.startswith('callback_deadline_misses=')]
    # Exit 4 reports measured quality/timing failures; exit 1 is a process error.
    if process_exit == 4 and (host_errors or budget_error):
        audio_errors = [e for e in audio_errors if e != 'exit=4']
    if process_exit == 5 and values.get('diagnostic_csv_save_ok')=='0':
        audio_errors=[e for e in audio_errors if e!='exit=5']
    measurement_errors=list(host_errors)
    if values.get('diagnostic_csv_save_ok')=='0':measurement_errors.append('native_csv_io_failed')
    for key in ('callback_records_evicted','worker_profile_records_dropped'):
        try:
            if integer(values,key): measurement_errors.append(f'{key}={values[key]}')
        except (KeyError,ValueError,TypeError): measurement_errors.append(f'{key}=unmeasured')
    return dict(AUDIO_QUALITY='FAIL' if audio_errors or budget_error else
                    'INDETERMINATE' if host_errors else 'PASS',
                SUPPLY_INTEGRITY='FAIL' if audio_errors else 'PASS',
                CALLBACK_PROCESS_BUDGET='FAIL' if budget_error else 'PASS',
                HOST_TIMESTAMP='FAIL' if host_errors else 'PASS',
                MEASUREMENT_QUALITY='FAIL' if measurement_errors else 'PASS',
                measurement_failures=';'.join(measurement_errors),
                failures=';'.join(all_errors))
