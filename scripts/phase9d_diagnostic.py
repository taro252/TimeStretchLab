#!/usr/bin/env python3
"""Phase 9D: fixed-tracker event-density, matched local A/B and blind clips."""
import csv
import math
import pathlib
import random
import shutil
import sys
import numpy as np

from phase9b_components import read,write,save
from phase9b_loudness import lufs
from phase9b_residual_metrics import frames,estimate_f0

ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'results/phase9d'
MANIFEST=ROOT/'results/phase9c/component_manifest.csv'
RATE=48000
RATIO=2.0
SELECT_WINDOW=2400       # 50 ms on the output timeline
METRIC_WINDOW=4800       # 100 ms on the output timeline
CLIP_HALF=14400          # 300 ms before/after selected center
SEPARATION=31200         # >=650 ms between chosen centers

def track_events(path,output_length):
    grouped={}
    with pathlib.Path(path).open() as file:
        for row in csv.DictReader(file):
            grouped.setdefault(int(row['trackId']),[]).append(
                (int(row['centerSample']),float(row['amplitude'])))
    births=[];deaths=[];short=[];ranges=[]
    for nodes in grouped.values():
        first,last=nodes[0][0],nodes[-1][0]
        birth=int(round(first*RATIO));death=int(round(last*RATIO))
        births.append(birth);deaths.append(death)
        if (last-first+512)/RATE<.060:short.append(birth)
        ranges.append((birth,death,max(amplitude for _,amplitude in nodes)))
    edges=np.arange(0,output_length+SELECT_WINDOW,SELECT_WINDOW)
    if edges[-1]<output_length:edges=np.append(edges,output_length)
    counts={key:np.histogram(values,bins=edges)[0] for key,values in
            (('births',births),('deaths',deaths),('short',short))}
    return grouped,ranges,edges,counts

