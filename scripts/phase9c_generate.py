#!/usr/bin/env python3
"""Generate Phase 9C components, tonal metrics and three-way matched A/B/C."""
import csv
import math
import pathlib
import subprocess
import sys
import numpy as np

import phase9b_loudness as loud
import phase9b_residual_metrics as spectral
from phase9b_components import tracks,lifetime_bin

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase9c'
MANIFEST=ROOT/'results/phase9a/manifest.csv'
ENGINE=ROOT/'build/tonal_residual_stretch'

def save(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)

def rms(signal):
    return float(np.sqrt(np.mean(np.asarray(signal,dtype=np.float64)**2)))

def harmonic_variation(signal,source_centers,source_f0,ratio,name):
    centers,power=spectral.frames(signal)
    if name.startswith(('pure_vowel','breathy_vowel')):
        f0=165*np.exp2(16*np.sin(2*np.pi*5.5*centers/48000/ratio)/1200)
    else:
        f0=np.interp(centers/ratio,source_centers,source_f0)
    values=[]
    for frame,frequency in zip(power,f0):
        total=float(frame[spectral.BAND].sum())
        if total<1e-9:continue
        band=np.zeros(len(frame),bool)
        for harmonic in range(1,int(8000/frequency)+1):
            lo=max(1,int(np.floor((harmonic*frequency-12)*spectral.SIZE/48000)))
            hi=min(len(frame),int(np.ceil((harmonic*frequency+12)*spectral.SIZE/48000))+1)
            band[lo:hi]=True
        values.append(float(frame[band&spectral.BAND].sum()/total))
    return float(np.std(values)) if values else 0

def write_lifetimes(components):
    rows=[]
    for item in components:
        if not item['name'].startswith(('female','male')) or float(item['speed'])!=.5:
            continue
        groups=tracks(pathlib.Path(item['track_csv']))
        times=[(nodes[-1]-nodes[0]+512)/48000*1000 for nodes in groups.values()]
        counts={key:sum(lifetime_bin(value)==key for value in times)
            for key in ('<30ms','30-60ms','60-120ms','120-250ms','>250ms')}
        rows.append({'name':item['name'],'tracks':len(groups),
            'median_lifetime_ms':float(np.median(times)),
            'births_per_second':len(groups)/10,
            'deaths_per_second':len(groups)/10,**counts})
    save(OUT/'track_lifetimes.csv',rows)

