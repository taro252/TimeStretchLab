#!/usr/bin/env python3
"""Create equal-gain Normal/High audition WAVs and compare with Phase 5.2 A/B."""
import argparse
import concurrent.futures
import csv
import pathlib
import subprocess


def run(command):
    return subprocess.run(command,check=True,capture_output=True,text=True).stdout.strip()


def main():
    parser=argparse.ArgumentParser()
    for name in ('bass','mix','female','male'):
        parser.add_argument(name,type=pathlib.Path)
    parser.add_argument('--start',type=float,default=90)
    parser.add_argument('--duration',type=float,default=45)
    parser.add_argument('--jobs',type=int,default=3)
    args=parser.parse_args()
    root=pathlib.Path(__file__).resolve().parent.parent
    result=root/'results/phase53/real'
    result.mkdir(parents=True,exist_ok=True)
    inputs={}
    for name in ('bass','mix','female','male'):
        path=result/f'{name}_input.wav'
        run(['ffmpeg','-v','error','-y','-ss',str(args.start),'-i',str(getattr(args,name)),
             '-t',str(args.duration),'-c:a','pcm_f32le',str(path)])
        inputs[name]=path
    jobs=[(name,speed,quality,source,result/f'{name}_{speed.replace(".", "")}_{quality}.wav')
          for name,source in inputs.items() for speed in ('0.75','0.50')
          for quality in ('normal','high')]

    def process(job):
        name,speed,quality,source,output=job
        line=run([str(root/'build/timestretch'),str(source),str(output),
                  '--speed',speed,'--phase-locking','on','--transient','on',
                  '--adaptive-time-map','on','--precise-anchoring','on',
                  '--stereo-coherence','on','--quality',quality,'--chunked','on'])
        fields=dict(item.split('=',1) for item in line.split() if '=' in item)
        print(name,speed,quality,line,flush=True)
        return {'name':name,'speed':speed,'quality':quality,'input':str(source),
                'output':str(output),**fields}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows=list(pool.map(process,jobs))
    with (result/'manifest.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    for name in ('bass','mix','female','male'):
        for speed in ('0.75','0.5'):
            group=[row for row in rows if row['name']==name and row['speed']==speed]
            if len(group)!=2 or len({row['time_map_hash'] for row in group})!=1 or \
               len({row['output_frames'] for row in group})!=1 or \
               len({row['event_count'] for row in group})!=1:
                raise AssertionError(f'Quality-mode timeline mismatch: {name} {speed}')
    compare=[]
    old=root/'results/phase52/real'
    for row in rows:
        path=old/f'{row["name"]}_{row["speed"].replace(".", "").ljust(3,"0")}_{"a" if row["quality"]=="normal" else "b"}.wav'
        if path.exists():
            line=run([str(root/'build/wav_compare'),str(path),row['output']])
            difference=dict(item.split('=',1) for item in line.split() if '=' in item)
            compare.append({'name':row['name'],'speed':row['speed'],
                            'quality':row['quality'],'max_difference':difference['max_difference'],
                            'changed_samples':difference['changed_samples']})
            if int(difference['changed_samples'])!=0:
                raise AssertionError(f'Phase 5.2 sample mismatch: {path}')
    with (result/'phase52_regression.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(compare[0]) if compare else
                              ['name','speed','quality','max_difference','changed_samples'],
                              lineterminator='\n')
        writer.writeheader();writer.writerows(compare)
    print(f'Exact Phase 5.2 regressions: {len(compare)}',flush=True)


if __name__=='__main__': main()
