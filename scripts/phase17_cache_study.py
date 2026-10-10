#!/usr/bin/env python3
"""Independent Phase 17 PCM-cache experiment; never edits a Golden WAV."""
import csv
import hashlib
import json
import math
import os
import pathlib
import random
import resource
import statistics
import struct
import subprocess
import time


ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT / "results/phase12/golden/input/mix.wav"
GOLDEN = ROOT / "results/phase12/golden/raw/mix_050.wav"
CACHE = ROOT / "results/phase17/cache/mix_050_cache.wav"
DIAGNOSTICS = ROOT / "results/phase17/diagnostics"
ENGINE = ROOT / "build/phase13_stream"
CONFIG = {
    "time_ratio": 2.0,
    "speed": 0.50,
    "quality": "Experimental3500",
    "fft_hops": [[8192, 2048], [4096, 1024], [1024, 256]],
    "crossovers_hz": [250, 3500],
    "phase_locking": True,
    "transient_handling": True,
    "adaptive_time_map": True,
    "precise_anchoring": True,
    "stereo_coherence": True,
    "format": "RIFF_float32_interleaved",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def engine_fingerprint():
    digest = hashlib.sha256()
    paths = sorted((ROOT / "src/dsp").glob("*.cpp"))
    paths += sorted((ROOT / "src/dsp").glob("*.h"))
    paths += sorted((ROOT / "src/audio").glob("*.cpp"))
    paths += sorted((ROOT / "src/audio").glob("*.h"))
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def wav_data(path):
    with path.open("rb") as stream:
        if stream.read(4) != b"RIFF":
            raise ValueError("Expected RIFF WAV")
        stream.seek(8)
        if stream.read(4) != b"WAVE":
            raise ValueError("Expected WAVE")
        fmt = None
        data = None
        while True:
            chunk = stream.read(8)
            if len(chunk) != 8:
                break
            size = struct.unpack_from("<I", chunk, 4)[0]
            at = stream.tell()
            if chunk[:4] == b"fmt ":
                fmt = stream.read(size)
            if chunk[:4] == b"data":
                data = (at, size)
            stream.seek(at + size + (size & 1))
        if fmt is None or data is None:
            raise ValueError("Missing WAV format/data")
        code, channels, rate = struct.unpack_from("<HHI", fmt)
        if code != 3 or channels not in (1, 2):
            raise ValueError("Expected mono/stereo float32")
        return {"offset": data[0], "bytes": data[1], "channels": channels,
                "sample_rate": rate, "frames": data[1] // (channels * 4)}


def percentile(values, q):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def points(frames, rate):
    fixed = [("start", fraction) for fraction in (0.0, 0.01, 0.10)]
    fixed += [("middle", fraction) for fraction in (0.45, 0.50, 0.55)]
    fixed += [("end", fraction) for fraction in (0.90, 0.95, 0.99)]
    fixed += [("rapid", fraction) for fraction in (0.75, 0.25, 0.80, 0.15)]
    rng = random.Random(17)
    extra = [("rapid_repeat", rng.random()) for _ in range(200)]
    return [(kind, min(frames - 1, int(frames * fraction)))
            for kind, fraction in fixed + extra]


def main():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(SOURCE)
    fingerprint = engine_fingerprint()
    config_bytes = json.dumps(CONFIG, sort_keys=True, separators=(",", ":")).encode()
    config_hash = hashlib.sha256(config_bytes).hexdigest()
    key = hashlib.sha256((source_hash + fingerprint + config_hash).encode()).hexdigest()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter()
    generated = subprocess.run([str(ENGINE), str(SOURCE), str(CACHE)],
                               capture_output=True, text=True, check=True)
    generation_seconds = time.perf_counter() - start
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    fields = dict(line.split("=", 1) for line in generated.stdout.strip().splitlines())
    cache_info, golden_info = wav_data(CACHE), wav_data(GOLDEN)
    if cache_info != golden_info:
        raise RuntimeError("Cache and Golden WAV metadata differ")
    cache_hash, golden_hash = sha256(CACHE), sha256(GOLDEN)
    if cache_hash != golden_hash:
        raise RuntimeError("Generated PCM cache is not byte-identical to Golden")
    rows = []
    block_align = cache_info["channels"] * 4
    cache_fd, golden_fd = os.open(CACHE, os.O_RDONLY), os.open(GOLDEN, os.O_RDONLY)
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    try:
        for kind, frame in points(cache_info["frames"], cache_info["sample_rate"]):
            count = min(16384, cache_info["frames"] - frame)
            byte_count = count * block_align
            offset = cache_info["offset"] + frame * block_align
            started = time.perf_counter_ns()
            got = os.pread(cache_fd, byte_count, offset)
            microseconds = (time.perf_counter_ns() - started) / 1000
            expected = os.pread(golden_fd, byte_count, offset)
            if len(got) != byte_count or got != expected:
                raise RuntimeError(f"Cache read mismatch at frame {frame}")
            rows.append({"kind": kind, "output_frame": frame, "frames_read": count,
                         "read_microseconds": microseconds, "exact": True})
    finally:
        os.close(cache_fd)
        os.close(golden_fd)
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    with (DIAGNOSTICS / "cache_seeks.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    durations = [row["read_microseconds"] for row in rows]
    manifest = {
        "cache_key": key, "input_sha256": source_hash,
        "engine_source_sha256": fingerprint, "config_sha256": config_hash,
        "time_map_hash": fields["time_map_hash"],
        "cache_sha256": cache_hash, "golden_sha256": golden_hash,
        "cache_path": str(CACHE.relative_to(ROOT)), "cache_bytes": CACHE.stat().st_size,
        "source": str(SOURCE.relative_to(ROOT)), "golden": str(GOLDEN.relative_to(ROOT)),
        "sample_rate": cache_info["sample_rate"], "channels": cache_info["channels"],
        "output_frames": cache_info["frames"], "generation_wall_seconds": generation_seconds,
        "generation_child_cpu_seconds": (after.ru_utime + after.ru_stime) -
                                        (before.ru_utime + before.ru_stime),
        "generation_child_max_rss_bytes": after.ru_maxrss,
        "seek_count": len(rows), "seek_median_us": statistics.median(durations),
        "seek_p95_us": percentile(durations, 0.95), "seek_max_us": max(durations),
        "seek_cpu_seconds": (usage_after.ru_utime + usage_after.ru_stime) -
                            (usage_before.ru_utime + usage_before.ru_stime),
        "seek_process_max_rss_bytes": usage_after.ru_maxrss,
        "read_pattern": "persistent fd, pread 16384 frames, warm OS cache likely",
    }
    (DIAGNOSTICS / "cache_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
