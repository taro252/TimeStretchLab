#!/usr/bin/env python3
"""Generate deterministic Phase 5.2 probes and measure all three paths."""
import csv
import pathlib
import subprocess
import numpy as np

RATE = 48000
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'results/phase52/artificial'
OUT.mkdir(parents=True, exist_ok=True)


def command(args, data=None):
    return subprocess.run(args, input=data, check=True, capture_output=True).stdout


def write(path, samples):
    command(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(RATE), '-ac', '1',
             '-i', '-', '-c:a', 'pcm_f32le', str(path)],
            np.asarray(samples, dtype='<f4').tobytes())


def read(path):
    raw = command(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'f32le', '-ac', '1', '-'])
    return np.frombuffer(raw, dtype='<f4').astype(np.float64)


def envelope(x, milliseconds=0.5):
    size = max(1, round(RATE * milliseconds / 1000))
    return np.sqrt(np.convolve(x*x, np.ones(size)/size, mode='same'))


def pitch(x, frequency):
    size, hop = 16384, 4096
    estimated, magnitudes = [], []
    for start in range(RATE, len(x)-size-RATE, hop):
        frame = x[start:start+size] * np.hanning(size)
        spectrum = np.abs(np.fft.rfft(frame))
        center = round(frequency*size/RATE)
        lo, hi = max(2, center-3), center+4
        k = lo + np.argmax(spectrum[lo:hi])
        a, b, c = np.log(np.maximum(spectrum[k-1:k+2], 1e-12))
        offset = np.clip(0.5*(a-c)/(a-2*b+c), -0.5, 0.5) if a-2*b+c else 0
        estimated.append((k+offset)*RATE/size)
        magnitudes.append(spectrum[k])
    f, m = np.asarray(estimated), np.asarray(magnitudes)
    return {'median_hz': float(np.median(f)),
            'frequency_mod_cents_sd': float(np.std(1200*np.log2(f/np.median(f)))),
            'magnitude_mod_cv': float(np.std(m)/np.mean(m))}


def harmonic(x):
    metrics = pitch(x, 110)
    segment = x[RATE:3*RATE]
    window = np.hanning(len(segment))
    spectrum = np.abs(np.fft.rfft(segment*window))
    frequencies = np.fft.rfftfreq(len(segment), 1/RATE)
    peaks = []
    for h in range(1, 6):
        keep = np.abs(frequencies-110*h) < 5
        peaks.append(np.max(spectrum[keep]))
    metrics['harmonic_db_vs_fundamental'] = ','.join(f'{20*np.log10(p/peaks[0]):.3f}' for p in peaks[1:])
    return metrics


def burst(x, speed, onset=0.5):
    ideal = round(onset*RATE/speed)
    env = envelope(x)
    search = env[max(0, ideal-round(.025*RATE)):ideal+round(.045*RATE)]
    start = max(0, ideal-round(.025*RATE))
    peak = start+int(np.argmax(search))
    level = env[peak]
    def first(threshold):
        idx = np.flatnonzero(env[max(0,ideal-round(.04*RATE)):peak+1] >= level*threshold)
        return max(0,ideal-round(.04*RATE))+int(idx[0]) if len(idx) else peak
    def decay(threshold):
        hits = np.flatnonzero(env[peak:peak+round(.15*RATE)] <= level*threshold)
        return float(hits[0]*1000/RATE) if len(hits) else float('nan')
    detected_onset=first(.1)
    pre = x[max(0,detected_onset-round(.02*RATE)):detected_onset]
    pre_ideal = x[max(0,ideal-round(.02*RATE)):ideal]
    early = x[ideal:ideal+round(.02*RATE)]
    return {'rise_10_90_ms': (first(.9)-first(.1))*1000/RATE,
            'time_to_peak_ms': (peak-first(.1))*1000/RATE,
            'peak_position_error_ms': (peak-ideal)*1000/RATE,
            'first20_energy': float(np.sum(early*early)),
            'pre_echo_energy': float(np.sum(pre*pre)),
            'pre_ideal_energy': float(np.sum(pre_ideal*pre_ideal)),
            'decay_3db_ms': decay(10**(-3/20)),
            'decay_10db_ms': decay(10**(-10/20))}


