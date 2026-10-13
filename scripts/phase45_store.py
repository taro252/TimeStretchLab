"""Unique per-run artifacts and a locked, atomic rebuild of the combined CSV."""
import csv
import fcntl
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path


def new_run(output, label):
    now = datetime.now(timezone(timedelta(hours=9)))
    run_id = now.strftime("%Y%m%dT%H%M%S.%f%z") + "_" + label + "_" + uuid.uuid4().hex[:8]
    # Child tools run from the repository root; retain an absolute artifact
    # path even when CTest or the caller has a different working directory.
    path = Path(output).resolve() / "runs" / run_id
    path.mkdir(parents=True, exist_ok=False)
    return path, run_id, now.isoformat()


def save_result(output, path, row):
    pending = path / '.result.pending'
    with pending.open("x") as stream:
        json.dump(row, stream, ensure_ascii=False, indent=2)
        stream.flush(); os.fsync(stream.fileno())
    # Publish only a complete JSON; link refuses to overwrite an existing run.
    try: os.link(pending, path / 'result.json')
    finally: pending.unlink()
    with (path / "result.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=sorted(row), lineterminator="\n")
        writer.writeheader(); writer.writerow(row)
    # This lock is on the control process, never in the audio callback or DSP.
    output = Path(output)
    with (output / ".summary.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = [json.loads(item.read_text()) for item in sorted((output / "runs").glob("*/result.json"))]
        fields = sorted(set().union(*(item.keys() for item in rows)))
        fd, temporary = tempfile.mkstemp(prefix="summary_", dir=output)
        try:
            with os.fdopen(fd, "w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
                writer.writeheader(); writer.writerows(rows)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, output / "summary.csv")
        finally:
            if os.path.exists(temporary): os.unlink(temporary)


def parse_log(text):
    values = {}
    duplicates = []
    for line in text.splitlines():
        if line.count('=') != 1: continue
        key, value = line.split('=', 1)
        if key in values:
            duplicates.append(key);values[key] = '__duplicate__'
        else: values[key] = value
    if duplicates: values['duplicate_scalar_fields'] = ';'.join(duplicates)
    return values
