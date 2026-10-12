#!/usr/bin/env python3
"""Phase 35 isolated WAV comparison; the frozen DSP and Golden files are read-only."""
import argparse
import csv
import hashlib
import math
from pathlib import Path
import subprocess
import time

import numpy as np

from phase32_study import read, wav
from phase32_metrics import envelope, stereo
from phase34_metrics import attack, geometry, mapped, spectral_variation
from phase33_analysis import stereo_band

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/phase35/variable_hop'
BIN = ROOT / 'build/phase35_render'
SOURCES = ('mix', 'drums', 'vocal', 'bass', 'guitar', 'click',
           'harmonic', 'decay_noise')
PAIRS = (('0.40', '0.50'), ('0.50', '0.40'),
         ('0.45', '0.50'), ('0.50', '0.45'),
         ('0.49', '0.50'), ('0.50', '0.49'))
REGIONS = {'mix': (2.6, 5.0), 'drums': (3.4, 4.6),
           'vocal': (2.8, 4.3), 'bass': (2.5, 4.2),
           'guitar': (2.7, 4.5)}


def source(name):
    sub = 'phase32' if name in ('harmonic', 'decay_noise') else 'phase31'
    return ROOT / f'results/{sub}/input/{name}.wav'


def records(path):
    with path.open(newline='') as file:
        return list(csv.DictReader(file))


def table(path, rows):
    if not rows:
        raise ValueError(f'No table rows: {path}')
    with path.open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys(), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name, initial, changes, *, block=16384, tag=None):
    tag = tag or name + '_' + initial.replace('.', '') + '_' + '_'.join(
        target.replace('.', '') for _, target in changes)
    rate, input_audio = read(source(name))
    stem = OUT / 'trace' / tag
    schedule = stem.with_suffix('.schedule.csv')
    schedule.write_text('input_sample,target_speed\n' + ''.join(
        f'{round(seconds*rate)},{target}\n' for seconds, target in changes))
    output = OUT / 'raw' / (tag + '.wav')
    started = time.monotonic()
    result = subprocess.run((BIN, source(name), output, initial, schedule, stem, str(block)),
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f'{tag}: {result.stderr}')
    details = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    details['wall_seconds'] = f'{time.monotonic()-started:.6f}'
    details['input_frames'] = len(input_audio)
    details['rate'] = rate
    return output, details, stem


def frame_metrics(stem):
    rows = records(stem.with_suffix('.frames.csv'))
    stats = {}
    for fft in (8192, 4096, 1024):
        selected = [r for r in rows if int(r['fft']) == fft]
        hops = sorted({int(r['analysis_hop']) for r in selected})
        g = geometry([{'outputSample': r['output_sample']} for r in selected], fft)
        stats[str(fft)] = dict(frames=len(selected), analysis_hops='/'.join(map(str, hops)),
                               synthesis_min=g[1], synthesis_max=g[2],
                               nonpositive=g[3], hop_outside_window=g[4],
                               worst_gap_hann2_weight=g[5],
                               resets=sum(int(r['reset']) for r in selected))
    return rows, stats