def cymbal(x, speed):
    metrics = burst(x, speed)
    begin = round(.55*RATE/speed)
    end = min(len(x), begin+round(.6*RATE))
    frame, step = round(.01*RATE), round(.005*RATE)
    rms = np.array([np.sqrt(np.mean(x[i:i+frame]**2))
                    for i in range(begin,end-frame,step)])
    if len(rms)>5:
        log = np.log(np.maximum(rms,1e-9))
        trend = np.polyval(np.polyfit(np.arange(len(log)),log,1),np.arange(len(log)))
        metrics['decay_envelope_mod_db_sd'] = float(np.std((log-trend)*20/np.log(10)))
    frame = x[begin:min(len(x),begin+round(.25*RATE))]
    if len(frame):
        spectrum = np.abs(np.fft.rfft(frame*np.hanning(len(frame))))**2
        frequencies = np.fft.rfftfreq(len(frame),1/RATE)
        high = spectrum[(frequencies>=3500)&(frequencies<=18000)]
        metrics['highband_peak_to_mean_db'] = float(10*np.log10(np.max(high)/np.mean(high)))
    return metrics


def main():
    rng = np.random.default_rng(5200)
    length = RATE*4
    t = np.arange(length)/RATE
    signals = {f'sine_{frequency:g}': .2*np.sin(2*np.pi*frequency*t)
               for frequency in (55,82.41,110)}
    signals['harmonic_bass'] = sum((.23/h)*np.sin(2*np.pi*110*h*t) for h in range(1,6))
    noise = rng.normal(size=length)
    short = np.zeros(length)
    position = RATE//2
    short[position:position+round(.004*RATE)] = (
        noise[position:position+round(.004*RATE)] *
        np.exp(-np.arange(round(.004*RATE))/45) * .45)
    signals['short_noise_burst'] = short
    long = np.zeros(length)
    spectrum = np.fft.rfft(noise)
    spectrum[np.fft.rfftfreq(length,1/RATE)<3500] = 0
    high = np.fft.irfft(spectrum,n=length)
    high /= np.max(np.abs(high))
    duration = round(.8*RATE)
    long[position:position+duration] = .6*high[position:position+duration]*np.exp(-np.arange(duration)/(RATE*.17))
    signals['decaying_high_noise'] = long
    rows=[]
    for name, samples in signals.items():
        source = OUT/f'{name}_input.wav'
        write(source,samples)
        for speed in (0.75,0.5):
            for mode in 'abc':
                output=OUT/f'{name}_{str(speed).replace(".", "")}_{mode}.wav'
                raw=command([str(ROOT/'build/timestretch'),str(source),str(output),
                    '--speed',str(speed),'--phase-locking','on','--transient','on',
                    '--adaptive-time-map','on','--precise-anchoring','on',
                    '--stereo-coherence','on','--multiresolution','on','--chunked','on',
                    '--ablation',mode]).decode().strip()
                fields=dict(item.split('=',1) for item in raw.split() if '=' in item)
                data=read(output)
                row={'signal':name,'speed':speed,'mode':mode,'output_frames':len(data),
                     'finite':bool(np.all(np.isfinite(data))),
                     'time_map_hash':fields['time_map_hash']}
                if name.startswith('sine_'):
                    row.update(pitch(data,float(name.split('_')[1])))
                elif name=='harmonic_bass': row.update(harmonic(data))
                elif name=='short_noise_burst': row.update(burst(data,speed))
                else: row.update(cymbal(data,speed))
                rows.append(row)
                print(name,speed,mode,row,flush=True)
    with (OUT/'metrics.csv').open('w',newline='') as file:
        fields=list(dict.fromkeys(key for row in rows for key in row))
        writer=csv.DictWriter(file,fieldnames=fields,lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    for name in signals:
        for speed in (0.75,0.5):
            group=[r for r in rows if r['signal']==name and r['speed']==speed]
            if len({r['time_map_hash'] for r in group})!=1 or \
               len({r['output_frames'] for r in group})!=1 or \
               not all(r['finite'] for r in group):
                raise AssertionError(f'A/B/C mismatch: {name} {speed}')


if __name__=='__main__': main()
