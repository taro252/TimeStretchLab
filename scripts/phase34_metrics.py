#!/usr/bin/env python3
"""Input-mapped envelope, phase, OLA, attack, pitch and stereo diagnostics."""
import csv
from pathlib import Path

import numpy as np

from phase31_synthetic_metrics import clicks
from phase32_metrics import envelope, rms, stereo
from phase32_study import read
from phase33_analysis import stft, stereo_band

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase34'
REGIONS = {
    'drums_attack': ('drums', 3.77, 4.02),
    'drums_tail': ('drums', 4.05, 4.35),
    'mix_busy': ('mix', 2.9, 4.2),
    'mix_quiet': ('mix', 4.2, 4.8),
    'vocal_vowel': ('vocal', 3.2, 3.85),
}
WINDOWS = {'low': 8192, 'mid': 4096, 'high': 1024}


def rows(path):
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def write(path, records):
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)


def mapped(trace, input_samples):
    x = np.array([float(r['inputSample']) for r in trace])
    y = np.array([float(r['outputSample']) for r in trace])
    return np.interp(input_samples, x, y)


def expected_envelope(source, output, rate, speed, trace, begin, end):
    input_t, input_e = envelope(source, rate, 10)
    output_t, output_e = envelope(output, rate, round(10/speed))
    x = np.array([float(r['inputSample']) for r in trace])
    y = np.array([float(r['outputSample']) for r in trace])
    input_at_output = np.interp(output_t*rate, y, x)/rate
    select = (input_at_output >= begin) & (input_at_output <= end)
    expected = np.interp(input_at_output[select], input_t, input_e)
    actual = output_e[select]
    valid = expected > max(float(np.max(expected, initial=0))*.005, 1e-8)
    if np.count_nonzero(valid) < 8:
        return float('nan'), float('nan'), float('nan'), float('nan')
    xdb = 20*np.log10(expected[valid])
    ydb = 20*np.log10(np.maximum(actual[valid], 1e-10))
    difference = ydb-xdb
    centered = difference-np.median(difference)
    # The slope is compared on the actual output-time axis; natural decay
    # is included in the input reference, not treated as an artifact.
    output_seconds = output_t[select][valid]
    slope_expected = np.polyfit(output_seconds, xdb, 1)[0]
    slope_actual = np.polyfit(output_seconds, ydb, 1)[0]
    return (float(np.std(centered)), float(np.corrcoef(xdb, ydb)[0, 1]),
            float(slope_expected), float(slope_actual))


def spectral_variation(section, rate, speed):
    mono = np.mean(section, axis=1)
    size = 4096
    hop = max(128, round(rate*.01/speed))
    if len(mono) < size+hop:
        return float('nan')
    frames = np.lib.stride_tricks.sliding_window_view(mono, size)[::hop]
    magnitude = np.abs(np.fft.rfft(frames*np.hanning(size), axis=1))
    normalized = magnitude/np.maximum(np.linalg.norm(magnitude, axis=1, keepdims=True), 1e-12)
    return float(np.median(np.linalg.norm(np.diff(normalized, axis=0), axis=1)))


def band_diagnostic(original, section, rate, trace, output_start, selection):
    source_spectrum = stft(np.mean(original, axis=1), rate)
    output_spectrum = stft(np.mean(section, axis=1), rate)
    source_energy = np.sqrt(np.mean(np.abs(source_spectrum[:,selection])**2, axis=1))
    output_energy = np.sqrt(np.mean(np.abs(output_spectrum[:,selection])**2, axis=1))
    output_samples = output_start+np.arange(len(output_energy))*512+2048
    x = np.array([float(r['inputSample']) for r in trace])
    y = np.array([float(r['outputSample']) for r in trace])
    input_samples = np.interp(output_samples,y,x)
    expected = np.interp(input_samples,np.arange(len(source_energy))*512+2048,
                         source_energy)
    valid = expected > max(float(np.max(expected,initial=0))*.005,1e-9)
    delta = 20*np.log10(np.maximum(output_energy[valid],1e-12)) - \
            20*np.log10(expected[valid])
    norm = np.abs(output_spectrum[:,selection])
    norm /= np.maximum(np.linalg.norm(norm,axis=1,keepdims=True),1e-12)
    spectral = float(np.median(np.linalg.norm(np.diff(norm,axis=0),axis=1)))
    return float(np.std(delta-np.median(delta))), spectral


def geometry(trace, window):
    starts = np.array([int(r['outputSample']) for r in trace], dtype=np.int64)
    hops = np.diff(starts)
    if not len(hops):
        return (0, 0, 0, 0, 0, float('nan'))
    frames = len(starts)
    interior = np.where((starts[:-1] > 4*window) &
                        (starts[1:] < starts[-1]-4*window))[0]
    worst = interior[np.argmax(hops[interior])] if len(interior) else int(np.argmax(hops))
    left, right = starts[worst], starts[worst+1]
    weight = np.zeros(max(0, right-left), dtype=np.float64)
    previous = max(0, np.searchsorted(starts, left-window+1))
    for s in starts[previous:np.searchsorted(starts, right)]:
        a, b = max(left, s), min(right, s+window)
        index = np.arange(a-s, b-s)
        hann = .5*(1-np.cos(2*np.pi*index/window))
        weight[a-left:b-left] += hann*hann
    return (frames, int(np.min(hops)), int(np.max(hops)),
            int(np.count_nonzero(hops<=0)),int(np.count_nonzero(hops>=window)),
            float(np.min(weight)) if len(weight) else float('nan'))


