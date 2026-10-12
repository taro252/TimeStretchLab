"""Strict audio-quality verdict for absolute-clock playback measurements."""


def failures(values, process_exit=0):
    problems = []
    if process_exit:
        problems.append(f"process_exit={process_exit}")
    for name in ("missing_frames", "underrun_calls", "rejected_writes",
                 "callback_overruns", "worker_errors"):
        try:
            count = int(values[name])
        except (KeyError, ValueError, TypeError):
            problems.append(f"{name}=unmeasured")
        else:
            if count != 0:
                problems.append(f"{name}={count}")
    if values.get("request_state") != "Completed":
        problems.append(f"request_state={values.get('request_state', 'unmeasured')}")
    if values.get("eos_drained") != "1":
        problems.append(f"eos_drained={values.get('eos_drained', 'unmeasured')}")
    try:
        expected = int(values["output_frames"])
        consumed = int(values["pcm_consumed"])
        presented = int(values["presented_timeline"])
    except (KeyError, ValueError, TypeError):
        problems.append("output_length=unmeasured")
    else:
        if expected != consumed or expected != presented:
            problems.append(f"output_length={expected}/{consumed}/{presented}")
    return problems
