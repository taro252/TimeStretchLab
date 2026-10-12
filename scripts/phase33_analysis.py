#!/usr/bin/env python3
"""Input-referenced decay, stereo, and pre/post crossover diagnostics."""
import csv
from pathlib import Path

import numpy as np

from phase32_metrics import envelope, rms, stereo
from phase32_study import read

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase33'
PHASE32 = ROOT / 'results/phase32/raw'
REGIONS = {
    'drums_attack': ('drums', 3.77, 4.02),
    'drums_tail': ('drums', 4.05, 4.35),
    'mix_busy': ('mix', 2.9, 4.2),
    'mix_quiet': ('mix', 4.2, 4.8),
}


def stft(audio, rate, size=4096, hop=512):
    if len(audio) < size:
        return np.empty((0, size // 2 + 1), dtype=complex)
    windows = np.lib.stride_tricks.sliding_window_view(audio, size)[::hop]
    return np.fft.rfft(windows * np.hanning(size), axis=1)


def circular(a, b):
    product = a * np.conj(b)
    weight = np.abs(a) * np.abs(b)
    valid = weight > np.max(weight, initial=0) * 1e-4
    if not np.any(valid):
        return float('nan'), float('nan'), 0
    unit = product[valid] / np.maximum(np.abs(product[valid]), 1e-20)
    weighted = np.sum(unit * weight[valid]) / np.sum(weight[valid])
    return float(np.angle(weighted)), float(abs(weighted)), int(np.count_nonzero(valid))


def envelope_error(input_audio, output_audio, rate, trace, begin, end):
    output_time, output_env = envelope(output_audio, rate, 40)
    input_time, input_env = envelope(input_audio, rate, 10)
    mask = (output_time >= begin / 0.25) & (output_time < end / 0.25)
    points = output_time[mask]
    if len(points) < 10:
        return float('nan'), float('nan'), float('nan'), float('nan')
    output_positions = points * rate
    map_output = np.array([float(row['outputSample']) for row in trace])
    map_input = np.array([float(row['inputSample']) for row in trace])
    source_time = np.interp(output_positions, map_output, map_input) / rate
    expected = np.interp(source_time, input_time, input_env)
    observed = output_env[mask]
    valid = expected > max(np.max(expected) * 0.005, 1e-7)
    if np.count_nonzero(valid) < 8:
        return float('nan'), float('nan'), float('nan'), float('nan')
    x = 20 * np.log10(expected[valid])
    y = 20 * np.log10(np.maximum(observed[valid], 1e-10))
    difference = y - x
    centered = difference - np.median(difference)
    corr = float(np.corrcoef(x, y)[0, 1]) if np.std(x) > 1e-8 else float('nan')
    # Modulation of the *error* envelope, excluding a constant loudness offset.
    series = centered - np.mean(centered)
    frequencies = np.fft.rfftfreq(len(series), np.median(np.diff(points[valid])))
    power = np.abs(np.fft.rfft(series * np.hanning(len(series))))
    active = (frequencies >= 1) & (frequencies <= 12)
    modulation = float(frequencies[active][np.argmax(power[active])]) if np.any(active) else float('nan')
    return float(np.std(centered)), corr, float(np.median(difference)), modulation


def band_envelope_error(input_audio, output_section, rate, trace, begin, select):
    source_spec = stft(np.mean(input_audio, axis=1), rate)
    output_spec = stft(np.mean(output_section, axis=1), rate)
    if len(output_spec) < 8:
        return float('nan'), float('nan')
    source_env = np.sqrt(np.mean(np.abs(source_spec[:, select])**2, axis=1))
    output_env = np.sqrt(np.mean(np.abs(output_spec[:, select])**2, axis=1))
    source_samples = np.arange(len(source_env))*512 + 2048
    start = round(begin / 0.25 * rate)
    output_samples = start + np.arange(len(output_env))*512 + 2048
    map_output = np.array([float(row['outputSample']) for row in trace])
    map_input = np.array([float(row['inputSample']) for row in trace])
    positions = np.interp(output_samples,map_output,map_input)
    expected = np.interp(positions,source_samples,source_env)
    valid = expected > max(np.max(expected)*0.005, 1e-8)
    if np.count_nonzero(valid) < 8:
        return float('nan'), float('nan')
    x = 20*np.log10(expected[valid])
    y = 20*np.log10(np.maximum(output_env[valid],1e-12))
    delta = y-x
    return float(np.std(delta-np.median(delta))),float(np.corrcoef(x,y)[0,1])


def stereo_band(audio, rate, select):
    if audio.shape[1] < 2:
        return float('nan'), float('nan'), 0
    left = stft(audio[:, 0], rate)[:, select]
    right = stft(audio[:, 1], rate)[:, select]
    _, concentration, count = circular(left, right)
    phase = np.angle(left * np.conj(right))
    weight = np.abs(left) * np.abs(right)
    mean = np.angle(np.sum(weight * np.exp(1j * phase)))
    deviation = np.angle(np.exp(1j * (phase - mean)))
    ipd_rms = float(np.sqrt(np.sum(weight * deviation**2) / max(np.sum(weight), 1e-12)))
    ild = float(20 * np.log10(np.sqrt(np.sum(np.abs(left)**2)) /
                              max(np.sqrt(np.sum(np.abs(right)**2)), 1e-12)))
    return ipd_rms, ild, count


def region_metrics():
    rows = []
    for label, (source, begin, end) in REGIONS.items():
        rate, source_audio = read(ROOT / f'results/phase31/input/{source}.wav')
        for mode in ('baseline', 'no_lock', 'no_reset', 'no_propagation'):
            key = f'{source}_{mode}_025'
            _, final = read(PHASE32 / f'{key}.wav')
            with (OUT / 'trace' / key / 'mid.csv').open(newline='') as stream:
                trace = list(csv.DictReader(stream))
            a, b = round(begin / .25 * rate), round(end / .25 * rate)
            section = final[a:b]
            full_error = envelope_error(source_audio, final, rate, trace, begin, end)
            before = [read(PHASE32 / f'{key}_{band}.wav')[1][a:b]
                      for band in ('low', 'mid', 'high')]
            after = [read(OUT / 'crossover' / f'{key}_{band}.wav')[1][a:b]
                     for band in ('low', 'mid', 'high')]
            freq = np.fft.rfftfreq(4096, 1 / rate)
            for band, select in (('low', freq < 250),
                                 ('mid', (freq >= 250) & (freq < 3500)),
                                 ('high', freq >= 3500)):
                for stage, collection in (('pre', before), ('post', after),
                                          ('final', [section]*3)):
                    part = collection[('low', 'mid', 'high').index(band)]
                    mono = np.mean(part, axis=1)
                    power = np.abs(stft(mono, rate)[:, select]) ** 2
                    e = np.sqrt(np.mean(power, axis=1))
                    db = 20 * np.log10(np.maximum(e, 1e-9))
                    ipd, ild, bins = stereo_band(part, rate, select)
                    side_mid, correlation = stereo(part)
                    band_error,band_correlation = band_envelope_error(
                        source_audio,part,rate,trace,begin,select)
                    rows.append(dict(region=label,source=source,mode=mode,
                                     resolution=band,stage=stage,rms=rms(part),
                                     band_envelope_std_db=float(np.std(db)),
                                     ipd_rms_rad=ipd,ild_db=ild,
                                     valid_stereo_bins=bins,side_mid=side_mid,
                                     lr_correlation=correlation,
                                     input_band_envelope_error_db=band_error,
                                     input_band_envelope_correlation=band_correlation,
                                     input_full_envelope_error_db=full_error[0] if stage=='final' else '',
                                     input_full_envelope_correlation=full_error[1] if stage=='final' else '',
                                     input_median_gain_db=full_error[2] if stage=='final' else '',
                                     error_modulation_hz=full_error[3] if stage=='final' else ''))
    with (OUT / 'region_diagnostics.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    print(len(rows),'pre/post region measurements')


def crossover_metrics():
    rows=[]
    for source in ('drums','mix'):
        rate,_=read(ROOT/f'results/phase31/input/{source}.wav')
        for mode in ('baseline','no_lock','no_reset','no_propagation'):
            key=f'{source}_{mode}_025'
            for label,(region_source,begin,end) in REGIONS.items():
                if region_source!=source:continue
                a,b=round(begin/.25*rate),round(end/.25*rate)
                for stage,folder in (('pre',PHASE32),('post',OUT/'crossover')):
                    components=[]
                    for band in ('low','mid','high'):
                        path=folder/f'{key}_{band}.wav'
                        _,data=read(path)
                        components.append(stft(np.mean(data[a:b],axis=1),rate))
                    freq=np.fft.rfftfreq(4096,1/rate)
                    for edge,region,first,second in (
                            ('250', (freq>=200)&(freq<300),0,1),
                            ('3500',(freq>=3300)&(freq<3700),1,2)):
                        x,y=components[first][:,region],components[second][:,region]
                        angle,concentration,count=circular(x,y)
                        amp1=np.sqrt(np.sum(np.abs(x)**2,axis=1))
                        amp2=np.sqrt(np.sum(np.abs(y)**2,axis=1))
                        ratio=20*np.log10(np.maximum(amp1,1e-9)/np.maximum(amp2,1e-9))
                        denominator=np.abs(x)+np.abs(y)
                        cancellation=np.abs(x+y)/np.maximum(denominator,1e-12)
                        rows.append(dict(region=label,source=source,mode=mode,
                                         stage=stage,edge_hz=edge,
                                         phase_difference_rad=angle,
                                         phase_concentration=concentration,
                                         valid_bin_pairs=count,
                                         envelope_ratio_median_db=float(np.median(ratio)),
                                         envelope_ratio_std_db=float(np.std(ratio)),
                                         pair_cancellation_median=float(np.median(cancellation)),
                                         pair_cancellation_p10=float(np.percentile(cancellation,10))))
    with (OUT/'crossover_regions.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    print(len(rows),'crossover-region measurements')


if __name__=='__main__':
    region_metrics()
    crossover_metrics()