def write_energies(components):
    rows=[]
    for item in components:
        source_rms=rms(spectral.audio(item['input']))
        values={key:rms(spectral.audio(item[key])) for key in
            ('primary','tonal_input','noise_input','tonal_output','noise_output')}
        rows.append({'name':item['name'],'speed':item['speed'],
            'input_rms':source_rms,
            **{key+'_rms':value for key,value in values.items()},
            **{key+'_energy_over_input':(value/source_rms)**2 for key,value in values.items()}})
    save(OUT/'component_energy.csv',rows)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with MANIFEST.open() as file:manifest=list(csv.DictReader(file))
    components=[];metrics=[];levels=[];matched=[]
    for item in manifest:
        name=item['name'];speed=item['speed']
        code='075' if float(speed)==.75 else '050'
        ratio=1/float(speed)
        folder=OUT/'components'/f'{name}_{code}'
        folder.mkdir(parents=True,exist_ok=True)
        combined=folder/'combined.wav'
        process=subprocess.run([str(ENGINE),item['input'],str(combined),
            '--speed',speed,'--diagnostics',str(folder)],capture_output=True,
            text=True,check=True)
        detail=dict(pair.split('=',1) for pair in process.stdout.split())
        paths={'primary':folder/'primary.wav',
               'tonal_input':folder/'tonal_input.wav',
               'noise_input':folder/'noise_input.wav',
               'tonal_output':folder/'tonal_output.wav',
               'noise_output':folder/'noise_output.wav',
               'primary_and_tonal':folder/'primary_and_tonal.wav',
               'combined':combined}
        source=spectral.audio(item['input'])
        source_rms=rms(source)
        source_centers,power=spectral.frames(source)
        source_f0=(spectral.estimate_f0(source_centers,power)
            if not name.startswith(('pure_vowel','breathy_vowel'))
            else np.zeros(len(source_centers)))
        data={key:spectral.audio(path) for key,path in paths.items()}
        if any(not np.isfinite(value).all() for value in data.values()):
            raise RuntimeError(f'Nonfinite component {name} {speed}')
        if len(data['combined'])!=round(len(source)*ratio):
            raise RuntimeError(f'Duration mismatch {name} {speed}')
        if not np.allclose(data['combined'],data['primary']+
            data['tonal_output']+data['noise_output'],atol=1e-5,rtol=0):
            raise RuntimeError(f'Component sum mismatch {name} {speed}')
        components.append({'name':name,'speed':speed,'input':item['input'],
            'phase53':item['phase53'],'phase9a':item['phase9a'],
            **{key:str(path) for key,path in paths.items()},
            'track_csv':str(folder/'tracks.csv'),**detail})
        for component in ('tonal_input','noise_input','tonal_output','noise_output'):
            component_ratio=1 if component.endswith('_input') else ratio
            value=spectral.metric(data[component],source_centers,source_f0,
                component_ratio,name,source_rms)
            metrics.append({'name':name,'speed':speed,'component':component,
                'file':str(paths[component]),'source_rms':source_rms,
                'primary_rms':rms(data['primary']),
                'harmonic_variation_std':harmonic_variation(data[component],
                    source_centers,source_f0,component_ratio,name),**value})
        originals={'phase53':pathlib.Path(item['phase53']),
                   'phase9a':pathlib.Path(item['phase9a']),
                   'phase9c':combined}
        original={key:loud.metrics(path) for key,path in originals.items()}
        if len({value['frames'] for value in original.values()})!=1:
            raise RuntimeError(f'Three-way length mismatch {name} {speed}')
        target=min(value['integrated_lufs'] for value in original.values())
        gain={};files={};measured={}
        for mode,path in originals.items():
            destination=OUT/'matched_lufs'/f'{name}_{code}_{mode}.wav'
            adjustment=target-original[mode]['integrated_lufs']
            for attempt in range(4):
                loud.gain_copy(path,destination,adjustment)
                value=loud.metrics(destination)
                correction=target-value['integrated_lufs']
                if abs(correction)<0.025:break
                adjustment+=correction
            gain[mode]=adjustment;files[mode]=destination;measured[mode]=value
        maximum=max(value['peak'] for value in measured.values())
        common=20*math.log10(0.85/maximum) if maximum>0.85 else 0
        if common:
            for mode,path in originals.items():
                gain[mode]+=common
                loud.gain_copy(path,files[mode],gain[mode])
                measured[mode]=loud.metrics(files[mode])
        spread=max(value['integrated_lufs'] for value in measured.values())-\
               min(value['integrated_lufs'] for value in measured.values())
        if spread>0.1:raise RuntimeError(f'LUFS mismatch {name} {speed}: {spread}')
        for mode,path in originals.items():
            levels.append({'name':name,'speed':speed,'mode':mode,
                'original_file':str(path),
                'original_rms':original[mode]['rms'],
                'original_peak':original[mode]['peak'],
                'original_lufs':original[mode]['integrated_lufs'],
                'applied_gain_db':gain[mode],
                'common_safety_gain_db':common,
                'matched_file':str(files[mode]),
                'matched_rms':measured[mode]['rms'],
                'matched_peak':measured[mode]['peak'],
                'matched_lufs':measured[mode]['integrated_lufs']})
        matched.append({'name':name,'speed':speed,
            **{mode:str(path) for mode,path in files.items()},
            'lufs_spread':spread})
        print(name,code,'noise/input',rms(data['noise_input'])/source_rms,
              'LUFS spread',spread,flush=True)
    save(OUT/'component_manifest.csv',components)
    save(OUT/'residual_metrics.csv',metrics)
    save(OUT/'loudness.csv',levels)
    save(OUT/'matched_triples.csv',matched)
    write_lifetimes(components)
    write_energies(components)

if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='--tracks-only':
        with (OUT/'component_manifest.csv').open() as file:
            write_lifetimes(list(csv.DictReader(file)))
    elif len(sys.argv)==2 and sys.argv[1]=='--energies-only':
        with (OUT/'component_manifest.csv').open() as file:
            write_energies(list(csv.DictReader(file)))
    elif len(sys.argv)==1:main()
    else:raise SystemExit('Usage: phase9c_generate.py [--tracks-only|--energies-only]')