def phase_summary(trace, begin, end, rate):
    selected = [r for r in trace if begin*rate <= int(r['inputSample']) < end*rate]
    valid = [r for r in selected if int(r['validBins']) > 0]
    def median(key):
        return float(np.median([float(r[key]) for r in valid])) if valid else float('nan')
    return dict(frames=len(selected), reset_frames=sum(int(r['reset']) for r in selected),
                analysis_phase_residual_rad=median('analysisPhaseResidualRms'),
                output_phase_residual_rad=median('outputPhaseResidualRms'),
                peak_phase_residual_rad=median('peakOutputPhaseResidualRms'),
                owner_change_fraction=median('ownerChangeFraction'))


def attack(audio, rate, center):
    mono = np.mean(audio, axis=1)
    center = int(round(center))
    first = max(0, center-round(.08*rate))
    last = min(len(mono), center+round(.12*rate))
    position = first+int(np.argmax(np.abs(mono[first:last])))
    peak = abs(float(mono[position]))
    before = mono[max(0, center-round(.02*rate)):center]
    after = mono[center:center+round(.02*rate)]
    local = audio[max(0, center-round(.15*rate)):center+round(.20*rate)]
    _, power = envelope(local, rate, 10)
    top = int(np.argmax(power)); threshold = power[top]/np.sqrt(2)
    left = right = top
    while left and power[left-1] >= threshold: left -= 1
    while right+1 < len(power) and power[right+1] >= threshold: right += 1
    return dict(peak=peak, peak_offset_ms=1000*(position-center)/rate,
                envelope_halfpower_width_ms=5*(right-left+1),
                pre20ms_rms=rms(before), post20ms_rms=rms(after),
                pre_post20_ratio=rms(before)/max(rms(after), 1e-12))


