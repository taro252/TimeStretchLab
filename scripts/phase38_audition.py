#!/usr/bin/env python3
"""Fixed-gain, input-aligned blind A/B clips; never alter Phase 37 raw WAVs."""
import csv
import hashlib
import subprocess

import numpy as np

from phase32_study import read, wav
from phase37_study import ROOT, SOURCES
from phase38_burst_diagnostic import OUT, map_points

GAIN = np.float32(.45)
REGIONS = {
    'mix_busy': ('mix', 2.9, 4.2),
    'mix_quiet': ('mix', 4.2, 4.8),
    'drums_attack': ('drums', 3.77, 4.02),
    'drums_tail': ('drums', 4.05, 4.35),
    'vocal_consonant': ('vocal', 2.9, 3.2),
    'vocal_vowel': ('vocal', 3.2, 3.85),
    'guitar_pick': ('guitar', 3.75, 4.05),
    'guitar_sustain': ('guitar', 4.05, 4.35),
    'bass_attack': ('bass', 3.75, 4.05),
    'bass_sustain': ('bass', 4.05, 4.35),
    'white_noise_attack': ('white_burst', .58, .78),
    'pink_noise_attack': ('pink_burst', .58, .78),
}


def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1<<20),b''):
            result.update(block)
    return result.hexdigest()


def run_dense():
    source = ROOT / 'results/phase37/input/dense_click_025.wav'
    directory = OUT / 'raw'
    directory.mkdir(parents=True, exist_ok=True)
    rows=[]
    for speed in ('1.50','2.00'):
        for mode in 'AB':
            path = directory / f'dense_click_{mode}_{speed.replace(".", "")}.wav'
            result=subprocess.run((str(ROOT/'build/phase37_render'),str(source),
                str(path),speed,mode),capture_output=True,text=True,check=True)
            details=dict(line.split('=',1) for line in result.stdout.splitlines()
                         if '=' in line)
            rows.append(dict(sha256=digest(path),**details))
    with (OUT/'dense_renders.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0],lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


def main():
    (OUT/'audition').mkdir(parents=True,exist_ok=True)
    run_dense()
    rows=[]
    blind=[]
    for speed in ('1.50','2.00'):
        for region,(source,begin,end) in {
            **REGIONS,
            'mix_full': ('mix',0,10),
            'drums_full': ('drums',0,10),
            'dense_click': ('dense_click',0,8),
        }.items():
            key=int(hashlib.sha256(f'phase38-{region}-{speed}'.encode()).hexdigest(),16)
            assignment='AB' if key&1 else 'BA'
            for label,mode in zip('AB',assignment):
                input_path = (ROOT/'results/phase37/input/dense_click_025.wav'
                    if source=='dense_click' else SOURCES[source])
                raw = ((OUT/'raw') if source=='dense_click' else
                    (ROOT/'results/phase37/raw')) / f'{source}_{mode}_{speed.replace(".", "")}.wav'
                rate,audio=read(raw)
                if source=='dense_click':
                    a,b=0,len(audio)
                else:
                    x,y=map_points(input_path,speed,mode)
                    a,b=np.rint(np.interp(np.array([begin,end])*rate,x,y)).astype(int)
                    a=max(0,a);b=min(len(audio),b)
                clip=np.array(audio[a:b],copy=True)*GAIN
                # Playback-only edge ramp; none is applied to raw comparisons.
                fade=min(round(rate*.003),len(clip)//2)
                if fade:
                    shape=np.linspace(0,1,fade,dtype=np.float32)
                    clip[:fade]*=shape[:,None]
                    clip[-fade:]*=shape[::-1,None]
                if not len(clip) or np.max(np.abs(clip)) >= 1:
                    raise RuntimeError(f'Invalid audition clip: {region} {speed} {mode}')
                target=OUT/'audition'/f'{region}_{speed.replace(".", "")}_{label}.wav'
                wav(target,clip,rate)
                entry=dict(region=region,source=source,speed=speed,
                    input_begin_s=begin,input_end_s=end,blind_label=label,
                    mode=mode,gain=float(GAIN),edge_ramp_ms=3,output_begin=int(a),
                    output_end=int(b),frames=len(clip),peak=float(np.max(np.abs(clip))),
                    sha256=digest(target),path=str(target.relative_to(ROOT)))
                rows.append(entry)
                blind.append(dict(region=region,speed=speed,label=label,mode=mode))
    with (OUT/'audition_manifest.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0],lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    with (OUT/'blind_key.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=blind[0],lineterminator='\n')
        writer.writeheader();writer.writerows(blind)
    print(f'{len(rows)} fixed-gain blind clips')


if __name__ == '__main__':
    main()