def select_regions(audio,primary,ranges,edges,counts):
    centers=((edges[:-1]+edges[1:])/2).astype(int)
    valid=np.where((centers>=CLIP_HALF)&(centers+CLIP_HALF<len(audio)))[0]
    energy=np.array([np.sqrt(np.mean(audio[max(0,c-SELECT_WINDOW//2):
        min(len(audio),c+SELECT_WINDOW//2)]**2)) for c in centers])
    primary_energy=np.array([np.sqrt(np.mean(primary[max(0,c-SELECT_WINDOW//2):
        min(len(primary),c+SELECT_WINDOW//2)]**2)) for c in centers])
    active=np.array([sum(a<=c<=b
        for a,b,amplitude in ranges) for c in centers])
    churn=counts['births']+counts['deaths']+counts['short']
    level_floor=max(np.percentile(energy[valid],30),.03*np.max(energy[valid]))
    voiced=valid[(energy[valid]>=level_floor)&(active[valid]>=3)&
        (primary_energy[valid]/(energy[valid]+1e-9)>=.35)]
    if len(voiced)<10:raise RuntimeError('Too few voiced regions')
    target_count=min(5,max(2,int(len(voiced)*SELECT_WINDOW/(2*SEPARATION))))
    selected=[]
    def far(index):
        return all(abs(centers[index]-centers[old])>=SEPARATION for old in selected)
    # Choose dense events from audible, track-active material.
    high=sorted(voiced,key=lambda i:(-churn[i],-counts['short'][i],-energy[i]))
    for index in high:
        if far(index):selected.append(index)
        if len(selected)==target_count:break
    if len(selected)<target_count:raise RuntimeError('Too few independent dense regions')
    high_selected=selected.copy()
    target=np.median(energy[high_selected])
    # Controls have no nearby event and a sustained primary component.
    stable=[i for i in voiced if
        all(abs(centers[i]-centers[j])>=SEPARATION for j in high_selected)]
    stable.sort(key=lambda i:(churn[i],
                              abs(np.log((energy[i]+1e-9)/(target+1e-9))),
                              -active[i],-primary_energy[i]))
    for index in stable:
        if far(index):selected.append(index)
        if len(selected)==2*target_count:break
    if len(selected)<2*target_count:
        raise RuntimeError('Too few independent stable controls')
    return centers,energy,primary_energy,active,churn,high_selected,selected[target_count:]

def spectral_variation(signal,center,f0):
    start=center-METRIC_WINDOW//2
    segment=signal[start:start+METRIC_WINDOW]
    size=2048;hop=384
    window=np.hanning(size)
    spectrum=np.abs(np.fft.rfft(np.asarray([
        segment[i:i+size]*window for i in range(0,len(segment)-size+1,hop)])))
    frequencies=np.fft.rfftfreq(size,1/RATE)
    harmonic=[]
    for multiple in range(1,17):
        hz=multiple*f0
        if hz>4000:break
        index=int(round(hz*size/RATE))
        if index<2 or index+2>=spectrum.shape[1]:continue
        magnitude=np.max(spectrum[:,index-1:index+2],axis=1)
        if np.mean(magnitude)<1e-5:continue
        harmonic.append(np.std(20*np.log10(magnitude+1e-7)))
    harmonic_value=float(np.median(harmonic)) if harmonic else float('nan')
    smoothed=np.asarray([np.convolve(row,np.ones(11)/11,'same')
        for row in spectrum])
    band=(frequencies>=80)&(frequencies<=8000)
    log_envelope=np.log(smoothed[:,band]+1e-6)
    # Remove global gain; compare changes in spectral shape only.
    log_envelope-=log_envelope.mean(axis=1,keepdims=True)
    envelope_value=float(np.mean(np.sqrt(np.mean(
        np.diff(log_envelope,axis=0)**2,axis=1))))
    return harmonic_value,envelope_value

def correlation(x,y):
    a=np.asarray(x,float);b=np.asarray(y,float)
    valid=np.isfinite(a)&np.isfinite(b)
    a=a[valid];b=b[valid]
    if len(a)<3 or np.std(a)<1e-10 or np.std(b)<1e-10:return float('nan')
    return float(np.corrcoef(a,b)[0,1])

def rank_values(values):
    x=np.asarray(values,float)
    order=np.argsort(x,kind='stable');result=np.empty(len(x),float)
    result[order]=np.arange(len(x))
    unique,inverse,counts=np.unique(x,return_inverse=True,return_counts=True)
    if np.any(counts>1):
        for group in range(len(unique)):
            result[inverse==group]=np.mean(result[inverse==group])
    return result

def clip_match(name,kind,index,center,signals,event_row,rng):
    clip_dir=OUT/'clips'/name/f'{kind}_{index:02d}'
    blind_dir=OUT/'blind'/name/f'{kind}_{index:02d}'
    clip_dir.mkdir(parents=True,exist_ok=True)
    blind_dir.mkdir(parents=True,exist_ok=True)
    raw={key:signal[center-CLIP_HALF:center+CLIP_HALF].astype('<f4')
         for key,signal in signals.items()}
    for key,audio in raw.items():
        if len(audio)!=2*CLIP_HALF:raise RuntimeError('Clip length mismatch')
        write(clip_dir/f'{key}_raw.wav',audio)
    # Constant gain on a complete 600 ms clip. Component gain follows combined.
    input_lufs={key:lufs(clip_dir/f'{key}_raw.wav') for key in ('phase53','combined')}
    if not all(math.isfinite(value) for value in input_lufs.values()):
        raise RuntimeError(f'Unmeasurable local LUFS {name} {kind} {index}')
    target=min(input_lufs.values())
    gain={key:target-value for key,value in input_lufs.items()}
    pair={}
    for repeat in range(4):
        pair={key:raw[key]*10**(gain[key]/20) for key in ('phase53','combined')}
        for key,audio in pair.items():write(clip_dir/f'{key}.wav',audio)
        final={key:lufs(clip_dir/f'{key}.wav') for key in pair}
        correction={key:target-value for key,value in final.items()}
        if max(abs(value) for value in correction.values())<.025:break
        for key in gain:gain[key]+=correction[key]
    final_peak=max(float(np.max(np.abs(raw[key]*10**(gain[key]/20))))
        for key in ('phase53','combined'))
    common=20*np.log10(.85/final_peak) if final_peak>.85 else 0
    for key in gain:gain[key]+=common
    for key in ('phase53','primary','primary_tonal','combined'):
        amount=gain['phase53'] if key=='phase53' else gain['combined']
        write(clip_dir/f'{key}.wav',raw[key]*10**(amount/20))
    matched={key:lufs(clip_dir/f'{key}.wav') for key in ('phase53','combined')}
    gap=abs(matched['phase53']-matched['combined'])
    if gap>.1:raise RuntimeError(f'Local LUFS gap {name} {kind}: {gap}')
    labels=['A','B'];rng.shuffle(labels)
    phase53_label,phase9c_label=labels
    shutil.copyfile(clip_dir/'phase53.wav',blind_dir/f'{phase53_label}.wav')
    shutil.copyfile(clip_dir/'combined.wav',blind_dir/f'{phase9c_label}.wav')
    event_row.update({'phase53_file':str(clip_dir/'phase53.wav'),
        'phase9c_file':str(clip_dir/'combined.wav'),
        'primary_file':str(clip_dir/'primary.wav'),
        'primary_tonal_file':str(clip_dir/'primary_tonal.wav'),
        'phase53_original_lufs':input_lufs['phase53'],
        'phase9c_original_lufs':input_lufs['combined'],
        'phase53_gain_db':gain['phase53'],'phase9c_gain_db':gain['combined'],
        'phase53_matched_lufs':matched['phase53'],
        'phase9c_matched_lufs':matched['combined'],'lufs_gap':gap,
        'blind_A':str(blind_dir/'A.wav'),'blind_B':str(blind_dir/'B.wav')})
    key={'name':name,'region':kind,'rank':index,
         'blind_A_method':'Phase 5.3' if phase53_label=='A' else 'Phase 9C',
         'blind_B_method':'Phase 9C' if phase9c_label=='B' else 'Phase 5.3'}
    return key

def write_correlations(windows):
    aggregate=[]
    for name in sorted(set(row['name'] for row in windows)):
        all_windows=[row for row in windows if row['name']==name]
        maximum=max(float(row['output_rms_50ms']) for row in all_windows)
        voiced=[row for row in all_windows if
            float(row['output_rms_50ms'])>=.03*maximum and
            int(row['active_tracks'])>=3 and
            float(row['primary_rms_50ms'])/
                (float(row['output_rms_50ms'])+1e-9)>=.35]
        for scope,group in (('all',all_windows),('voiced',voiced)):
            churn=[float(row['churn_50ms']) for row in group]
            for metric in ('phase9c_harmonic_magnitude_variation_db',
                           'phase9c_spectral_envelope_variation',
                           'harmonic_variation_delta_db','envelope_variation_delta'):
                values=[float(row[metric]) for row in group]
                aggregate.append({'name':name,'scope':scope,'windows':len(group),
                    'metric':metric,'pearson_churn':correlation(churn,values),
                    'spearman_churn':correlation(rank_values(churn),rank_values(values)),
                    'high_median':float(np.nanmedian([float(row[metric]) for row in group
                        if row['selection']=='high'])),
                    'control_median':float(np.nanmedian([float(row[metric]) for row in group
                        if row['selection']=='control']))})
    save(OUT/'correlations.csv',aggregate)

def write_listening_sheet(regions):
    rows=[]
    for region in regions:
        for trial in range(1,4):
            rows.append({'name':region['name'],'region':region['region'],
                'rank':region['rank'],'trial':trial,
                'A_file':region['blind_A'],'B_file':region['blind_B'],
                'preferred_A_or_B':'','flutter_A':'','flutter_B':'',
                'robotic_A':'','robotic_B':'','buzz_A':'','buzz_B':'',
                'timbre_instability_A':'','timbre_instability_B':'','notes':''})
    save(OUT/'blind_listening_sheet.csv',rows)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with MANIFEST.open() as file:
        sources=[item for item in csv.DictReader(file)
                 if item['name'].startswith(('female','male')) and float(item['speed'])==.5]
    windows=[];regions=[];blind_keys=[];rng=random.Random(0x9d2026)
    for item in sources:
        name=item['name']
        signals={'phase53':read(item['phase53']).astype(np.float64),
                 'primary':read(item['primary']).astype(np.float64),
                 'primary_tonal':read(item['primary_and_tonal']).astype(np.float64),
                 'combined':read(item['combined']).astype(np.float64)}
        if len({len(value) for value in signals.values()})!=1:
            raise RuntimeError(f'Output length mismatch {name}')
        output_length=len(signals['combined'])
        _,ranges,edges,counts=track_events(item['track_csv'],output_length)
        centers,energy,primary_energy,active,churn,high,control=select_regions(
            signals['combined'],signals['primary'],ranges,edges,counts)
        # Input F0 is mapped to the shared output timeline for both methods.
        input_audio=read(item['input']).astype(np.float64)
        source_centers,source_power=frames(input_audio)
        source_f0=estimate_f0(source_centers,source_power)
        for index,center in enumerate(centers):
            if center<METRIC_WINDOW//2 or center+METRIC_WINDOW//2>=output_length:
                continue
            f0=float(np.interp(center/RATIO,source_centers,source_f0))
            h9,e9=spectral_variation(signals['combined'],center,f0)
            h5,e5=spectral_variation(signals['phase53'],center,f0)
            windows.append({'name':name,'output_center_sample':center,
                'output_second':center/RATE,'input_second':center/RATE/RATIO,
                'births_50ms':int(counts['births'][index]),
                'deaths_50ms':int(counts['deaths'][index]),
                'short_tracks_50ms':int(counts['short'][index]),
                'churn_50ms':int(churn[index]),
                'active_tracks':int(active[index]),
                'output_rms_50ms':float(energy[index]),
                'primary_rms_50ms':float(primary_energy[index]),
                'estimated_f0_hz':f0,
                'phase9c_harmonic_magnitude_variation_db':h9,
                'phase9c_spectral_envelope_variation':e9,
                'phase53_harmonic_magnitude_variation_db':h5,
                'phase53_spectral_envelope_variation':e5,
                'harmonic_variation_delta_db':h9-h5,
                'envelope_variation_delta':e9-e5,
                'selection':'high' if index in high else
                    ('control' if index in control else '')})
        for kind,chosen in (('high',high),('control',control)):
            for rank,index in enumerate(chosen,1):
                center=int(centers[index])
                event={'name':name,'region':kind,'rank':rank,
                    'output_center_sample':center,'output_second':center/RATE,
                    'input_second':center/RATE/RATIO,
                    'births_50ms':int(counts['births'][index]),
                    'deaths_50ms':int(counts['deaths'][index]),
                    'short_tracks_50ms':int(counts['short'][index]),
                    'churn_50ms':int(churn[index]),
                    'active_tracks':int(active[index]),
                    'output_rms_50ms':float(energy[index])}
                blind_keys.append(clip_match(name,kind,rank,center,signals,event,rng))
                regions.append(event)
        print(name,'high',[int(churn[i]) for i in high],
              'control',[int(churn[i]) for i in control],flush=True)
    save(OUT/'window_metrics.csv',windows)
    save(OUT/'selected_regions.csv',regions)
    save(OUT/'blind_key.csv',blind_keys)
    write_listening_sheet(regions)
    write_correlations(windows)
    print('maximum local LUFS gap',max(float(row['lufs_gap']) for row in regions))

if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='--correlations-only':
        with (OUT/'window_metrics.csv').open() as file:
            write_correlations(list(csv.DictReader(file)))
    elif len(sys.argv)==2 and sys.argv[1]=='--sheet-only':
        with (OUT/'selected_regions.csv').open() as file:
            write_listening_sheet(list(csv.DictReader(file)))
    elif len(sys.argv)==1:main()
    else:raise SystemExit('Usage: phase9d_diagnostic.py [--correlations-only|--sheet-only]')
