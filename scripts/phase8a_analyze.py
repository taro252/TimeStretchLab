#!/usr/bin/env python3
"""Numeric diagnostics for Phase 8A; perceptual A/B remains a human decision."""
import csv
import pathlib
import subprocess
import numpy as np
from phase52_analyze import fields, run
from phase6_analyze import paired_vocal, save
from phase6_artificial import metrics as vibrato_metrics
from phase6_artificial import log_peak

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase8a"
BUILD = ROOT / "build"

def audio(path):
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "stream=sample_rate,channels", "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    rate, channels = int(probe[0]), int(probe[1])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, channels).astype(np.float64), rate

def splice_metrics(wav, diagnostics):
    x, rate = audio(wav)
    mid = x.mean(axis=1)
    with open(diagnostics) as file:
        grains = list(csv.DictReader(file))
    # Grain starts are padded by half the window in the internal OLA timeline.
    positions = np.array([int(g["outputSample"]) - 1024 for g in grains], dtype=int)
    positions = positions[(positions > 512) & (positions + 512 < len(mid))]
    derivative = np.abs(np.diff(mid))
    local_derivative = np.array([np.max(derivative[p-8:p+8]) for p in positions])
    exact_derivative = derivative[positions-1]
    local_median = np.array([np.median(derivative[p-8:p+8]) for p in positions])
    left = np.array([np.sqrt(np.mean(mid[p-256:p]**2)) for p in positions])
    right = np.array([np.sqrt(np.mean(mid[p:p+256]**2)) for p in positions])
    valid = np.maximum(left, right) > 1e-4
    jumps = np.abs(20*np.log10((right[valid]+1e-8)/(left[valid]+1e-8)))
    return dict(splice_count=len(positions), splice_derivative_max=float(local_derivative.max()),
                splice_derivative_p99=float(np.percentile(local_derivative, 99)),
                exact_boundary_derivative_p99=float(np.percentile(exact_derivative, 99)),
                boundary_to_neighborhood_p99=float(np.percentile(
                    exact_derivative/(local_median+1e-5), 99)),
                global_derivative_p999=float(np.percentile(derivative, 99.9)),
                splice_rms_jump_p95_db=float(np.percentile(jumps, 95)) if len(jumps) else 0,
                splice_rms_jump_max_db=float(jumps.max()) if len(jumps) else 0)

def vibrato_rate(signal):
    size, hop, rate = 8192, 1024, 48000
    frequencies = []
    for start in range(rate, len(signal)-rate-size, hop):
        spectrum = np.abs(np.fft.rfft(signal[start:start+size]*np.hanning(size)))
        frequencies.append(log_peak(spectrum, 440, size)[0])
    cents = 1200*np.log2(np.asarray(frequencies)/np.median(frequencies))
    envelope = np.hanning(len(cents))
    spectrum = np.abs(np.fft.rfft((cents-np.mean(cents))*envelope))
    hz = np.fft.rfftfreq(len(cents), hop/rate)
    valid = (hz >= 1) & (hz <= 10)
    return float(hz[valid][np.argmax(spectrum[valid])])

def main():
    with (OUT / "manifest.csv").open() as file:
        manifest = list(csv.DictReader(file))
    measurements = []
    vocal = []
    vibrato = []
    for row in manifest:
        x, rate = audio(row["wsola"])
        source, _ = audio(row["input"])
        expected = round(len(source) / float(row["speed"]))
        assert len(x) == expected
        assert np.isfinite(x).all()
        for mode, path in (("wsola", row["wsola"]), ("phase53", row["phase53"])):
            basic = fields(run([str(BUILD / "wav_metrics"), path]))
            spectral = fields(run([str(BUILD / "stereo_spectral_metrics"), row["input"],
                                  path, row["speed"]]))
            data = {"section": row["section"], "speed": row["speed"], "mode": mode,
                    "duration_error_samples": int(basic["frames"]) - expected,
                    "finite": basic.get("finite", "unknown"),
                    "processingSeconds": row["processingSeconds"] if mode == "wsola" else "",
                    "peakRSSBytes": row["peakRSSBytes"] if mode == "wsola" else "",
                    **basic, **spectral}
            if mode == "wsola":
                data.update(splice_metrics(path, row["diagnostics"]))
            measurements.append(data)
            if row["section"] == "vibrato":
                vibrato.append({"speed": row["speed"], "mode": mode,
                                **vibrato_metrics(audio(path)[0].mean(axis=1), 440, 1),
                                "vibrato_rate_hz": vibrato_rate(audio(path)[0].mean(axis=1))})
        if row["section"].startswith(("female", "male")) or row["section"] == "vowel":
            for detail in paired_vocal(row["phase53"], row["wsola"], rate):
                vocal.append({"section": row["section"], "speed": row["speed"], **detail})
        print(row["section"], row["speed"], flush=True)
    save(OUT / "metrics.csv", measurements)
    save(OUT / "vocal_modulation.csv", vocal)
    save(OUT / "vibrato_metrics.csv", vibrato)

if __name__ == "__main__":
    main()
