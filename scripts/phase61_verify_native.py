"""Compare callback RAW captures with an independent full-render oracle.
Prefix captures and complete seek suffixes are counted separately.
"""
import argparse,hashlib,json,subprocess
from pathlib import Path

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--sessions',type=Path,required=True);parser.add_argument('--reference',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--expected-sessions',type=int,default=20);a=parser.parse_args()
    a.output.mkdir(parents=True,exist_ok=False);source=a.input.resolve();reference=a.reference.resolve()
    sessions=[json.loads(line) for line in (a.sessions/'sessions.jsonl').read_text().splitlines()]
    refs={};results=[];skipped=[];empty=0
    def full(speed,preset,positions):
        key=(speed,preset)
        if key not in refs:
            raw=a.output/f'{speed}_{preset}.f32';log=a.output/f'{speed}_{preset}.log'
            cmd=[str(reference),str(source),str(speed),preset,str(raw.resolve()),*map(str,positions)]
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=180);log.write_text(p.stdout+p.stderr)
            if p.returncode:raise RuntimeError(p.stderr)
            result=json.loads(p.stdout);assert sha(raw)==result['sha256'];refs[key]=(raw,result,dict(zip(positions,result['positions'])))
        return refs[key]
    for row in sessions:
        folder=a.sessions/row['name'];seeks=json.loads((folder/'seeks.json').read_text());captures=json.loads((folder/'captures.json').read_text());preset=row['name'].split('_')[0]
        positions_by_speed={}
        for op in seeks:
            if op['state']=='Completed':positions_by_speed.setdefault(op['speed_micros'],set()).add(op['input_frame'])
        for capture in captures:positions_by_speed.setdefault(capture['speed_micros'],set()).add(0)
        # Include every completed position for this speed across sessions so the
        # same full reference can be shared without trusting the current map.
        for other in sessions:
            if not other['name'].startswith(preset+'_'):continue
            for op in json.loads((a.sessions/other['name']/'seeks.json').read_text()):
                if op['state']=='Completed':positions_by_speed.setdefault(op['speed_micros'],set()).add(op['input_frame'])
        for capture in captures:
            if not capture['fixed_oracle_applicable']:
                skipped.append({'session':row['name'],'epoch':capture['epoch'],'scope':'old dynamic prefix; checked for identity/order by capture but not compared to a fixed-speed oracle'})
                continue
            raw,expected,mapping=full(capture['speed_micros'],preset,sorted(positions_by_speed[capture['speed_micros']]))
            path=Path(capture['path']);start=capture['start'];frames=capture['frames'];channels=capture['channels'];matched=True;error=''
            operation=next((op for op in seeks if op['epoch']==capture['epoch'] and op['state']=='Completed'),None)
            if operation:matched&=mapping[operation['input_frame']]==start
            else:matched&=start==0
            matched&=channels==expected['channels'] and path.stat().st_size==frames*channels*4
            if capture['complete_suffix']:matched&=frames==expected['output_frames']-start
            with path.open('rb') as actual,raw.open('rb') as wanted:
                wanted.seek(start*channels*4);offset=0
                while chunk:=actual.read(1<<20):
                    other=wanted.read(len(chunk))
                    if chunk!=other:
                        matched=False;first=next((i for i,(x,y) in enumerate(zip(chunk,other)) if x!=y),min(len(chunk),len(other)))
                        sample=(offset+first)//4;error=f'first differing frame={start+sample//channels} channel={sample%channels}';break
                    offset+=len(chunk)
            results.append({'session':row['name'],'epoch':capture['epoch'],'PASS':bool(matched),'scope':'complete_suffix' if capture['complete_suffix'] else 'prefix','frames':frames,'start':start,'pcm_sha256':sha(path),'reference_sha256':expected['sha256'],'error':error})
        for op in seeks:
            if op['state']=='Completed' and row['name'].endswith('_eof'):
                _,expected,mapping=full(op['speed_micros'],preset,sorted(positions_by_speed[op['speed_micros']]))
                good=op['input_frame']==expected['input_frames'] and op['output_start']==expected['output_frames'] and not any(c['epoch']==op['epoch'] for c in captures)
                results.append({'session':row['name'],'epoch':op['epoch'],'PASS':good,'scope':'empty_suffix','frames':0,'start':op['output_start']});empty+=good
    completed=len(sessions)==a.expected_sessions and all(r['functional'] for r in sessions)
    summary={'PASS':completed and bool(results) and all(r['PASS'] for r in results),'measurement_completed':completed,'sessions':len(sessions),'full_suffix_passed':sum(r['PASS'] and r['scope']=='complete_suffix' for r in results),'prefix_passed':sum(r['PASS'] and r['scope']=='prefix' for r in results),'empty_suffix_passed':empty,'skipped_dynamic_prefixes':skipped,'results':results,'input_sha256':sha(source),'reference_binary_sha256':sha(reference),'driver_sha256':sha(Path(__file__))}
    (a.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in summary.items() if k not in ('results','skipped_dynamic_prefixes')}),flush=True)
    return 0 if summary['PASS'] else 2
if __name__=='__main__':raise SystemExit(main())
