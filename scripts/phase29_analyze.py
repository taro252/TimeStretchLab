#!/usr/bin/env python3
"""Read-only phase/OLA/FIR and synthetic sound measurements for Phase 29."""
from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

from phase29_study import OUT, NAMES, PAIRS, golden, input_path, wav, write_csv


def stages(label: str) -> list[dict[str, str]]:
    with (OUT / "diagnostics" / f"{label}.stages.csv").open(newline="") as stream:
        return list(csv.DictReader(stream))


def frequency(piece: np.ndarray, rate: int) -> float:
    signal = np.asarray(np.mean(piece, axis=1), dtype=np.float64)
    if len(signal) < 4096:
        return math.nan
    window = np.hanning(len(signal))
    power = np.abs(np.fft.rfft(signal * window))
    peak = int(np.argmax(power[1:])) + 1
    left, middle, right = np.log(np.maximum(power[peak-1:peak+2], 1e-20))
    adjust = 0.5 * (left-right) / (left-2*middle+right)
    return float((peak+adjust)*rate/len(signal))


def spectral_stereo(piece: np.ndarray) -> tuple[float, float]:
    size = 4096
    if len(piece) < size:
        return math.nan, math.nan
    window = np.hanning(size)
    ipd_power = ild_power = weights = 0.0
    for index in range(0, len(piece)-size+1, 2048):
        left = np.fft.rfft(np.asarray(piece[index:index+size, 0], dtype=np.float64)*window)
        right = np.fft.rfft(np.asarray(piece[index:index+size, 1], dtype=np.float64)*window)
        lmag, rmag = np.abs(left), np.abs(right)
        weight = np.minimum(lmag, rmag)
        valid = weight > max(float(np.max(weight))*0.01, 1e-10)
        if not np.any(valid):
            continue
        w = weight[valid]**2
        ipd = np.angle(left[valid]*np.conj(right[valid]))
        ild = 20*np.log10(np.maximum(lmag[valid], 1e-12) /
                          np.maximum(rmag[valid], 1e-12))
        ipd_power += float(np.sum(w*ipd*ipd))
        ild_power += float(np.sum(w*ild*ild))
        weights += float(np.sum(w))
    return (math.sqrt(ipd_power/weights), math.sqrt(ild_power/weights)) if weights else (math.nan, math.nan)


def adjacent_spectrum(piece: np.ndarray) -> tuple[float, float]:
    mono = np.asarray(np.mean(piece, axis=1), dtype=np.float64)
    size = 4096
    if len(mono) < size*2:
        return math.nan, math.nan
    window = np.hanning(size)
    spectra = [np.log(np.maximum(np.abs(np.fft.rfft(mono[i:i+size]*window)), 1e-7))
               for i in range(0, len(mono)-size+1, 1024)]
    changes = np.sqrt(np.mean(np.diff(spectra, axis=0)**2, axis=1))
    return float(np.median(changes)), float(np.percentile(changes, 90))


def click_peaks(piece: np.ndarray, rate: int) -> list[tuple[int, float, int]]:
    envelope = np.max(np.abs(piece), axis=1)
    candidate = np.flatnonzero((envelope > 0.1) &
                               (envelope >= np.roll(envelope, 1)) &
                               (envelope > np.roll(envelope, -1)))
    groups: list[list[int]] = []
    for item in candidate:
        if not groups or item - groups[-1][-1] > rate//10:
            groups.append([int(item)])
        else:
            groups[-1].append(int(item))
    peaks = []
    for group in groups:
        index = max(group, key=lambda item: envelope[item])
        height = float(envelope[index])
        left = right = index
        while left and envelope[left-1] >= height*0.5:
            left -= 1
        while right+1 < len(envelope) and envelope[right+1] >= height*0.5:
            right += 1
        peaks.append((index, height, right-left+1))
    return peaks


