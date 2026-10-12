#!/usr/bin/env python3
"""Phase 36 local-only deterministic simulated callback and offline replay."""
import csv
import hashlib
import subprocess
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'results/phase36'
RAW = OUT/'raw'
TRACE = OUT/'trace'
SIM = ROOT/'build/phase36_sim'
REF = ROOT/'build/phase36_reference'
SOURCES = ('mix','drums','vocal','bass','guitar','click','harmonic','decay_noise')
PAIRS = (('0.40','0.50'),('0.50','0.40'),('0.45','0.50'),
         ('0.50','0.45'),('0.49','0.50'),('0.50','0.49'))

def source(name):
    phase='phase32' if name in ('harmonic','decay_noise') else 'phase31'
    return ROOT/f'results/{phase}/input/{name}.wav'

def run(*args):
    result=subprocess.run(tuple(map(str,args)),capture_output=True,text=True,timeout=180)
    if result.returncode:
        raise RuntimeError(f'{args}: {result.stderr}')
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def table(name,rows):
    with (OUT/name).open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0].keys(),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)

def fixed():
    rows=[]
    for name in SOURCES:
        for speed in ('0.40','0.45','0.49','0.50'):
            tag=f'{name}_{speed.replace(".","")}'
            output=RAW/f'fixed_{tag}.wav'
            result=run(SIM,source(name),output,speed,'-',512)
            baseline=ROOT/'results/phase35/variable_hop/raw'/(
                f'{name}_{speed.replace(".","")}_prototype_fixed.wav'
                if speed!='0.50' else f'{name}_A_050_prototype_fixed.wav')
            if not baseline.exists() and speed=='0.50':
                baseline=RAW/f'phase35_{tag}.wav'
                (TRACE/'empty.csv').write_text('input_sample,target_speed\n')
                run(ROOT/'build/phase35_render',source(name),baseline,speed,
                    TRACE/'empty.csv',
                    TRACE/f'{tag}_phase35',16384)
            if not baseline.exists():
                baseline=ROOT/'results/phase35/variable_hop/raw'/f'fixed_{tag}.wav'
            equal=output.read_bytes()==baseline.read_bytes()
            rows.append(dict(source=name,speed=speed,frames=result['frames'],
                             baseline_sha=sha(baseline),stream_sha=sha(output),
                             byte_equal=equal,underrun=result['underrun'],
                             rejected_writes=result['rejected_writes']))
            if not equal: raise RuntimeError(f'Fixed mismatch: {tag}')
    for name in SOURCES[:5]:
        for speed in ('0.50','0.60','0.70','0.75','0.80'):
            tag=f'{name}_{speed.replace(".","")}'
            output=RAW/f'golden_{tag}.wav'
            result=run(SIM,ROOT/f'results/phase12/golden/input/{name}.wav',
                       output,speed,'-',512)
            baseline=ROOT/'results/phase35/variable_hop/golden_check'/f'{tag}.wav'
            equal=output.read_bytes()==baseline.read_bytes()
            rows.append(dict(source=name,speed=speed,frames=result['frames'],
                             baseline_sha=sha(baseline),stream_sha=sha(output),
                             byte_equal=equal,underrun=result['underrun'],
                             rejected_writes=result['rejected_writes']))
            if not equal: raise RuntimeError(f'Fixed mismatch: {tag}')
    table('fixed.csv',rows)

def transitions():
    rows=[]
    for name in SOURCES:
        for initial,target in PAIRS:
            tag=f'{name}_{initial.replace(".","")}_{target.replace(".","")}'
            output=RAW/f'{tag}.wav';reference=RAW/f'{tag}_reference.wav'
            plans=TRACE/f'{tag}.csv'
            request=3/float(initial)
            result=run(SIM,source(name),output,initial,f'{request:.6f}:{target}',512,plans)
            run(REF,source(name),reference,initial,plans)
            equal=output.read_bytes()==reference.read_bytes()
            with plans.open(newline='') as file:plan=list(csv.DictReader(file))[0]
            fixed_path=RAW/f'fixed_{name}_{initial.replace(".","")}.wav'
            from phase32_study import read
            rate,variable_audio=read(output)
            _,fixed_audio=read(fixed_path)
            published=int(plan['published'])
            prefix_equal=bool((variable_audio[:published]==
                               fixed_audio[:published]).all())
            center=int(plan['applied_output'])
            section=variable_audio[max(0,center-rate//5):min(len(variable_audio),center+rate//5)]
            peak=float(np.max(np.abs(variable_audio)))
            derivative=float(np.max(np.abs(np.diff(section,axis=0))))
            if section.shape[1]==2:
                mid=(section[:,0]+section[:,1])*0.5
                side=(section[:,0]-section[:,1])*0.5
                side_mid=float(np.sqrt(np.mean(side**2))/max(1e-12,np.sqrt(np.mean(mid**2))))
                lr_corr=float(np.corrcoef(section[:,0],section[:,1])[0,1])
            else:side_mid=lr_corr=0.0
            zero_frames=int(np.sum(np.all(variable_audio==0,axis=1)))
            finite=bool(np.isfinite(variable_audio).all())
            rows.append(dict(source=name,initial=initial,target=target,
                callback=512,frames=result['frames'],byte_equal=equal,
                published_prefix_equal=prefix_equal,
                finite=finite,peak=peak,transition_max_derivative=derivative,
                transition_side_mid=side_mid,transition_lr_correlation=lr_corr,
                zero_frames=zero_frames,
                stream_sha=sha(output),reference_sha=sha(reference),
                applied_frame=plan['applied_frame'],applied_output=plan['applied_output'],
                planning_fence=plan['planning_fence'],published=plan['published'],
                next_low=plan['next_low'],next_mid=plan['next_mid'],next_high=plan['next_high'],
                ola_low=plan['ola_low'],ola_mid=plan['ola_mid'],ola_high=plan['ola_high'],
                fir_low=plan['fir_low'],fir_high=plan['fir_high'],
                plan_ms=plan['plan_ms'],map_bytes=plan['map_bytes'],
                underrun=result['underrun'],
                rejected_writes=result['rejected_writes'],
                max_worker_chunk_seconds=result['max_worker_chunk_seconds']))
            if not equal or not prefix_equal or not finite:
                raise RuntimeError(f'Transition or published prefix mismatch: {tag}')
    table('transitions.csv',rows)

def extras():
    cases=(('mix','0.40','5:0.60,12:0.45'),
           ('drums','0.50','4:0.40,11:0.50'),
           ('mix','0.50','4:0.70'),('mix','0.70','4:0.50'))
    rows=[]
    for name,initial,schedule in cases:
        tag=f'{name}_{initial.replace(".","")}_{schedule.replace(":","_").replace(",","_").replace(".","")}'
        out=RAW/f'{tag}.wav';ref=RAW/f'{tag}_reference.wav';plans=TRACE/f'{tag}.csv'
        info=run(SIM,source(name),out,initial,schedule,512,plans)
        run(REF,source(name),ref,initial,plans)
        equal=out.read_bytes()==ref.read_bytes()
        rows.append(dict(case=tag,frames=info['frames'],changes=info['changes'],
                         byte_equal=equal,sha=sha(out)))
        if not equal: raise RuntimeError(f'Extra mismatch: {tag}')
    table('extras.csv',rows)

if __name__=='__main__':
    import sys
    for path in (OUT,RAW,TRACE):path.mkdir(parents=True,exist_ok=True)
    {'fixed':fixed,'transitions':transitions,'extras':extras}[sys.argv[1]]()
