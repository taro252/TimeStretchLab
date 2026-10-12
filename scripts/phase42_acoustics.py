#!/usr/bin/env python3
"""Objective transition-region diagnostics; no automatic quality decision."""
import csv
from pathlib import Path

import numpy as np
from phase32_study import read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results/phase42"
rows = []
for validation in csv.DictReader((OUT / "validation.csv").open()):
    name = validation["case"]
    plan = next(csv.DictReader((OUT / "plans" / f"{name}.csv").open()))
    rate, audio = read(OUT / "raw" / f"{name}.wav")
    center = int(plan["completion_output"] if float(plan["from"]) < .5 else
                 plan["applied_output"])
    excerpt = np.asarray(audio[max(0, center - rate // 2):
                               min(len(audio), center + rate // 2)], dtype=np.float64)
    if not len(excerpt):
        continue
    mono = excerpt.mean(axis=1)
    amplitude = np.abs(mono)
    peak_index = int(np.argmax(amplitude))
    attack_threshold = amplitude[peak_index] / np.sqrt(2.)
    attack_left = peak_index
    attack_right = peak_index
    while attack_left and amplitude[attack_left - 1] >= attack_threshold:
        attack_left -= 1
    while attack_right + 1 < len(amplitude) and amplitude[attack_right + 1] >= attack_threshold:
        attack_right += 1
    lead = max(0, attack_left - round(.020 * rate))
    pre_energy = float(np.sum(mono[lead:attack_left] ** 2))
    first_energy = float(np.sum(mono[attack_left:min(len(mono), attack_left + round(.020 * rate))] ** 2))
    frame = max(1, rate // 100)  # 10 ms
    rms = np.array([np.sqrt(np.mean(mono[n:n + frame] ** 2))
                    for n in range(0, len(mono), frame) if len(mono[n:n + frame]) >= frame // 2])
    deriv = np.abs(np.diff(mono))
    fft_size, fft_hop = 2048, 512
    spectra = np.array([np.abs(np.fft.rfft(mono[n:n + fft_size] * np.hanning(fft_size)))
                        for n in range(0, max(0, len(mono) - fft_size), fft_hop)])
    flux = (np.sum(np.maximum(0, np.diff(spectra, axis=0)), axis=1) /
            np.maximum(np.sum(spectra[1:], axis=1), 1e-12)) if len(spectra) > 1 else np.array([0.])
    if excerpt.shape[1] == 2:
        left, right = excerpt[:, 0], excerpt[:, 1]
        corr = float(np.corrcoef(left, right)[0, 1]) if np.std(left) and np.std(right) else 0.
        mid, side = (left + right) / 2, (left - right) / 2
        side_mid = float(np.sqrt(np.mean(side ** 2)) / max(np.sqrt(np.mean(mid ** 2)), 1e-12))
        ipd_power = 0.
        ipd_weighted = 0.
        for n in range(0, max(0, len(excerpt) - fft_size), fft_hop):
            l_spec = np.fft.rfft(left[n:n + fft_size] * np.hanning(fft_size))
            r_spec = np.fft.rfft(right[n:n + fft_size] * np.hanning(fft_size))
            weight = np.abs(l_spec) * np.abs(r_spec)
            phase = np.angle(l_spec * np.conj(r_spec))
            ipd_power += float(np.sum(weight))
            ipd_weighted += float(np.sum(weight * phase ** 2))
        ipd_rms = float(np.sqrt(ipd_weighted / max(ipd_power, 1e-12)))
    else:
        corr, side_mid, ipd_rms = 1., 0., 0.
    rows.append(dict(case=name, center_output=center, peak=float(np.max(np.abs(excerpt))),
                     attack_peak_from_center_ms=(peak_index + max(0, center - rate // 2) - center) * 1000 / rate,
                     attack_width_3db_ms=(attack_right - attack_left + 1) * 1000 / rate,
                     preecho_to_first20ms=pre_energy / max(first_energy, 1e-12),
                     derivative_peak=float(np.max(deriv)) if len(deriv) else 0.,
                     rms_min=float(np.min(rms)), rms_max=float(np.max(rms)),
                     rms_modulation=float(np.std(rms) / max(np.mean(rms), 1e-12)),
                     spectral_flux_median=float(np.median(flux)),
                     lr_corr=corr, side_mid=side_mid, ipd_rms=ipd_rms,
                     finite=int(np.isfinite(audio).all())))
with (OUT / "acoustics.csv").open("w", newline="") as stream:
    writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
print(len(rows), "transition-region measurements")
