#!/usr/bin/env python3
"""Make listening copies with pairwise RMS or BS.1770 integrated-LUFS matching."""
import csv
import json
import math
import pathlib
import re
import subprocess
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase9b'
SOURCE=ROOT/'results/phase9a/manifest.csv'

def run(command):
    return subprocess.run(command,capture_output=True,text=False,check=True)

def samples(path):
    raw=run(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-']).stdout
    return np.frombuffer(raw,dtype='<f4')

def lufs(path):
    result=run(['ffmpeg','-hide_banner','-nostats','-i',str(path),'-af',
                'loudnorm=I=-23:TP=-1:LRA=11:print_format=json','-f','null','-'])
    log=result.stderr.decode(errors='replace')
    match=re.search(r'\{\s*"input_i"\s*:.*?\}',log,re.S)
    if match is None:raise RuntimeError(f'No loudness result for {path}')
    value=float(json.loads(match.group())['input_i'])
    if not math.isfinite(value):raise RuntimeError(f'Invalid LUFS for {path}')
    return value

def metrics(path):
    x=samples(path).astype(np.float64)
    if len(x)==0 or not np.isfinite(x).all():
        raise RuntimeError(f'Empty or nonfinite audio: {path}')
    return {'rms':float(np.sqrt(np.mean(x*x))),
            'peak':float(np.max(np.abs(x))),
            'integrated_lufs':lufs(path),'frames':len(x)}

def gain_copy(source,destination,gain_db):
    destination.parent.mkdir(parents=True,exist_ok=True)
    run(['ffmpeg','-v','error','-y','-i',str(source),'-af',
         f'volume={gain_db:.12f}dB','-c:a','pcm_f32le',str(destination)])

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with SOURCE.open() as file:manifest=list(csv.DictReader(file))
    rows=[];pairs=[]
    for item in manifest:
        name=item['name'];speed=item['speed'];code='075' if float(speed)==.75 else '050'
        originals={'phase53':pathlib.Path(item['phase53']),
                   'phase9a':pathlib.Path(item['phase9a'])}
        original={mode:metrics(path) for mode,path in originals.items()}
        if original['phase53']['frames']!=original['phase9a']['frames']:
            raise RuntimeError(f'Length mismatch {name} {speed}')
        for matching in ('rms','lufs'):
            key='rms' if matching=='rms' else 'integrated_lufs'
            target=min(original[mode][key] for mode in originals)
            files={};final={};gains={}
            for mode,path in originals.items():
                destination=OUT/'matched'/matching/f'{name}_{code}_{mode}.wav'
                if matching=='rms':
                    gain=20*math.log10(target/original[mode]['rms'])
                else:
                    gain=target-original[mode]['integrated_lufs']
                for attempt in range(3):
                    gain_copy(path,destination,gain)
                    measured=metrics(destination)
                    correction=(target-measured['integrated_lufs']) if matching=='lufs' \
                        else 20*math.log10(target/measured['rms'])
                    if abs(correction)<0.025:break
                    gain+=correction
                files[mode]=str(destination);final[mode]=measured;gains[mode]=gain
            # Apply a common post-match attenuation to avoid playback clipping
            # of float WAV peaks above full scale. Pairwise differences stay put.
            maximum=max(final[mode]['peak'] for mode in originals)
            common_gain=20*math.log10(0.85/maximum) if maximum>0.85 else 0.0
            if common_gain:
                for mode,path in originals.items():
                    gains[mode]+=common_gain
                    gain_copy(path,pathlib.Path(files[mode]),gains[mode])
                    final[mode]=metrics(files[mode])
            effective_target=(target*10**(common_gain/20) if matching=='rms'
                              else target+common_gain)
            for mode,path in originals.items():
                measured=final[mode]
                rows.append({'name':name,'speed':speed,'mode':mode,'match_type':matching,
                    'source':str(path),'original_rms':original[mode]['rms'],
                    'original_peak':original[mode]['peak'],
                    'original_integrated_lufs':original[mode]['integrated_lufs'],
                    'target':effective_target,'applied_gain_db':gains[mode],
                    'common_peak_safety_gain_db':common_gain,
                    'matched_file':files[mode],
                    'matched_rms':measured['rms'],'matched_peak':measured['peak'],
                    'matched_integrated_lufs':measured['integrated_lufs'],
                    'frames':measured['frames']})
            difference=abs(final['phase53']['integrated_lufs']-
                           final['phase9a']['integrated_lufs'])
            if matching=='lufs' and difference>0.1:
                raise RuntimeError(f'LUFS mismatch {name} {speed}: {difference}')
            pairs.append({'name':name,'speed':speed,'match_type':matching,
                'phase53':files['phase53'],'phase9a':files['phase9a'],
                'lufs_difference':difference,
                'rms_difference_db':20*math.log10(final['phase53']['rms']/
                                                 final['phase9a']['rms'])})
        print(name,code,'RMS/LUFS ready',flush=True)
    with (OUT/'loudness.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    with (OUT/'matched_pairs.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=pairs[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(pairs)

if __name__=='__main__':main()
