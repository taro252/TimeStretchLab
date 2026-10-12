#!/usr/bin/env python3
"""Phase 41 independent acoustic and overlap diagnostics around the heard event."""
import csv
import math
import sys
from pathlib import Path

import numpy as np
from phase32_study import read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase41"
RATE = 44100
CENTRE = 22494 + 3 * RATE  # The user's approximate 3 s in the audition clip.
MODES = {
    "original_C": (ROOT / "results/phase40/mix_040_to_200_C.wav",
                   OUT / "components_normal.csv", OUT / "map_mix_040_to_200_C.csv"),
    "hold_density": (OUT / "mix_040_to_200_C_hold_density.wav",
                     OUT / "components_hold.csv", OUT / "map_mix_040_to_200_C_hold_density.csv"),
    "delay_density": (OUT / "mix_040_to_200_C_delay_density.wav",
                      OUT / "components_delay.csv", OUT / "map_mix_040_to_200_C_delay_density.csv"),
}


def rms(values):
    return float(np.sqrt(np.mean(np.square(values.astype(np.float64)))))


def spectral(values, rate=RATE):
    mono = values.mean(axis=1)
    size, hop = 2048, 512
    frames = np.stack([mono[p:p+size] for p in range(0, len(mono)-size, hop)])
    spectra = np.fft.rfft(frames * np.hanning(size), axis=1)
    power = abs(spectra)
    flux = np.sqrt(np.mean(np.diff(power, axis=0)**2, axis=1))
    frequency = np.fft.rfftfreq(size, 1/rate)
    peak = frequency[np.argmax(power[:, 1:], axis=1)+1]
    phase = np.angle(spectra)
    phase_step = np.angle(spectra[1:] * np.conj(spectra[:-1]))
    weights = power[1:] * power[:-1]
    band = (frequency >= 500) & (frequency <= 5000)
    phase_rms = np.sqrt(np.sum(weights[:, band]*phase_step[:, band]**2) /
                        max(np.sum(weights[:, band]), 1e-20))
    return float(np.median(flux)), float(np.percentile(flux, 95)), \
        float(np.std(peak)), float(phase_rms)


def stereo(values):
    left, right = values[:, 0].astype(float), values[:, 1].astype(float)
    mid, side = (left+right)/2, (left-right)/2
    corr = float(np.corrcoef(left, right)[0, 1])
    n = len(values)
    window = np.hanning(n)
    left_fft = np.fft.rfft(left*window)
    right_fft = np.fft.rfft(right*window)
    freq = np.fft.rfftfreq(n, 1/RATE)
    weight = abs(left_fft*right_fft)
    phase = np.angle(left_fft*np.conj(right_fft))
    band = (freq>=200) & (freq<=5000)
    ipd = math.sqrt(float(np.sum(weight[band]*phase[band]**2) /
                          max(np.sum(weight[band]), 1e-20)))
    return corr, rms(side)/max(rms(mid), 1e-20), ipd


def weight_stats(path, first, last):
    rows = list(csv.DictReader(path.open()))
    result = []
    for resolution, size in enumerate((8192, 4096, 1024)):
        positions = np.array([int(row["output_sample"]) for row in rows
                              if int(row["resolution"])==resolution], dtype=int)
        # Include every frame that can overlap this region, including frames
        # before the displayed transition portion of the trace.
        points = np.arange(first, last, 128)
        weights = np.zeros(len(points))
        overlaps = np.zeros(len(points), dtype=int)
        for start in positions[(positions < last) & (positions + size > first)]:
            loc = points-start
            mask = (loc>=0) & (loc<size)
            weights[mask] += (0.5*(1-np.cos(2*np.pi*loc[mask]/size)))**2
            overlaps[mask] += 1
        result.append((float(np.min(weights)), float(np.median(weights)),
                       int(np.min(overlaps))))
    return result


def main():
    rows = []
    for mode, (wav, component, trace) in MODES.items():
        rate, audio = read(wav)
        assert rate == RATE and len(audio) == 365440
        assert np.isfinite(audio).all()
        band = audio[CENTRE-RATE//2:CENTRE+RATE//2]
        envelope = {}
        for ms in (10, 20, 50):
            n = ms*RATE//1000
            envelope[ms] = [rms(band[p:p+n]) for p in range(0,len(band)-n+1,n)]
        flux50, flux95, peak_var, phase_rms = spectral(band)
        corr, side_mid, ipd = stereo(band)
        components = np.loadtxt(component, delimiter=",", skiprows=1)
        components = components[(components[:, 0]>=CENTRE-RATE//2) &
                                (components[:, 0]<CENTRE+RATE//2)]
        weights = weight_stats(trace, CENTRE-RATE//2, CENTRE+RATE//2)
        row = dict(mode=mode,center_sample=CENTRE,peak=float(abs(band).max()),
                   rms_10ms_min=min(envelope[10]),rms_10ms_max=max(envelope[10]),
                   rms_20ms_min=min(envelope[20]),rms_20ms_max=max(envelope[20]),
                   rms_50ms_min=min(envelope[50]),rms_50ms_max=max(envelope[50]),
                   spectral_flux_median=flux50,spectral_flux_p95=flux95,
                   dominant_frequency_std_hz=peak_var,phase_step_rms_rad=phase_rms,
                   lr_corr=corr,side_mid=side_mid,ipd_rms_rad=ipd,
                   finite=int(np.isfinite(audio).all()),
                   local_silence_frames=int(np.sum(np.max(abs(band),axis=1)<1e-9)))
        for index, label in enumerate(("low", "mid", "high")):
            row[f"{label}_raw_rms"] = rms(components[:, index+2])
            row[f"{label}_weight_min"] = weights[index][0]
            row[f"{label}_weight_median"] = weights[index][1]
            row[f"{label}_overlap_min"] = weights[index][2]
        row["lp250_contribution_rms"] = rms(components[:, 5])
        row["lp3500_contribution_rms"] = rms(components[:, 6])
        rows.append(row)
    with (OUT / "acoustics.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row["mode"], "minimum weights", *(row[f"{x}_weight_min"] for x in
              ("low", "mid", "high")), "phase step", row["phase_step_rms_rad"])


if __name__ == "__main__":
    main()