def main() -> None:
    measured, stage_rows, fir_rows, click_rows, hop_rows, target_rows, drum_rows = [], [], [], [], [], [], []
    for name in NAMES:
        input_audio, rate = wav(input_path(name))
        for initial, target in PAIRS:
            label = f"{name}_{initial.replace('.', '')}_to_{target.replace('.', '')}"
            with (OUT / "diagnostics" / f"{label}.plans.csv").open() as stream:
                change = next(csv.DictReader(stream))
            data = dict(line.split("=", 1) for line in
                        (OUT / "diagnostics" / f"{label}.txt").read_text().splitlines()
                        if "=" in line)
            for resolution, window in (("low", 8192), ("mid", 4096), ("high", 1024)):
                minimum, maximum = int(data[f"{resolution}_hop_min"]), int(data[f"{resolution}_hop_max"])
                if minimum <= 0 or maximum >= window:
                    raise RuntimeError(f"Unsafe {resolution} hop: {label}")
                hop_rows.append(dict(case=label, resolution=resolution,
                                     window=window, minimum=minimum, maximum=maximum))
            applied = int(change["applied_output"])
            complete = int(change["completion_output"])
            before_rows = stages(f"fixed_{name}_{initial.replace('.', '')}")
            after_rows = stages(label)
            target_rows_trace = stages(f"fixed_{name}_{target.replace('.', '')}")
            fixed = {(row["resolution"], row["frame"]): row for row in before_rows
                     if row["stage"] == "frame"}
            switched = {(row["resolution"], row["frame"]): row for row in after_rows
                        if row["stage"] == "frame"}
            for resolution in ("0", "1", "2"):
                keys = sorted((key for key in fixed if key[0] == resolution and key in switched),
                              key=lambda item: int(item[1]))
                if not keys:
                    raise RuntimeError(f"Missing stage trace: {label} {resolution}")
                mismatch = {field: next((int(key[1]) for key in keys
                                         if fixed[key][field] != switched[key][field]), -1)
                            for field in ("fft", "phase", "ifft", "ola")}
                if mismatch["fft"] >= 0:
                    raise RuntimeError(f"Input FFT changed: {label} {resolution}")
                stage_rows.append(dict(case=label, resolution=resolution,
                                       common_frames=len(keys),
                                       **{f"first_{key}_difference_frame": value
                                          for key, value in mismatch.items()}))
            a_fir = {row["output_sample"]: row for row in before_rows
                     if row["stage"] == "fir"}
            b_fir = {row["output_sample"]: row for row in after_rows
                     if row["stage"] == "fir"}
            common = sorted(set(a_fir).intersection(b_fir), key=int)
            fir_rows.append(dict(case=label, common_blocks=len(common),
                                 **{f"first_{field}_difference_sample":
                                    next((int(sample) for sample in common
                                          if a_fir[sample][field] != b_fir[sample][field]), -1)
                                    for field in ("low_fir", "high_fir", "output_fir")}))
            audio, _ = wav(OUT / "raw" / f"{label}.wav")
            before = audio[max(0, applied-rate):max(0, applied-rate//5)]
            after = audio[min(len(audio), complete+rate//5):min(len(audio), complete+rate)]
            ipd_before, ild_before = spectral_stereo(before)
            ipd_after, ild_after = spectral_stereo(after)
            spectral_before, p90_before = adjacent_spectrum(before)
            spectral_after, p90_after = adjacent_spectrum(after)
            measured.append(dict(case=label, source=name, initial=initial, target=target,
                                 ipd_before=ipd_before, ipd_after=ipd_after,
                                 ild_before_db=ild_before, ild_after_db=ild_after,
                                 spectral_change_before=spectral_before,
                                 spectral_change_after=spectral_after,
                                 spectral_change_p90_before=p90_before,
                                 spectral_change_p90_after=p90_after,
                                 sine_hz_before=frequency(before, rate) if name == "sine" else "",
                                 sine_hz_after=frequency(after, rate) if name == "sine" else ""))
            completion_frame = change["completion_frame"]
            matching = [row for row in target_rows_trace
                        if row["stage"] == "frame" and row["resolution"] == "1"
                        and row["frame"] == completion_frame]
            if len(matching) != 1:
                raise RuntimeError(f"Missing fixed target completion frame: {label}")
            fixed_sample = int(matching[0]["output_sample"])
            target_path = (golden(name, target) if target in ("0.50", "0.60", "0.70", "0.75", "0.80")
                           else OUT / "raw" / f"{name}_fixed_{target.replace('.', '')}.wav")
            target_audio, _ = wav(target_path)
            target_piece = target_audio[fixed_sample+rate//5:fixed_sample+rate]
            if len(target_piece) != len(after):
                raise RuntimeError(f"Target fixed window length differs: {label}")
            target_ipd, target_ild = spectral_stereo(target_piece)
            target_l = np.asarray(target_piece[:, 0], dtype=np.float64)
            target_r = np.asarray(target_piece[:, 1], dtype=np.float64)
            var_l = np.asarray(after[:, 0], dtype=np.float64)
            var_r = np.asarray(after[:, 1], dtype=np.float64)
            target_mid, target_side = (target_l+target_r)*0.5, (target_l-target_r)*0.5
            var_mid, var_side = (var_l+var_r)*0.5, (var_l-var_r)*0.5
            target_rows.append(dict(case=label, source=name, target=target,
                                    completion_frame=completion_frame,
                                    target_fixed_sample=fixed_sample,
                                    variable_ipd=ipd_after, target_ipd=target_ipd,
                                    ipd_difference=ipd_after-target_ipd,
                                    variable_ild=ild_after, target_ild=target_ild,
                                    ild_difference=ild_after-target_ild,
                                    variable_lr_corr=float(np.corrcoef(var_l, var_r)[0, 1]),
                                    target_lr_corr=float(np.corrcoef(target_l, target_r)[0, 1]),
                                    variable_side_mid=float(np.sqrt(np.mean(var_side*var_side)) /
                                                            max(np.sqrt(np.mean(var_mid*var_mid)), 1e-12)),
                                    target_side_mid=float(np.sqrt(np.mean(target_side*target_side)) /
                                                          max(np.sqrt(np.mean(target_mid*target_mid)), 1e-12))))
            if name == "drums":
                variable_attacks = click_peaks(after, rate)
                target_attacks = click_peaks(target_piece, rate)
                drum_rows.append(dict(case=label, variable_count=len(variable_attacks),
                                      target_count=len(target_attacks),
                                      variable_max_half_width=max((p[2] for p in variable_attacks), default=0),
                                      target_max_half_width=max((p[2] for p in target_attacks), default=0),
                                      variable_max_peak=max((p[1] for p in variable_attacks), default=0.0),
                                      target_max_peak=max((p[1] for p in target_attacks), default=0.0)))
            if name == "click":
                click_rows.append(dict(case=label, attack_count=len(click_peaks(audio, rate)),
                                       positions="/".join(str(p[0]) for p in click_peaks(audio, rate)),
                                       peaks="/".join(f"{p[1]:.7f}" for p in click_peaks(audio, rate)),
                                       half_max_widths="/".join(str(p[2]) for p in click_peaks(audio, rate))))
            print(label, "FFT identical", "sine after", measured[-1]["sine_hz_after"], flush=True)
    write_csv(OUT / "spectral_metrics.csv", measured)
    write_csv(OUT / "stage_comparison.csv", stage_rows)
    write_csv(OUT / "fir_comparison.csv", fir_rows)
    write_csv(OUT / "click_attacks.csv", click_rows)
    write_csv(OUT / "hop_ranges.csv", hop_rows)
    write_csv(OUT / "aligned_target_stereo.csv", target_rows)
    write_csv(OUT / "drum_attack_comparison.csv", drum_rows)


if __name__ == "__main__":
    main()
