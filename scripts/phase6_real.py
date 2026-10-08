#!/usr/bin/env python3
"""Generate equal-gain Phase 5.3/6 comparisons from identical source sections."""
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
    result=root/'results/phase6/real'
    result.mkdir(parents=True,exist_ok=True)
    inputs={}
    for name in ('bass','mix','female','male'):
        source=getattr(args,name)
        if not source.is_file(): raise FileNotFoundError(source)
        target=result/f'{name}_input.wav'
        run(['ffmpeg','-v','error','-y','-ss',str(args.start),'-i',str(source),
             '-t',str(args.duration),'-c:a','pcm_f32le',str(target)])
        inputs[name]=target
    jobs=[(name,speed,tracking,source,
           result/f'{name}_{speed.replace(".","")}_{tracking}.wav')
          for name,source in inputs.items() for speed in ('0.75','0.50')
          for tracking in ('off','on')]

    def process(job):
        name,speed,tracking,source,output=job
        line=run([str(root/'build/timestretch'),str(source),str(output),
            '--speed',speed,'--phase-locking','on','--partial-tracking',tracking,
            '--transient','on','--adaptive-time-map','on','--precise-anchoring','on',
            '--stereo-coherence','on','--quality','high','--chunked','on'])
        fields=dict(item.split('=',1) for item in line.split() if '=' in item)
        print(name,speed,tracking,line,flush=True)
        return {'name':name,'speed':speed,'tracking':tracking,
                'input':str(source),'output':str(output),**fields}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows=list(pool.map(process,jobs))
    with (result/'manifest.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)
    for name in inputs:
        for speed in ('0.75','0.5'):
            pair=[row for row in rows if row['name']==name and row['speed']==speed]
            if len(pair)!=2 or len({row['time_map_hash'] for row in pair})!=1 or \
               len({row['output_frames'] for row in pair})!=1 or \
               len({row['event_count'] for row in pair})!=1:
                raise AssertionError(f'Time-map mismatch: {name} {speed}')
    old=root/'results/phase53/real'
    regressions=[]
    for row in rows:
        if row['tracking']!='off': continue
        oldPath=old/f'{row["name"]}_{row["speed"].replace(".","").ljust(3,"0")}_high.wav'
        if not oldPath.exists(): continue
        comparison=run([str(root/'build/wav_compare'),str(oldPath),row['output']])
        fields=dict(item.split('=',1) for item in comparison.split() if '=' in item)
        regressions.append({'name':row['name'],'speed':row['speed'],
                            'max_difference':fields['max_difference'],
                            'changed_samples':fields['changed_samples']})
        if int(fields['changed_samples'])!=0:
            raise AssertionError(f'Phase 6 OFF changed Phase 5.3: {oldPath}')
    with (result/'off_regression.csv').open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=['name','speed','max_difference','changed_samples'],
                              lineterminator='\n')
        writer.writeheader();writer.writerows(regressions)
    print('Exact OFF regressions',len(regressions),flush=True)


if __name__=='__main__': main()