def harmonic_pitch(audio, rate):
    signal = np.mean(audio, axis=1)
    a, b = len(signal)//4, 3*len(signal)//4
    signal = signal[a:b]
    size = min(len(signal), 2**17)
    signal = signal[len(signal)//2-size//2:len(signal)//2+size//2]
    spectrum = np.abs(np.fft.rfft(signal*np.hanning(len(signal))))
    hz = np.fft.rfftfreq(len(signal), 1/rate)
    indices = np.where((hz>=100)&(hz<=120))[0]
    peak = indices[np.argmax(spectrum[indices])]
    if 0 < peak < len(spectrum)-1:
        y = np.log(np.maximum(spectrum[peak-1:peak+2], 1e-12))
        offset = .5*(y[0]-y[2])/(y[0]-2*y[1]+y[2]) if y[0]-2*y[1]+y[2] else 0
    else: offset = 0
    return float((peak+offset)*rate/len(signal))


def bass_pitch_frames(audio, rate):
    mono=np.mean(audio,axis=1)
    size=4096; hop=512
    result=[]
    for start in range(0,len(mono)-size+1,hop):
        frame=mono[start:start+size].astype(np.float64)
        if np.sqrt(np.mean(frame*frame))<.01: continue
        frame-=np.mean(frame)
        frame*=np.hanning(size)
        spectrum=np.fft.rfft(frame,n=8192)
        autocorrelation=np.fft.irfft(np.abs(spectrum)**2,n=8192)[:size]
        lo,hi=round(rate/180),round(rate/40)
        period=lo+int(np.argmax(autocorrelation[lo:hi]))
        if autocorrelation[period]<autocorrelation[0]*.25: continue
        if 0<period+1<len(autocorrelation):
            y=autocorrelation[period-1:period+2]
            denominator=y[0]-2*y[1]+y[2]
            offset=.5*(y[0]-y[2])/denominator if denominator else 0
        else: offset=0
        result.append(rate/(period+offset))
    return np.array(result)


def main():
    manifest = rows(OUT/'renders.csv')
    geometry_rows, region_rows, band_rows, attack_rows, synthetic_rows, bass_rows = [], [], [], [], [], []
    regions=dict(REGIONS)
    bass_region=next(r for r in rows(OUT/'audition.csv') if r['region']=='bass_sustain')
    regions['bass_sustain']=('bass',float(bass_region['input_begin']),
                            float(bass_region['input_end']))
    for item in manifest:
        source, speed_text, mode = item['source'], item['speed'], item['mode']
        speed = float(speed_text)
        key = f'{source}_{mode}_{speed_text.replace(".", "")}'
        input_file = (ROOT / f'results/phase32/input/{source}.wav'
                      if source in ('decay_noise','harmonic') else
                      ROOT / f'results/phase31/input/{source}.wav')
        rate, original = read(input_file)
        _, output = read(OUT/'raw'/f'{key}.wav')
        trace = {band: rows(OUT/'trace'/key/f'{band}.csv')
                 for band in ('low','mid','high')}
        for band, window in WINDOWS.items():
            frames, hmin, hmax, nonpositive, outside, minweight = geometry(trace[band], window)
            geometry_rows.append(dict(source=source,speed=speed_text,mode=mode,
                                      resolution=band,window=window,
                                      analysis_hop=window//8 if mode=='B' else window//4,
                                      frames=frames,hop_min=hmin,hop_max=hmax,
                                      hop_ge_window=outside,hop_nonpositive=nonpositive,
                                      min_hann2_weight_worst_gap=minweight))
        for region, (which, begin, end) in regions.items():
            if which != source: continue
            a,b = np.rint(mapped(trace['mid'], np.array([begin,end])*rate)).astype(int)
            section = output[a:b]
            envelope_error, correlation, expected_slope, observed_slope = expected_envelope(
                original,output,rate,speed,trace['mid'],begin,end)
            side_mid, lr_corr = stereo(section)
            freq = np.fft.rfftfreq(4096,1/rate)
            ipd,ild,valid = stereo_band(section,rate,(freq>=200)&(freq<6000))
            phases={f'{band}_{name}':value for band in ('low','mid','high')
                    for name,value in phase_summary(trace[band],begin,end,rate).items()}
            region_rows.append(dict(region=region,source=source,speed=speed_text,
                                    mode=mode,input_begin=begin,input_end=end,
                                    output_begin=int(a),output_end=int(b),
                                    rms=rms(section),side_mid=side_mid,
                                    lr_correlation=lr_corr,ipd_rms_rad=ipd,
                                    ild_db=ild,valid_stereo_bins=valid,
                                    input_mapped_envelope_error_db=envelope_error,
                                    input_mapped_envelope_correlation=correlation,
                                    input_decay_slope_db_s=expected_slope,
                                    output_decay_slope_db_s=observed_slope,
                                    short_spectral_variation=spectral_variation(section,rate,speed),
                                    **phases))
            if region in ('drums_tail','mix_busy','mix_quiet'):
                for band, selection in (('low',freq<250),
                                        ('mid',(freq>=250)&(freq<3500)),
                                        ('high',freq>=3500)):
                    band_error, band_spectral = band_diagnostic(
                        original,section,rate,trace['mid'],int(a),selection)
                    band_rows.append(dict(region=region,source=source,
                                          speed=speed_text,mode=mode,band=band,
                                          input_mapped_band_envelope_error_db=band_error,
                                          short_spectral_variation=band_spectral))
            if region=='drums_attack':
                onset=3.865
                center=mapped(trace['mid'],np.array([onset*rate]))[0]
                attack_rows.append(dict(source=source,speed=speed_text,mode=mode,
                                        input_onset=onset,output_center=center,
                                        **attack(output,rate,center)))
            if region=='bass_sustain':
                pitches=bass_pitch_frames(section,rate)
                changes=np.abs(np.diff(pitches))
                bass_rows.append(dict(source=source,speed=speed_text,mode=mode,
                                      valid_pitch_frames=len(pitches),
                                      median_pitch_hz=float(np.median(pitches)),
                                      adjacent_pitch_change_median_hz=float(np.median(changes)),
                                      adjacent_pitch_change_p90_hz=float(np.percentile(changes,90))))
        if source=='click':
            synthetic_rows.append(dict(source=source,speed=speed_text,mode=mode,
                                       **clicks(OUT/'raw'/f'{key}.wav',speed)))
        elif source=='harmonic':
            _,env=envelope(output,rate,round(100/speed))
            active=env[round(len(env)*.2):round(len(env)*.8)]
            synthetic_rows.append(dict(source=source,speed=speed_text,mode=mode,
                                       dominant_hz=harmonic_pitch(output,rate),
                                       envelope_range_db=float(20*np.log10(
                                           max(np.percentile(active,95),1e-12)/
                                           max(np.percentile(active,5),1e-12)))))
        elif source=='decay_noise':
            error,corr,in_slope,out_slope=expected_envelope(
                original,output,rate,speed,trace['mid'],.7,1.5)
            synthetic_rows.append(dict(source=source,speed=speed_text,mode=mode,
                                       input_mapped_tail_error_db=error,
                                       tail_envelope_correlation=corr,
                                       input_decay_slope_db_s=in_slope,
                                       output_decay_slope_db_s=out_slope))
        print(key, 'measured', flush=True)
    write(OUT/'geometry.csv',geometry_rows)
    write(OUT/'regions.csv',region_rows)
    write(OUT/'bands.csv',band_rows)
    write(OUT/'attacks.csv',attack_rows)
    write(OUT/'bass_pitch.csv',bass_rows)
    fields=list(dict.fromkeys(field for r in synthetic_rows for field in r))
    with (OUT/'synthetic.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n')
        writer.writeheader(); writer.writerows(synthetic_rows)


if __name__=='__main__': main()
