#!/usr/bin/env python3
"""Create Phase 5.3/PVSOLA comparisons with identical sections and gain."""
import argparse
import csv
import pathlib
import subprocess

ROOT=pathlib.Path(__file__).resolve().parent.parent
OUT=ROOT/'results/phase7'
SECTIONS={
    'female':[(15,10),(103,10),(145,10)],
    'male':[(43,10),(90,10),(146,10)],
    'mix':[(90,45)],'bass':[(90,45)],
    'drums':[(90,20)],'guitar':[(90,20)],
}

def run(command):
    return subprocess.run(command,check=True,capture_output=True,text=True).stdout.strip()

def fields(line):
    return dict(part.split('=',1) for part in line.split() if '=' in part)

def main():
    parser=argparse.ArgumentParser()
    for name in SECTIONS:
        parser.add_argument(name,type=pathlib.Path)
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for name,sections in SECTIONS.items():
        source=getattr(args,name)
        if not source.is_file():raise FileNotFoundError(source)
        for section,(start,duration) in enumerate(sections,1):
            key=f'{name}_{section}'
            sample=OUT/f'{key}_input.wav'
            run(['ffmpeg','-v','error','-y','-ss',str(start),'-i',str(source),
                 '-t',str(duration),'-c:a','pcm_f32le',str(sample)])
            for speed in ('0.75','0.50'):
                for mode in ('off','on'):
                    output=OUT/f'{key}_{speed.replace(".","")}_{mode}.wav'
                    diagnostic=OUT/'diagnostics'/f'{key}_{speed.replace(".","")}'
                    cmd=[str(ROOT/'build/timestretch'),str(sample),str(output),
                         '--speed',speed,'--phase-locking','on','--partial-tracking','off',
                         '--pvsola',mode,'--transient','on','--adaptive-time-map','on',
                         '--precise-anchoring','on','--stereo-coherence','on',
                         '--quality','high','--chunked','on']
                    if mode=='on':cmd+=['--debug-csv',str(diagnostic)]
                    row={**fields(run(cmd)),
                         'name':name,'section':section,'start_sec':start,
                         'duration_sec':duration,'speed':speed,'mode':mode,
                         'input':str(sample),'output':str(output),
                         'diagnostics':str(diagnostic/'pvsola_resync.csv') if mode=='on' else ''}
                    rows.append(row)
                    print(key,speed,mode,'resync',row['resync_applied'],
                          'cpu',row['cpu_seconds'],flush=True)
            for speed in ('0.75','0.50'):
                pair=[r for r in rows if r['name']==name and r['section']==section
                      and r['speed']==speed]
                if len(pair)!=2 or len({r['output_frames'] for r in pair})!=1 or \
                   len({r['time_map_hash'] for r in pair})!=1 or \
                   len({r['event_count'] for r in pair})!=1:
                    raise AssertionError(f'Mismatched timing: {key} {speed}')
    with (OUT/'manifest.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    old=ROOT/'results/phase53/real'
    regression=[]
    # The saved Phase 5.3 study uses the same 90-135 s sections.
    for name in ('mix','bass'):
        for speed in ('0.75','0.50'):
            row=next(r for r in rows if r['name']==name and r['section']==1
                     and r['speed']==speed and r['mode']=='off')
            reference=old/f'{name}_{speed.replace(".","")}_high.wav'
            if not reference.exists():continue
            comparison=fields(run([str(ROOT/'build/wav_compare'),str(reference),row['output']]))
            # These are 45 s excerpts and should match the saved baseline exactly.
            regression.append({'name':name,'speed':speed,
                               'changed_samples':comparison['changed_samples'],
                               'max_difference':comparison['max_difference']})
            if int(comparison['changed_samples']):raise AssertionError('OFF regression')
    for name in ('female','male'):
        source=getattr(args,name)
        sample=OUT/f'{name}_regression_input.wav'
        run(['ffmpeg','-v','error','-y','-ss','90','-i',str(source),
             '-t','45','-c:a','pcm_f32le',str(sample)])
        for speed in ('0.75','0.50'):
            output=OUT/f'{name}_regression_{speed.replace(".","")}_off.wav'
            run([str(ROOT/'build/timestretch'),str(sample),str(output),
                 '--speed',speed,'--phase-locking','on','--partial-tracking','off',
                 '--pvsola','off','--transient','on','--adaptive-time-map','on',
                 '--precise-anchoring','on','--stereo-coherence','on',
                 '--quality','high','--chunked','on'])
            reference=old/f'{name}_{speed.replace(".","")}_high.wav'
            if not reference.exists():continue
            comparison=fields(run([str(ROOT/'build/wav_compare'),str(reference),str(output)]))
            regression.append({'name':name,'speed':speed,
                               'changed_samples':comparison['changed_samples'],
                               'max_difference':comparison['max_difference']})
            if int(comparison['changed_samples']):raise AssertionError('OFF regression')
    with (OUT/'off_regression.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=['name','speed','changed_samples','max_difference'],
                              lineterminator='\n')
        writer.writeheader();writer.writerows(regression)

if __name__=='__main__':main()
