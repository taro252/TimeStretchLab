#!/usr/bin/env python3
"""Phase 9B component and track diagnostics; Phase 9A defaults stay untouched."""
import csv
import pathlib
import subprocess
import numpy as np

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase9b'
SOURCE=ROOT/'results/phase9a'
ENGINE=ROOT/'build/sinusoidal_residual_stretch'
RATE=48000

def run(command,**kwargs):
    return subprocess.run(command,check=True,capture_output=True,**kwargs)

def read(path):
    raw=run(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-']).stdout
    return np.frombuffer(raw,dtype='<f4').copy()

def write(path,audio):
    path.parent.mkdir(parents=True,exist_ok=True)
    run(['ffmpeg','-v','error','-y','-f','f32le','-ar',str(RATE),'-ac','1',
         '-i','-','-c:a','pcm_f32le',str(path)],input=np.asarray(audio,dtype='<f4').tobytes())

def save(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)

def tracks(path):
    groups={}
    with path.open() as file:
        for row in csv.DictReader(file):
            groups.setdefault(int(row['trackId']),[]).append(int(row['centerSample']))
    return groups

def lifetime_bin(milliseconds):
    if milliseconds<30:return '<30ms'
    if milliseconds<60:return '30-60ms'
    if milliseconds<120:return '60-120ms'
    if milliseconds<250:return '120-250ms'
    return '>250ms'

def snippets(name,components,groups,ratio):
    if not name.startswith(('female','male')) or ratio!=2:return []
    duration=len(read(components/'combined.wav'))
    margin=int(.05*RATE)
    rows=[]
    for kind,index in (('birth',0),('death',-1)):
        positions=np.array([round(nodes[index]*ratio) for nodes in groups.values()],dtype=int)
        positions=positions[(positions>margin)&(positions<duration-margin)]
        if len(positions)==0:continue
        # Find an interior event surrounded by the most track changes within 10 ms.
        counts=np.array([np.count_nonzero(np.abs(positions-p)<=int(.01*RATE))
                         for p in positions])
        point=int(positions[np.argmax(counts)])
        folder=OUT/'birth_death'/name
        outputs={}
        for component,filename in (('sinusoidal','sinusoidal_output.wav'),
                                   ('residual','residual_output.wav'),
                                   ('combined','combined.wav')):
            signal=read(components/filename)
            destination=folder/f'{kind}_{component}.wav'
            write(destination,signal[point-margin:point+margin])
            outputs[component]=str(destination)
        rows.append({'name':name,'event':kind,'output_sample':point,
                     'output_second':point/RATE,'events_within_10ms':int(counts.max()),
                     **outputs})
    return rows

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with (SOURCE/'manifest.csv').open() as file:manifest=list(csv.DictReader(file))
    rows=[];hist=[];cuts=[]
    for row in manifest:
        name=row['name'];speed=float(row['speed']);code='075' if speed==.75 else '050'
        ratio=1/speed
        folder=OUT/'components'/f'{name}_{code}'
        folder.mkdir(parents=True,exist_ok=True)
        combined=folder/'combined.wav'
        run([str(ENGINE),row['input'],str(combined),'--speed',str(speed),
             '--diagnostics',str(folder)])
        exact=combined.read_bytes()==pathlib.Path(row['phase9a']).read_bytes()
        if not exact:raise RuntimeError(f'Phase 9A default changed: {name} {speed}')
        optional={}
        if name in ('pure_vowel','breathy_vowel','female_1','male_1'):
            phaseFolder=OUT/'phase_variants'/f'{name}_{code}'
            phaseFolder.mkdir(parents=True,exist_ok=True)
            phaseCombined=phaseFolder/'combined.wav'
            run([str(ENGINE),row['input'],str(phaseCombined),'--speed',str(speed),
                 '--residual-phase','analysis','--diagnostics',str(phaseFolder)])
            optional={'analysis_phase_combined':str(phaseCombined),
                      'analysis_phase_residual':str(phaseFolder/'residual_output.wav')}
        groups=tracks(folder/'tracks.csv')
        rows.append({'name':name,'speed':speed,'input':row['input'],
                     'phase53':row['phase53'],'phase9a_original':row['phase9a'],
                     'random_combined':str(combined),
                     'sinusoidal_output':str(folder/'sinusoidal_output.wav'),
                     'random_residual':str(folder/'residual_output.wav'),
                     'sinusoidal_input':str(folder/'sinusoidal_input.wav'),
                     'residual_input':str(folder/'residual_input.wav'),
                     'track_csv':str(folder/'tracks.csv'),'default_exact':int(exact),
                     **optional})
        if name.startswith(('female','male')) and speed==.5:
            lifetimes=[(nodes[-1]-nodes[0]+512)/RATE*1000 for nodes in groups.values()]
            counts={key:sum(lifetime_bin(t)==key for t in lifetimes)
                    for key in ('<30ms','30-60ms','60-120ms','120-250ms','>250ms')}
            hist.append({'name':name,'tracks':len(groups),
                         'median_lifetime_ms':float(np.median(lifetimes)),
                         'births_per_second':len(groups)/10,
                         'deaths_per_second':len(groups)/10,**counts})
            cuts.extend(snippets(name,folder,groups,ratio))
        print(name,code,'exact',exact,flush=True)
    save(OUT/'component_manifest.csv',rows)
    save(OUT/'track_lifetimes.csv',hist)
    save(OUT/'birth_death_clips.csv',cuts)

if __name__=='__main__':main()