def first_difference(left, right):
    n = min(len(left), len(right))
    differences = np.flatnonzero(left[:n].view('u4') != right[:n].view('u4'))
    return int(differences[0]//left.shape[1]) if len(differences) else n//left.shape[1]


def middle_trace(rows):
    return [{'inputSample': row['input_sample'], 'outputSample': row['output_sample']}
            for row in rows if int(row['fft']) == 4096]


def output_metrics(name, path, stem, initial):
    rate, audio = read(path)
    if not np.isfinite(audio).all():
        raise RuntimeError(f'Non-finite output: {path}')
    if len(audio)==0:
        raise RuntimeError('Zero output')
    trace, stages = frame_metrics(stem)
    if any(s['nonpositive'] or s['hop_outside_window'] or s['worst_gap_hann2_weight']<=1e-5
           for s in stages.values()):
        raise RuntimeError(f'Unsafe geometry: {path}')
    plans = records(stem.with_suffix('.plans.csv'))
    published = int(plans[0]['published_output'])
    fixed_name = f'{name}_{"B" if float(initial)<.50 else "A"}_{initial.replace(".", "")}.wav'
    fixed = ROOT / 'results/phase34/raw' / fixed_name
    _, base = read(fixed)
    if not np.array_equal(audio[:published], base[:published]):
        raise RuntimeError(f'Published PCM changed: {path}')
    first = first_difference(audio, base)
    start = int(plans[0]['applied_output'])
    window = audio[max(0,start-rate//4):min(len(audio),start+rate//4)]
    mono = np.mean(window, axis=1)
    derivative = np.abs(np.diff(mono))
    side_mid, correlation = stereo(window)
    frequency=np.fft.rfftfreq(4096,1/rate)
    ipd,ild,valid_bins=stereo_band(window,rate,(frequency>=200)&(frequency<6000))
    max_run = 0
    if name in ('mix','drums','vocal','bass','guitar'):
        silent = np.all(np.abs(window)<1e-8, axis=1)
        boundaries = np.flatnonzero(np.diff(np.r_[False,silent,False]))
        max_run = int(np.max(boundaries[1::2]-boundaries[::2],initial=0))
    mid = middle_trace(trace)
    attack_result = attack(audio,rate,mapped(mid,np.array([3.865*rate]))[0]) if name=='drums' else None
    region_variation=''
    tail_error=''
    if name in ('mix','drums'):
        begin,end=(4.05,4.35) if name=='drums' else (2.9,4.2)
        a,b=np.rint(mapped(mid,np.array([begin,end])*rate)).astype(int)
        region_variation=spectral_variation(audio[a:b],rate,float(initial))
        if name=='drums':
            _,original=read(source(name))
            source_t,source_e=envelope(original,rate,10)
            output_t,output_e=envelope(audio,rate,10)
            x=np.array([float(r['inputSample']) for r in mid])
            y=np.array([float(r['outputSample']) for r in mid])
            input_t=np.interp(output_t*rate,y,x)/rate
            mask=(input_t>=begin)&(input_t<=end)
            expected=np.interp(input_t[mask],source_t,source_e)
            actual=output_e[mask]
            valid=expected>max(float(np.max(expected,initial=0))*.005,1e-8)
            if np.count_nonzero(valid)>=8:
                difference=(20*np.log10(np.maximum(actual[valid],1e-10)) -
                            20*np.log10(expected[valid]))
                tail_error=float(np.std(difference-np.median(difference)))
    return dict(published_prefix_equal=True,first_changed_frame=first,
                first_change_after_published=first-published,
                peak=float(np.max(np.abs(audio))),
                transition_max_derivative=float(np.max(derivative,initial=0)),
                transition_p99_derivative=float(np.percentile(derivative,99)),
                transition_side_mid=side_mid,transition_lr_correlation=correlation,
                transition_ipd_rms_rad=ipd,transition_ild_db=ild,
                transition_stereo_valid_bins=valid_bins,
                transition_spectral_variation=spectral_variation(window,rate,float(initial)),
                near_zero_run_frames=max_run,
                drums_attack_peak=attack_result['peak'] if attack_result else '',
                drums_attack_offset_ms=attack_result['peak_offset_ms'] if attack_result else '',
                drums_attack_width_ms=attack_result['envelope_halfpower_width_ms'] if attack_result else '',
                region_spectral_variation=region_variation,
                drums_tail_envelope_error_db=tail_error), stages


def transitions():
    rows, geometry_rows = [], []
    for name in SOURCES:
        for initial,target in PAIRS:
            tag=f'{name}_{initial.replace(".", "")}_to_{target.replace(".", "")}'
            output, details, stem = run(name,initial,[(3.0,target)],tag=tag)
            _,audio=read(output)
            if len(audio)!=int(details['output_frames']):
                raise RuntimeError(f'Incorrect EOS length: {tag}')
            metrics, stages = output_metrics(name,output,stem,initial)
            plans = records(stem.with_suffix('.plans.csv'))
            row=dict(source=name,initial=initial,target=target,request_input_seconds=3.0,
                     output_frames=details['output_frames'],map_hash=details['map_hash'],
                     output_sha256=sha(output),wall_seconds=details['wall_seconds'],
                     user_cpu_seconds=details['user_cpu_seconds'],
                     system_cpu_seconds=details['system_cpu_seconds'],
                     peak_rss_bytes=details['peak_rss_bytes'],
                     **plans[0],**metrics)
            rows.append(row)
            for fft,stat in stages.items():
                geometry_rows.append(dict(source=name,initial=initial,target=target,
                                          fft=fft,**stat))
            print('transition',tag,'first_changed',metrics['first_changed_frame'],flush=True)
    table(OUT/'transitions.csv',rows)
    table(OUT/'geometry.csv',geometry_rows)
    extras=[]
    for name,initial,changes in (
        ('mix','0.40',[(2.0,'0.60'),(6.0,'0.45')]),
        ('drums','0.50',[(2.0,'0.40'),(6.0,'0.50')]),
        ('drums','0.40',[(3.55,'0.50')]),
        ('drums','0.50',[(3.77,'0.40')]),
        ('drums','0.40',[(4.15,'0.50')]),
    ):
        tag=f'{name}_extra_{len(extras)}'
        output,details,stem=run(name,initial,changes,tag=tag)
        trace,stages=frame_metrics(stem)
        _,audio=read(output)
        if not np.isfinite(audio).all() or any(x['hop_outside_window'] for x in stages.values()):
            raise RuntimeError(f'Extra case unsafe: {tag}')
        second_prefix=''
        if len(changes)>1:
            prior,_,_=run(name,initial,changes[:1],tag=tag+'_first_only')
            _,prior_audio=read(prior)
            second_published=int(records(stem.with_suffix('.plans.csv'))[1]['published_output'])
            second_prefix=np.array_equal(audio[:second_published],prior_audio[:second_published])
            if not second_prefix:
                raise RuntimeError(f'Second change rewrote published PCM: {tag}')
        extras.append(dict(source=name,initial=initial,changes=';'.join(
            f'{at}:{speed}' for at,speed in changes),output_frames=len(audio),
            sha256=sha(output),peak=float(np.max(np.abs(audio))),
            wall_seconds=details['wall_seconds'],
            user_cpu_seconds=details['user_cpu_seconds'],
            system_cpu_seconds=details['system_cpu_seconds'],
            peak_rss_bytes=details['peak_rss_bytes'],
            second_published_prefix_equal=second_prefix,
            applied_frames=';'.join(r['applied_frame'] for r in records(stem.with_suffix('.plans.csv')))))
    table(OUT/'multiple_and_attack.csv',extras)
    for name, initial, target in (('mix','0.40','0.50'),('drums','0.50','0.40')):
        original=OUT/'raw'/f'{name}_{initial.replace(".", "")}_to_{target.replace(".", "")}.wav'
        repeat,_,_=run(name,initial,[(3.0,target)],block=8192,tag=f'{name}_partition')
        if original.read_bytes()!=repeat.read_bytes():
            raise RuntimeError('Output depends on chunk size')
    first=OUT/'raw/mix_040_to_050.wav'
    duplicate,_,_=run('mix','0.40',[(3.0,'0.50')],tag='mix_repeated')
    if first.read_bytes()!=duplicate.read_bytes():
        raise RuntimeError('Same history is not reproducible')


def metrics_only():
    rows=records(OUT/'transitions.csv')
    for row in rows:
        name,initial,target=row['source'],row['initial'],row['target']
        tag=f'{name}_{initial.replace(".", "")}_to_{target.replace(".", "")}'
        measurements,_=output_metrics(name,OUT/'raw'/f'{tag}.wav',OUT/'trace'/tag,initial)
        row.pop('transition_ild_rms_db',None)
        row.update(measurements)
    table(OUT/'transitions.csv',rows)


def audition():
    manifest=[]
    for name,(begin,end) in REGIONS.items():
        _,original=read(source(name))
        for initial,target in PAIRS:
            tag=f'{name}_{initial.replace(".", "")}_to_{target.replace(".", "")}'
            raw=OUT/'raw'/f'{tag}.wav'
            if not raw.exists(): raise RuntimeError(f'Missing raw: {tag}')
            rate,audio=read(raw)
            trace=middle_trace(records((OUT/'trace'/tag).with_suffix('.frames.csv')))
            bounds=np.rint(mapped(trace,np.array([begin,end])*rate)).astype(int)
            clip=np.array(audio[bounds[0]:bounds[1]],dtype='<f4',copy=True)
            clip*=np.float32(.5)
            edge=min(round(rate*.003),len(clip)//2)
            if edge:
                ramp=np.linspace(0,1,edge,dtype='<f4')[:,None]
                clip[:edge]*=ramp
                clip[-edge:]*=ramp[::-1]
            path=OUT/'audition'/f'{tag}.wav'
            wav(path,clip,rate)
            manifest.append(dict(source=name,initial=initial,target=target,
                                 input_begin=begin,input_end=end,output_begin=bounds[0],
                                 output_end=bounds[1],gain=.5,edge_fade_ms=3,
                                 peak=float(np.max(np.abs(clip))),sha256=sha(path),
                                 wav=str(path.relative_to(ROOT))))
        for speed in ('0.40','0.45','0.49','0.50'):
            mode='B' if float(speed)<.5 else 'A'
            key=f'{name}_{mode}_{speed.replace(".", "")}'
            rate,audio=read(ROOT/'results/phase34/raw'/f'{key}.wav')
            fixed_trace=records(ROOT/'results/phase34/trace'/key/'mid.csv')
            a,b=np.rint(mapped(fixed_trace,np.array([begin,end])*rate)).astype(int)
            clip=np.array(audio[a:b],dtype='<f4',copy=True)*np.float32(.5)
            edge=min(round(rate*.003),len(clip)//2)
            if edge:
                ramp=np.linspace(0,1,edge,dtype='<f4')[:,None]
                clip[:edge]*=ramp;clip[-edge:]*=ramp[::-1]
            path=OUT/'audition'/f'{name}_fixed_{speed.replace(".", "")}.wav'
            wav(path,clip,rate)
            manifest.append(dict(source=name,initial=speed,target='fixed',
                                 input_begin=begin,input_end=end,output_begin=a,
                                 output_end=b,gain=.5,edge_fade_ms=3,
                                 peak=float(np.max(np.abs(clip))),sha256=sha(path),
                                 wav=str(path.relative_to(ROOT))))
    table(OUT/'audition.csv',manifest)


def golden():
    references=records(ROOT/'results/phase12/golden/manifest.csv')+records(
        ROOT/'results/phase28/golden/manifest.csv')
    rows=[]
    for ref in references:
        speed=ref['speed']
        if speed not in ('0.50','0.60','0.70','0.75','0.80'): continue
        name=ref['name']
        input_path=ROOT/ref['input_path']
        output=OUT/'golden_check'/f'{name}_{speed.replace(".", "")}.wav'
        output.parent.mkdir(parents=True,exist_ok=True)
        schedule=OUT/'trace/empty.csv'
        schedule.write_text('input_sample,target_speed\n')
        result=subprocess.run((BIN,input_path,output,speed,schedule,
                               OUT/'trace'/f'golden_{name}_{speed.replace(".", "")}'),
                              capture_output=True,text=True,timeout=300)
        if result.returncode: raise RuntimeError(result.stderr)
        actual=sha(output)
        rows.append(dict(source=name,speed=speed,expected=ref['output_sha256'],
                         actual=actual,byte_identical=actual==ref['output_sha256']))
        print('golden',name,speed,actual==ref['output_sha256'],flush=True)
    if len(rows)!=25 or not all(r['byte_identical'] for r in rows):
        raise RuntimeError('Golden regression failed')
    table(OUT/'golden.csv',rows)


def fixed_b():
    rows=[]
    for name in SOURCES:
        for speed in ('0.40','0.45','0.49'):
            output,details,_=run(name,speed,[],tag=f'fixed_{name}_{speed.replace(".", "")}')
            prior=ROOT/'results/phase34/raw'/f'{name}_B_{speed.replace(".", "")}.wav'
            rows.append(dict(source=name,speed=speed,phase34_sha256=sha(prior),
                             phase35_sha256=sha(output),byte_identical=output.read_bytes()==prior.read_bytes(),
                             frames=details['output_frames']))
    if not all(row['byte_identical'] for row in rows):
        raise RuntimeError('Phase 34 B regression failed')
    table(OUT/'fixed_b.csv',rows)


def prototype_fixed():
    rows=[]
    schedule=OUT/'trace/empty.csv'
    schedule.write_text('input_sample,target_speed\n')
    for name in SOURCES:
        for speed in ('0.40','0.45','0.49','0.50'):
            key=f'{name}_{speed.replace(".", "")}'
            mode='B' if float(speed)<.5 else 'A'
            target=OUT/'raw'/f'{key}_prototype_fixed.wav'
            stem=OUT/'trace'/f'{key}_prototype_fixed'
            command=(BIN,source(name),target,speed,schedule,stem,
                     '16384','--prototype-fixed')
            result=subprocess.run(command,capture_output=True,text=True,timeout=300)
            if result.returncode: raise RuntimeError(result.stderr)
            reference=ROOT/'results/phase34/raw'/f'{name}_{mode}_{speed.replace(".", "")}.wav'
            equal=target.read_bytes()==reference.read_bytes()
            rows.append(dict(source=name,speed=speed,mode=mode,
                             reference_sha256=sha(reference),prototype_sha256=sha(target),
                             byte_identical=equal))
            print('prototype fixed',name,speed,equal,flush=True)
    table(OUT/'prototype_fixed.csv',rows)
    if not all(row['byte_identical'] for row in rows):
        raise RuntimeError('Variable-hop engine failed fixed-speed equivalence')


def density_only():
    binary=ROOT/'build/phase35_density_control'
    rows=[]
    for name in ('mix','drums','vocal'):
        rate,_=read(source(name))
        outputs={}
        for mode in ('A_to_B','B_to_A','B_only'):
            path=OUT/'raw'/f'{name}_density_{mode}.wav'
            result=subprocess.run((binary,source(name),path,mode,str(3*rate)),
                                  capture_output=True,text=True,timeout=300)
            if result.returncode: raise RuntimeError(result.stderr)
            _,outputs[mode]=read(path)
        _,outputs['A_only']=read(ROOT/'results/phase34/raw'/f'{name}_A_050.wav')
        for mode,reference in (('A_to_B','A_only'),('B_to_A','B_only')):
            audio=outputs[mode];base=outputs[reference]
            if len(audio)!=len(base) or not np.isfinite(audio).all():
                raise RuntimeError('Density control invalid output')
            first=first_difference(audio,base)
            region=audio[max(0,first-rate//10):min(len(audio),first+rate//10)]
            derivative=np.abs(np.diff(np.mean(region,axis=1)))
            side,correlation=stereo(region)
            rows.append(dict(source=name,mode=mode,reference=reference,
                             speed='0.50',time_map='unchanged',
                             first_changed_frame=first,
                             peak=float(np.max(np.abs(audio))),
                             local_max_derivative=float(np.max(derivative,initial=0)),
                             local_p99_derivative=float(np.percentile(derivative,99)),
                             local_side_mid=side,local_lr_correlation=correlation,
                             rms_difference=float(np.sqrt(np.mean((audio-base)**2))),
                             sha256=sha(OUT/'raw'/f'{name}_density_{mode}.wav')))
            a,b=round(2.5*rate*2),round(4.5*rate*2)
            clip=np.array(audio[a:b],dtype='<f4',copy=True)*np.float32(.5)
            wav(OUT/'audition'/f'{name}_density_{mode}.wav',clip,rate)
        a,b=round(2.5*rate*2),round(4.5*rate*2)
        for mode in ('A_only','B_only'):
            clip=np.array(outputs[mode][a:b],dtype='<f4',copy=True)*np.float32(.5)
            wav(OUT/'audition'/f'{name}_density_{mode}.wav',clip,rate)
    table(OUT/'density_only.csv',rows)


def phase():
    rows=[]
    for name in ('sine','harmonic'):
        for initial,target in (('0.40','0.50'),('0.50','0.40')):
            tag=f'{name}_phase_{initial.replace(".", "")}_{target.replace(".", "")}'
            output,details,stem=run(name,initial,[(3.0,target)],tag=tag)
            plans=records(stem.with_suffix('.plans.csv'))
            apply_input=int(plans[0]['applied_frame'])*1024
            frames=records(stem.with_suffix('.frames.csv'))
            for fft in (8192,4096,1024):
                selected=[f for f in frames if int(f['fft'])==fft]
                residual=[];near=[]
                resets=0
                for before,after in zip(selected,selected[1:]):
                    position=int(after['input_sample'])
                    if abs(position-apply_input)>50*1024: continue
                    if int(after['reset']): resets+=1;continue
                    if int(before['peak_bin'])!=int(after['peak_bin']): continue
                    if float(before['peak_magnitude'])<1e-6 or float(after['peak_magnitude'])<1e-6:
                        continue
                    k=int(after['peak_bin']);ha=int(after['analysis_hop']);hs=int(after['synthesis_hop'])
                    omega=2*math.pi*k/fft
                    input_delta=math.remainder(float(after['analysis_phase_rad'])-
                                               float(before['analysis_phase_rad'])-omega*ha,2*math.pi)
                    expected=omega+input_delta/ha
                    observed=math.remainder(float(after['synthesis_phase_rad'])-
                                            float(before['synthesis_phase_rad'])-expected*hs,2*math.pi)
                    residual.append(abs(observed))
                    if abs(position-apply_input)<2*1024: near.append(abs(observed))
                if not residual: raise RuntimeError(f'No phase tracking samples for {tag}/{fft}')
                rows.append(dict(source=name,initial=initial,target=target,fft=fft,
                                 stable_peak_frames=len(residual),reset_frames=resets,
                                 phase_residual_median_rad=float(np.median(residual)),
                                 phase_residual_p95_rad=float(np.percentile(residual,95)),
                                 phase_residual_max_rad=float(np.max(residual)),
                                 boundary_max_rad=float(np.max(near)) if near else '',
                                 wav_sha256=sha(output),map_hash=details['map_hash']))
    table(OUT/'phase_continuity.csv',rows)


def synthetic():
    rows=[]
    for name in ('click','harmonic','sine'):
        pairs=PAIRS if name=='click' else (('0.40','0.50'),('0.50','0.40'))
        for initial,target in pairs:
            tag=(f'{name}_{initial.replace(".", "")}_to_{target.replace(".", "")}'
                 if name=='click' else
                 f'{name}_phase_{initial.replace(".", "")}_{target.replace(".", "")}')
            rate,audio=read(OUT/'raw'/f'{tag}.wav')
            trace=middle_trace(records((OUT/'trace'/tag).with_suffix('.frames.csv')))
            row=dict(source=name,initial=initial,target=target,
                     output_frames=len(audio),sha256=sha(OUT/'raw'/f'{tag}.wav'))
            if name=='click':
                errors=[];peaks=[];widths=[];secondary=0;pre_echo=[]
                mono=np.mean(audio,axis=1)
                for event in range(12):
                    expected=mapped(trace,np.array([12000+24000*event]))[0]
                    lo=max(0,round(expected-rate*.08));hi=min(len(mono),round(expected+rate*.08))
                    found=lo+int(np.argmax(np.abs(mono[lo:hi])))
                    peak=abs(float(mono[found]));peaks.append(peak)
                    errors.append(1000*(found-expected)/rate)
                    left=right=found
                    while left>lo and abs(mono[left-1])>=peak*.5:left-=1
                    while right+1<hi and abs(mono[right+1])>=peak*.5:right+=1
                    widths.append(1000*(right-left+1)/rate)
                    region=np.abs(mono[lo:hi]);distant=np.abs(np.arange(lo,hi)-found)>rate*.005
                    if np.any(region[distant]>peak*.5):secondary+=1
                    a=max(0,round(expected-rate*.02));b=max(a,round(expected))
                    pre_echo.append(float(np.sqrt(np.mean(mono[a:b]**2))) if b>a else 0)
                row.update(max_attack_error_ms=max(map(abs,errors)),min_peak=min(peaks),
                           max_peak=max(peaks),mean_halfpeak_width_ms=float(np.mean(widths)),
                           events_with_secondary_peak=secondary,
                           mean_pre20ms_rms=float(np.mean(pre_echo)))
            else:
                expected=110 if name=='harmonic' else 437.3
                for label,begin,end in (('before',1.5,2.5),('after',4.0,5.0)):
                    a,b=np.rint(mapped(trace,np.array([begin,end])*rate)).astype(int)
                    mono=np.mean(audio[a:b],axis=1)
                    if name=='sine':
                        crossings=np.flatnonzero((mono[:-1]<=0)&(mono[1:]>0))
                        measured=(len(crossings)-1)*rate/(crossings[-1]-crossings[0])
                    else:
                        spectrum=np.abs(np.fft.rfft(mono*np.hanning(len(mono))))
                        freq=np.fft.rfftfreq(len(mono),1/rate)
                        candidates=np.flatnonzero((freq>expected*.9)&(freq<expected*1.1))
                        k=candidates[np.argmax(spectrum[candidates])]
                        measured=float(freq[k])
                    row[label+'_frequency_hz']=measured
                    row[label+'_pitch_error_cents']=1200*math.log2(measured/expected)
            rows.append(row)
    # The sparse columns are intentional: click and tonal diagnostics differ.
    fields=list(dict.fromkeys(key for row in rows for key in row))
    with (OUT/'synthetic.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=fields,lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=('fixed-b','prototype-fixed','transitions','metrics-only',
                                         'audition','golden','density-only','phase','synthetic'))
    args=parser.parse_args()
    for folder in ('raw','trace','audition','golden_check'):
        (OUT/folder).mkdir(parents=True,exist_ok=True)
    {'fixed-b':fixed_b,'prototype-fixed':prototype_fixed,
     'transitions':transitions,'audition':audition,
     'metrics-only':metrics_only,'golden':golden,
     'density-only':density_only,'phase':phase,'synthetic':synthetic}[args.stage]()
